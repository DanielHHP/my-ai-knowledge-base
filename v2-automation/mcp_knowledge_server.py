#!/usr/bin/env python3
"""MCP Server for local knowledge base search.

Provides 3 tools:
  - search_articles(keyword, limit=5)
  - get_article(article_id)
  - knowledge_stats()

Reads knowledge/articles/*.json and serves via JSON-RPC 2.0 over stdio.
"""

import json
import sys
from pathlib import Path
from typing import Any

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"


class KnowledgeBase:
    def __init__(self, articles_dir: Path = ARTICLES_DIR) -> None:
        self.articles_dir = articles_dir
        self._articles: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.articles_dir.is_dir():
            return
        for fpath in sorted(self.articles_dir.glob("*.json")):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    article = json.load(f)
                if "id" not in article:
                    continue
                self._articles.append(article)
                self._by_id[article["id"]] = article
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: skip {fpath.name}: {e}", file=sys.stderr)

    def search(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        kw = keyword.lower()
        hits: list[dict[str, Any]] = []
        for article in self._articles:
            if article.get("status") == "archived":
                continue
            title = (article.get("title") or "").lower()
            summary = (article.get("summary") or "").lower()
            tags = [t.lower() for t in article.get("tags", [])]
            if kw in title or kw in summary or any(kw in t for t in tags):
                hits.append(article)
                if len(hits) >= limit:
                    break
        return hits

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        return self._by_id.get(article_id)

    def stats(self) -> dict[str, Any]:
        total = len(self._articles)
        source_dist: dict[str, int] = {}
        tag_counter: dict[str, int] = {}
        for article in self._articles:
            src = article.get("source", "unknown")
            source_dist[src] = source_dist.get(src, 0) + 1
            for tag in article.get("tags", []):
                tag_counter[tag] = tag_counter.get(tag, 0) + 1
        top_tags = sorted(tag_counter.items(), key=lambda x: -x[1])[:20]
        return {
            "total_articles": total,
            "source_distribution": source_dist,
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        }


def json_text(content: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": content}]


class MCPServer:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def handle(self, req: dict[str, Any]) -> dict[str, Any] | None:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "knowledge-server", "version": "1.0.0"},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "search_articles",
                            "description": "Search knowledge base articles by keyword in title, summary, and tags",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "keyword": {
                                        "type": "string",
                                        "description": "Search keyword",
                                    },
                                    "limit": {
                                        "type": "integer",
                                        "description": "Maximum results (default: 5)",
                                        "default": 5,
                                    },
                                },
                                "required": ["keyword"],
                            },
                        },
                        {
                            "name": "get_article",
                            "description": "Get full article content by its unique ID",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "article_id": {
                                        "type": "string",
                                        "description": "Article unique ID",
                                    }
                                },
                                "required": ["article_id"],
                            },
                        },
                        {
                            "name": "knowledge_stats",
                            "description": "Return knowledge base statistics: total articles, source distribution, and top tags",
                            "inputSchema": {
                                "type": "object",
                                "properties": {},
                            },
                        },
                    ]
                },
            }

        if method == "tools/call":
            return self._call_tool(req_id, params)

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _call_tool(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name == "search_articles":
            keyword = args.get("keyword", "")
            limit = int(args.get("limit", 5))
            if limit < 1:
                limit = 5
            results = self.kb.search(keyword, limit)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": json_text(
                        json.dumps(results, ensure_ascii=False, indent=2)
                    )
                },
            }

        if name == "get_article":
            article_id = args.get("article_id", "")
            article = self.kb.get_by_id(article_id)
            if article is None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": f"Article not found: {article_id}",
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": json_text(
                        json.dumps(article, ensure_ascii=False, indent=2)
                    )
                },
            }

        if name == "knowledge_stats":
            stats = self.kb.stats()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": json_text(
                        json.dumps(stats, ensure_ascii=False, indent=2)
                    )
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {name}"},
        }


def main() -> None:
    kb = KnowledgeBase()
    server = MCPServer(kb)

    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        resp = server.handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
