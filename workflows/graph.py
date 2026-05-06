"""LangGraph workflow assembly — linear pipeline with 3-way review routing.

Graph structure::

    plan → collect → analyze → review ──passed──────────→ organize → END
                                      ├──failed + iter<3──→ revise ──→ review (loop)
                                      └──failed + iter≥3──→ human_flag → END
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from workflows.collector import collect_node
from workflows.human_flag import human_flag_node
from workflows.nodes import analyze_node
from workflows.organizer import organize_node
from workflows.planner import planner_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.state import KBState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------


def route_after_review(state: KBState) -> str:
    """3-way route from review node.

    - passed → "organize"
    - not passed + iteration < max_iterations → "revise" (trigger LLM revision)
    - not passed + iteration >= max_iterations → "human_flag" (escalation)
    """
    if state.get("review_passed", False):
        return "organize"
    max_iter = (state.get("plan") or {}).get("max_iterations", 3)
    if state.get("iteration", 0) < max_iter:
        return "revise"
    return "human_flag"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    """Build and compile the LangGraph workflow.

    Returns:
        Compiled ``StateGraph`` application ready for ``.invoke()`` or
        ``.stream()``.
    """
    graph = StateGraph(KBState)

    # Register nodes
    graph.add_node("plan", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("review", review_node)
    graph.add_node("organize", organize_node)
    graph.add_node("revise", revise_node)
    graph.add_node("human_flag", human_flag_node)

    # Linear pipeline: plan → collect → analyze → review
    graph.set_entry_point("plan")
    graph.add_edge("plan", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")

    # 3-way conditional branch after review
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"organize": "organize", "revise": "revise", "human_flag": "human_flag"},
    )

    # Revise → review loop (feedback-driven iteration)
    graph.add_edge("revise", "review")

    # Organize → terminal (articles saved to disk)
    graph.add_edge("organize", END)

    # Human flag → terminal (escalation when max iterations exceeded)
    graph.add_edge("human_flag", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _print_header(text: str) -> None:
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def _print_dict(label: str, data: dict, indent: int = 2) -> None:
    prefix = " " * indent
    for k, v in data.items():
        if isinstance(v, list):
            print(f"{prefix}{k}: [{len(v)} items]")
            if v and len(v) <= 3:
                for item in v:
                    title = item.get("title", item.get("id", str(item)[:80]))
                    print(f"{prefix}  - {title}")
        elif isinstance(v, dict):
            print(f"{prefix}{k}: {json.dumps(v, ensure_ascii=False)[:120]}")
        else:
            print(f"{prefix}{k}: {v}")


if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print()
    print("╔" + "═" * 58 + "╗")
    print("║  LangGraph Knowledge Base Workflow                      ║")
    print("╚" + "═" * 58 + "╝")

    app = build_graph()

    initial_state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0,
        },
    }

    final_state: dict = dict(initial_state)

    for step in app.stream(initial_state):
        for node_name, output in step.items():
            _print_header(f"Node: {node_name}")
            if output:
                final_state.update(output)
                _print_dict(node_name, output)

    _print_header("Workflow Complete")
    tracker = (final_state or {}).get("cost_tracker", {})
    if tracker:
        print(f"  Total tokens:     {tracker.get('total_tokens', 0)}")
        print(f"  Prompt tokens:    {tracker.get('prompt_tokens', 0)}")
        print(f"  Completion tokens: {tracker.get('completion_tokens', 0)}")
        print(f"  Estimated cost:   ${tracker.get('estimated_cost', 0):.6f}")

    articles = (final_state or {}).get("articles", [])
    passed = (final_state or {}).get("review_passed", True)
    iterations = (final_state or {}).get("iteration", 0)
    print(f"  Articles produced: {len(articles)}")
    print(f"  Review passed:     {passed}")
    print(f"  Iterations:        {iterations}")
    print()
