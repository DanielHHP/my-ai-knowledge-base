"""[CollectNode] 从 GitHub Search API 采集 AI/LLM/Agent 相关仓库。"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from tests.security import sanitize_input
from workflows.state import KBState

logger = logging.getLogger(__name__)

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def collect_node(state: KBState) -> dict:
    """Fetch top AI/LLM repos from GitHub Search API via urllib.

    Args:
        state: 当前工作流状态。

    Returns:
        Partial state update，包含 ``sources`` 字段。
    """
    logger.info("[CollectNode] Fetching GitHub trending repos...")

    plan = state.get("plan", {}) or {}
    per_page = int(plan.get("per_source_limit", 10))

    query = "ai OR llm OR agent OR machine-learning in:topics"
    encoded_query = urllib.parse.quote(query)
    url = f"{GITHUB_SEARCH_URL}?q={encoded_query}&sort=stars&order=desc&per_page={per_page}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    sources: list[dict] = []
    injection_hits = 0

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for repo in data.get("items", []):
                title = repo.get("full_name", "")
                description = repo.get("description") or ""

                cleaned_title, title_warnings = sanitize_input(title)
                cleaned_desc, desc_warnings = sanitize_input(description)
                all_warnings = title_warnings + desc_warnings

                if all_warnings:
                    injection_hits += 1
                    logger.warning(
                        "[CollectNode] 注入风险 - repo=%s, warnings=%s",
                        title,
                        all_warnings,
                    )

                sources.append({
                    "platform": "github",
                    "title": cleaned_title,
                    "url": repo.get("html_url", ""),
                    "description": cleaned_desc,
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

    logger.info("[CollectNode] Collected %d repos, injection_hits=%d", len(sources), injection_hits)
    return {"sources": sources}
