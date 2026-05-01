"""LangGraph workflow node functions (5 nodes).

Each node is a pure function: receives KBState, returns dict (partial state update).
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflows.model_client import accumulate_usage, chat, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

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

REVIEW_SYSTEM = (
    "You are a quality reviewer for AI knowledge entries. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

REVIEW_PROMPT = """Review this knowledge article entry:

Title: {title}
Summary: {summary}
Tags: {tags}
Category: {category}
Score: {score}

Evaluate four dimensions and return a JSON object:
{{
  "passed": bool,
  "overall_score": float 0-1,
  "feedback": str (Chinese improvement suggestions if not passed),
  "scores": {{
    "summary_quality": float 0-1,
    "tag_accuracy": float 0-1,
    "category_reasonable": float 0-1,
    "consistency": float 0-1
  }}
}}"""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _make_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return slug.lower()[:80]


# ---------------------------------------------------------------------------
# Node 1: Collect
# ---------------------------------------------------------------------------


def collect_node(state: KBState) -> dict:
    """[CollectNode] Fetch top AI/LLM repos from GitHub Search API via urllib."""
    logger.info("[CollectNode] Fetching GitHub trending repos...")

    query = "ai OR llm OR agent OR machine-learning in:topics"
    encoded_query = urllib.parse.quote(query)
    url = f"{GITHUB_SEARCH_URL}?q={encoded_query}&sort=stars&order=desc&per_page=10"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    sources: list[dict] = []

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for repo in data.get("items", []):
                sources.append({
                    "platform": "github",
                    "title": repo.get("full_name", ""),
                    "url": repo.get("html_url", ""),
                    "description": repo.get("description") or "",
                    "metadata": {
                        "stars": repo.get("stargazers_count", 0),
                        "language": repo.get("language") or "",
                        "topics": repo.get("topics", []),
                    },
                })
    except urllib.error.HTTPError as e:
        logger.error("[CollectNode] HTTP error %s: %s", e.code, e.reason)
    except urllib.error.URLError as e:
        logger.error("[CollectNode] URL error: %s", e.reason)
    except json.JSONDecodeError as e:
        logger.error("[CollectNode] JSON decode error: %s", e)
    except OSError as e:
        logger.error("[CollectNode] Network error: %s", e)

    logger.info("[CollectNode] Collected %d repos", len(sources))
    return {"sources": sources}


# ---------------------------------------------------------------------------
# Node 2: Analyze
# ---------------------------------------------------------------------------


def analyze_node(state: KBState) -> dict:
    """[AnalyzeNode] Analyze each source item via LLM to produce structured analyses."""
    sources = state.get("sources", [])
    logger.info("[AnalyzeNode] Analyzing %d items...", len(sources))

    analyses: list[dict] = []
    tracker: dict | None = state.get("cost_tracker")

    for item in sources:
        title = item.get("title", "")
        description = item.get("description", "")
        prompt = ANALYSIS_PROMPT.format(title=title, description=description)

        try:
            result, usage = chat_json(prompt, system=ANALYSIS_SYSTEM, max_tokens=1000)
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


# ---------------------------------------------------------------------------
# Node 3: Organize
# ---------------------------------------------------------------------------


def organize_node(state: KBState) -> dict:
    """[OrganizeNode] Filter low-score, dedup by URL, optionally revise with LLM."""
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    logger.info("[OrganizeNode] Processing %d analyses (iter=%d)...", len(analyses), iteration)

    # Step 1: Filter low quality (< 0.6)
    filtered = [a for a in analyses if a.get("quality_score", 0) >= 0.6]

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
    if iteration > 0 and feedback and deduped:
        logger.info("[OrganizeNode] Applying LLM fix based on feedback...")
        tracker: dict | None = state.get("cost_tracker")
        fixed: list[dict] = []
        for article in deduped:
            prompt = ORGANIZE_FIX_PROMPT.format(
                json_data=json.dumps(article, ensure_ascii=False),
                feedback=feedback,
            )
            try:
                result, usage = chat_json(
                    prompt, system=ORGANIZE_FIX_SYSTEM, max_tokens=1500
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

    # Step 4: Build final articles list
    now = _now_iso()
    articles: list[dict] = []
    for a in deduped:
        articles.append({
            "id": a.get("id", ""),
            "title": a.get("title", ""),
            "source": a.get("source", "github"),
            "source_url": a.get("source_url", ""),
            "published_at": a.get("published_at", ""),
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
    return {"articles": articles}


# ---------------------------------------------------------------------------
# Node 4: Review
# ---------------------------------------------------------------------------


def review_node(state: KBState) -> dict:
    """[ReviewNode] LLM 4-dimension quality review. Forced pass after iteration >= 2."""
    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)
    logger.info(
        "[ReviewNode] Reviewing %d articles (iteration %d)...",
        len(articles),
        iteration,
    )

    if iteration >= 2:
        logger.info("[ReviewNode] Max iteration reached, force passing")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    if not articles:
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    tracker: dict | None = state.get("cost_tracker")
    feedback_parts: list[str] = []
    all_passed = True

    for article in articles:
        prompt = REVIEW_PROMPT.format(
            title=article.get("title", ""),
            summary=article.get("summary", ""),
            tags=json.dumps(article.get("tags", []), ensure_ascii=False),
            category=article.get("category", ""),
            score=article.get("quality_score", 0),
        )

        try:
            result, usage = chat_json(prompt, system=REVIEW_SYSTEM, max_tokens=800)
            tracker = accumulate_usage(tracker, usage)
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning(
                "[ReviewNode] Review failed for '%s': %s",
                article.get("title"),
                e,
            )
            continue

        passed = result.get("passed", True)
        overall_score = result.get("overall_score", 0.5)
        feedback = result.get("feedback", "")

        if not passed or overall_score < 0.6:
            all_passed = False
            feedback_parts.append(f"- {article.get('title')}: {feedback}")

    return {
        "review_passed": all_passed,
        "review_feedback": "\n".join(feedback_parts) if feedback_parts else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# ---------------------------------------------------------------------------
# Node 5: Save
# ---------------------------------------------------------------------------


def save_node(state: KBState) -> dict:
    """[SaveNode] Write articles to knowledge/articles/ and update index.json."""
    articles = state.get("articles", [])
    logger.info("[SaveNode] Saving %d articles...", len(articles))

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved_ids: list[str] = []

    for article in articles:
        article_id = article.get("id", "")
        if not article_id:
            logger.warning("[SaveNode] Skipping article without id")
            continue

        path = ARTICLES_DIR / f"{article_id}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)
            saved_ids.append(article_id)
        except OSError as e:
            logger.error("[SaveNode] Failed to write %s: %s", article_id, e)

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

    now = _now_iso()
    index_data["updated_at"] = now

    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("[SaveNode] Failed to update index.json: %s", e)

    logger.info("[SaveNode] Saved %d / %d articles", len(saved_ids), len(articles))
    return {"articles": articles}
