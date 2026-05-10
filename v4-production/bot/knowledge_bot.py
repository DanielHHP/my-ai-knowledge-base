#!/usr/bin/env python3
"""Knowledge bot module providing search, subscription and permission management.

This module implements an interactive knowledge base bot with rule-based intent
recognition, keyword/tag/date search, user subscription management, and
three-level permission control (READ/WRITE/DELETE).

Typical usage::

    from bot.knowledge_bot import KnowledgeBot, recognize_intent, Intent

    bot = KnowledgeBot()
    reply = bot.handle_message("user_001", "/search transformer")
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
_INDEX_PATH = _KNOWLEDGE_DIR / "index.json"

_DATA_DIR = Path(__file__).resolve().parent / "data"
_SUBSCRIPTIONS_PATH = _DATA_DIR / "subscriptions.json"
_PERMISSIONS_PATH = _DATA_DIR / "permissions.json"

_DEFAULT_LIMIT = 10
_MAX_RESULTS = 50

# Command pattern: /<command> [args]
_COMMAND_RE = re.compile(r"^/(\w+)(?:\s+(.*))?$")

# Natural-language intent patterns: (patterns list, target Intent)
_NL_INTENTS: list[tuple[list[re.Pattern], "Intent"]] = []

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Intent(Enum):
    """Recognised user intent types."""

    SEARCH = "search"
    TODAY = "today"
    TOP = "top"
    SUBSCRIBE = "subscribe"
    HELP = "help"
    UNKNOWN = "unknown"


class Permission(Enum):
    """Three-level access control.

    Hierarchy: DELETE > WRITE > READ.
    A user with DELETE automatically has WRITE and READ.
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"


# ---------------------------------------------------------------------------
# Natural-language intent patterns (populated post-class-declaration)
# ---------------------------------------------------------------------------

_NL_INTENTS = [
    (
        [
            re.compile(
                r"搜索|查找|查询|搜寻|寻找|search|find|look\s*for|query", re.IGNORECASE
            ),
        ],
        Intent.SEARCH,
    ),
    (
        [
            re.compile(
                r"今天|今日|简报|日报|today|daily|briefing|digest", re.IGNORECASE
            ),
        ],
        Intent.TODAY,
    ),
    (
        [
            re.compile(r"热门|排行|top|popular|trending|best", re.IGNORECASE),
        ],
        Intent.TOP,
    ),
    (
        [
            re.compile(r"订阅|subscribe|notification|通知|追踪|follow", re.IGNORECASE),
        ],
        Intent.SUBSCRIBE,
    ),
    (
        [
            re.compile(
                r"帮助|help|怎么用|功能|指令|命令|使用说明|usage|commands?",
                re.IGNORECASE,
            ),
        ],
        Intent.HELP,
    ),
]

# ---------------------------------------------------------------------------
# Help message
# ---------------------------------------------------------------------------

_HELP_TEXT = """🤖 **知识库助手**

**支持的命令：**

`/search <关键词>` — 搜索知识库
`/today` — 今日技术简报
`/top [数量]` — 查看热门条目
`/subscribe [add|remove|list]` — 管理订阅
`/help` — 显示帮助信息

**自然语言：**
- "搜索 transformer" / "查找 OpenAI 相关文章"
- "今天有什么新内容" / "今日简报"
- "热门项目排行" / "top 5"
- "订阅 AI 标签" / "subscribe add --tag llm"
"""

# ---------------------------------------------------------------------------
# KnowledgeSearchEngine
# ---------------------------------------------------------------------------


class KnowledgeSearchEngine:
    """Search engine for the local knowledge base of AI/LLM articles.

    Loads articles from ``knowledge/articles/`` JSON files on initialisation
    and supports keyword, tag, and date-range filtering.

    Attributes:
        articles: In-memory list of article dicts, sorted by quality_score desc.
        knowledge_dir: Path to the articles directory.
    """

    def __init__(self, knowledge_dir: Path | None = None) -> None:
        """Initialise the search engine and load articles.

        Args:
            knowledge_dir: Directory containing article JSON files.
                Defaults to ``knowledge/articles/`` relative to the project root.
        """
        self._knowledge_dir = knowledge_dir or _KNOWLEDGE_DIR
        self._articles: list[dict[str, Any]] = []
        self._load_articles()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_articles(self) -> None:
        """Load all published articles from the knowledge directory into memory.

        Prefers ``index.json`` for speed; falls back to scanning individual
        ``*.json`` files when the index is absent or unreadable.
        """
        self._articles = []
        index_path = self._knowledge_dir / "index.json"

        if index_path.exists():
            try:
                with open(index_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._articles = data.get("articles", [])
                logger.info("Loaded %d articles from index.json", len(self._articles))
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read index.json: %s", exc)

        # Fallback: scan individual files
        if not self._knowledge_dir.is_dir():
            logger.warning("Knowledge directory not found: %s", self._knowledge_dir)
            return

        for fpath in sorted(self._knowledge_dir.glob("*.json")):
            if fpath.name == "index.json":
                continue
            try:
                with open(fpath, encoding="utf-8") as fh:
                    article = json.load(fh)
                if article.get("status") == "published":
                    self._articles.append(article)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping unreadable file %s: %s", fpath.name, exc)

        # Sort by quality_score descending
        self._articles.sort(key=lambda a: a.get("quality_score", 0), reverse=True)
        logger.info(
            "Loaded %d published articles from individual files", len(self._articles)
        )

    def reload(self) -> None:
        """Reload all articles from disk, discarding the in-memory cache."""
        self._load_articles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        keywords: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Search articles by keyword, tag, and date range.

        Matching is case-insensitive and scans the title, summary, and
        tags fields of each article.

        Args:
            keywords: Space-separated search terms.  An article matches if
                **any** term appears in its title, summary, or tags.
            tags: List of tag strings.  An article matches if it contains
                **any** of the specified tags.
            date_from: ISO-8601 date string (inclusive) for ``published_at``.
            date_to: ISO-8601 date string (inclusive) for ``published_at``.
            limit: Maximum number of results to return (capped at
                ``_MAX_RESULTS``).

        Returns:
            Matching articles sorted by quality_score descending.
            An empty list if nothing matches.

        Example:
            >>> engine = KnowledgeSearchEngine()
            >>> results = engine.search(keywords="transformer", tags=["llm"])
            >>> len(results) >= 0
            True
        """
        limit = min(limit, _MAX_RESULTS)
        results: list[dict[str, Any]] = []

        # Parse keyword terms
        kw_terms: list[str] = []
        if keywords:
            kw_terms = [t.lower().strip() for t in keywords.split() if t.strip()]

        # Parse date bounds
        dt_from = _parse_iso_date(date_from) if date_from else None
        dt_to = _parse_iso_date(date_to) if date_to else None

        for article in self._articles:
            if not _matches_keywords(article, kw_terms):
                continue
            if not _matches_tags(article, tags):
                continue
            if not _matches_date_range(article, dt_from, dt_to):
                continue
            results.append(article)
            if len(results) >= limit:
                break

        return results

    def get_recent(
        self, days: int = 1, limit: int = _DEFAULT_LIMIT
    ) -> list[dict[str, Any]]:
        """Return articles published within the last ``days`` calendar days.

        Args:
            days: Number of calendar days to look back (inclusive of today).
            limit: Maximum number of results.

        Returns:
            Recent articles sorted by quality_score descending.
        """
        now = datetime.now(tz=timezone.utc)
        since = now - timedelta(days=days - 1)
        date_from = since.strftime("%Y-%m-%d")
        date_to = now.strftime("%Y-%m-%d")
        return self.search(date_from=date_from, date_to=date_to, limit=limit)

    def get_top(self, n: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
        """Return the top ``n`` articles sorted by quality_score.

        Args:
            n: Number of top entries to return.

        Returns:
            Top ``n`` articles by quality_score descending.
        """
        n = min(n, _MAX_RESULTS, len(self._articles))
        return self._articles[:n]

    def article_count(self) -> int:
        """Return the total number of loaded articles."""
        return len(self._articles)


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------


class SubscriptionManager:
    """Manages user subscriptions to tags and categories.

    Subscriptions are persisted as a flat JSON object keyed by ``user_id``.
    Each subscription record contains ``tags`` and ``categories`` lists.

    Typical usage::

        mgr = SubscriptionManager()
        mgr.add_subscription("user_001", tags=["llm", "agent"])
        sub = mgr.get_subscription("user_001")
    """

    def __init__(self, store_path: Path | None = None) -> None:
        """Initialise the subscription manager.

        Args:
            store_path: Path to the subscriptions JSON file.
                Defaults to ``bot/data/subscriptions.json``.
        """
        self._store_path = store_path or _SUBSCRIPTIONS_PATH
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read subscriptions from the JSON file."""
        if self._store_path.exists():
            try:
                with open(self._store_path, encoding="utf-8") as fh:
                    self._subscriptions = json.load(fh)
                logger.debug("Loaded %d subscriptions", len(self._subscriptions))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load subscriptions: %s", exc)
                self._subscriptions = {}

    def _save(self) -> None:
        """Persist subscriptions to the JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._store_path, "w", encoding="utf-8") as fh:
            json.dump(self._subscriptions, fh, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_subscription(
        self,
        user_id: str,
        tags: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a subscription for a user (merges with existing one if any).

        Args:
            user_id: Unique identifier for the user.
            tags: List of tags to subscribe to.
            categories: List of categories to subscribe to.

        Returns:
            The updated subscription record for the user.

        Raises:
            ValueError: If neither tags nor categories are provided.
        """
        if not tags and not categories:
            raise ValueError("At least one of tags or categories must be provided")

        existing = self._subscriptions.get(user_id)
        if existing:
            merged_tags = list(dict.fromkeys(existing.get("tags", []) + (tags or [])))
            merged_cats = list(
                dict.fromkeys(existing.get("categories", []) + (categories or []))
            )
        else:
            merged_tags = list(dict.fromkeys(tags or []))
            merged_cats = list(dict.fromkeys(categories or []))

        record: dict[str, Any] = {
            "user_id": user_id,
            "tags": merged_tags,
            "categories": merged_cats,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        # Preserve original creation time
        if existing and "created_at" in existing:
            record["created_at"] = existing["created_at"]
        else:
            record["created_at"] = record["updated_at"]

        self._subscriptions[user_id] = record
        self._save()
        logger.info(
            "Subscription updated for user=%s tags=%s categories=%s",
            user_id,
            merged_tags,
            merged_cats,
        )
        return dict(record)

    def remove_subscription(
        self,
        user_id: str,
        tag: str | None = None,
        category: str | None = None,
    ) -> bool:
        """Remove a specific tag/category from a subscription or the whole record.

        Args:
            user_id: User identifier.
            tag: A specific tag to remove.  If ``None``, all tags are unaffected.
            category: A specific category to remove.  If ``None``, all categories
                are unaffected.  If both ``tag`` and ``category`` are ``None``,
                the entire subscription is removed.

        Returns:
            ``True`` if something was removed, ``False`` if no matching
            subscription was found.
        """
        if user_id not in self._subscriptions:
            return False

        if tag is None and category is None:
            del self._subscriptions[user_id]
            self._save()
            logger.info("Removed entire subscription for user=%s", user_id)
            return True

        record = self._subscriptions[user_id]
        changed = False

        if tag and tag in record.get("tags", []):
            record["tags"].remove(tag)
            changed = True
        if category and category in record.get("categories", []):
            record["categories"].remove(category)
            changed = True

        if changed:
            record["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
            # Remove the record entirely if both lists are now empty
            if not record.get("tags") and not record.get("categories"):
                del self._subscriptions[user_id]
            self._save()
            logger.info(
                "Removed tag=%s or category=%s for user=%s", tag, category, user_id
            )
            return True

        return False

    def get_subscription(self, user_id: str) -> dict[str, Any] | None:
        """Return the subscription record for a user, or ``None``.

        Args:
            user_id: User identifier.

        Returns:
            The subscription dict or ``None`` if not found.
        """
        return self._subscriptions.get(user_id)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all subscription records.

        Returns:
            A list of subscription dicts.
        """
        return list(self._subscriptions.values())


# ---------------------------------------------------------------------------
# PermissionManager
# ---------------------------------------------------------------------------


class PermissionManager:
    """Three-level permission controller (READ < WRITE < DELETE).

    Permissions are hierarchical: a user with ``DELETE`` automatically has
    ``WRITE`` and ``READ``.  Users not explicitly granted a permission
    default to ``READ``.

    Typical usage::

        pm = PermissionManager()
        pm.grant("admin", Permission.DELETE)
        pm.check("admin", Permission.WRITE)  # True
    """

    # Numeric level for hierarchical comparison
    _LEVEL: dict[Permission, int] = {
        Permission.READ: 1,
        Permission.WRITE: 2,
        Permission.DELETE: 3,
    }

    def __init__(self, store_path: Path | None = None) -> None:
        """Initialise the permission manager.

        Args:
            store_path: Path to the permissions JSON file.
                Defaults to ``bot/data/permissions.json``.
        """
        self._store_path = store_path or _PERMISSIONS_PATH
        self._permissions: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read permissions from the JSON file."""
        if self._store_path.exists():
            try:
                with open(self._store_path, encoding="utf-8") as fh:
                    self._permissions = json.load(fh)
                logger.debug("Loaded %d permission entries", len(self._permissions))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load permissions: %s", exc)
                self._permissions = {}

    def _save(self) -> None:
        """Persist permissions to the JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._store_path, "w", encoding="utf-8") as fh:
            json.dump(self._permissions, fh, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, user_id: str, required: Permission) -> bool:
        """Check whether a user has the required permission level.

        Args:
            user_id: User identifier.
            required: Minimum permission level needed.

        Returns:
            ``True`` if the user's permission level is >= the required level.

        Example:
            >>> pm = PermissionManager()
            >>> pm.check("anonymous", Permission.READ)
            True
            >>> pm.check("anonymous", Permission.WRITE)
            False
        """
        perm_str = self._permissions.get(user_id, Permission.READ.value)

        try:
            user_perm = Permission(perm_str)
        except ValueError:
            logger.warning(
                "Invalid permission '%s' for user=%s, defaulting to READ",
                perm_str,
                user_id,
            )
            user_perm = Permission.READ

        return self._LEVEL.get(user_perm, 1) >= self._LEVEL.get(required, 1)

    def grant(self, user_id: str, perm: Permission) -> None:
        """Assign a permission level to a user.

        Args:
            user_id: User identifier.
            perm: Permission level to assign.
        """
        self._permissions[user_id] = perm.value
        self._save()
        logger.info("Granted %s to user=%s", perm.value, user_id)

    def revoke(self, user_id: str, _perm: Permission | None = None) -> None:
        """Remove a user's custom permission, resetting them to the default (READ).

        Args:
            user_id: User identifier.
            _perm: Ignored — kept for API symmetry; the entire entry is removed.
        """
        if user_id in self._permissions:
            del self._permissions[user_id]
            self._save()
            logger.info("Revoked custom permissions for user=%s", user_id)

    def get_permission(self, user_id: str) -> Permission:
        """Return the effective permission level for a user.

        Args:
            user_id: User identifier.

        Returns:
            The ``Permission`` enum value for this user.
        """
        perm_str = self._permissions.get(user_id, Permission.READ.value)
        try:
            return Permission(perm_str)
        except ValueError:
            return Permission.READ


# ---------------------------------------------------------------------------
# Helper functions (module-level)
# ---------------------------------------------------------------------------


def _parse_iso_date(date_str: str) -> datetime:
    """Parse an ISO-8601 date or datetime string to a timezone-aware datetime.

    Args:
        date_str: A string like ``"2026-05-10"`` or ``"2026-05-10T00:00:00Z"``.

    Returns:
        A timezone-aware ``datetime`` object (UTC).

    Raises:
        ValueError: If the string cannot be parsed.
    """
    date_str = date_str.strip()
    # Try full datetime first
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Fall back to date-only
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _matches_keywords(article: dict[str, Any], terms: list[str]) -> bool:
    """Check if an article matches all keyword terms.

    Args:
        article: An article dict.
        terms: Lowercased keyword terms.

    Returns:
        ``True`` if no terms to match or the article matches.
    """
    if not terms:
        return True

    title = (article.get("title") or "").lower()
    summary = (article.get("summary") or "").lower()
    tag_text = " ".join(t.lower() for t in article.get("tags", []))

    haystack = f"{title} {summary} {tag_text}"
    return all(term in haystack for term in terms)


def _matches_tags(article: dict[str, Any], tags: list[str] | None) -> bool:
    """Check if an article has at least one of the requested tags.

    Args:
        article: An article dict.
        tags: List of tag strings (case-insensitive match).  ``None`` means
            no filter.

    Returns:
        ``True`` if no tags to match or the article has a matching tag.
    """
    if not tags:
        return True

    article_tags = {t.lower() for t in article.get("tags", [])}
    return any(t.lower() in article_tags for t in tags)


def _matches_date_range(
    article: dict[str, Any],
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> bool:
    """Check if an article's ``published_at`` falls within [dt_from, dt_to].

    Args:
        article: An article dict.
        dt_from: Inclusive start of range (UTC).  ``None`` means unbounded.
        dt_to: Inclusive end of range (UTC).  ``None`` means unbounded.

    Returns:
        ``True`` if the article's date is within range or both bounds are
        ``None``.
    """
    if dt_from is None and dt_to is None:
        return True

    raw = article.get("published_at")
    if not raw:
        return False

    try:
        pub_date = _parse_iso_date(str(raw))
    except ValueError:
        return False

    if dt_from and pub_date < dt_from:
        return False
    if dt_to and pub_date > dt_to:
        return False
    return True


def _format_article(article: dict[str, Any]) -> str:
    """Format a single article for display.

    Args:
        article: An article dict.

    Returns:
        A formatted string suitable for chat response.
    """
    title = article.get("title", "未知标题")
    url = article.get("source_url", "")
    category = article.get("category", "")
    score = article.get("quality_score", 0)
    tags_str = ", ".join(article.get("tags", [])[:5])
    insight = article.get("key_insight", "")
    summary = article.get("summary", "")

    lines = [
        f"**[{title}]({url})**  ⭐{score:.1f}",
    ]
    if category:
        lines.append(f"分类: {category}")
    if tags_str:
        lines.append(f"标签: `{tags_str}`")
    if insight:
        lines.append(f"> {insight}")
    elif summary:
        lines.append(f"> {summary[:150]}{'...' if len(summary) > 150 else ''}")
    return "\n".join(lines)


def _format_results(results: list[dict[str, Any]], header: str = "搜索结果") -> str:
    """Format a list of articles for display.

    Args:
        results: List of article dicts.
        header: Section header text.

    Returns:
        Formatted multiline string.
    """
    if not results:
        return f"未找到匹配的条目。"

    parts = [f"{header} (共 {len(results)} 条):"]
    for article in results:
        parts.append("")
        parts.append(_format_article(article))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Intent recognition
# ---------------------------------------------------------------------------


def recognize_intent(text: str) -> tuple[Intent, str]:
    """Recognise user intent from message text using rule-based matching.

    Evaluates in order:
        1. Command prefix (``/search``, ``/today``, ``/top``,
           ``/subscribe``, ``/help``).
        2. Natural-language keyword patterns.

    Args:
        text: Raw message text from the user.

    Returns:
        A tuple of ``(Intent, params)`` where ``params`` is the
        argument portion of the message (empty string if none).

    Example:
        >>> recognize_intent("/search transformer")
        (<Intent.SEARCH: 'search'>, 'transformer')
        >>> recognize_intent("今天的简报")
        (<Intent.TODAY: 'today'>, '')
    """
    text = text.strip()
    if not text:
        return Intent.UNKNOWN, ""

    # 1. Command prefix matching
    cmd_match = _COMMAND_RE.match(text)
    if cmd_match:
        cmd = cmd_match.group(1).lower()
        params = cmd_match.group(2) or ""

        cmd_map: dict[str, Intent] = {
            "search": Intent.SEARCH,
            "s": Intent.SEARCH,  # shorthand
            "today": Intent.TODAY,
            "top": Intent.TOP,
            "subscribe": Intent.SUBSCRIBE,
            "sub": Intent.SUBSCRIBE,  # shorthand
            "help": Intent.HELP,
            "h": Intent.HELP,  # shorthand
        }
        intent = cmd_map.get(cmd)
        if intent:
            return intent, params.strip()
        # Unknown command: treat as search
        return Intent.SEARCH, text[1:].strip()

    # 2. Natural-language keyword matching
    for patterns, intent in _NL_INTENTS:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                # Extract remaining text after the matched keyword as params
                params = text[match.end() :].strip()
                return intent, params

    return Intent.UNKNOWN, text


# ---------------------------------------------------------------------------
# KnowledgeBot
# ---------------------------------------------------------------------------


class KnowledgeBot:
    """Main entry point integrating search, subscription, and permission modules.

    Provides a unified ``handle_message(user_id, text)`` interface for
    processing user messages and returning formatted replies.

    Typical usage::

        bot = KnowledgeBot()
        reply = bot.handle_message("user_001", "/search langchain")
        print(reply)
    """

    def __init__(
        self,
        search_engine: KnowledgeSearchEngine | None = None,
        subscription_manager: SubscriptionManager | None = None,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        """Initialise the knowledge bot with its sub-modules.

        Args:
            search_engine: Pre-configured search engine.  A default instance
                is created if not supplied.
            subscription_manager: Pre-configured subscription manager.
            permission_manager: Pre-configured permission manager.
        """
        self._search = search_engine or KnowledgeSearchEngine()
        self._subs = subscription_manager or SubscriptionManager()
        self._perms = permission_manager or PermissionManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_message(self, user_id: str, text: str) -> str:
        """Process an incoming user message and return a reply.

        Args:
            user_id: Identifier of the user sending the message.
            text: Raw message text.

        Returns:
            A formatted reply string.
        """
        intent, params = recognize_intent(text)

        handler_map = {
            Intent.SEARCH: self._handle_search,
            Intent.TODAY: self._handle_today,
            Intent.TOP: self._handle_top,
            Intent.SUBSCRIBE: self._handle_subscribe,
            Intent.HELP: self._handle_help,
        }

        handler = handler_map.get(intent, self._handle_unknown)
        logger.info(
            "Handling message from user=%s intent=%s params=%r",
            user_id,
            intent.value,
            params,
        )

        try:
            return handler(user_id, params)
        except Exception as exc:
            logger.exception("Error handling message for user=%s", user_id)
            return f"处理请求时发生错误：{exc}"

    def reload_knowledge(self) -> None:
        """Reload the knowledge base from disk."""
        self._search.reload()

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    def _handle_search(self, user_id: str, params: str) -> str:
        """Handle a search intent.

        Supports::

            /search <keywords> [--tag <t1,t2>] [--from <date>] [--to <date>]

        Args:
            user_id: User identifier.
            params: Query string possibly containing flags.

        Returns:
            Formatted search results.
        """
        if not self._perms.check(user_id, Permission.READ):
            return "权限不足：搜索操作需要 READ 权限。"

        keywords, tags, date_from, date_to = _parse_search_params(params)

        if not keywords and not tags:
            return (
                "请提供搜索关键词。例如：`/search transformer` "
                "或 `/search --tag llm,agent`"
            )

        results = self._search.search(
            keywords=keywords,
            tags=tags,
            date_from=date_from,
            date_to=date_to,
        )
        return _format_results(results, header="搜索结果")

    def _handle_today(self, user_id: str, _params: str) -> str:
        """Handle a today briefing intent.

        Args:
            user_id: User identifier.
            _params: Unused.

        Returns:
            Today's briefing of recent articles.
        """
        if not self._perms.check(user_id, Permission.READ):
            return "权限不足：查看简报需要 READ 权限。"

        results = self._search.get_recent(days=1, limit=_DEFAULT_LIMIT)
        today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return _format_results(results, header=f"今日简报 ({today_str})")

    def _handle_top(self, user_id: str, params: str) -> str:
        """Handle a top-ranking intent.

        Args:
            user_id: User identifier.
            params: Optional number of results, e.g. ``"5"``.

        Returns:
            Top N articles by quality score.
        """
        if not self._perms.check(user_id, Permission.READ):
            return "权限不足：查看热门排行需要 READ 权限。"

        try:
            n = int(params) if params.strip() else _DEFAULT_LIMIT
        except ValueError:
            return f"无效的数量参数：`{params}`，请输入数字。例如：`/top 5`。"

        n = max(1, min(n, _MAX_RESULTS))
        results = self._search.get_top(n=n)
        return _format_results(results, header=f"热门 Top {n}")

    def _handle_subscribe(self, user_id: str, params: str) -> str:
        """Handle a subscription management intent.

        Supports::

            /subscribe add --tag <t1,t2> --category <c1,c2>
            /subscribe remove --tag <t1> --category <c1>
            /subscribe list
            /subscribe cancel  (remove all)

        Requires WRITE permission for add/remove/cancel.

        Args:
            user_id: User identifier.
            params: Sub-command and arguments.

        Returns:
            Operation result message.
        """
        sub_cmd, sub_params = _parse_subscribe_params(params)

        if sub_cmd == "list":
            if not self._perms.check(user_id, Permission.READ):
                return "权限不足：查看订阅需要 READ 权限。"
            sub = self._subs.get_subscription(user_id)
            if not sub:
                return "你当前还没有订阅任何内容。\n使用 `/subscribe add --tag <标签>` 来订阅。"
            tags = sub.get("tags", [])
            cats = sub.get("categories", [])
            lines = ["你的订阅："]
            if tags:
                lines.append(f"标签: {', '.join(tags)}")
            if cats:
                lines.append(f"分类: {', '.join(cats)}")
            return "\n".join(lines)

        if sub_cmd == "add":
            if not self._perms.check(user_id, Permission.WRITE):
                return "权限不足：添加订阅需要 WRITE 权限。"
            sub_tags, sub_cats = sub_params
            if not sub_tags and not sub_cats:
                return (
                    "请指定要订阅的标签或分类。\n"
                    "示例：`/subscribe add --tag llm,agent`"
                )
            self._subs.add_subscription(user_id, tags=sub_tags, categories=sub_cats)
            parts = ["订阅已更新！"]
            if sub_tags:
                parts.append(f"标签: {', '.join(sub_tags)}")
            if sub_cats:
                parts.append(f"分类: {', '.join(sub_cats)}")
            return "\n".join(parts)

        if sub_cmd in ("remove", "rm"):
            if not self._perms.check(user_id, Permission.WRITE):
                return "权限不足：移除订阅需要 WRITE 权限。"
            tag, cat = sub_params
            removed = self._subs.remove_subscription(user_id, tag=tag, category=cat)
            if removed:
                if tag:
                    return f"已移除标签 `{tag}`。"
                if cat:
                    return f"已移除分类 `{cat}`。"
                return "已移除订阅。"
            return "未找到匹配的订阅项。"

        if sub_cmd == "cancel":
            if not self._perms.check(user_id, Permission.WRITE):
                return "权限不足：取消订阅需要 WRITE 权限。"
            removed = self._subs.remove_subscription(user_id)
            if removed:
                return "已取消所有订阅。"
            return "你当前没有订阅，无需取消。"

        # Unknown sub-command: show help for subscribe
        return (
            "无效的订阅操作。支持的操作：\n"
            "`/subscribe add --tag <标签>` — 添加标签订阅\n"
            "`/subscribe add --category <分类>` — 添加分类订阅\n"
            "`/subscribe remove --tag <标签>` — 移除标签\n"
            "`/subscribe list` — 查看当前订阅\n"
            "`/subscribe cancel` — 取消所有订阅"
        )

    def _handle_help(self, _user_id: str, _params: str) -> str:
        """Handle a help intent.  No permission check needed.

        Args:
            _user_id: User identifier (unused).
            _params: Parameters (unused).

        Returns:
            The help text.
        """
        return _HELP_TEXT

    def _handle_unknown(self, user_id: str, params: str) -> str:
        """Handle unrecognised intents by falling back to a keyword search.

        Args:
            user_id: User identifier.
            params: The unrecognised message text.

        Returns:
            Search results or a fallback message.
        """
        if not params.strip():
            return (
                "我不太明白你的意思。\n"
                "你可以使用以下命令：\n"
                "`/search`, `/today`, `/top`, `/subscribe`, `/help`\n"
                "或者直接输入关键词进行搜索。"
            )

        if not self._perms.check(user_id, Permission.READ):
            return "权限不足：搜索操作需要 READ 权限。"

        results = self._search.search(keywords=params)
        if results:
            return _format_results(results, header=f"搜索「{params}」的结果")
        return f"未找到与「{params}」相关的内容。\n输入 `/help` 查看使用帮助。"


# ---------------------------------------------------------------------------
# Parameter-parsing helpers
# ---------------------------------------------------------------------------


def _parse_search_params(
    params: str,
) -> tuple[str | None, list[str] | None, str | None, str | None]:
    """Extract keywords, tags, and date filters from a search parameter string.

    Args:
        params: Raw parameter string, e.g.
            ``"transformer --tag llm,agent --from 2026-05-01 --to 2026-05-10"``.

    Returns:
        A tuple of ``(keywords, tags, date_from, date_to)``.  ``None`` values
        indicate no filter was specified.
    """
    keywords: list[str] = []
    tags: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None

    # Split into tokens while respecting quoted strings
    tokens = _tokenize(params)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--tag" and i + 1 < len(tokens):
            i += 1
            tags = [t.strip() for t in tokens[i].split(",") if t.strip()]
        elif token == "--from" and i + 1 < len(tokens):
            i += 1
            date_from = tokens[i]
        elif token == "--to" and i + 1 < len(tokens):
            i += 1
            date_to = tokens[i]
        else:
            keywords.append(token)
        i += 1

    kw_str = " ".join(keywords) if keywords else None
    return kw_str, tags, date_from, date_to


def _parse_subscribe_params(
    params: str,
) -> tuple[str, tuple[list[str] | str | None, list[str] | str | None]]:
    """Parse subscription sub-command and arguments.

    Args:
        params: Raw subscription parameter string, e.g.
            ``"add --tag llm,agent --category 模型发布"`` or ``"list"``.

    Returns:
        A tuple of ``(sub_command, (tags_or_single_tag, categories_or_single_cat))``.
        For ``remove`` the second element contains single strings instead of lists.
    """
    tokens = _tokenize(params)

    sub_cmd = tokens[0].lower() if tokens else "list"

    tags_arg: list[str] = []
    cats_arg: list[str] = []

    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == "--tag" and i + 1 < len(tokens):
            i += 1
            tags_arg = [t.strip() for t in tokens[i].split(",") if t.strip()]
        elif token == "--category" and i + 1 < len(tokens):
            i += 1
            cats_arg = [c.strip() for c in tokens[i].split(",") if c.strip()]
        i += 1

    if sub_cmd == "remove" or sub_cmd == "rm":
        single_tag = tags_arg[0] if tags_arg else None
        single_cat = cats_arg[0] if cats_arg else None
        return sub_cmd, (single_tag, single_cat)

    return sub_cmd, (tags_arg if tags_arg else None, cats_arg if cats_arg else None)


def _tokenize(text: str) -> list[str]:
    """Split a parameter string into tokens, respecting double-quoted groups.

    Args:
        text: Raw parameter string.

    Returns:
        List of string tokens.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False

    for ch in text:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)

    if current:
        tokens.append("".join(current))

    return tokens
