"""
Question file generator — creates a structured interview question plan
from HR-defined topics + job details + candidate profile.

If HR provides interview_topics with per-topic thresholds, those topics
are used directly. Otherwise, topics are auto-generated from the job description.
"""

import json
import time
import logging
from backend.services.llm_client import call_gemini

logger = logging.getLogger("interviewer.question_gen")


def generate_question_file(candidate_profile: dict, job_details: dict, interview_topics: list = None) -> dict:
    """
    Generate a structured question file.

    Args:
        candidate_profile: Extracted from resume {name, skills, experience_years, ...}
        job_details: {title, description, skills_required, questions_to_ask}
        interview_topics: HR-defined list [{"topic": "X", "threshold": 7}, ...]
                          If empty/None, topics are auto-generated.

    Returns:
        {
            "topics": [
                {"topic": "Python", "threshold": 7, "primary_question": "Explain..."},
                ...
            ]
        }
    """
    logger.info("[QuestionGen] Generating question file...")
    t0 = time.time()

    if not interview_topics:
        interview_topics = []

    skills = json.dumps(candidate_profile.get("skills", []), default=str)
    past_roles = json.dumps(candidate_profile.get("past_roles", []), default=str)

    system_prompt = "You are an expert technical interviewer designing interview questions."

    if interview_topics:
        # ── HR-defined topics: generate ONE primary question per topic ──
        logger.info(f"[QuestionGen] Using {len(interview_topics)} HR-defined topics")
        topics_description = "\n".join(
            f"- Topic: \"{t['topic']}\" (threshold: {t['threshold']}/10)"
            for t in interview_topics
        )

        user_prompt = f"""JOB TITLE: {job_details.get('title', 'Software Engineer')}
JOB DESCRIPTION: {job_details.get('description', 'General software engineering role')}
REQUIRED SKILLS: {job_details.get('skills_required', 'Not specified')}
HR FOCUS AREAS: {job_details.get('questions_to_ask', 'General assessment')}

CANDIDATE PROFILE:
- Name: {candidate_profile.get('name', 'Candidate')}
- Experience: {candidate_profile.get('experience_years', 0)} years
- Skills: {skills}
- Past Roles: {past_roles}
- Education: {candidate_profile.get('education', 'Not specified')}

HR HAS DEFINED THESE INTERVIEW TOPICS (with strictness thresholds):
{topics_description}

For EACH topic above, generate exactly ONE primary interview question — the single best,
most revealing question that tests the candidate's knowledge on that topic.

Rules:
1. Each question must be open-ended and suitable for a VOICE conversation (not a coding puzzle)
2. Tailor question difficulty to the candidate's experience level
3. Questions should test practical knowledge, not just theory
4. Keep questions concise and clear
5. You MUST use the exact topic names provided by HR

Return ONLY a JSON object with this exact format:
{{
    "topics": [
        {{"topic": "<exact topic name from HR>", "threshold": <threshold from HR>, "primary_question": "<your question>"}}
    ]
}}"""

    else:
        # ── Auto-generate topics from job description ──
        logger.info("[QuestionGen] No HR topics provided, auto-generating from job description")

        user_prompt = f"""JOB TITLE: {job_details.get('title', 'Software Engineer')}
JOB DESCRIPTION: {job_details.get('description', 'General software engineering role')}
REQUIRED SKILLS: {job_details.get('skills_required', 'Not specified')}
HR FOCUS AREAS: {job_details.get('questions_to_ask', 'General assessment')}

CANDIDATE PROFILE:
- Name: {candidate_profile.get('name', 'Candidate')}
- Experience: {candidate_profile.get('experience_years', 0)} years
- Skills: {skills}
- Past Roles: {past_roles}
- Education: {candidate_profile.get('education', 'Not specified')}

Generate an interview plan with 4-5 topic areas. Each topic gets exactly ONE primary question.

Rules:
1. Topics should be based on the required skills and job description
2. Each topic gets exactly ONE primary question (followups will be generated dynamically)
3. Questions must be open-ended and suitable for a VOICE conversation
4. Start with topics the candidate is likely strong in to build confidence
5. Include at least one behavioral/situational topic
6. Set a threshold (1-10) for each topic indicating how strict grading should be
   (6 = standard, 7-8 = strict for critical skills, 4-5 = lenient for nice-to-have)

Return ONLY a JSON object:
{{
    "topics": [
        {{"topic": "Topic Name", "threshold": 6, "primary_question": "The question"}}
    ]
}}"""

    try:
        raw = call_gemini(user_prompt, system_prompt, json_mode=True,
                       temperature=0.5, max_tokens=1000)
        qf = json.loads(raw) if raw else {}
        elapsed = round(time.time() - t0, 2)

        topics = qf.get("topics", [])
        logger.info(f"[QuestionGen] Generated {len(topics)} topics in {elapsed}s")
        for i, t in enumerate(topics):
            logger.info(
                f"[QuestionGen]   Topic {i+1}: '{t.get('topic')}' "
                f"(threshold={t.get('threshold', 6)}) "
                f"Q: '{t.get('primary_question', 'N/A')[:60]}...'"
            )

        return qf

    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        logger.error(f"[QuestionGen] Generation failed after {elapsed}s: {type(e).__name__}: {e}")
        # Return a minimal fallback question file
        fallback_topics = interview_topics if interview_topics else [
            {"topic": "Technical Background", "threshold": 6},
            {"topic": "Problem Solving", "threshold": 6},
            {"topic": "Teamwork & Communication", "threshold": 5},
        ]
        fallback_questions = [
            "Can you walk me through your most significant technical project?",
            "How do you approach breaking down a complex problem?",
            "Describe a time you had a disagreement with a teammate. How did you resolve it?",
        ]
        return {
            "topics": [
                {
                    "topic": t.get("topic", f"Topic {i+1}"),
                    "threshold": t.get("threshold", 6),
                    "primary_question": fallback_questions[i] if i < len(fallback_questions)
                        else "Tell me about your experience with this area.",
                }
                for i, t in enumerate(fallback_topics)
            ]
        }
