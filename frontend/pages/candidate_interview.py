import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import streamlit.components.v1 as components
from frontend.services.api import get_token

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
st.markdown("Ensure your microphone is connected. The interviewer will speak to you shortly.")

# We inject the custom HTML/JS component to handle WebSockets and Web Audio API
html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Voice Interview</title>
    <style>
        body {{ font-family: sans-serif; text-align: center; color: #333; }}
        #status {{ font-size: 1.2em; margin-top: 20px; font-weight: bold; }}
        .pulse {{
            animation: pulse-animation 1.5s infinite;
        }}
        @keyframes pulse-animation {{
            0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7); }}
            70% {{ transform: scale(1); box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }}
            100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }}
        }}
        #mic-btn {{
            background-color: #4CAF50; color: white; border: none; padding: 15px 32px;
            text-align: center; display: inline-block; font-size: 16px; margin: 4px 2px;
            cursor: pointer; border-radius: 50px; transition: background-color 0.3s;
        }}
        #mic-btn.recording {{ background-color: #f44336; }}
        #chat-log {{
            margin-top: 20px; text-align: left; max-height: 200px;
            overflow-y: auto; border: 1px solid #ccc; padding: 10px; border-radius: 5px;
            background: #fff;
        }}
        .user-msg {{ color: #2196F3; font-weight: bold; margin-bottom: 5px; }}
        .ai-msg {{ color: #4CAF50; margin-bottom: 5px; }}
    </style>
</head>
<body>
    <button id="mic-btn">Start Interview</button>
    <div id="status">Click Start to connect</div>
    <div id="chat-log"></div>

    <script>
        const job_id = {job_id};
        const token = "{token}";
        const wsUrl = `ws://localhost:8000/api/ws/interview/${{job_id}}?token=${{token}}`;
        
        let ws;
        let audioContext;
        let mediaStream;
        let scriptNode;
        let isRecording = false;
        
        // For playback
        let audioQueue = [];
        let isPlaying = false;
        
        const btn = document.getElementById("mic-btn");
        const statusDiv = document.getElementById("status");
        const chatLog = document.getElementById("chat-log");

        function addLog(role, text) {{
            const d = document.createElement("div");
            d.className = role === 'user' ? 'user-msg' : 'ai-msg';
            d.innerText = (role === 'user' ? "You: " : "AI: ") + text;
            chatLog.appendChild(d);
            chatLog.scrollTop = chatLog.scrollHeight;
        }}

        function initWebSocket() {{
            ws = new WebSocket(wsUrl);
            ws.onopen = () => {{
                statusDiv.innerText = "Connected! Waiting for AI...";
                startRecording();
            }};
            
            ws.onmessage = async (event) => {{
                if (typeof event.data === "string") {{
                    const msg = JSON.parse(event.data);
                    if (msg.type === "clear") {{
                        // Barge-in detected! Clear queue
                        audioQueue = [];
                        isPlaying = false;
                        document.querySelectorAll('audio').forEach(a => a.pause());
                    }} else if (msg.type === "text") {{
                        addLog(msg.role, msg.text);
                    }} else if (msg.type === "audio") {{
                        // Base64 MP3 chunk
                        const audioSrc = "data:audio/mp3;base64," + msg.data;
                        audioQueue.push(audioSrc);
                        playNextAudio();
                    }}
                }}
            }};
            
            ws.onclose = () => {{
                statusDiv.innerText = "Disconnected.";
                stopRecording();
            }};
            
            ws.onerror = (e) => {{
                console.error("WS error", e);
                statusDiv.innerText = "Connection Error.";
            }};
        }}
        
        function playNextAudio() {{
            if (isPlaying || audioQueue.length === 0) return;
            isPlaying = true;
            
            const src = audioQueue.shift();
            const audio = new Audio(src);
            
            audio.onended = () => {{
                isPlaying = false;
                audio.remove();
                if(audioQueue.length > 0) playNextAudio();
            }};
            
            audio.onerror = () => {{
                isPlaying = false;
                if(audioQueue.length > 0) playNextAudio();
            }};
            
            audio.play().catch(e => {{
                console.error("Audio play error", e);
                isPlaying = false;
                playNextAudio();
            }});
        }}

        async function startRecording() {{
            try {{
                mediaStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                audioContext = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate: 16000 }});
                const source = audioContext.createMediaStreamSource(mediaStream);
                
                // 4096 framing ~250ms chunks (at 16kHz)
                scriptNode = audioContext.createScriptProcessor(4096, 1, 1);
                
                scriptNode.onaudioprocess = (audioProcessingEvent) => {{
                    if (!isRecording || ws.readyState !== WebSocket.OPEN) return;
                    
                    const inputBuffer = audioProcessingEvent.inputBuffer;
                    const inputData = inputBuffer.getChannelData(0); // Float32Array from -1.0 to 1.0
                    
                    // Simple VAD logic to send interrupt if user starts talking loud while AI is playing
                    let maxEnergy = 0;
                    
                    // Convert Float32 to Int16
                    const pcmData = new Int16Array(inputData.length);
                    for (let i = 0; i < inputData.length; ++i) {{
                        let s = Math.max(-1, Math.min(1, inputData[i]));
                        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                        maxEnergy = Math.max(maxEnergy, Math.abs(pcmData[i]));
                    }}
                    
                    if (isPlaying && maxEnergy > 2000) {{
                        // User barge-in detected!
                        ws.send(JSON.stringify({{ type: "interrupt" }}));
                        // We also clear our own local playback queue to stop immediately
                        audioQueue = [];
                        isPlaying = false;
                        document.querySelectorAll('audio').forEach(a => a.pause());
                    }}
                    
                    ws.send(pcmData.buffer); // Send binary data ArrayBuffer
                }};
                
                source.connect(scriptNode);
                scriptNode.connect(audioContext.destination);
                
                isRecording = true;
                btn.innerText = "Stop Interview";
                btn.classList.add("recording");
                btn.classList.add("pulse");
                statusDiv.innerText = "Interviewer is listening...";
                
            }} catch (err) {{
                console.error('Error accessing microphone:', err);
                statusDiv.innerText = "Microphone access denied.";
            }}
        }}

        function stopRecording() {{
            isRecording = false;
            btn.innerText = "Start Interview";
            btn.classList.remove("recording");
            btn.classList.remove("pulse");
            statusDiv.innerText = "Interview Stopped.";
            
            if (scriptNode) {{
                scriptNode.disconnect();
                scriptNode = null;
            }}
            if (mediaStream) {{
                mediaStream.getTracks().forEach(track => track.stop());
                mediaStream = null;
            }}
            if (audioContext) {{
                audioContext.close();
                audioContext = null;
            }}
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.close();
            }}
        }}

        btn.onclick = () => {{
            if (!isRecording) {{
                initWebSocket();
            }} else {{
                stopRecording();
            }}
        }};
    </script>
</body>
</html>
"""

# Render the HTML component
components.html(html_code, height=600)

st.markdown("---")
if st.button("End Interview & Return"):
    st.switch_page("app.py")
