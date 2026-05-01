#!/usr/bin/env python3
"""Four-step knowledge base automation pipeline: Collect -> Analyze -> Organize -> Save.

Usage:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from model_client import LLMProvider, create_provider, chat_with_retry

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "knowledge" / "raw"
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"
RSS_SOURCES_PATH = BASE_DIR / "pipeline" / "rss_sources.yaml"

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"

ANALYSIS_SYSTEM_PROMPT = (
    "You are an AI technology content analyst. "
    "Analyze the given content and return ONLY valid JSON. "
    "No markdown, no extra text, no code fences."
)

ANALYSIS_USER_PROMPT = """Analyze this AI-related content:

Title: {title}
Description: {description}

Return a JSON object with these fields:
- "summary": Chinese summary (100-200 characters)
- "highlights": array of 2-3 key highlights in Chinese
- "tags": array of 3-5 English lowercase tags (e.g. "llm", "open-source")
- "category": one of ["模型发布", "工具库", "论文", "行业动态", "综合技术"]
- "score": integer 1-10 rating
- "score_reason": brief Chinese explanation for the score"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Base Pipeline - Collect -> Analyze -> Organize -> Save"
    )
    parser.add_argument(
        "--sources",
        default="github,rss",
        help='Comma-separated data sources: github, rss (default: github,rss)',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max items per source (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without saving files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _make_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return slug.lower()[:80]


# ---------------------------------------------------------------------------
# Step 1: Collect
# ---------------------------------------------------------------------------


def collect_github(limit: int = 20) -> list[dict[str, Any]]:
    """Fetch top AI/LLM repositories from GitHub Search API."""
    logger.info("[Collect] GitHub Search API (limit=%d)...", limit)

    query = "ai OR llm OR agent OR machine-learning in:topics"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 100)}
    headers = {"Accept": "application/vnd.github.v3+json"}
    items: list[dict[str, Any]] = []

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(GITHUB_SEARCH_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            for repo in data.get("items", [])[:limit]:
                items.append({
                    "name": repo.get("full_name", ""),
                    "url": repo.get("html_url", ""),
                    "summary": repo.get("description") or "",
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language") or "",
                    "topics": repo.get("topics", []),
                })

            logger.info("[Collect] GitHub: %d repos collected.", len(items))
    except httpx.HTTPStatusError as e:
        logger.error("GitHub API HTTP error: %s", e)
    except httpx.RequestError as e:
        logger.error("GitHub API request failed: %s", e)
    return items


def _parse_rfc2822_date(text: str) -> str:
    """Convert RFC 2822 date string to ISO 8601."""
    if not text:
        return _now_iso()
    text = text.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return _now_iso()


def _parse_rss_items(xml: str, limit: int) -> list[dict[str, Any]]:
    """Extract items from RSS XML using regex."""
    items: list[dict[str, Any]] = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.DOTALL | re.IGNORECASE):
        if len(items) >= limit:
            break
        block = m.group(1)

        def _extract(tag: str) -> str:
            match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
            if not match:
                return ""
            val = match.group(1).strip()
            val = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", val)
            return val

        title = _extract("title")
        link = _extract("link")
        desc = _extract("description")
        desc = re.sub(r"<[^>]+>", "", desc).strip()[:500]
        pub_date = _extract("pubDate")

        if not title:
            continue
        items.append({
            "title": title,
            "url": link,
            "summary": desc,
            "published_at": _parse_rfc2822_date(pub_date),
        })
    return items


def collect_rss(limit: int = 20) -> list[dict[str, Any]]:
    """Fetch and parse enabled RSS feeds."""
    logger.info("[Collect] RSS feeds (limit=%d per source)...", limit)

    if not RSS_SOURCES_PATH.exists():
        logger.warning("RSS config not found: %s", RSS_SOURCES_PATH)
        return []

    with open(RSS_SOURCES_PATH) as f:
        config = yaml.safe_load(f)

    sources = [s for s in config.get("sources", []) if s.get("enabled")]
    if not sources:
        logger.warning("No enabled RSS sources.")
        return []

    all_items: list[dict[str, Any]] = []
    per_source = max(1, limit // len(sources))

    with httpx.Client(timeout=30.0) as client:
        for src in sources:
            name, url, cat = src["name"], src["url"], src.get("category", "综合技术")
            logger.debug("  Fetching: %s", name)
            try:
                resp = client.get(url, headers={"User-Agent": "Pipeline/1.0"})
                resp.raise_for_status()
                for item in _parse_rss_items(resp.text, per_source):
                    item["source_name"] = name
                    item["category"] = cat
                    all_items.append(item)
                logger.debug("    Got %d items from %s", sum(1 for _ in sources if _), name)
            except Exception as e:
                logger.warning("    RSS fetch failed %s: %s", name, e)

    logger.info("[Collect] RSS: %d items collected.", len(all_items))
    return all_items


# ---------------------------------------------------------------------------
# Step 2: Analyze
# ---------------------------------------------------------------------------


def _call_llm_analysis(title: str, description: str, provider: LLMProvider) -> dict[str, Any] | None:
    """Call LLM to analyze a single item and return structured analysis."""
    prompt = ANALYSIS_USER_PROMPT.format(title=title, description=description)
    messages = [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = chat_with_retry(provider, messages=messages, max_tokens=1000)
        text = resp.content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        logger.warning("LLM analysis failed for '%s': %s", title, e)
        return None


def analyze_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analyze all collected items via LLM."""
    logger.info("[Analyze] Analyzing %d items with LLM...", len(items))
    if not items:
        return []

    provider = create_provider()
    articles: list[dict[str, Any]] = []
    today = _today_str()
    now = _now_iso()

    try:
        for idx, item in enumerate(items):
            source = item.get("_source", "rss")
            title = item.get("name") or item.get("title", "")
            logger.debug("  [%d/%d] %s", idx + 1, len(items), title)

            result = _call_llm_analysis(title, item.get("summary", ""), provider)
            if not result:
                continue

            slug = _make_slug(title)
            article = {
                "id": f"{source}_{slug}_{today}",
                "title": title,
                "source": source,
                "source_url": item.get("url", ""),
                "published_at": item.get("published_at", f"{today}T00:00:00Z"),
                "summary": result.get("summary", ""),
                "highlights": result.get("highlights", []),
                "tags": result.get("tags", []),
                "category": result.get("category", "综合技术"),
                "score": int(result.get("score", 5)),
                "score_reason": result.get("score_reason", ""),
                "status": "published",
                "metadata": _build_metadata(item, source),
                "created_at": now,
                "updated_at": now,
            }
            articles.append(article)
    finally:
        provider.close()

    logger.info("[Analyze] %d articles generated.", len(articles))
    return articles


def _build_metadata(item: dict[str, Any], source: str) -> dict[str, Any]:
    if source == "github":
        return {
            "stars": item.get("stars", 0),
            "language": item.get("language", ""),
            "topics": item.get("topics", []),
        }
    return {
        "source_name": item.get("source_name", ""),
        "category": item.get("category", ""),
    }


# ---------------------------------------------------------------------------
# Step 3: Organize
# ---------------------------------------------------------------------------


def _dedup(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for a in articles:
        url = a.get("source_url", "")
        if url and url in seen:
            logger.debug("  Dedup removed: %s", a.get("title"))
            continue
        if url:
            seen.add(url)
        result.append(a)
    return result


def _standardize(article: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "id": "", "title": "", "source": "", "source_url": "",
        "published_at": "", "summary": "", "highlights": [],
        "tags": [], "category": "综合技术", "score": 5,
        "score_reason": "", "status": "published",
        "metadata": {}, "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    for k, default in fields.items():
        article.setdefault(k, default)

    article["score"] = int(article.get("score", 5))
    if not isinstance(article.get("tags"), list):
        article["tags"] = []
    article["tags"] = sorted(set(str(t) for t in article["tags"]))
    if not isinstance(article.get("highlights"), list):
        article["highlights"] = []
    return article


def organize(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup, standardize, and sort articles."""
    logger.info("[Organize] Processing %d articles...", len(articles))
    articles = _dedup(articles)
    articles = [_standardize(a) for a in articles]
    articles.sort(key=lambda a: (-a.get("score", 0), a.get("title", "")))
    logger.info("[Organize] %d articles after processing.", len(articles))
    return articles


# ---------------------------------------------------------------------------
# Step 4: Save
# ---------------------------------------------------------------------------


def _write_json(data: Any, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("  Saved: %s", path.name)
        return True
    except OSError as e:
        logger.error("  Write failed: %s - %s", path, e)
        return False


def save_raw(github_items: list[dict[str, Any]], rss_items: list[dict[str, Any]]) -> None:
    """Save raw collected data to knowledge/raw/."""
    today = _today_str()
    now = _now_iso()

    if github_items:
        clean = [{k: v for k, v in item.items() if not k.startswith("_")} for item in github_items]
        _write_json(
            {"source": "github", "collected_at": now, "items": clean},
            RAW_DIR / f"github-search-{today}.json",
        )
    if rss_items:
        clean = [{k: v for k, v in item.items() if not k.startswith("_")} for item in rss_items]
        _write_json(
            {"source": "rss", "collected_at": now, "items": clean},
            RAW_DIR / f"rss-feeds-{today}.json",
        )


def save_articles(articles: list[dict[str, Any]]) -> None:
    """Save each article as an individual JSON file in knowledge/articles/."""
    for article in articles:
        article_id = article.get("id", "")
        if not article_id:
            logger.warning("  Skipping article without id: %s", article.get("title"))
            continue
        _write_json(article, ARTICLES_DIR / f"{article_id}.json")


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run(sources: list[str], limit: int, dry_run: bool) -> int:
    """Run the full pipeline: Collect -> Analyze -> Organize -> Save."""
    logger.info("=" * 56)
    logger.info("  PIPELINE  sources=%s  limit=%d  dry_run=%s", ",".join(sources), limit, dry_run)
    logger.info("=" * 56)

    # Step 1: Collect
    logger.info("")
    logger.info("--- Step 1/4: Collect ---")
    github_items: list[dict[str, Any]] = []
    rss_items: list[dict[str, Any]] = []

    if "github" in sources:
        github_items = collect_github(limit)
    if "rss" in sources:
        rss_items = collect_rss(limit)

    if not github_items and not rss_items:
        logger.warning("No data collected. Exiting.")
        return 1

    # Merge with source tags for analysis
    all_raw: list[dict[str, Any]] = []
    for item in github_items:
        item["_source"] = "github"
        all_raw.append(item)
    for item in rss_items:
        item["_source"] = "rss"
        all_raw.append(item)

    # Step 2: Analyze
    logger.info("")
    logger.info("--- Step 2/4: Analyze ---")
    articles = analyze_items(all_raw)

    # Step 3: Organize
    logger.info("")
    logger.info("--- Step 3/4: Organize ---")
    articles = organize(articles)

    # Step 4: Save
    logger.info("")
    logger.info("--- Step 4/4: Save ---")
    if dry_run:
        logger.info("[DRY RUN] Would save %d raw + %d article files.",
                     (1 if github_items else 0) + (1 if rss_items else 0), len(articles))
    else:
        save_raw(github_items, rss_items)
        save_articles(articles)

    # Summary
    total = len(github_items) + len(rss_items)
    saved = max(1, (1 if github_items else 0) + (1 if rss_items else 0))
    logger.info("")
    logger.info("=" * 56)
    logger.info("  PIPELINE COMPLETE  collected=%d  articles=%d  saved=%d files",
                 total, len(articles), saved if dry_run else saved + len(articles))
    logger.info("=" * 56)
    return 0


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    return run(sources, args.limit, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
