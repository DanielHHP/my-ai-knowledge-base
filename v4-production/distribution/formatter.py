#!/usr/bin/env python3
"""Formatters for knowledge articles: Markdown, Telegram MarkdownV2, and Feishu interactive cards.

Pure functions — no network I/O.  Network communication belongs to ``publisher.py``.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telegram MarkdownV2 转义字符映射
# ---------------------------------------------------------------------------

_TELEGRAM_ESCAPE_CHARS = str.maketrans(
    {
        "_": r"\_",
        "*": r"\*",
        "[": r"\[",
        "]": r"\]",
        "(": r"\(",
        ")": r"\)",
        "~": r"\~",
        "`": r"\`",
        ">": r"\>",
        "#": r"\#",
        "+": r"\+",
        "-": r"\-",
        "=": r"\=",
        "|": r"\|",
        "{": r"\{",
        "}": r"\}",
        ".": r"\.",
        "!": r"\!",
    }
)


def _escape_telegram(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped string safe for Telegram MarkdownV2.
    """
    return text.translate(_TELEGRAM_ESCAPE_CHARS)


def _score_emoji(score: float) -> str:
    """Return a visual indicator for a quality score.

    Args:
        score: Quality score (0.0–1.0).

    Returns:
        ``🟢`` for ≥0.8, ``🟟`` for ≥0.6, ``🔴`` otherwise.
    """
    if score >= 0.8:
        return "🟢"
    if score >= 0.6:
        return "🟟"
    return "🔴"


def _score_feishu_color(score: float) -> str:
    """Return Feishu card header template color based on quality score.

    Args:
        score: Quality score (0.0–1.0).

    Returns:
        ``"green"`` for ≥0.8, ``"yellow"`` for ≥0.6, ``"red"`` otherwise.
    """
    if score >= 0.8:
        return "green"
    if score >= 0.6:
        return "yellow"
    return "red"


def _resolve_date(article: dict[str, Any]) -> str:
    """Extract a date string from the article, returning the first 10 chars.

    Tries ``created_at`` first, then ``collected_at``, then ``published_at``.

    Args:
        article: Knowledge article dict.

    Returns:
        ``YYYY-MM-DD`` date string, or empty string if none found.
    """
    for field in ("created_at", "collected_at", "published_at"):
        value = article.get(field, "")
        if value:
            return value[:10]
    return ""


# ---------------------------------------------------------------------------
# Single-article formatters
# ---------------------------------------------------------------------------


def json_to_markdown(article: dict[str, Any]) -> str:
    """Format a single knowledge article as Markdown.

    Args:
        article: Knowledge article dict with fields ``title``, ``source``,
            ``source_url``, ``quality_score``, ``tags``, ``summary``,
            ``key_insight``, and a date field (``created_at`` /
            ``collected_at`` / ``published_at``).

    Returns:
        Markdown formatted string.

    Example::

        >>> a = {"title": "test/repo", "source": "github",
        ...      "source_url": "https://github.com/test/repo",
        ...      "created_at": "2026-05-09T10:30:00Z",
        ...      "quality_score": 0.85, "tags": ["ai", "llm"],
        ...      "summary": "A test repo.", "key_insight": "key insight"}
        >>> print(json_to_markdown(a))
    """
    title = article.get("title", "Untitled")
    source = article.get("source", "unknown")
    score = article.get("quality_score", 0.0)
    tags = ", ".join(f"`{t}`" for t in article.get("tags", []))
    summary = article.get("summary", "")
    source_url = article.get("source_url", "")
    key_insight = article.get("key_insight", "")
    article_date = _resolve_date(article)

    lines: list[str] = []

    lines.append(f"### {title}")
    lines.append("")
    lines.append(f"- **来源**: {source}")
    lines.append(f"- **日期**: {article_date}")
    lines.append(f"- **相关性**: {_score_emoji(score)} ({score:.2f})")
    if key_insight:
        lines.append(f"- **核心洞察**: {key_insight}")
    if tags:
        lines.append(f"- **标签**: {tags}")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append(f"🔗 [原文链接]({source_url})")

    return "\n".join(lines)


def json_to_telegram(article: dict[str, Any]) -> str:
    """Format a single knowledge article for Telegram MarkdownV2.

    Special characters ``_*[]()~`>#+-=|{}.!`` are escaped. Tags have spaces
    replaced with underscores.

    Args:
        article: Knowledge article dict.

    Returns:
        Telegram MarkdownV2 formatted string.

    Example::

        >>> a = {"title": "test/repo",
        ...      "source_url": "https://github.com/test/repo",
        ...      "summary": "A test.", "quality_score": 0.85,
        ...      "source": "github",
        ...      "tags": ["ai agents", "ml"]}
        >>> print(json_to_telegram(a))
    """
    title = _escape_telegram(article.get("title", "Untitled"))
    source_url = article.get("source_url", "")
    summary = _escape_telegram(article.get("summary", ""))
    score = article.get("quality_score", 0.0)
    source = _escape_telegram(article.get("source", "unknown"))
    tags = article.get("tags", [])
    tags_text = ", ".join(
        _escape_telegram(f"#{t.replace(' ', '_')}") for t in tags
    )

    lines: list[str] = []

    lines.append(f"[{title}]({source_url})")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append(f"{_score_emoji(score)} 相关性: {score:.2f}")
    lines.append(f"来源: {source}")
    if tags_text:
        lines.append(f"标签: {tags_text}")

    return "\n".join(lines)


def json_to_feishu(article: dict[str, Any]) -> dict[str, Any]:
    """Format a single knowledge article as a Feishu Card JSON v2.0 dict.

    Returns the bare card dict (``schema`` / ``config`` / ``header`` /
    ``body``).  The caller (``publisher.py``) is responsible for wrapping it
    with ``msg_type: "interactive"`` and ``content: json.dumps(card)`` in the
    API request body.

    The header colour is driven by ``quality_score``:
    ``green`` for ≥0.8, ``yellow`` for ≥0.6, ``red`` otherwise.

    Official Feishu Card JSON v2.0 reference:
    https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-json-v2-structure

    Args:
        article: Knowledge article dict.

    Returns:
        Feishu Card JSON v2.0 dict (without ``msg_type``).

    Example::

        >>> import json
        >>> a = {"title": "test/repo",
        ...      "source_url": "https://github.com/test/repo",
        ...      "summary": "A test.", "quality_score": 0.85,
        ...      "source": "github",
        ...      "created_at": "2026-05-09T10:30:00Z",
        ...      "tags": ["ai", "ml"],
        ...      "key_insight": "key insight"}
        >>> card = json_to_feishu(a)
        >>> card["schema"]
        '2.0'
        >>> card["header"]["template"]
        'green'
        >>> # Publisher wraps: {"msg_type": "interactive", "content": json.dumps(card)}
    """
    title = article.get("title", "Untitled")
    source = article.get("source", "unknown")
    score = article.get("quality_score", 0.0)
    summary = article.get("summary", "")
    source_url = article.get("source_url", "")
    tags = article.get("tags", [])
    key_insight = article.get("key_insight", "")
    article_date = _resolve_date(article)

    body_elements: list[dict[str, Any]] = []

    if key_insight:
        body_elements.append(
            {
                "tag": "markdown",
                "content": f"**核心洞察**: {key_insight}",
            }
        )

    if summary:
        body_elements.append(
            {
                "tag": "markdown",
                "content": summary,
            }
        )

    fields: list[dict[str, Any]] = [
        {
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**来源**\n{source}"},
        },
        {
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**日期**\n{article_date}"},
        },
        {
            "is_short": True,
            "text": {"tag": "lark_md", "content": f"**相关性**\n{score:.2f}"},
        },
    ]
    if tags:
        fields.append(
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**标签**\n{', '.join(tags)}",
                },
            }
        )

    body_elements.append({"tag": "div", "fields": fields})

    body_elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看原文"},
                    "type": "primary",
                    "url": source_url,
                },
            ],
        }
    )

    body_elements.append({"tag": "hr"})

    body_elements.append(
        {
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": "AI 知识库助手自动生成"},
            ],
        }
    )

    return {
        "schema": "2.0",
        "config": {
            "enable_forward": True,
            "update_multi": True,
            "width_mode": "fill",
        },
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": _score_feishu_color(score),
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": body_elements,
        },
    }


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def generate_daily_digest(
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """Generate a daily digest from knowledge article JSON files.

    Scans ``knowledge_dir`` for files matching ``*_{date}.json``, sorts them
    by ``quality_score`` in descending order, and formats the top N articles
    for all three output channels.

    Args:
        knowledge_dir: Path to the directory containing knowledge article JSON
            files.
        date: Date string in ``YYYY-MM-DD`` format.  Defaults to today's date.
        top_n: Maximum number of articles to include in the digest.

    Returns:
        A dict with keys:

        - ``"markdown"`` — combined Markdown string.
        - ``"telegram"`` — combined Telegram MarkdownV2 string.
        - ``"feishu"`` — list of Feishu card dicts.

        When no articles are found for the given date, all string values are
        set to ``"📭 {date} 暂无新增知识条目"`` and ``"feishu"`` is an empty
        list.

    Example::

        >>> digest = generate_daily_digest(date="2026-05-09")
        >>> len(digest["feishu"]) <= 5
        True
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    articles_dir = Path(knowledge_dir)

    if not articles_dir.is_dir():
        logger.warning("Knowledge directory not found: %s", articles_dir)
        empty_msg = f"📭 {date} 暂无新增知识条目"
        return {"markdown": empty_msg, "telegram": empty_msg, "feishu": []}

    files = sorted(articles_dir.glob(f"*_{date}.json"))

    if not files:
        logger.info("No knowledge articles found for %s", date)
        empty_msg = f"📭 {date} 暂无新增知识条目"
        return {"markdown": empty_msg, "telegram": empty_msg, "feishu": []}

    articles: list[dict[str, Any]] = []
    for filepath in files:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            articles.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read article %s: %s", filepath, exc)

    if not articles:
        empty_msg = f"📭 {date} 暂无新增知识条目"
        return {"markdown": empty_msg, "telegram": empty_msg, "feishu": []}

    articles.sort(key=lambda a: a.get("quality_score", 0.0), reverse=True)
    top_articles = articles[:top_n]

    # -- Markdown digest --
    markdown_lines: list[str] = [
        f"# 📰 AI 技术动态日报 — {date}",
        "",
        f"共 {len(articles)} 条知识，以下展示相关度最高的 {len(top_articles)} 条：",
        "",
    ]
    for i, art in enumerate(top_articles, 1):
        markdown_lines.append("---")
        markdown_lines.append("")
        markdown_lines.append(f"## {i}. {art.get('title', 'Untitled')}")
        markdown_lines.append("")
        markdown_lines.append(json_to_markdown(art))
        markdown_lines.append("")
    markdown = "\n".join(markdown_lines)

    # -- Telegram digest --
    telegram_lines: list[str] = [
        f"📰 *{_escape_telegram(date)} AI 技术动态日报*",
        "",
    ]
    for i, art in enumerate(top_articles, 1):
        telegram_lines.append(f"━━━  *第 {i} 条*  ━━━")
        telegram_lines.append(json_to_telegram(art))
        telegram_lines.append("")
    telegram = "\n".join(telegram_lines)

    # -- Feishu digest (list of individual card dicts) --
    feishu_cards: list[dict[str, Any]] = [json_to_feishu(a) for a in top_articles]

    return {
        "markdown": markdown,
        "telegram": telegram,
        "feishu": feishu_cards,
    }
