"""
InterviewState — the single source of truth for an interview session.

Fields with `Annotated[list, operator.add]` use a reducer so that
new items are **appended** to the checkpoint rather than replacing it.
Scalar fields (int, bool, str, dict) are simply overwritten on each update.
"""

import operator
from typing import TypedDict, List, Optional, Annotated


class InterviewState(TypedDict):
    # ── Accumulating lists (reducer = concatenation) ──────────────
    messages: Annotated[List[dict], operator.add]
    """Full conversation: [{"role": "user"|"model", "content": "..."}]"""

    evaluation_notes: Annotated[List[dict], operator.add]
    """Per-turn scores: [{"topic": str, "score": int, "reasoning": str}]"""

    # ── Static context (set once at session start) ────────────────
    resume_profile: dict
    """Extracted from PDF: {name, skills[], experience_years, past_roles[], education}"""

    question_file: dict
    """Generated question plan: {topics: [{topic, threshold, primary_question}]}"""

    job_details: dict
    """Job posting info: {title, description, skills_required, questions_to_ask}"""

    candidate_name: str
    """Candidate's display name for the greeting."""

    # ── Mutable scalars (overwritten each turn) ───────────────────
    current_topic_index: int
    """Which topic block we're on (0-based)."""

    current_topic_turn: int
    """How many turns spent on the current topic (max 3 before forced next)."""

    current_topic_score: int
    """Grader's score for the latest answer (0-10)."""

    grader_reasoning: str
    """Grader's one-sentence explanation of the score."""

    planner_instruction: str
    """Instruction string from router/question_gen/greeting_setup → consumed by planner."""

    is_complete: bool
    """True after the end_node fires."""

    route: Optional[str]
    """Router decision: 'same_topic' | 'next_topic' | 'end' | None"""
