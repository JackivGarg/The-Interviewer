import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import streamlit.components.v1 as components
from frontend.services.api import get_token, get_websocket_url

st.set_page_config(page_title="Live Interview", page_icon="🎙️", layout="wide")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "candidate":
    st.error("Please login as Candidate to access this page.")
    st.switch_page("app.py")

job_id = st.session_state.get("selected_job_id")
token = get_token()

if not job_id:
    st.error("No job selected. Please select a job to start the interview.")
    if st.button("Go to Dashboard"):
        st.switch_page("app.py")
    st.stop()

st.title("🎙️ Live Voice Interview")
st.markdown("Click **Start Interview** and allow microphone access. The AI interviewer will speak first, then it's your turn.")

ws_base_url = get_websocket_url()

html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Voice Interview</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }}

        .container {{ max-width: 800px; margin: 0 auto; }}

        .status-panel {{
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            text-align: center;
            border: 1px solid #0f3460;
        }}

        #status-icon {{ font-size: 2.5em; margin-bottom: 8px; display: block; }}
        #status-text {{ font-size: 1.1em; color: #a8dadc; }}
        #state-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
            margin-top: 8px;
            background: #0f3460;
            color: #a8dadc;
        }}

        /* Level meter bar */
        .meter-wrap {{
            background: #0f3460;
            border-radius: 8px;
            height: 12px;
            margin-top: 12px;
            overflow: hidden;
        }}
        #level-bar {{
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #4ade80, #facc15, #f87171);
            border-radius: 8px;
            transition: width 0.1s ease;
        }}

        #mic-btn {{
            display: block;
            width: 100%;
            padding: 14px;
            font-size: 1em;
            font-weight: bold;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            background: #4CAF50;
            color: white;
            margin-bottom: 16px;
            transition: background 0.3s;
        }}
        #mic-btn.active {{ background: #ef4444; }}
        #mic-btn:disabled {{ background: #555; cursor: not-allowed; }}

        .chat-box {{
            background: #16213e;
            border-radius: 12px;
            padding: 16px;
            height: 280px;
            overflow-y: auto;
            border: 1px solid #0f3460;
        }}
        .chat-box::-webkit-scrollbar {{ width: 6px; }}
        .chat-box::-webkit-scrollbar-thumb {{ background: #0f3460; border-radius: 3px; }}

        .msg {{ padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; max-width: 90%; line-height: 1.4; font-size: 0.95em; }}
        .msg-user {{ background: #0f3460; color: #a8dadc; margin-left: auto; text-align: right; }}
        .msg-ai {{ background: #1b4332; color: #86efac; }}
        .msg-label {{ font-size: 0.75em; opacity: 0.7; margin-bottom: 2px; }}

        .debug-panel {{
            margin-top: 12px;
            background: #111;
            border-radius: 8px;
            padding: 10px;
            font-family: monospace;
            font-size: 0.78em;
            color: #888;
            max-height: 100px;
            overflow-y: auto;
        }}
        .debug-panel::-webkit-scrollbar {{ width: 4px; }}
        .debug-panel::-webkit-scrollbar-thumb {{ background: #333; }}
    </style>
</head>
<body>
    <div class="container">
        <button id="mic-btn">🎙️ Start Interview</button>

        <div class="status-panel">
            <span id="status-icon">⏳</span>
            <div id="status-text">Click Start to connect</div>
            <div id="state-badge">IDLE</div>
            <div class="meter-wrap">
                <div id="level-bar"></div>
            </div>
        </div>

        <div class="chat-box" id="chat-log"></div>

        <div class="debug-panel" id="debug-log">Debug logs will appear here...<br></div>
    </div>

    <script>
        const JOB_ID = {job_id};
        const TOKEN = "{token}";
        const WS_URL = `{ws_base_url}/interview/${{JOB_ID}}?token=${{TOKEN}}`;

        // ── State ─────────────────────────────────────────────────
        let ws = null;
        let audioCtx = null;
        let mediaStream = null;
        let scriptProcessor = null;
        let isSessionActive = false;

        // AI turn-taking: we pause sending audio to the server while AI is playing
        let aiIsSpeaking = false;
        let currentAudio = null; // The playing HTMLAudioElement

        const btn        = document.getElementById("mic-btn");
        const statusIcon = document.getElementById("status-icon");
        const statusText = document.getElementById("status-text");
        const stateBadge = document.getElementById("state-badge");
        const levelBar   = document.getElementById("level-bar");
        const chatLog    = document.getElementById("chat-log");
        const debugLog   = document.getElementById("debug-log");

        // ── Helpers ───────────────────────────────────────────────
        function dbg(msg) {{
            const d = new Date();
            const ts = `${{d.getHours().toString().padStart(2,'0')}}:${{d.getMinutes().toString().padStart(2,'0')}}:${{d.getSeconds().toString().padStart(2,'0')}}`;
            debugLog.innerHTML += `<span style="color:#555">[${{ts}}]</span> ${{msg}}<br>`;
            debugLog.scrollTop = debugLog.scrollHeight;
        }}

        function setStatus(icon, text, state, color) {{
            statusIcon.innerText = icon;
            statusText.innerText = text;
            stateBadge.innerText = state;
            stateBadge.style.background = color || '#0f3460';
        }}

        function addMessage(role, text) {{
            const wrap = document.createElement("div");
            wrap.className = `msg msg-${{role}}`;
            const label = document.createElement("div");
            label.className = "msg-label";
            label.innerText = role === 'user' ? 'You' : 'AI Interviewer';
            const content = document.createElement("div");
            content.innerText = text;
            wrap.appendChild(label);
            wrap.appendChild(content);
            chatLog.appendChild(wrap);
            chatLog.scrollTop = chatLog.scrollHeight;
        }}

        function sendWS(obj) {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify(obj));
            }}
        }}

        // ── Audio Playback ────────────────────────────────────────
        function playAudio(base64Data) {{
            dbg("Playing AI audio...");
            setStatus("🔊", "AI Interviewer is speaking...", "AI SPEAKING", "#7c3aed");
            aiIsSpeaking = true;

            const audioSrc = "data:audio/mp3;base64," + base64Data;
            if (currentAudio) {{
                currentAudio.pause();
                currentAudio = null;
            }}

            currentAudio = new Audio(audioSrc);

            currentAudio.onended = () => {{
                dbg("Audio finished playing. Signaling server.");
                currentAudio = null;
                aiIsSpeaking = false;
                // Tell the backend we finished playing - it will resume listening
                sendWS({{ type: "audio_done" }});
                setStatus("🎙️", "Your turn — please speak now", "LISTENING", "#15803d");
            }};

            currentAudio.onerror = (e) => {{
                dbg("Audio playback error: " + e.message);
                currentAudio = null;
                aiIsSpeaking = false;
                sendWS({{ type: "audio_done" }});
                setStatus("⚠️", "Audio error. Please speak.", "LISTENING", "#15803d");
            }};

            currentAudio.play().catch(err => {{
                dbg("play() rejected: " + err.message + " (user gesture may be needed)");
                // If play is rejected (autoplay policy), reset state
                aiIsSpeaking = false;
                sendWS({{ type: "audio_done" }});
                setStatus("🎙️", "Speak now (audio blocked by browser)", "LISTENING", "#15803d");
            }});
        }}

        // ── WebSocket ─────────────────────────────────────────────
        function initWebSocket() {{
            dbg("Connecting to: " + WS_URL);
            ws = new WebSocket(WS_URL);

            ws.onopen = () => {{
                dbg("WebSocket connected.");
                // Fix: reset button from 'Connecting...' to active session state
                btn.innerText = "⏹️ End Interview";
                btn.classList.add("active");
                btn.disabled = false;
                setStatus("✅", "Connected! Waiting for AI greeting...", "CONNECTED", "#0f3460");
            }};

            ws.onmessage = (event) => {{
                if (typeof event.data !== "string") return;
                let msg;
                try {{ msg = JSON.parse(event.data); }} catch(e) {{ return; }}

                const t = msg.type;

                if (t === "ping") {{
                    // Server keepalive ping — respond immediately to keep the connection alive
                    sendWS({{ type: "pong" }});

                }} else if (t === "status") {{
                    // Update status. If AI is speaking, only allow 'thinking' or 'speaking' overrides
                    // to avoid confusing transitions, but ensure the user sees the 'AI is thinking' lag.
                    if (!aiIsSpeaking || msg.state === "thinking" || msg.state === "speaking") {{
                        const statusColors = {{
                            "listening": "#15803d",
                            "thinking": "#1d4ed8",
                            "processing": "#6b21a8",
                            "speaking": "#c2410c"
                        }};
                        const color = msg.color || statusColors[msg.state] || "#1f2937";
                        setStatus(msg.icon || "⏳", msg.message, msg.state, color);
                    }}
                }} else if (t === "text") {{
                    addMessage(msg.role === 'user' ? 'user' : 'ai', msg.text);

                }} else if (t === "audio") {{
                    dbg("Received audio payload (" + msg.data.length + " chars b64).");
                    playAudio(msg.data);

                }} else if (t === "speaking_done") {{
                    // Fallback: server signals TTS is done (e.g., on error)
                    // In case the audio element never fires onended, this unblocks the mic
                    dbg("Received speaking_done fallback from server.");
                    if (currentAudio) {{
                        currentAudio.pause();
                        currentAudio = null;
                    }}
                    aiIsSpeaking = false;
                    sendWS({{ type: "audio_done" }});
                    setStatus("🎙️", "Your turn — please speak now", "LISTENING", "#15803d");

                }} else if (t === "clear") {{
                    dbg("Received clear signal.");
                    if (currentAudio) {{
                        currentAudio.pause();
                        currentAudio = null;
                    }}
                    aiIsSpeaking = false;

                }} else if (t === "interview_complete") {{
                    dbg("Interview completed by AI.");
                    setStatus("🏁", msg.message || "Interview complete!", "COMPLETED", "#15803d");
                    // Gracefully end session
                    isSessionActive = false;
                    aiIsSpeaking = false;
                    teardownMicrophone();
                    if (ws) ws.close();
                    btn.innerText = "🎙️ Start New Interview";
                    btn.classList.remove("active");
                    btn.disabled = false;
                }}
            }};

            ws.onclose = (e) => {{
                dbg(`WebSocket closed. Code: ${{e.code}}, Reason: ${{e.reason}}`);
                setStatus("🔌", "Disconnected.", "ENDED", "#555");
                teardownMicrophone();
                isSessionActive = false;
                btn.innerText = "🎙️ Start Interview";
                btn.classList.remove("active");
                btn.disabled = false;
            }};

            ws.onerror = (e) => {{
                dbg("WebSocket error occurred.");
                setStatus("❌", "Connection error. Retry.", "ERROR", "#b91c1c");
            }};
        }}

        function getIconForState(state) {{
            const map = {{ listening: "🎙️", processing: "⏳", thinking: "🤖", speaking: "🔊" }};
            return map[state] || "ℹ️";
        }}
        function getColorForState(state) {{
            const map = {{ listening: "#15803d", processing: "#92400e", thinking: "#1d4ed8", speaking: "#7c3aed" }};
            return map[state] || "#0f3460";
        }}

        // ── Microphone ────────────────────────────────────────────
        async function requestMicPermission() {{
            try {{
                mediaStream = await navigator.mediaDevices.getUserMedia({{ audio: {{
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }} }});
                dbg("Microphone access granted.");

                audioCtx = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate: 16000 }});
                const source = audioCtx.createMediaStreamSource(mediaStream);

                // Buffer size 4096 = ~256ms per chunk at 16kHz
                scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);

                scriptProcessor.onaudioprocess = (e) => {{
                    if (!isSessionActive || !ws || ws.readyState !== WebSocket.OPEN) return;

                    const input = e.inputBuffer.getChannelData(0); // Float32
                    const pcm = new Int16Array(input.length);
                    let maxVal = 0;

                    for (let i = 0; i < input.length; i++) {{
                        const s = Math.max(-1, Math.min(1, input[i]));
                        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                        const abs = Math.abs(pcm[i]);
                        if (abs > maxVal) maxVal = abs;
                    }}

                    // Update visual level meter regardless of AI state
                    const levelPct = Math.min(100, (maxVal / 32767) * 100 * 3);
                    levelBar.style.width = levelPct + "%";

                    // CRITICAL: Only send audio bytes when AI is NOT speaking
                    // This prevents mic echo from triggering false VAD on the server
                    if (!aiIsSpeaking) {{
                        ws.send(pcm.buffer);
                    }}
                }};

                source.connect(scriptProcessor);
                scriptProcessor.connect(audioCtx.destination);

                isSessionActive = true;
                btn.innerText = "⏹️ End Interview";
                btn.classList.add("active");
                dbg("Audio pipeline started.");
                return true;

            }} catch(err) {{
                dbg("Mic error: " + err.message);
                setStatus("❌", "Microphone access denied. Please allow microphone.", "ERROR", "#b91c1c");
                btn.innerText = "🎙️ Start Interview";
                btn.classList.remove("active");
                btn.disabled = false;
                isSessionActive = false;
                return false;
            }}
        }}

        function teardownMicrophone() {{
            if (scriptProcessor) {{ scriptProcessor.disconnect(); scriptProcessor = null; }}
            if (mediaStream) {{ mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }}
            if (audioCtx) {{ audioCtx.close().catch(()=>{{}}); audioCtx = null; }}
            if (currentAudio) {{ currentAudio.pause(); currentAudio = null; }}
            levelBar.style.width = "0%";
            dbg("Microphone and audio pipeline torn down.");
        }}

        // ── Button ────────────────────────────────────────────────
        btn.onclick = async () => {{
            if (!isSessionActive) {{
                btn.disabled = true;
                btn.innerText = "Requesting mic...";
                setStatus("📡", "Requesting microphone access...", "CONNECTING", "#1d4ed8");
                // Request mic FIRST so it's ready when WebSocket connects
                const micReady = await requestMicPermission();
                if (micReady) {{
                    btn.innerText = "Connecting...";
                    setStatus("📡", "Connecting to interview server...", "CONNECTING", "#1d4ed8");
                    initWebSocket();
                }}
            }} else {{
                dbg("User ended interview.");
                if (ws) ws.close();
                teardownMicrophone();
                isSessionActive = false;
                aiIsSpeaking = false;
                btn.innerText = "🎙️ Start Interview";
                btn.classList.remove("active");
                btn.disabled = false;
                setStatus("🏁", "Interview ended.", "ENDED", "#555");
            }}
        }};

        dbg("Interview page loaded. Ready.");
    </script>
</body>
</html>
"""

components.html(html_code, height=700)

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")
