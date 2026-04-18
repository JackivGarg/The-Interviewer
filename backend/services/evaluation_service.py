import os
import json
from google import genai
from google.genai import types
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

class EvaluationService:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.model_name = model_name
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    def _generate_evaluation_prompt(self, history: List[Dict[str, Any]], job_details: Dict[str, Any], candidate_details: Dict[str, Any]) -> str:
        """
        Takes the interview history and generates a structured JSON report.
        """
        # Format the transcript
        transcript = ""
        for msg in history:
            role = "Candidate" if msg['role'] == 'user' else "Interviewer"
            parts = msg.get('parts', [])
            content = " ".join(parts) if isinstance(parts, list) else str(parts)
            transcript += f"{role}: {content}\n\n"

        prompt = f"""
You are an expert technical recruiter and Engineering Manager evaluating a candidate based on an interview transcript.

JOB TITLE: {job_details.get('title')}
REQUIRED SKILLS: {job_details.get('skills_required')}

CANDIDATE: {candidate_details.get('name')}
RESUME SUMMARY/SKILLS: {candidate_details.get('skills')}

INTERVIEW TRANSCRIPT:
{transcript}

Please evaluate the candidate's performance and return EXCLUSIVELY a JSON object with the following schema:
{{
    "technical_score": float (0-10),
    "behavioral_score": float (0-10),
    "confidence_score": float (0-10),
    "summary": "string (1-2 paragraph summary of their performance)",
    "strengths": ["string", "string"],
    "weaknesses": ["string", "string"],
    "verdict": "Hire" or "No Hire" or "Strong Hire"
}}
"""
        return prompt

    def evaluate_interview(self, history: List[Dict[str, Any]], job_details: Dict[str, Any], candidate_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes the interview history and generates a structured evaluation report.
        """
        print(f"[EvaluationService] Starting evaluation for {candidate_details.get('name')}...")
        prompt = self._generate_evaluation_prompt(history, job_details, candidate_details)
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            raw_text = response.text.strip()
            # Clean possible markdown formatting
            if raw_text.startswith("```"):
                # Extract content between first and last triple-backticks
                lines = raw_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines[-1].startswith("```"): lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
            
            return json.loads(raw_text)
        except Exception as e:
            print(f"[EvaluationService] Error generating report: {type(e).__name__}: {e}")
            return {
                "technical_score": 0,
                "behavioral_score": 0,
                "confidence_score": 0,
                "summary": "Evaluation failed due to a technical error.",
                "strengths": [],
                "weaknesses": [],
                "verdict": "Error"
            }

evaluation_service = EvaluationService()
