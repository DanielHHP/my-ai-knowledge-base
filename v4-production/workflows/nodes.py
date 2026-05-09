"""Workflow node re-exports hub — centralized import point for all node functions.

Use this module as a single import source for all workflow nodes in graph.py.
"""

from workflows.analyzer import analyze_node
from workflows.collector import collect_node
from workflows.human_flag import human_flag_node
from workflows.organizer import organize_node
from workflows.planner import planner_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.state import KBState


def review_node_test(state: KBState) -> dict:
    """[ReviewNode-Test] 前 2 次审核不通过，第 3 次通过。"""
    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)

    feedbacks = [
        "摘要缺少对技术实现细节的分析，建议补充核心架构说明",
        "标签分类不够精准，建议增加 'agent'、'workflow' 等关键标签",
    ]

    if iteration >= 2 or not articles:
        review_passed = True
        feedback = ""
    else:
        review_passed = False
        feedback = feedbacks[iteration]

    print(f"[ReviewNode] iteration={iteration}, review_passed={review_passed}")

    return {
        "review_passed": review_passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
    }
