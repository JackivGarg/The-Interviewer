import asyncio
import base64
import json
import numpy as np
import io
import wave
from fastapi import WebSocket, WebSocketDisconnect
from faster_whisper import WhisperModel
import edge_tts
from backend.voice_service import voice_service

# Load Whisper model globally to avoid reloading
# Using tiny.en for maximum speed
whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

class VoiceConnectionManager:
    def __init__(self):
        self.active_tasks = set()
    
    async def handle_session(self, websocket: WebSocket, job_details: dict, candidate_details: dict):
        await websocket.accept()
        
        # Session state
        audio_buffer = bytearray()
        is_speaking = False
        silence_frames = 0
        SILENCE_THRESHOLD = 50  # ~1 second of silence at 50 frames/sec
        ENERGY_THRESHOLD = 500  # Will need tuning based on mic
        
        # History for LLM
        history = []
        
        current_playback_task = None

        try:
            # Send initial greeting
            greeting = "Hello! I am ready to begin the interview. Could you please introduce yourself?"
            history.append({"role": "model", "parts": [greeting]})
            await self._speak_and_send(websocket, greeting)
            
            while True:
                # Receive message (binary for audio, text for control)
                message = await websocket.receive()
                
                if "text" in message:
                    data = json.loads(message["text"])
                    if data.get("type") == "interrupt":
                        # Client detected speech! Barge-in time.
                        if current_playback_task and not current_playback_task.done():
                            current_playback_task.cancel()
                        # Tell client to clear its buffer just in case
                        await websocket.send_text(json.dumps({"type": "clear"}))
                        continue
                        
                elif "bytes" in message:
                    chunk = message["bytes"]
                    # Audio chunk (Int16, 16kHz mono)
                    audio_array = np.frombuffer(chunk, dtype=np.int16)
                    energy = np.sqrt(np.mean(audio_array.astype(np.float32)**2))
                    
                    if energy > ENERGY_THRESHOLD:
                        if not is_speaking:
                            is_speaking = True
                            # If AI is currently speaking, client-side VAD might have missed it, 
                            # or we rely purely on client interrupt. We'll also cancel here as fallback.
                            if current_playback_task and not current_playback_task.done():
                                current_playback_task.cancel()
                                await websocket.send_text(json.dumps({"type": "clear"}))
                        
                        silence_frames = 0
                        audio_buffer.extend(chunk)
                        
                    elif is_speaking:
                        silence_frames += 1
                        audio_buffer.extend(chunk)
                        
                        if silence_frames > SILENCE_THRESHOLD:
                            # End of utterance
                            is_speaking = False
                            silence_frames = 0
                            
                            # Process audio buffer
                            final_audio = bytes(audio_buffer)
                            audio_buffer.clear()
                            
                            # Transcribe
                            transcription = await asyncio.to_thread(self._transcribe, final_audio)
                            
                            if transcription.strip():
                                # Send text to frontend for debug/captions
                                await websocket.send_text(json.dumps({"type": "text", "role": "user", "text": transcription}))
                                
                                # Add to history
                                history.append({"role": "user", "parts": [transcription]})
                                
                                # Generate AI response
                                # Running in thread to not block WS
                                ai_response = await asyncio.to_thread(
                                    voice_service.get_response, history, job_details, candidate_details
                                )
                                history.append({"role": "model", "parts": [ai_response]})
                                
                                # Send text to frontend
                                await websocket.send_text(json.dumps({"type": "text", "role": "ai", "text": ai_response}))
                                
                                # Start TTS playback
                                current_playback_task = asyncio.create_task(self._speak_and_send(websocket, ai_response))
                                
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"WS Error: {e}")
            
    def _transcribe(self, audio_bytes: bytes) -> str:
        # Convert raw PCM to a format faster_whisper can read (it accepts file paths or file-like objects with wav headers)
        # Create an in-memory wav file
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) # 16-bit
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_bytes)
            
        wav_io.seek(0)
        
        segments, _ = whisper_model.transcribe(wav_io, beam_size=1)
        text = " ".join([m.text for m in segments])
        return text

    async def _speak_and_send(self, websocket: WebSocket, text: str):
        try:
            communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural") # Professional male voice
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    # Send audio chunk as json with base64
                    b64_audio = base64.b64encode(chunk["data"]).decode("utf-8")
                    await websocket.send_text(json.dumps({
                        "type": "audio",
                        "data": b64_audio
                    }))
        except asyncio.CancelledError:
            print("TTS Playback cancelled due to barge-in")
            raise
        except Exception as e:
            print(f"TTS Error: {e}")

manager = VoiceConnectionManager()

async def handle_voice_session(websocket: WebSocket, job_details: dict, candidate_details: dict):
    await manager.handle_session(websocket, job_details, candidate_details)
