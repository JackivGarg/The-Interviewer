import os
import json
import logging
import time
from typing import List, Dict, Any, Optional
from backend.services.llm_client import call_gemini
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("interviewer.evaluation")

# Max messages to include in evaluation transcript
# 4 topics × 3 turns = 12 Q&A pairs = ~24 messages. 30 gives safety margin.
MAX_EVAL_MESSAGES = 30
# Max chars per message in transcript
MAX_MSG_CHARS = 500


class EvaluationService:
    def __init__(self):
        logger.info("[Evaluation] Service initialized (using Gemini via shared client)")

    def _generate_evaluation_prompt(
        self,
        history: List[Dict[str, Any]],
        job_details: Dict[str, Any],
        candidate_details: Dict[str, Any],
        evaluation_notes: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Takes the interview history and generates a structured JSON report.
        Accepts per-turn evaluation_notes from the LangGraph grader.
        """
        # Cap transcript to avoid blowing context window
        capped_history = history[-MAX_EVAL_MESSAGES:] if len(history) > MAX_EVAL_MESSAGES else history

        transcript = ""
        for msg in capped_history:
            role = "Candidate" if msg.get('role') == 'user' else "Interviewer"
            if 'parts' in msg:
                parts = msg['parts']
                content = " ".join(parts) if isinstance(parts, list) else str(parts)
            elif 'content' in msg:
                content = msg['content']
            else:
                content = ""
            # Truncate individual messages
            if len(content) > MAX_MSG_CHARS:
                content = content[:MAX_MSG_CHARS] + "..."
            transcript += f"{role}: {content}\n\n"

        # Build per-topic notes section if available
        notes_section = ""
        if evaluation_notes:
            notes_section = "\nPER-TURN SCORES (collected live during interview):\n"
            for note in evaluation_notes:
                notes_section += (
                    f"- Topic: {note.get('topic', 'N/A')} | "
                    f"Score: {note.get('score', 'N/A')}/10 | "
                    f"Reasoning: {note.get('reasoning', 'N/A')}\n"
                )
            notes_section += "\nUse these scores as grounding data for your evaluation.\n"

        prompt = f"""You are an expert technical recruiter evaluating a candidate based on an interview transcript.

JOB TITLE: {job_details.get('title', 'N/A')}
REQUIRED SKILLS: {str(job_details.get('skills_required', 'N/A'))[:500]}

CANDIDATE: {candidate_details.get('name', 'N/A')}
SKILLS: {str(candidate_details.get('skills', 'N/A'))[:300]}
{notes_section}
INTERVIEW TRANSCRIPT:
{transcript}

Evaluate the candidate and return a JSON object with this exact schema:
{{
    "technical_score": <float 0-10>,
    "behavioral_score": <float 0-10>,
    "confidence_score": <float 0-10>,
    "summary": "<1-2 paragraph performance summary>",
    "strengths": ["<strength 1>", "<strength 2>"],
    "weaknesses": ["<weakness 1>", "<weakness 2>"],
    "verdict": "<Hire or No Hire or Strong Hire>",
    "per_topic_breakdown": [
        {{"topic": "<topic>", "score": <float>, "reasoning": "<brief reasoning>"}}
    ]
}}"""
        return prompt

    def evaluate_interview(
        self,
        history: List[Dict[str, Any]],
        job_details: Dict[str, Any],
        candidate_details: Dict[str, Any],
        evaluation_notes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Analyzes the interview history and generates a structured evaluation report.
        """
        logger.info(f"[Evaluation] Starting evaluation for {candidate_details.get('name')}")
        logger.info(f"[Evaluation]   Job: {job_details.get('title')} | Messages: {len(history)} | Eval notes: {len(evaluation_notes or [])}")
        t0 = time.time()
        prompt = self._generate_evaluation_prompt(history, job_details, candidate_details, evaluation_notes)
        logger.info(f"[Evaluation]   Prompt size: {len(prompt)} chars")

        system_prompt = "You are an expert technical recruiter. Evaluate objectively and return valid JSON."

        try:
            raw_text = call_gemini(prompt, system_prompt, json_mode=True,
                                   temperature=0.3, max_tokens=1500)

            if not raw_text:
                raise ValueError("Empty response from LLM")

            # Clean possible markdown formatting
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines[-1].startswith("```"): lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            report = json.loads(raw_text)
            elapsed = round(time.time() - t0, 2)
            logger.info(f"[Evaluation] Report generated in {elapsed}s")
            logger.info(f"[Evaluation]   Verdict: {report.get('verdict')}")
            logger.info(f"[Evaluation]   Technical: {report.get('technical_score')}/10 | Behavioral: {report.get('behavioral_score')}/10 | Confidence: {report.get('confidence_score')}/10")
            logger.info(f"[Evaluation]   Strengths: {report.get('strengths', [])}")
            logger.info(f"[Evaluation]   Weaknesses: {report.get('weaknesses', [])}")
            breakdown = report.get('per_topic_breakdown', [])
            for item in breakdown:
                logger.info(f"[Evaluation]   Topic '{item.get('topic')}': {item.get('score')}/10 — {item.get('reasoning', '')[:80]}")
            return report
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            logger.error(f"[Evaluation] FAILED after {elapsed}s: {type(e).__name__}: {e}")
            return {
                "technical_score": 0,
                "behavioral_score": 0,
                "confidence_score": 0,
                "summary": "Evaluation failed due to a technical error.",
                "strengths": [],
                "weaknesses": [],
                "verdict": "Error",
                "per_topic_breakdown": [],
            }


evaluation_service = EvaluationService()
