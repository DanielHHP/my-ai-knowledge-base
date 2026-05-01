"""LangGraph workflow assembly — linear pipeline with review feedback loop.

Graph structure::

    collect → analyze → organize → review ──passed──→ save → END
                                        └──failed──→ organize
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------


def review_router(state: KBState) -> str:
    """Route from review: passed → save, failed → organize (revision loop)."""
    if state.get("review_passed", False):
        return "save"
    return "organize"


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
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # Linear pipeline: collect → analyze → organize → review
    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # Conditional branch: review → save (passed) / organize (not passed)
    graph.add_conditional_edges(
        "review",
        review_router,
        {"save": "save", "organize": "organize"},
    )

    # Terminal edge
    graph.add_edge("save", END)

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
            if node_name == "save":
                articles_count = len(output.get("articles", [])) if output else 0
                print(f"  articles in state: {articles_count}")
            elif output:
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
