import os
import time
from google import genai
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class VoiceInterviewService:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    def _generate_system_prompt(self, job_details: Dict[str, Any], candidate_details: Dict[str, Any]) -> str:
        """Creates a specialized prompt for the AI to act as a professional interviewer."""
        prompt = f"""
You are an expert technical interviewer for a company hiring for the position: {job_details.get('title')}.

INTERVIEW CONTEXT:
Job Title: {job_details.get('title')}
Job Description: {job_details.get('description')}
Required Skills: {job_details.get('skills_required')}

CANDIDATE PROFILE:
Name: {candidate_details.get('name')}
Experience: {candidate_details.get('experience')}
Skills: {candidate_details.get('skills')}
Resume / Additional Info: {candidate_details.get('additional_info')}

INTERVIEW PROTOCOL (FOLLOW STRICTLY):
1. Ask ONE technical or behavioral question at a time. Do not overwhelm the candidate.
2. Your tone should be professional, encouraging, and firm.
3. Focus on these specific questions if provided: {job_details.get('questions_to_ask')}
4. If the candidate gives a short or vague answer, ask a follow-up ("Could you elaborate on that?").
5. Keep your responses concise (under 3 sentences).
6. CRITICAL: If you feel the interview has reached a natural conclusion or you have enough information, end with the exact phrase: "[END_INTERVIEW]"
7. STRICT RULE: Do not explain your logic. Just speak directly to the candidate.
"""
        return prompt

    def _log(self, message: str) -> None:
        """Print a log message safely on Windows (avoids UnicodeEncodeError)."""
        try:
            print(message)
        except UnicodeEncodeError:
            # Windows console may not support certain chars — strip to ASCII
            print(message.encode("ascii", errors="replace").decode("ascii"))

    def get_response(
        self,
        history: List[Dict[str, Any]],
        job_details: Dict[str, Any],
        candidate_details: Dict[str, Any],
    ) -> str:
        """
        Generates the next interviewer response.

        Strategy:
        - Try self.model_name first (default: gemini-2.0-flash)
        - On RESOURCE_EXHAUSTED (quota/rate-limit), retry up to 3x with exponential backoff
        - If all retries on primary model exhausted, cascade to gemini-1.5-flash
        - If all models fail, return a graceful context-aware fallback
        """
        from google.genai import types

        system_instruction = self._generate_system_prompt(job_details, candidate_details)

        # Window history to last 10 turns to keep cost / latency low
        recent_history = history[-10:] if len(history) > 10 else history

        # Build Gemini Content objects
        contents = []
        for msg in recent_history:
            role = "user" if msg.get("role") == "user" else "model"
            if "parts" in msg:
                raw_parts = msg["parts"]
                parts = (
                    [types.Part.from_text(text=p) for p in raw_parts]
                    if isinstance(raw_parts, list)
                    else [types.Part.from_text(text=str(raw_parts))]
                )
            elif "content" in msg:
                parts = [types.Part.from_text(text=msg["content"])]
            else:
                parts = []
            contents.append(types.Content(role=role, parts=parts))

        # Model cascade: primary -> fallback
        models_to_try = [self.model_name, "gemini-1.5-flash"]

        for model in models_to_try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self._log(f"[VoiceService] Calling model={model} attempt={attempt + 1}/{max_retries}")
                    response = self.client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.7,
                            max_output_tokens=200,
                        ),
                    )
                    result = response.text.strip() if response.text else ""
                    if not result:
                        self._log(f"[VoiceService] {model} returned empty text.")
                        return "I see. Could you tell me a bit more about your background and what drew you to this role?"
                    self._log(f"[VoiceService] OK model={model}: {result[:80]}...")
                    return result

                except Exception as e:
                    error_name = type(e).__name__
                    error_msg = str(e)
                    is_quota_error = (
                        "RESOURCE_EXHAUSTED" in error_msg
                        or "quota" in error_msg.lower()
                        or "429" in error_msg
                        or "rateLimitExceeded" in error_msg
                    )
                    is_last_attempt = attempt == max_retries - 1

                    self._log(
                        f"[VoiceService] ERROR {error_name} | model={model} | attempt={attempt + 1} | quota={is_quota_error}"
                    )
                    self._log(f"[VoiceService] Detail: {error_msg[:300]}")

                    if is_quota_error:
                        if is_last_attempt:
                            # All retries exhausted for this model -> cascade to next
                            self._log(f"[VoiceService] All retries exhausted for {model}. Trying next model...")
                            break
                        else:
                            # Rate-limited: wait with exponential backoff (2s, 4s, 8s)
                            wait_sec = 2 ** (attempt + 1)
                            self._log(f"[VoiceService] Rate limited. Waiting {wait_sec}s before retry...")
                            time.sleep(wait_sec)
                    else:
                        # Non-retryable error (auth, bad request) — cascade immediately
                        self._log(f"[VoiceService] Non-retryable error on {model}. Cascading...")
                        break

        # All models and retries exhausted
        self._log("[VoiceService] CRITICAL: All models exhausted. Returning graceful fallback.")
        return (
            "That's interesting. Could you walk me through your most significant technical achievement so far?"
        )


voice_service = VoiceInterviewService()
