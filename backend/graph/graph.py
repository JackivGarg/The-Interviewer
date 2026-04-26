"""
Graph assembly — builds and compiles the LangGraph interview graph.

Topology:
    START → entry_router:
        "greeting" → greeting_setup → planner → __end__
        "grading"  → grader → router → route_after_router:
            "question_gen"  → question_gen → planner → __end__
            "planner_next"  → planner → __end__
            "planner_end"   → planner → end_node → END

Each invoke() call processes ONE turn.
The voice_handler loop calls invoke() once per turn.
"""

import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from backend.graph.state import InterviewState
from backend.graph.nodes import (
    greeting_setup_node,
    grader_node,
    router_node,
    question_gen_node,
    planner_node,
    end_node,
)
from backend.graph.edges import entry_router, route_after_router, route_after_planner

logger = logging.getLogger("interviewer.graph")


def build_interview_graph():
    """Construct and compile the interview graph with in-memory checkpointer."""

    graph = StateGraph(InterviewState)

    # ── Register nodes ────────────────────────────────────────
    graph.add_node("greeting_setup", greeting_setup_node)
    graph.add_node("grader", grader_node)
    graph.add_node("router", router_node)
    graph.add_node("question_gen", question_gen_node)
    graph.add_node("planner", planner_node)
    graph.add_node("end_node", end_node)

    # ── Entry: greeting vs grading ────────────────────────────
    graph.add_conditional_edges(START, entry_router, {
        "greeting": "greeting_setup",
        "grading": "grader",
    })

    # ── Greeting flow ─────────────────────────────────────────
    graph.add_edge("greeting_setup", "planner")

    # ── Grading flow ──────────────────────────────────────────
    graph.add_edge("grader", "router")
    graph.add_conditional_edges("router", route_after_router, {
        "question_gen": "question_gen",
        "planner_next": "planner",
        "planner_end": "planner",
    })

    # ── QuestionGen → Planner ─────────────────────────────────
    graph.add_edge("question_gen", "planner")

    # ── After Planner: end or continue ────────────────────────
    graph.add_conditional_edges("planner", route_after_planner, {
        "end_node": "end_node",
        "__end__": END,
    })
    graph.add_edge("end_node", END)

    # ── Compile with MemorySaver for thread_id-based state persistence ──
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    logger.info("[Graph] Interview graph compiled successfully (4-node pipeline).")
    return compiled


# Module-level singleton — imported by voice_handler and main
interview_graph = build_interview_graph()
