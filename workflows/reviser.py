"""[ReviseNode] Revise analyses based on review feedback with creative LLM rewriting.

Unlike the organize_node's fix step (which operates on articles), this node
revises the raw analyses list before they enter the organize pipeline. Uses
temperature=0.4 to allow creative improvements while staying on-topic.
"""

import json
import logging
from typing import Any

from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

REVISE_SYSTEM = (
    "You are an AI knowledge entry editor. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

REVISE_PROMPT = """Revise the following AI knowledge analysis entries based on the feedback provided. Improve summary quality, tag accuracy, and category assignments.

Review feedback:
{feedback}

Current analyses (JSON array):
{analyses_json}

Return a JSON array of revised analyses with the same structure. Each analysis must retain the same keys: id, title, source, source_url, published_at, summary, tags, category, quality_score, score_reason, metadata, created_at, updated_at.

Only modify fields that need improvement based on the feedback. Keep all IDs and metadata unchanged."""


def revise_node(state: KBState) -> dict:
    """[ReviseNode] Revise analyses using LLM with feedback-guided creative rewriting.

    Reads ``state["analyses"]`` and ``state["review_feedback"]``, injects the
    feedback into a revision prompt, calls the LLM at temperature=0.4, and
    returns the improved analyses list.

    Args:
        state: KBState with analyses, review_feedback, cost_tracker.

    Returns:
        Partial state update: analyses (revised), cost_tracker.
        Returns ``{}`` if analyses or review_feedback is empty.
    """
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")

    if not analyses or not feedback:
        return {}

    logger.info("[ReviseNode] Revising %d analyses based on feedback...", len(analyses))

    tracker: dict | None = state.get("cost_tracker")
    prompt = REVISE_PROMPT.format(
        feedback=feedback,
        analyses_json=json.dumps(analyses, ensure_ascii=False, indent=2),
    )

    try:
        result, usage = chat_json(
            prompt, system=REVISE_SYSTEM, temperature=0.4
        )
        tracker = accumulate_usage(tracker, usage)
    except (json.JSONDecodeError, RuntimeError) as e:
        logger.warning("[ReviseNode] LLM revision failed: %s — keeping original", e)
        return {}

    if not isinstance(result, list):
        logger.warning("[ReviseNode] Expected JSON array, got %s", type(result).__name__)
        return {}

    now = _now_iso()
    for item in result:
        if isinstance(item, dict):
            item["updated_at"] = now

    logger.info("[ReviseNode] %d analyses revised", len(result))
    return {"analyses": result, "cost_tracker": tracker}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
