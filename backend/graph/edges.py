"""
Conditional edges for the interview graph.

entry_router:          Decides greeting vs grading based on message history.
route_after_router:    Reads router's decision from state (same_topic/next_topic/end).
route_after_planner:   Checks if interview should end after planner speaks.
"""

import logging

logger = logging.getLogger("interviewer.graph.edges")


def entry_router(state: dict) -> str:
    """
    Entry point conditional edge.
    Returns:
      - "greeting" → first invocation (no messages yet)
      - "grading"  → subsequent invocations (has user answer to grade)
    """
    messages = state.get("messages", [])
    if len(messages) == 0:
        logger.info("[Edge] entry_router → 'greeting' (no messages)")
        return "greeting"
    else:
        logger.info(f"[Edge] entry_router → 'grading' ({len(messages)} messages)")
        return "grading"


def route_after_router(state: dict) -> str:
    """
    Reads the router's route decision from state.
    Returns:
      - "question_gen"  → same_topic (needs followup question)
      - "planner_next"  → next_topic (router already set planner_instruction)
      - "planner_end"   → end (router already set planner_instruction for farewell)
    """
    route = state.get("route", "same_topic")
    logger.info(f"[Edge] route_after_router → route='{route}'")

    if route == "same_topic":
        return "question_gen"
    elif route == "end":
        return "planner_end"
    else:  # next_topic
        return "planner_next"


def route_after_planner(state: dict) -> str:
    """
    After planner speaks, check if interview should end.
    Returns:
      - "end_node" → route == "end" (planner just spoke the farewell)
      - "__end__"  → otherwise (graph invocation finishes, voice_handler waits for next audio)
    """
    route = state.get("route")
    logger.info(f"[Edge] route_after_planner → route='{route}'")

    if route == "end":
        return "end_node"
    return "__end__"
