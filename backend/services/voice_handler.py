"""
voice_handler.py — WebSocket session handler for live voice interviews.

This module handles:
  - VAD (Voice Activity Detection) via energy thresholding
  - Whisper STT (speech-to-text)
  - LangGraph interview graph invocation (replaces old voice_service)
  - edge-tts TTS (text-to-speech)
  - WebSocket keepalive heartbeat
  - Per-turn error recovery

The LangGraph graph is invoked once per turn with the user's transcribed
answer. It returns the AI's response text, routing decision, and score.
"""

import asyncio
import base64
import json
import numpy as np
import io
import wave
import time
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel
import edge_tts
from backend.graph.graph import interview_graph
from backend.services.evaluation_service import evaluation_service
import os

logger = logging.getLogger("interviewer.voice")

# Load Whisper model globally to avoid reloading
whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
logger.info(f"[Voice] Whisper model loaded: tiny.en (cpu, int8)")

# Energy threshold for VAD
# Int16 range is 0-32767. Fan noise is typically 200-800 RMS.
# Human speech is typically 2000-10000+ RMS.
ENERGY_THRESHOLD = int(os.environ.get("VOICE_ENERGY_THRESHOLD", "2000"))

# Number of silent frames to wait before treating utterance as complete
# At 4096 samples/chunk @ 16kHz: each chunk is ~256ms
# 8 chunks = ~2 seconds of silence
SILENCE_THRESHOLD = 8

# How often (seconds) to send a keepalive ping to prevent uvicorn from
# closing the WebSocket during long Whisper/Gemini API calls
KEEPALIVE_INTERVAL = 8


async def _send(websocket: WebSocket, data: dict, lock: Optional[asyncio.Lock] = None):
    """Send a JSON dict as text over websocket, using a lock to prevent concurrent write errors."""
    if lock:
        async with lock:
            await websocket.send_text(json.dumps(data))
    else:
        await websocket.send_text(json.dumps(data))


async def _keepalive_loop(websocket: WebSocket, stop_event: asyncio.Event, lock: asyncio.Lock):
    """
    Runs concurrently with the main session loop.
    Sends a 'ping' message every KEEPALIVE_INTERVAL seconds to prevent
    the WebSocket from being considered idle and closed.
    Uses the provided lock to avoid concurrent write issues with the main loop.
    """
    while not stop_event.is_set():
        try:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
        except asyncio.CancelledError:
            break

        if stop_event.is_set():
            break

        try:
            async with lock:
                await websocket.send_text(json.dumps({"type": "ping"}))
            logger.debug("[Voice] Keepalive ping sent.")
        except Exception:
            logger.warning("[Voice] Keepalive: WebSocket already closed, stopping heartbeat.")
            break


class VoiceConnectionManager:

    async def handle_session(
        self,
        websocket: WebSocket,
        job_details: dict,
        candidate_details: dict,
        resume_profile: dict,
        question_file: dict,
    ):
        await websocket.accept()
        candidate_name = candidate_details.get('name', 'Candidate')
        job_title = job_details.get('title', 'the position')
        logger.info(f"[Voice] ═══════════════════════════════════════════════")
        logger.info(f"[Voice] Session started | candidate={candidate_name} | job={job_title}")
        logger.info(f"[Voice]   VAD threshold={ENERGY_THRESHOLD} | silence_frames={SILENCE_THRESHOLD} | keepalive={KEEPALIVE_INTERVAL}s")
        logger.info(f"[Voice]   Topics: {len(question_file.get('topics', []))} | Resume skills: {len(resume_profile.get('skills', []))}")
        logger.info(f"[Voice] ═══════════════════════════════════════════════")

        # ── Session State ─────────────────────────────────────────
        audio_buffer = bytearray()
        is_speaking = False
        silence_frames = 0
        ambient_energy = 0.0
        AMBIENT_ALPHA = 0.98  # Rolling average smoothing factor

        # Gate: ignore all incoming mic audio while AI is playing
        ai_is_speaking = False
        ai_speak_start_time = 0.0
        ai_speak_expected_duration = 0.0

        # LangGraph thread ID — MUST be unique per session to avoid state leaks
        # Using timestamp ensures each new interview session starts with a clean state
        session_ts = int(time.time() * 1000)
        thread_id = f"interview_{job_details.get('job_id', 0)}_{candidate_details.get('candidate_id', 0)}_{session_ts}"
        graph_config = {"configurable": {"thread_id": thread_id}}
        logger.info(f"[Voice] LangGraph thread_id={thread_id}")

        # Lock for synchronizing WebSocket sends between main loop and keepalive heartbeat
        ws_lock = asyncio.Lock()

        # Stop event for the keepalive task
        stop_keepalive = asyncio.Event()

        # Start the concurrent keepalive heartbeat
        keepalive_task = asyncio.create_task(_keepalive_loop(websocket, stop_keepalive, ws_lock))

        # Track the final graph state for evaluation
        final_graph_state = None

        try:
            # ── Initial Greeting via LangGraph ────────────────────
            logger.info("[Voice] Invoking graph for greeting (empty messages)...")
            await _send(websocket, {
                "type": "status",
                "message": "AI Interviewer is preparing...",
                "state": "thinking"
            }, ws_lock)

            t0 = time.time()
            try:
                greeting_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        interview_graph.invoke,
                        {
                            "messages": [],
                            "resume_profile": resume_profile,
                            "question_file": question_file,
                            "job_details": job_details,
                            "candidate_name": candidate_name,
                            "current_topic_index": 0,
                            "current_topic_turn": 0,
                            "current_topic_score": 0,
                            "grader_reasoning": "",
                            "planner_instruction": "",
                            "is_complete": False,
                            "evaluation_notes": [],
                            "route": "",
                        },
                        graph_config,
                    ),
                    timeout=45.0,
                )
                final_graph_state = greeting_result
                greeting = greeting_result["messages"][-1]["content"]
                elapsed = round(time.time() - t0, 2)
                logger.info(f"[Voice] Greeting generated in {elapsed}s: '{greeting[:80]}...'")

            except asyncio.TimeoutError:
                logger.error("[Voice] Greeting generation timed out after 45s, using fallback.")
                greeting = f"Hello {candidate_name}! Welcome to your interview for the {job_title} position. Let's get started -- could you please introduce yourself briefly?"
            except Exception as e:
                logger.error(f"[Voice] Greeting error: {type(e).__name__}: {e}")
                greeting = f"Hello {candidate_name}! Welcome to your interview for the {job_title} position. Let's get started -- could you please introduce yourself briefly?"

            await _send(websocket, {"type": "text", "role": "ai", "text": greeting}, ws_lock)

            ai_is_speaking = True
            ai_speak_start_time = time.time()
            ai_speak_expected_duration = len(greeting) / 10.0 + 5.0
            success = await self._speak_and_send(websocket, greeting, ws_lock)
            if not success:
                ai_is_speaking = False

            # ── Main Message Loop ─────────────────────────────────
            while True:
                message = await websocket.receive()

                # ── Text / Control Messages ───────────────────────
                if "text" in message:
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "audio_done":
                        # Client finished playing the AI audio.
                        # NOW it's safe to re-enable the microphone listener.
                        ai_is_speaking = False
                        logger.debug("[Voice] Client confirmed audio_done. Listening enabled.")
                        await _send(websocket, {
                            "type": "status",
                            "message": "Your turn -- please speak now",
                            "state": "listening"
                        }, ws_lock)

                    elif msg_type == "interrupt":
                        # Barge-in: user spoke while AI was playing
                        ai_is_speaking = False
                        logger.info("[Voice] Barge-in interrupt received.")
                        await _send(websocket, {"type": "clear"}, ws_lock)
                        await _send(websocket, {
                            "type": "status",
                            "message": "Listening...",
                            "state": "listening"
                        }, ws_lock)

                    elif msg_type == "pong":
                        # Client acknowledged our keepalive ping - nothing to do
                        pass

                    # Ignore 'ping' type from client (shouldn't happen but just in case)

                # ── Binary Audio Chunks ───────────────────────────
                elif "bytes" in message:
                    if ai_is_speaking:
                        if time.time() - ai_speak_start_time > ai_speak_expected_duration:
                            logger.info("[Voice] Server-side fallback: audio_done timeout reached. Ungating mic.")
                            ai_is_speaking = False
                            await _send(websocket, {
                                "type": "status",
                                "message": "Your turn -- please speak now",
                                "state": "listening"
                            }, ws_lock)
                        else:
                            # CRITICAL: Discard mic audio while AI is playing
                            # Prevents echo/TTS audio from triggering false VAD
                            continue

                    chunk = message["bytes"]
                    if len(chunk) == 0:
                        continue

                    audio_arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(audio_arr ** 2)))

                    # Update ambient noise estimate only during silence
                    if not is_speaking:
                        ambient_energy = AMBIENT_ALPHA * ambient_energy + (1 - AMBIENT_ALPHA) * rms

                    # Dynamic threshold: must be significantly louder than background
                    dynamic_threshold = max(ENERGY_THRESHOLD, ambient_energy * 3.0)

                    if rms > dynamic_threshold:
                        # ── Speech detected ───────────────────────
                        if not is_speaking:
                            is_speaking = True
                            silence_frames = 0
                            logger.info(f"[Voice] Speech start | rms={rms:.0f} | ambient={ambient_energy:.0f} | threshold={dynamic_threshold:.0f}")
                            await _send(websocket, {
                                "type": "status",
                                "message": "Listening to you...",
                                "state": "listening"
                            }, ws_lock)
                        silence_frames = 0
                        audio_buffer.extend(chunk)

                    elif is_speaking:
                        # ── Silence frames during speech window ───
                        silence_frames += 1
                        audio_buffer.extend(chunk)

                        if silence_frames >= SILENCE_THRESHOLD:
                            # ── End of utterance ──────────────────
                            is_speaking = False
                            silence_frames = 0
                            final_audio = bytes(audio_buffer)
                            audio_buffer.clear()
                            logger.info(f"[Voice] Utterance end | buffer={len(final_audio)} bytes")

                            await _send(websocket, {
                                "type": "status",
                                "message": "Transcribing your speech...",
                                "state": "processing"
                            }, ws_lock)

                            # ── Per-turn try/except: errors here should NOT kill the session ──
                            # Each turn is isolated so a transient API error just skips that turn.
                            try:
                                # Run Whisper in a thread (blocking, CPU-bound)
                                # The keepalive task keeps the WS alive during this
                                logger.info("[Voice] Starting transcription...")
                                t_stt = time.time()
                                transcription = await asyncio.to_thread(self._transcribe, final_audio)
                                stt_elapsed = round(time.time() - t_stt, 2)
                                logger.info(f"[Voice] Transcription ({stt_elapsed}s): '{transcription}'")

                                if not transcription.strip():
                                    logger.info("[Voice] Empty transcription (noise). Resuming listen.")
                                    await _send(websocket, {
                                        "type": "status",
                                        "message": "Didn't catch that. Please speak again.",
                                        "state": "listening"
                                    }, ws_lock)
                                    continue

                                # Send transcription to frontend chat
                                await _send(websocket, {"type": "text", "role": "user", "text": transcription.strip()}, ws_lock)

                                await _send(websocket, {
                                    "type": "status",
                                    "message": "AI is thinking...",
                                    "state": "thinking"
                                }, ws_lock)

                                # ── Invoke LangGraph Planner ──────────────────
                                logger.info("[Voice] Invoking LangGraph planner...")
                                t_llm = time.time()
                                try:
                                    graph_result = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            interview_graph.invoke,
                                            {"messages": [{"role": "user", "content": transcription.strip()}]},
                                            graph_config,
                                        ),
                                        timeout=45.0,
                                    )
                                    final_graph_state = graph_result
                                except asyncio.TimeoutError:
                                    logger.error("[Voice] LangGraph timed out after 45s.")
                                    graph_result = None

                                llm_elapsed = round(time.time() - t_llm, 2)

                                if graph_result:
                                    ai_response = graph_result["messages"][-1]["content"]
                                    interview_ended = graph_result.get("is_complete", False)
                                    route = graph_result.get("route", "unknown")
                                    logger.info(
                                        f"[Voice] Turn complete ({llm_elapsed}s) | route={route} | "
                                        f"score={graph_result.get('current_topic_score', '?')} | "
                                        f"topic_idx={graph_result.get('current_topic_index')} | "
                                        f"topic_turn={graph_result.get('current_topic_turn')} | "
                                        f"response='{ai_response[:80]}...'"
                                    )
                                else:
                                    ai_response = "I'm sorry, I took too long to process that. Could you repeat your answer?"
                                    interview_ended = False
                                    logger.warning("[Voice] Using fallback response due to timeout.")

                                # Guard against None/empty response
                                if not ai_response or not ai_response.strip():
                                    logger.warning("[Voice] AI response was empty, using fallback.")
                                    ai_response = "Thank you for sharing that. Could you tell me more about your technical background?"

                                await _send(websocket, {"type": "text", "role": "ai", "text": ai_response}, ws_lock)

                                # Gate mic before sending audio
                                ai_is_speaking = True
                                ai_speak_start_time = time.time()
                                ai_speak_expected_duration = len(ai_response) / 10.0 + 5.0
                                success = await self._speak_and_send(websocket, ai_response, ws_lock)
                                if not success:
                                    logger.warning("[Voice] TTS failed, immediately ungating microphone.")
                                    ai_is_speaking = False
                                    await _send(websocket, {
                                        "type": "status",
                                        "message": "Your turn -- please speak now",
                                        "state": "listening"
                                    }, ws_lock)

                                if interview_ended:
                                    logger.info("[Voice] Interview complete (route=end). Closing session.")
                                    await _send(websocket, {
                                        "type": "interview_complete",
                                        "message": "Interview complete! Thank you for participating."
                                    }, ws_lock)
                                    break  # Exit the main message loop

                            except asyncio.CancelledError:
                                raise  # Let CancelledError propagate (session shutdown)
                            except Exception as turn_error:
                                logger.error(f"[Voice] Per-turn error: {type(turn_error).__name__}: {turn_error}", exc_info=True)
                                # Recover gracefully: notify the user and resume listening
                                try:
                                    recovery_msg = "I encountered a brief technical issue. Let's continue -- could you please repeat or rephrase your last answer?"
                                    ai_is_speaking = True
                                    ai_speak_start_time = time.time()
                                    ai_speak_expected_duration = len(recovery_msg) / 10.0 + 5.0
                                    success = await self._speak_and_send(websocket, recovery_msg, ws_lock)
                                    if not success:
                                        ai_is_speaking = False
                                except Exception:
                                    # If even the recovery fails, just reset state and keep listening
                                    ai_is_speaking = False
                                    await _send(websocket, {
                                        "type": "status",
                                        "message": "Technical issue. Please speak again.",
                                        "state": "listening"
                                    }, ws_lock)

        except WebSocketDisconnect:
            logger.info("[Voice] WebSocket disconnected by client.")
        except RuntimeError as e:
            # Starlette raises RuntimeError when receiving after disconnect
            if "disconnect" in str(e).lower():
                logger.info("[Voice] WebSocket disconnected (RuntimeError).")
            else:
                logger.error(f"[Voice] Session RuntimeError: {e}")
        except Exception as e:
            logger.error(f"[Voice] Session error: {type(e).__name__}: {e}", exc_info=True)
        finally:
            # Stop the keepalive heartbeat
            stop_keepalive.set()
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass

            # Determine message count for evaluation
            msg_count = 0
            eval_notes = []
            eval_messages = []
            if final_graph_state:
                eval_messages = final_graph_state.get("messages", [])
                eval_notes = final_graph_state.get("evaluation_notes", [])
                msg_count = len(eval_messages)
            logger.info(f"[Voice] Session ended | messages={msg_count} | eval_notes={len(eval_notes)}")

            if msg_count > 2:
                logger.info("[Voice] Running evaluation in background thread...")
                import threading

                def run_eval():
                    try:
                        logger.info("[Voice/Eval] Background evaluation started")
                        report = evaluation_service.evaluate_interview(
                            history=eval_messages,
                            job_details=job_details,
                            candidate_details=candidate_details,
                            evaluation_notes=eval_notes,
                        )
                        job_id = job_details.get("job_id", 0)
                        candidate_id = candidate_details.get("candidate_id", 0)
                        if job_id and candidate_id:
                            EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluations")
                            os.makedirs(EVAL_DIR, exist_ok=True)
                            eval_path = os.path.join(EVAL_DIR, f"job_{job_id}_candidate_{candidate_id}.json")
                            with open(eval_path, "w") as f:
                                json.dump(report, f, indent=4)
                            logger.info(f"[Voice/Eval] Evaluation saved: {eval_path}")
                            logger.info(f"[Voice/Eval]   Verdict: {report.get('verdict')} | Tech: {report.get('technical_score')} | Behavioral: {report.get('behavioral_score')}")
                    except Exception as ex:
                        logger.error(f"[Voice/Eval] Evaluation FAILED: {type(ex).__name__}: {ex}")

                threading.Thread(target=run_eval, daemon=False).start()

    def _transcribe(self, audio_bytes: bytes) -> str:
        """Convert raw PCM bytes -> WAV -> Whisper transcription."""
        try:
            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)   # 16-bit
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)
            wav_io.seek(0)

            # vad_filter=True uses Whisper's built-in speech activity detection
            # to skip silent/noise-only segments before attempting transcription
            segments, _ = whisper_model.transcribe(
                wav_io,
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400}
            )
            return " ".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.error(f"[Voice] Transcription error: {e}")
            return ""

    async def _speak_and_send(self, websocket: WebSocket, text: str, lock: Optional[asyncio.Lock] = None) -> bool:
        """
        Generate TTS audio, collect ALL chunks, send as ONE payload.
        The 'speaking_done' signal is embedded in the audio message so
        the client knows when to signal 'audio_done' back after playback.
        """
        try:
            await _send(websocket, {
                "type": "status",
                "message": "AI is preparing to speak...",
                "state": "speaking"
            }, lock)
            logger.debug(f"[Voice] Generating TTS for: '{text[:60]}...'")

            communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
            full_audio = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    full_audio.extend(chunk["data"])

            if full_audio:
                b64 = base64.b64encode(full_audio).decode("utf-8")
                await _send(websocket, {"type": "audio", "data": b64}, lock)
                logger.info(f"[Voice] Audio sent: {len(full_audio)} bytes")
                return True
            else:
                logger.warning("[Voice] Warning: TTS produced no audio. Sending speaking_done anyway.")
                await _send(websocket, {"type": "speaking_done"}, lock)
                return False

        except asyncio.CancelledError:
            logger.info("[Voice] TTS cancelled (barge-in).")
            await _send(websocket, {"type": "speaking_done"}, lock)
            raise
        except Exception as e:
            logger.error(f"[Voice] TTS error: {e}")
            # Even on error, ungate the microphone
            await _send(websocket, {"type": "speaking_done"}, lock)
            return False


manager = VoiceConnectionManager()


async def handle_voice_session(
    websocket: WebSocket,
    job_details: dict,
    candidate_details: dict,
    resume_profile: dict,
    question_file: dict,
):
    """Entry point called from main.py WebSocket handler."""
    await manager.handle_session(websocket, job_details, candidate_details, resume_profile, question_file)
