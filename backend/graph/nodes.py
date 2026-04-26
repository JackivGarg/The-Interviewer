"""
Graph nodes — the interview pipeline broken into specialized nodes.

greeting_setup_node:  Sets up planner_instruction for the opening greeting.
grader_node:          LLM call to score the candidate's latest answer (strict).
router_node:          Pure Python logic — decides same_topic / next_topic / end.
question_gen_node:    LLM call to generate a followup question on the same topic.
planner_node:         THE ONLY NODE THAT SPEAKS — converts planner_instruction to speech.
end_node:             Sets is_complete = True.
"""

import json
import logging
from backend.services.llm_client import call_llm

logger = logging.getLogger("interviewer.graph.nodes")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _truncate(text: str, max_chars: int = 500) -> str:
    """Safely truncate a string to avoid bloating prompts."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _get_last_qa(messages: list) -> tuple[str, str]:
    """Returns (last_ai_message, last_user_message) from conversation history."""
    last_user = ""
    last_ai = ""
    for msg in reversed(messages):
        if msg.get("role") == "user" and not last_user:
            last_user = msg.get("content", "")
        elif msg.get("role") == "model" and not last_ai:
            last_ai = msg.get("content", "")
        if last_user and last_ai:
            break
    return last_ai, last_user


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1: GREETING SETUP (no LLM)
# ══════════════════════════════════════════════════════════════════════════════

def greeting_setup_node(state: dict) -> dict:
    """Sets up initial state and tells Planner what to say for greeting."""
    question_file = state.get("question_file", {})
    candidate_name = state.get("candidate_name", "Candidate")
    job_details = state.get("job_details", {})
    resume_profile = state.get("resume_profile", {})

    topics = question_file.get("topics", [])
    first_topic = topics[0] if topics else {}
    first_question = first_topic.get("primary_question", "Tell me about yourself and your background.")
    topic_name = first_topic.get("topic", "General")

    skills = resume_profile.get("skills", [])
    skill_mention = skills[0] if skills else "your background"

    instruction = (
        f"Generate a warm, professional greeting for the candidate.\n"
        f"Welcome them by name: '{candidate_name}'.\n"
        f"Mention the job: '{job_details.get('title', 'the position')}'.\n"
        f"Reference their expertise in '{skill_mention}' briefly.\n"
        f"Then ask this first interview question on '{topic_name}': \"{first_question}\"\n"
        f"Keep it to 2-3 sentences. Be natural and conversational."
    )

    logger.info(f"[GreetingSetup] First topic='{topic_name}' | Q='{first_question[:60]}...'")

    return {
        "planner_instruction": instruction,
        "current_topic_index": 0,
        "current_topic_turn": 1,  # First Q counts as turn 1
        "current_topic_score": 0,
        "grader_reasoning": "",
        "route": "greeting",
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2: GRADER (LLM — strict, low temperature)
# ══════════════════════════════════════════════════════════════════════════════

def grader_node(state: dict) -> dict:
    """Grades the candidate's last answer. Returns score (0-10) + reasoning."""
    messages = state.get("messages", [])
    job_details = state.get("job_details", {})
    question_file = state.get("question_file", {})
    topic_index = state.get("current_topic_index", 0)

    topics = question_file.get("topics", [])
    current_topic = topics[topic_index] if topic_index < len(topics) else {}
    topic_name = current_topic.get("topic", "General")

    last_ai_msg, last_user_msg = _get_last_qa(messages)
    # Truncate to keep prompt lean for Groq
    last_ai_msg = _truncate(last_ai_msg, 400)
    last_user_msg = _truncate(last_user_msg, 600)

    logger.info(f"[Grader] Grading answer on topic='{topic_name}'")
    logger.info(f"[Grader]   Q: '{last_ai_msg[:80]}...'")
    logger.info(f"[Grader]   A: '{last_user_msg[:80]}...'")

    # Keep system prompt compact — Llama performs better with focused instructions
    system_prompt = (
        "You are a strict technical interview grader. "
        "You evaluate answers objectively on a 0-10 scale. "
        "You always respond in JSON format.\n\n"
        "SCORING GUIDE:\n"
        "0-2: No relevant answer, off-topic, or 'I don't know'\n"
        "3-4: Vague or superficial — mentions the topic but no depth\n"
        "5-6: Partial answer — shows some knowledge but has gaps\n"
        "7-8: Good answer — covers key points with reasonable depth\n"
        "9-10: Excellent — deep knowledge with concrete examples"
    )

    user_prompt = (
        f"TOPIC: {topic_name}\n"
        f"JOB: {_truncate(job_details.get('title', ''), 100)}\n\n"
        f"QUESTION:\n{last_ai_msg}\n\n"
        f"ANSWER:\n{last_user_msg}\n\n"
        "Grade this answer. Return JSON:\n"
        '{"score": <integer 0-10>, "reasoning": "<one sentence>"}'
    )

    raw = call_llm(user_prompt, system_prompt, json_mode=True,
                   temperature=0.3, max_tokens=100)

    try:
        parsed = json.loads(raw)
        score = int(parsed.get("score", 5))
        reasoning = str(parsed.get("reasoning", "No reasoning provided"))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.error(f"[Grader] Failed to parse response: {raw[:200]}")
        score = 5
        reasoning = "Parse error — using default score"

    # Clamp score to 0-10
    score = max(0, min(10, score))

    logger.info(f"[Grader] Score={score}/10 | Reasoning: {reasoning}")

    return {
        "current_topic_score": score,
        "grader_reasoning": reasoning,
        "evaluation_notes": [{
            "topic": topic_name,
            "score": score,
            "reasoning": reasoning,
        }],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3: ROUTER (pure logic — NO LLM)
# ══════════════════════════════════════════════════════════════════════════════

MAX_TURNS_PER_TOPIC = 3

def router_node(state: dict) -> dict:
    """Pure logic router. Reads grader score vs per-topic threshold, decides route."""
    score = state.get("current_topic_score", 0)
    turn = state.get("current_topic_turn", 0)
    topic_index = state.get("current_topic_index", 0)
    question_file = state.get("question_file", {})

    topics = question_file.get("topics", [])
    total_topics = len(topics)
    current_topic = topics[topic_index] if topic_index < total_topics else {}
    topic_name = current_topic.get("topic", "General")

    # Per-topic threshold from HR, default 6
    topic_threshold = current_topic.get("threshold", 6)

    logger.info(
        f"[Router] Evaluating: score={score} vs threshold={topic_threshold} | "
        f"turn={turn}/{MAX_TURNS_PER_TOPIC} | topic='{topic_name}' ({topic_index+1}/{total_topics})"
    )

    # ── Route Decision ──────────────────────────────────────
    if score >= topic_threshold or turn >= MAX_TURNS_PER_TOPIC:
        # Move on — either good answer or max turns exhausted
        next_index = topic_index + 1

        if next_index >= total_topics:
            # All topics covered → END
            reason = "answered satisfactorily" if score >= topic_threshold else "max questions reached"
            instruction = (
                f"All interview topics have been covered (candidate {reason} on final topic). "
                "Thank the candidate warmly for their time and effort. "
                "Let them know the team will review and follow up soon. "
                "Keep it to 1-2 sentences. Be warm and professional."
            )
            logger.info(f"[Router] → END (all {total_topics} topics covered)")
            return {
                "route": "end",
                "planner_instruction": instruction,
                "current_topic_index": topic_index,
                "current_topic_turn": turn,
            }
        else:
            # Next topic
            next_topic = topics[next_index]
            next_question = next_topic.get("primary_question", "Tell me more about your experience.")
            next_topic_name = next_topic.get("topic", "General")

            transition_reason = (
                "answered satisfactorily" if score >= topic_threshold
                else f"max questions reached on '{topic_name}'"
            )
            instruction = (
                f"The candidate {transition_reason}. "
                f"Briefly acknowledge their answer (1 short sentence), then smoothly transition "
                f"to the next topic: '{next_topic_name}'. "
                f"Ask this question: \"{next_question}\""
            )
            logger.info(f"[Router] → NEXT TOPIC: '{next_topic_name}' (topic {next_index+1}/{total_topics})")
            return {
                "route": "next_topic",
                "planner_instruction": instruction,
                "current_topic_index": next_index,
                "current_topic_turn": 1,  # Primary Q counts as turn 1
            }
    else:
        # Same topic — needs deeper probing
        logger.info(f"[Router] → SAME TOPIC: score {score} < threshold {topic_threshold}, turn {turn+1}")
        return {
            "route": "same_topic",
            "planner_instruction": "",  # question_gen will fill this
            "current_topic_index": topic_index,
            "current_topic_turn": turn + 1,
        }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4: QUESTION GENERATOR (LLM — generates followup on same topic)
# ══════════════════════════════════════════════════════════════════════════════

def question_gen_node(state: dict) -> dict:
    """Generates a targeted followup question when the answer was insufficient."""
    messages = state.get("messages", [])
    job_details = state.get("job_details", {})
    question_file = state.get("question_file", {})
    topic_index = state.get("current_topic_index", 0)
    grader_reasoning = state.get("grader_reasoning", "")

    topics = question_file.get("topics", [])
    current_topic = topics[topic_index] if topic_index < len(topics) else {}
    topic_name = current_topic.get("topic", "General")

    last_ai_msg, last_user_msg = _get_last_qa(messages)
    last_ai_msg = _truncate(last_ai_msg, 300)
    last_user_msg = _truncate(last_user_msg, 400)

    logger.info(f"[QuestionGen] Generating followup for topic='{topic_name}'")
    logger.info(f"[QuestionGen]   Grader said: '{grader_reasoning}'")

    system_prompt = (
        "You are an expert interview question designer. "
        "Generate ONE targeted followup question. "
        "You always respond in JSON format."
    )

    user_prompt = (
        f"TOPIC: {topic_name}\n"
        f"JOB: {_truncate(job_details.get('title', ''), 100)}\n\n"
        f"PREVIOUS QUESTION:\n{last_ai_msg}\n\n"
        f"CANDIDATE'S ANSWER:\n{last_user_msg}\n\n"
        f"WEAKNESS IDENTIFIED: {_truncate(grader_reasoning, 200)}\n\n"
        "Generate ONE followup question that:\n"
        "1. Targets the specific gap identified above\n"
        "2. Is DIFFERENT from the previous question\n"
        "3. Is open-ended and suitable for a voice conversation\n"
        "4. Gives the candidate a fair chance to demonstrate knowledge\n\n"
        "Return JSON: {\"question\": \"<your followup question>\"}"
    )

    raw = call_llm(user_prompt, system_prompt, json_mode=True,
                   temperature=0.5, max_tokens=150)

    try:
        parsed = json.loads(raw)
        generated_question = parsed.get("question", "")
    except (json.JSONDecodeError, TypeError):
        logger.error(f"[QuestionGen] Failed to parse response: {raw[:200]}")
        generated_question = ""

    if not generated_question:
        generated_question = "Can you elaborate on that with a specific example from your experience?"

    logger.info(f"[QuestionGen] Followup: '{generated_question[:80]}...'")

    instruction = (
        f"The candidate's previous answer was not strong enough. "
        f"Grader noted: '{_truncate(grader_reasoning, 150)}'. "
        f"Ask this followup question on the same topic ('{topic_name}'): "
        f"\"{generated_question}\"\n"
        f"Be encouraging, not critical. Briefly acknowledge what they said, "
        f"then ask the followup naturally."
    )

    return {
        "planner_instruction": instruction,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 5: PLANNER (LLM — the ONLY node that speaks to the candidate)
# ══════════════════════════════════════════════════════════════════════════════

def planner_node(state: dict) -> dict:
    """
    THE ONLY NODE THAT SPEAKS. Reads planner_instruction and generates
    a natural spoken response. Does NOT score or route.
    """
    messages = state.get("messages", [])
    instruction = state.get("planner_instruction", "")

    # Keep history compact: last 6 messages, each capped at 200 chars
    recent = messages[-6:] if len(messages) > 6 else messages
    history_lines = []
    for m in recent:
        role = "Candidate" if m.get("role") == "user" else "Interviewer"
        content = _truncate(m.get("content", ""), 200)
        history_lines.append(f"{role}: {content}")
    history_text = "\n".join(history_lines)

    logger.info(f"[Planner] Generating response | instruction preview: '{instruction[:80]}...'")

    system_prompt = (
        "You are a professional interviewer conducting a live voice interview. "
        "You speak naturally and concisely. You always respond in JSON format.\n\n"
        "RULES:\n"
        "- Keep responses to 2-3 SHORT sentences maximum\n"
        "- Sound natural and conversational, like a real human interviewer\n"
        "- NEVER mention scores, grading, thresholds, or internal processes\n"
        "- NEVER repeat a question word-for-word from the conversation history\n"
        "- When transitioning topics, briefly acknowledge the previous answer first"
    )

    user_prompt = (
        f"RECENT CONVERSATION:\n{history_text if history_text else '(Starting the interview)'}\n\n"
        f"INSTRUCTION:\n{instruction}\n\n"
        "Generate a natural spoken response following the instruction.\n\n"
        "Return JSON: {\"response_text\": \"<your spoken response>\"}"
    )

    raw = call_llm(user_prompt, system_prompt, json_mode=True,
                   temperature=0.7, max_tokens=250)

    try:
        parsed = json.loads(raw)
        response_text = parsed.get("response_text", "")
    except (json.JSONDecodeError, TypeError):
        logger.error(f"[Planner] Failed to parse response: {raw[:200]}")
        response_text = ""

    # Context-aware fallback
    if not response_text or not response_text.strip():
        logger.warning("[Planner] Empty response, using fallback")
        route = state.get("route", "")
        if route == "greeting" or not messages:
            candidate_name = state.get("candidate_name", "there")
            job_title = state.get("job_details", {}).get("title", "the position")
            response_text = f"Hello {candidate_name}! Welcome to your interview for the {job_title} role. Let's start — could you introduce yourself and tell me about your technical background?"
        elif route == "end":
            response_text = "Thank you so much for your time today. The team will review your interview and get back to you soon. Best of luck!"
        else:
            response_text = "That's interesting. Could you give me a specific example from your experience to illustrate that?"

    logger.info(f"[Planner] Response: '{response_text[:80]}...'")

    return {
        "messages": [{"role": "model", "content": response_text}],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 6: END NODE
# ══════════════════════════════════════════════════════════════════════════════

def end_node(state: dict) -> dict:
    """
    Fires when route == 'end'. Just marks the interview as complete.
    The planner already generated the farewell message.
    """
    logger.info("[EndNode] Interview marked complete.")
    return {"is_complete": True}
