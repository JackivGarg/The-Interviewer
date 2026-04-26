"""
Resume parser — extracts text from PDF and uses LLM to build a structured profile.
"""

import json
import time
import logging
import pdfplumber
from backend.services.llm_client import call_gemini

logger = logging.getLogger("interviewer.resume_parser")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract raw text from a PDF file using pdfplumber."""
    import io
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                logger.debug(f"[ResumeParser] Page {i+1}: {len(page_text)} chars")
    except Exception as e:
        logger.error(f"[ResumeParser] PDF extraction failed: {type(e).__name__}: {e}")
        raise ValueError(f"Failed to read PDF: {e}")

    full_text = "\n".join(text_parts).strip()
    logger.info(f"[ResumeParser] Extracted {len(full_text)} chars from {len(text_parts)} pages")

    if not full_text:
        raise ValueError("PDF appears to be empty or image-only (no extractable text)")

    return full_text


def extract_candidate_profile(resume_text: str) -> dict:
    """
    Use LLM to extract a structured candidate profile from resume text.
    Returns: {name, skills[], experience_years, past_roles[], education}
    """
    logger.info("[ResumeParser] Extracting candidate profile via LLM...")
    t0 = time.time()

    system_prompt = "You are an expert resume analyzer. Extract structured information from resume text."

    user_prompt = f"""Extract a structured candidate profile from this resume text.

RESUME TEXT:
{resume_text[:8000]}

Return ONLY a JSON object with this schema:
{{
    "name": "Full Name",
    "skills": ["skill1", "skill2", ...],
    "experience_years": <int or best estimate>,
    "past_roles": ["Role at Company (duration)", ...],
    "education": "Degree, University"
}}

If a field cannot be determined, use reasonable defaults (e.g., experience_years: 0, skills: [])."""

    try:
        raw = call_gemini(user_prompt, system_prompt, json_mode=True,
                       temperature=0.3, max_tokens=500)
        profile = json.loads(raw) if raw else {}
        elapsed = round(time.time() - t0, 2)
        logger.info(f"[ResumeParser] Profile extracted in {elapsed}s | name={profile.get('name')} | skills={len(profile.get('skills', []))}")
        return profile

    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        logger.error(f"[ResumeParser] Profile extraction failed after {elapsed}s: {type(e).__name__}: {e}")
        # Return a minimal fallback profile
        return {
            "name": "Candidate",
            "skills": [],
            "experience_years": 0,
            "past_roles": [],
            "education": "Not specified",
        }
