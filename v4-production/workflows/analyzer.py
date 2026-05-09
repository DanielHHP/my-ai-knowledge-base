"""[AnalyzeNode] Analyze each source item via LLM to produce structured analyses."""

import json
import logging
import re
from datetime import datetime, timezone

from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM = (
    "You are an AI technology content analyst. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

ANALYSIS_PROMPT = """Analyze this AI-related repository:

Title: {title}
Description: {description}

Return a JSON object with these fields:
- "summary": Chinese summary (100-200 characters)
- "tags": array of 3-5 English lowercase tags (e.g. "llm", "open-source")
- "category": one of ["模型发布", "工具库", "论文", "行业动态", "综合技术"]
- "quality_score": float between 0 and 1
- "score_reason": brief Chinese explanation for the score"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _make_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return slug.lower()[:80]


def analyze_node(state: KBState) -> dict:
    """[AnalyzeNode] Analyze each source item via LLM to produce structured analyses.

    Args:
        state: KBState with sources, cost_tracker.

    Returns:
        Partial state update: analyses, cost_tracker.
    """
    sources = state.get("sources", [])
    logger.info("[AnalyzeNode] Analyzing %d items...", len(sources))

    analyses: list[dict] = []
    tracker: dict | None = state.get("cost_tracker")

    for item in sources:
        title = item.get("title", "")
        description = item.get("description", "")
        prompt = ANALYSIS_PROMPT.format(title=title, description=description)

        try:
            result, usage = chat_json(prompt, system=ANALYSIS_SYSTEM, max_tokens=1000, node_name="analyze")
            tracker = accumulate_usage(tracker, usage)
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning("[AnalyzeNode] LLM failed for '%s': %s", title, e)
            continue

        slug = _make_slug(title)
        now = _now_iso()
        today = _today_str()

        analyses.append({
            "id": f"github_{slug}_{today}",
            "title": title,
            "source": "github",
            "source_url": item.get("url", ""),
            "published_at": f"{today}T00:00:00Z",
            "summary": result.get("summary", ""),
            "tags": result.get("tags", []),
            "category": result.get("category", "综合技术"),
            "quality_score": float(result.get("quality_score", 0.5)),
            "score_reason": result.get("score_reason", ""),
            "metadata": item.get("metadata", {}),
            "created_at": now,
            "updated_at": now,
        })

    logger.info("[AnalyzeNode] %d analyses generated", len(analyses))
    return {"analyses": analyses, "cost_tracker": tracker}
