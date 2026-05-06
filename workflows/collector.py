"""[CollectNode] 从 GitHub Search API 采集 AI/LLM/Agent 相关仓库。"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

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
