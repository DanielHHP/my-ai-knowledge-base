"""[HumanFlagNode] 人工介入节点（异常终点）"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from workflows.state import KBState

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PENDING_DIR = BASE_DIR / "knowledge" / "pending_review"


def human_flag_node(state: KBState) -> dict:
    """审核循环超过上限时的兜底 —— 写入 pending_review/ 目录。

    Args:
        state: KBState with analyses, iteration, review_feedback, cost_tracker.

    Returns:
        Partial state update: needs_human_review, cost_tracker.
    """
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    tracker = state.get("cost_tracker")

    logger.warning("[HumanFlag] Reached %d iterations without passing review", iteration)
    logger.info("[HumanFlag] Last feedback: %s", feedback[:200])

    try:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("[HumanFlag] Failed to create pending_review dir: %s", e)
        return {"needs_human_review": True, "cost_tracker": tracker}

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    filepath = PENDING_DIR / f"pending-{timestamp}.json"

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": timestamp,
                    "iterations_used": iteration,
                    "last_feedback": feedback,
                    "analyses": analyses,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as e:
        logger.error("[HumanFlag] Failed to write %s: %s", filepath, e)
        return {"needs_human_review": True, "cost_tracker": tracker}

    logger.info("[HumanFlag] Saved to %s", filepath)
    return {"needs_human_review": True, "cost_tracker": tracker}
