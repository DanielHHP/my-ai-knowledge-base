"""[ReviewNode] 5-dimension quality review over state["analyses"].

Differs from the legacy reviewer in nodes.py:
  - Reviews `analyses` (not `articles`) — articles don't exist until after organize
  - 5 weighted dimensions (1–10 each), weighted total recomputed in code
  - Only first 5 analyses reviewed to control token consumption
  - temperature=0.1 for scoring consistency
  - LLM failures auto-pass (do not block the pipeline)
"""

import json
import logging
from typing import Any

from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

REVIEW_SYSTEM = (
    "You are a quality reviewer for AI knowledge entries. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

REVIEW_PROMPT = """Review this AI knowledge analysis entry on a 1-10 integer scale for 5 dimensions:

Title: {title}
Summary: {summary}
Tags: {tags}
Category: {category}

Scoring guidelines:
- summary_quality (摘要质量 25%): clarity, conciseness, accuracy
- technical_depth (技术深度 25%): depth of technical insight and analysis detail
- relevance (相关性 20%): relevance to AI/LLM/Agent domain
- originality (原创性 15%): uniqueness and novelty of perspective
- formatting (格式规范 15%): tag accuracy, category appropriateness, overall structure

Return ONLY a JSON object:
{{
  "scores": {{
    "summary_quality": int,
    "technical_depth": int,
    "relevance": int,
    "originality": int,
    "formatting": int
  }},
  "feedback": "Chinese improvement suggestions (empty string if all dimensions pass)"
}}"""

WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

PASS_THRESHOLD = 7.0
MAX_REVIEW_ITEMS = 5


def _clamp_score(value: Any) -> int:
    try:
        return max(1, min(10, int(value)))
    except (ValueError, TypeError):
        return 1


def review_node(state: KBState) -> dict:
    """[ReviewNode] 5-dimension weighted review over analyses.

    Reads ``state["analyses"]`` (not articles) and scores the first 5 entries
    across 5 weighted dimensions. Weighted total is recomputed in code
    (not trusting LLM arithmetic). Entries with weighted_total >= 7.0 pass.

    Args:
        state: KBState with analyses, iteration, cost_tracker, etc.

    Returns:
        Partial state update: review_passed, review_feedback, iteration,
        cost_tracker.
    """
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    logger.info(
        "[ReviewNode] Reviewing %d analyses (iteration %d)...",
        len(analyses),
        iteration,
    )

    if not analyses:
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": state.get("cost_tracker"),
        }

    tracker: dict | None = state.get("cost_tracker")
    feedback_parts: list[str] = []
    all_passed = True

    for analysis in analyses[:MAX_REVIEW_ITEMS]:
        title = analysis.get("title", analysis.get("id", "unknown"))
        prompt = REVIEW_PROMPT.format(
            title=title,
            summary=analysis.get("summary", ""),
            tags=json.dumps(analysis.get("tags", []), ensure_ascii=False),
            category=analysis.get("category", ""),
        )

        try:
            result, usage = chat_json(
                prompt, system=REVIEW_SYSTEM, temperature=0.1
            )
            tracker = accumulate_usage(tracker, usage)
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning(
                "[ReviewNode] LLM call failed for '%s': %s — auto passing",
                title,
                e,
            )
            continue

        scores_raw: dict[str, Any] = result.get("scores", {})
        feedback: str = result.get("feedback", "")

        weighted_total = sum(
            _clamp_score(scores_raw.get(k, 0)) * WEIGHTS[k] for k in WEIGHTS
        )

        logger.info(
            "[ReviewNode] '%s' weighted_total=%.2f", title, weighted_total
        )

        if weighted_total < PASS_THRESHOLD:
            all_passed = False
            feedback_parts.append(
                f"- {title} (score={weighted_total:.1f}): {feedback}"
            )

    return {
        "review_passed": all_passed,
        "review_feedback": "\n".join(feedback_parts) if feedback_parts else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }
