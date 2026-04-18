"""
Quick smoke test for the voice_service after the retry/cascade fix.
Run from the project root: venv\Scripts\python test_gemini.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("  Gemini API Smoke Test")
print("=" * 60)

api_key = os.getenv("GOOGLE_API_KEY", "")
print(f"API Key present: {bool(api_key)}")
if api_key:
    print(f"API Key prefix: {api_key[:12]}...")

try:
    from google import genai
    from google.genai import types
    print(f"google-genai version: {genai.__version__}")
except ImportError as e:
    print(f"IMPORT ERROR: {e}")
    sys.exit(1)

client = genai.Client(api_key=api_key)

models_to_test = ["gemini-2.0-flash", "gemini-1.5-flash"]

for model in models_to_test:
    print(f"\nTesting model: {model}")
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Please ask me one technical interview question.")]
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction="You are a professional technical interviewer.",
                temperature=0.7,
                max_output_tokens=100,
            ),
        )
        result = resp.text.strip() if resp.text else ""
        if result:
            print(f"  SUCCESS: {result[:120]}...")
        else:
            print(f"  WARNING: Empty response from {model}")
    except Exception as e:
        print(f"  ERROR [{type(e).__name__}]: {str(e)[:300]}")

print("\n" + "=" * 60)
print("  Testing VoiceInterviewService cascade")
print("=" * 60)
from backend.voice_service import voice_service

history = [
    {"role": "model", "parts": ["Hello! Please introduce yourself."]},
    {"role": "user", "parts": ["Hi, I'm Jack, a 2nd year CS student."]},
]
job_details = {
    "title": "Software Engineer Intern",
    "description": "Backend development with Python",
    "skills_required": "Python, REST APIs",
    "questions_to_ask": "Ask about Python experience",
}
candidate_details = {
    "name": "Jack",
    "experience": "2 years student",
    "skills": "Python, JavaScript",
    "additional_info": "",
}

try:
    response = voice_service.get_response(history, job_details, candidate_details)
    print(f"VoiceService response: {response[:200]}")
except Exception as e:
    print(f"VoiceService ERROR: {type(e).__name__}: {e}")
