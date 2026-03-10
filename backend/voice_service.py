import os
import google.generativeai as genai
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class VoiceInterviewService:
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.model = genai.GenerativeModel(model_name)
        
    def _generate_system_prompt(self, job_details: Dict[str, Any], candidate_details: Dict[str, Any]) -> str:
        """
        Creates a specialized prompt for the AI to act as a professional interviewer.
        """
        prompt = f"""
You are an expert technical interviewer for a company hiring for the position: {job_details.get('title')}.

JOB DESCRIPTION:
{job_details.get('description')}

REQUIRED SKILLS:
{job_details.get('skills_required')}

CANDIDATE PROFILE:
Name: {candidate_details.get('name')}
Experience: {candidate_details.get('experience')}
Skills: {candidate_details.get('skills')}

INTERVIEW PROTOCOL:
1. Start by welcoming the candidate and asking them to introduce themselves briefly.
2. Ask one technical or behavioral question at a time. Do not overwhelm the candidate.
3. Your tone should be professional, encouraging, and firm.
4. Focus on these specific questions if provided: {job_details.get('questions_to_ask')}
5. If the candidate gives a short or vague answer, ask a follow-up ("Could you elaborate on that?").
6. Keep your responses concise (under 3 sentences) because this is a voice-to-voice conversation.

STRICT RULE: Do not explain your logic. Just speak directly to the candidate.
"""
        return prompt

    def get_response(self, history: List[Dict[str, str]], job_details: Dict[str, Any], candidate_details: Dict[str, Any]) -> str:
        """
        Generates the next response in the interview conversation.
        """
        system_instruction = self._generate_system_prompt(job_details, candidate_details)
        
        # Format history for Gemini
        # We use a chat session for context management
        chat = self.model.start_chat(history=[])
        
        # Inject context in the first turn or as a system instruction if supported
        # For Flash, we'll prepend the context to the first message if history is empty
        # or use the system_instruction in the model initialization if using the newer API.
        
        # Using the prompt as the base for the turn
        full_content = f"CONTEXT: {system_instruction}\n\nCONVERSATION SO FAR:\n"
        for msg in history:
            role = "Candidate" if msg['role'] == 'user' else "Interviewer"
            full_content += f"{role}: {msg['content']}\n"
            
        full_content += "\nInterviewer (provide your next single question or response):"
        
        response = self.model.generate_content(full_content)
        return response.text.strip()

voice_service = VoiceInterviewService()
