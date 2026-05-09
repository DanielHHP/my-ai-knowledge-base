"""[OrganizeNode] Filter, dedup, fix, and persist knowledge articles.

Merges the former ``organize_node`` + ``save_node`` logic into a single node
that produces final articles AND writes them to disk.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.security import filter_output
from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"

ORGANIZE_FIX_SYSTEM = (
    "You are an editor fixing article issues. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

ORGANIZE_FIX_PROMPT = """Fix the following knowledge article based on review feedback.

Current article JSON:
{json_data}

Review feedback:
{feedback}

Return the corrected article JSON with the same structure."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def organize_node(state: KBState) -> dict:
    """[OrganizeNode] Filter, dedup, optionally fix, then persist articles.

    Args:
        state: KBState with analyses, iteration, review_feedback, cost_tracker.

    Returns:
        Partial state update: articles, cost_tracker.
    """
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    logger.info(
        "[OrganizeNode] Processing %d analyses (iter=%d)...", len(analyses), iteration
    )

    # Step 1: Filter low quality (below plan threshold or default 0.5)
    plan = state.get("plan", {}) or {}
    threshold = float(plan.get("relevance_threshold", 0.5))
    filtered = [a for a in analyses if a.get("quality_score", 0) >= threshold]

    # Step 2: Dedup by source_url
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for a in filtered:
        url = a.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(a)

    # Step 3: Apply LLM fix if review feedback exists and iteration > 0
    tracker: dict | None = state.get("cost_tracker")
    if iteration > 0 and feedback and deduped:
        logger.info("[OrganizeNode] Applying LLM fix based on feedback...")
        fixed: list[dict] = []
        for article in deduped:
            prompt = ORGANIZE_FIX_PROMPT.format(
                json_data=json.dumps(article, ensure_ascii=False),
                feedback=feedback,
            )
            try:
                result, usage = chat_json(
                    prompt, system=ORGANIZE_FIX_SYSTEM, max_tokens=1500, node_name="organizer"
                )
                tracker = accumulate_usage(tracker, usage)
                result["updated_at"] = _now_iso()
                fixed.append(result)
            except (json.JSONDecodeError, RuntimeError) as e:
                logger.warning(
                    "[OrganizeNode] Fix failed for '%s': %s",
                    article.get("title"),
                    e,
                )
                fixed.append(article)
        deduped = fixed

    # Step 4: Desensitize PII in title, summary, content
    desensitize_count = 0
    for a in deduped:
        for field in ("title", "summary", "content"):
            text = a.get(field, "")
            if text:
                filtered_text, detections = filter_output(text, mask=True)
                if detections:
                    desensitize_count += len(detections)
                    logger.info(
                        "[OrganizeNode] Desensitized %d PII in '%s' field of '%s'",
                        len(detections),
                        field,
                        a.get("title", ""),
                    )
                    a[field] = filtered_text

    # Step 5: Build final articles list
    now = _now_iso()
    articles: list[dict] = []
    for a in deduped:
        articles.append({
            "id": a.get("id", ""),
            "title": a.get("title", ""),
            "source": a.get("source", "github"),
            "source_url": a.get("source_url", ""),
            "published_at": a.get("published_at", ""),
            "key_insight": a.get("key_insight", ""),
            "summary": a.get("summary", ""),
            "content": a.get("content", ""),
            "tags": a.get("tags", []),
            "category": a.get("category", "综合技术"),
            "status": "published",
            "metadata": a.get("metadata", {}),
            "created_at": a.get("created_at", now),
            "updated_at": a.get("updated_at", now),
            "quality_score": a.get("quality_score", 0),
        })

    logger.info("[OrganizeNode] %d articles after organizing", len(articles))
    logger.info("[OrganizeNode] Total desensitization operations: %d", desensitize_count)

    # Step 6: Persist articles to disk
    _save_articles(articles)

    return {"articles": articles, "cost_tracker": tracker}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _save_articles(articles: list[dict]) -> None:
    """Write articles to knowledge/articles/ and update index.json."""
    logger.info("[OrganizeNode] Saving %d articles...", len(articles))

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved_ids: list[str] = []

    for article in articles:
        article_id = article.get("id", "")
        if not article_id:
            logger.warning("[OrganizeNode] Skipping article without id")
            continue

        path = ARTICLES_DIR / f"{article_id}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)
            saved_ids.append(article_id)
        except OSError as e:
            logger.error("[OrganizeNode] Failed to write %s: %s", article_id, e)

    # Update index.json
    index_path = ARTICLES_DIR / "index.json"
    index_data: dict[str, Any] = {"articles": [], "updated_at": ""}
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            index_data = {"articles": [], "updated_at": ""}

    existing_ids = {a.get("id") for a in index_data.get("articles", [])}
    for article in articles:
        aid = article.get("id", "")
        if aid and aid not in existing_ids:
            index_data.setdefault("articles", []).append({
                "id": aid,
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "category": article.get("category", ""),
                "tags": article.get("tags", []),
                "quality_score": article.get("quality_score", 0),
                "created_at": article.get("created_at", ""),
            })

    index_data["updated_at"] = _now_iso()

    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("[OrganizeNode] Failed to update index.json: %s", e)

    logger.info("[OrganizeNode] Saved %d / %d articles", len(saved_ids), len(articles))
