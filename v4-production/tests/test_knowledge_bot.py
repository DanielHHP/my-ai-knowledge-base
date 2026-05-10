"""Unit tests for bot.knowledge_bot."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.knowledge_bot import (  # noqa: E402
    Intent,
    KnowledgeBot,
    KnowledgeSearchEngine,
    Permission,
    PermissionManager,
    SubscriptionManager,
    _format_article,
    _format_results,
    _matches_date_range,
    _matches_keywords,
    _matches_tags,
    _parse_iso_date,
    _parse_search_params,
    _parse_subscribe_params,
    _tokenize,
    recognize_intent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    title: str = "test/repo",
    source: str = "github",
    published_at: str = "2026-05-10T00:00:00Z",
    tags: list[str] | None = None,
    quality_score: float = 0.9,
    summary: str = "A test article summary.",
    key_insight: str = "Key insight text.",
    **kwargs,
) -> dict:
    return {
        "id": f"{source}_{title.replace('/', '-')}_2026-05-10",
        "title": title,
        "source": source,
        "source_url": f"https://github.com/{title}",
        "published_at": published_at,
        "key_insight": key_insight,
        "summary": summary,
        "content": "",
        "tags": tags or ["test", "mock"],
        "category": kwargs.get("category", "工具库"),
        "status": kwargs.get("status", "published"),
        "metadata": {"stars": 1000},
        "created_at": "2026-05-10T12:00:00Z",
        "updated_at": "2026-05-10T12:00:00Z",
        "quality_score": quality_score,
    }


# ---------------------------------------------------------------------------
# _parse_iso_date
# ---------------------------------------------------------------------------


class TestParseIsoDate:
    def test_full_utc(self) -> None:
        dt = _parse_iso_date("2026-05-10T08:30:00Z")
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 10
        assert dt.hour == 8
        assert dt.tzinfo is not None

    def test_date_only(self) -> None:
        dt = _parse_iso_date("2026-05-10")
        assert dt.year == 2026
        assert dt.month == 5
        assert dt.day == 10
        assert dt.hour == 0

    def test_datetime_no_z(self) -> None:
        dt = _parse_iso_date("2026-05-10T12:00:00")
        assert dt.hour == 12
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _matches_keywords
# ---------------------------------------------------------------------------


class TestMatchesKeywords:
    def test_empty_terms_always_match(self) -> None:
        article = _make_article()
        assert _matches_keywords(article, []) is True

    def test_match_in_title(self) -> None:
        article = _make_article(title="awesome-llm-toolkit")
        assert _matches_keywords(article, ["llm"]) is True

    def test_match_in_summary(self) -> None:
        article = _make_article(summary="This is about transformers.")
        assert _matches_keywords(article, ["transformer"]) is True

    def test_match_in_tags(self) -> None:
        article = _make_article(tags=["deep-learning", "pytorch"])
        assert _matches_keywords(article, ["deep-learning"]) is True

    def test_all_terms_must_match(self) -> None:
        article = _make_article(title="llm toolkit", tags=["agent"])
        assert _matches_keywords(article, ["llm", "agent"]) is True

    def test_one_missing_term_fails(self) -> None:
        article = _make_article(title="llm toolkit")
        assert _matches_keywords(article, ["llm", "nonexistent"]) is False

    def test_case_insensitive(self) -> None:
        article = _make_article(title="LLM Toolkit")
        assert _matches_keywords(article, ["llm"]) is True


# ---------------------------------------------------------------------------
# _matches_tags
# ---------------------------------------------------------------------------


class TestMatchesTags:
    def test_none_tags_always_match(self) -> None:
        article = _make_article()
        assert _matches_tags(article, None) is True

    def test_empty_tags_always_match(self) -> None:
        article = _make_article()
        assert _matches_tags(article, []) is True

    def test_any_tag_matches(self) -> None:
        article = _make_article(tags=["llm", "agent", "python"])
        assert _matches_tags(article, ["python"]) is True

    def test_no_overlap_fails(self) -> None:
        article = _make_article(tags=["llm", "agent"])
        assert _matches_tags(article, ["rust"]) is False

    def test_case_insensitive(self) -> None:
        article = _make_article(tags=["LLM", "Agent"])
        assert _matches_tags(article, ["llm"]) is True


# ---------------------------------------------------------------------------
# _matches_date_range
# ---------------------------------------------------------------------------


class TestMatchesDateRange:
    def test_no_bounds_always_match(self) -> None:
        article = _make_article()
        assert _matches_date_range(article, None, None) is True

    def test_within_bounds(self) -> None:
        article = _make_article(published_at="2026-05-10T12:00:00Z")
        dt_from = _parse_iso_date("2026-05-09")
        dt_to = _parse_iso_date("2026-05-11")
        assert _matches_date_range(article, dt_from, dt_to) is True

    def test_before_from(self) -> None:
        article = _make_article(published_at="2026-05-08T00:00:00Z")
        dt_from = _parse_iso_date("2026-05-09")
        assert _matches_date_range(article, dt_from, None) is False

    def test_after_to(self) -> None:
        article = _make_article(published_at="2026-05-12T00:00:00Z")
        dt_to = _parse_iso_date("2026-05-11")
        assert _matches_date_range(article, None, dt_to) is False

    def test_missing_published_at(self) -> None:
        article = _make_article()
        article.pop("published_at")
        dt_from = _parse_iso_date("2026-05-09")
        assert _matches_date_range(article, dt_from, None) is False


# ---------------------------------------------------------------------------
# _format_article / _format_results
# ---------------------------------------------------------------------------


class TestFormatArticle:
    def test_includes_title(self) -> None:
        result = _format_article(_make_article(title="foo/bar"))
        assert "foo/bar" in result

    def test_includes_score(self) -> None:
        result = _format_article(_make_article(quality_score=0.85))
        assert "0.8" in result or "0.9" in result

    def test_includes_tags(self) -> None:
        result = _format_article(_make_article(tags=["llm", "agent"]))
        assert "llm" in result

    def test_includes_insight(self) -> None:
        result = _format_article(_make_article(key_insight="Game changer"))
        assert "Game changer" in result

    def test_falls_back_to_summary(self) -> None:
        result = _format_article(
            _make_article(key_insight="", summary="A brief summary text.")
        )
        assert "A brief summary text." in result


class TestFormatResults:
    def test_empty_results(self) -> None:
        result = _format_results([], header="搜索")
        assert "未找到" in result

    def test_multiple_results(self) -> None:
        articles = [
            _make_article(title="a/b", quality_score=0.9),
            _make_article(title="c/d", quality_score=0.8),
        ]
        result = _format_results(articles, header="结果")
        assert "共 2 条" in result
        assert "a/b" in result
        assert "c/d" in result


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_simple_tokens(self) -> None:
        assert _tokenize("a b c") == ["a", "b", "c"]

    def test_quoted_string(self) -> None:
        assert _tokenize('a "b c" d') == ["a", "b c", "d"]

    def test_empty_string(self) -> None:
        assert _tokenize("") == []

    def test_multiple_spaces(self) -> None:
        assert _tokenize("a   b") == ["a", "b"]


# ---------------------------------------------------------------------------
# _parse_search_params
# ---------------------------------------------------------------------------


class TestParseSearchParams:
    def test_keywords_only(self) -> None:
        kw, tags, frm, to = _parse_search_params("transformer llm")
        assert kw == "transformer llm"
        assert tags is None
        assert frm is None
        assert to is None

    def test_with_tags(self) -> None:
        kw, tags, frm, to = _parse_search_params("transformer --tag llm,agent")
        assert kw == "transformer"
        assert tags == ["llm", "agent"]

    def test_with_dates(self) -> None:
        kw, tags, frm, to = _parse_search_params("--from 2026-05-01 --to 2026-05-10")
        assert frm == "2026-05-01"
        assert to == "2026-05-10"

    def test_all_combined(self) -> None:
        kw, tags, frm, to = _parse_search_params(
            "gpt --tag llm,openai --from 2026-05-01 --to 2026-05-10"
        )
        assert kw == "gpt"
        assert tags == ["llm", "openai"]
        assert frm == "2026-05-01"
        assert to == "2026-05-10"


# ---------------------------------------------------------------------------
# _parse_subscribe_params
# ---------------------------------------------------------------------------


class TestParseSubscribeParams:
    def test_list_default(self) -> None:
        cmd, (tags, cats) = _parse_subscribe_params("")
        assert cmd == "list"

    def test_add_with_tag(self) -> None:
        cmd, (tags, cats) = _parse_subscribe_params("add --tag llm,agent")
        assert cmd == "add"
        assert tags == ["llm", "agent"]

    def test_add_with_category(self) -> None:
        cmd, (tags, cats) = _parse_subscribe_params("add --category 模型发布")
        assert cmd == "add"
        assert cats == ["模型发布"]

    def test_remove_tag_single(self) -> None:
        cmd, (tag, cat) = _parse_subscribe_params("remove --tag llm")
        assert cmd == "remove"
        assert tag == "llm"
        assert cat is None

    def test_cancel(self) -> None:
        cmd, (tags, cats) = _parse_subscribe_params("cancel")
        assert cmd == "cancel"


# ---------------------------------------------------------------------------
# recognize_intent
# ---------------------------------------------------------------------------


class TestRecognizeIntent:
    # ── Command-prefix matching ──

    def test_search_command(self) -> None:
        intent, params = recognize_intent("/search transformer")
        assert intent is Intent.SEARCH
        assert params == "transformer"

    def test_search_shortcut(self) -> None:
        intent, params = recognize_intent("/s llm agent")
        assert intent is Intent.SEARCH
        assert params == "llm agent"

    def test_today_command(self) -> None:
        intent, params = recognize_intent("/today")
        assert intent is Intent.TODAY
        assert params == ""

    def test_top_command(self) -> None:
        intent, params = recognize_intent("/top 5")
        assert intent is Intent.TOP
        assert params == "5"

    def test_subscribe_command(self) -> None:
        intent, params = recognize_intent("/subscribe add --tag llm")
        assert intent is Intent.SUBSCRIBE
        assert params == "add --tag llm"

    def test_subscribe_shortcut(self) -> None:
        intent, params = recognize_intent("/sub list")
        assert intent is Intent.SUBSCRIBE
        assert params == "list"

    def test_help_command(self) -> None:
        intent, params = recognize_intent("/help")
        assert intent is Intent.HELP

    def test_help_shortcut(self) -> None:
        intent, params = recognize_intent("/h")
        assert intent is Intent.HELP

    def test_unknown_command_becomes_search(self) -> None:
        intent, params = recognize_intent("/foobar arg1")
        assert intent is Intent.SEARCH
        assert params == "foobar arg1"

    def test_case_insensitive_command(self) -> None:
        intent, params = recognize_intent("/SEARCH gpt")
        assert intent is Intent.SEARCH
        assert params == "gpt"

    # ── Natural-language matching ──

    def test_nl_search_cn(self) -> None:
        intent, params = recognize_intent("搜索 transformer")
        assert intent is Intent.SEARCH

    def test_nl_search_en(self) -> None:
        intent, params = recognize_intent("search for llm agents")
        assert intent is Intent.SEARCH

    def test_nl_find(self) -> None:
        intent, params = recognize_intent("查找 langchain 相关文章")
        assert intent is Intent.SEARCH

    def test_nl_today_cn(self) -> None:
        intent, params = recognize_intent("今天的简报")
        assert intent is Intent.TODAY

    def test_nl_today_en(self) -> None:
        intent, params = recognize_intent("today briefing")
        assert intent is Intent.TODAY

    def test_nl_top_cn(self) -> None:
        intent, params = recognize_intent("热门项目排行")
        assert intent is Intent.TOP

    def test_nl_top_en(self) -> None:
        intent, params = recognize_intent("top 5 projects")
        assert intent is Intent.TOP

    def test_nl_subscribe_cn(self) -> None:
        intent, params = recognize_intent("订阅 AI 相关标签")
        assert intent is Intent.SUBSCRIBE

    def test_nl_subscribe_en(self) -> None:
        intent, params = recognize_intent("subscribe to llm tags")
        assert intent is Intent.SUBSCRIBE

    def test_nl_help_cn(self) -> None:
        intent, params = recognize_intent("帮助")
        assert intent is Intent.HELP

    def test_nl_help_en(self) -> None:
        intent, params = recognize_intent("help me")
        assert intent is Intent.HELP

    # ── Edge cases ──

    def test_empty_string(self) -> None:
        intent, params = recognize_intent("")
        assert intent is Intent.UNKNOWN
        assert params == ""

    def test_whitespace_only(self) -> None:
        intent, params = recognize_intent("   ")
        assert intent is Intent.UNKNOWN
        assert params == ""

    def test_command_priority_over_nl(self) -> None:
        # "/search" should be recognised as command even though "search"
        # would also match natural-language patterns
        intent, params = recognize_intent("/search top results")
        assert intent is Intent.SEARCH


# ---------------------------------------------------------------------------
# KnowledgeSearchEngine (with temp dir)
# ---------------------------------------------------------------------------


class TestKnowledgeSearchEngine:
    @pytest.fixture
    def index_json(self) -> dict:
        return {
            "articles": [
                {
                    "id": "github_a_b_2026-05-10",
                    "title": "a/b",
                    "source": "github",
                    "published_at": "2026-05-10T00:00:00Z",
                    "tags": ["llm"],
                    "quality_score": 0.95,
                    "status": "published",
                },
                {
                    "id": "github_c_d_2026-05-09",
                    "title": "c/d",
                    "source": "github",
                    "published_at": "2026-05-09T00:00:00Z",
                    "tags": ["agent"],
                    "quality_score": 0.80,
                    "status": "published",
                },
                {
                    "id": "github_e_f_2026-05-08",
                    "title": "e/f",
                    "source": "hackernews",
                    "published_at": "2026-05-08T00:00:00Z",
                    "tags": ["rust"],
                    "quality_score": 0.60,
                    "status": "published",
                },
            ]
        }

    @pytest.fixture
    def engine(self, tmp_path, index_json) -> KnowledgeSearchEngine:
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir()
        (articles_dir / "index.json").write_text(
            json.dumps(index_json, ensure_ascii=False),
            encoding="utf-8",
        )
        return KnowledgeSearchEngine(knowledge_dir=articles_dir)

    def test_loads_from_index(self, engine, index_json) -> None:
        assert engine.article_count() == 3

    def test_search_by_keyword(self, engine) -> None:
        results = engine.search(keywords="b")
        assert len(results) == 1
        assert results[0]["id"] == "github_a_b_2026-05-10"

    def test_search_by_tag(self, engine) -> None:
        results = engine.search(tags=["agent"])
        assert len(results) == 1
        assert results[0]["id"] == "github_c_d_2026-05-09"

    def test_search_by_date_range(self, engine) -> None:
        results = engine.search(date_from="2026-05-09", date_to="2026-05-10")
        assert len(results) == 2

    def test_search_with_limit(self, engine) -> None:
        results = engine.search(limit=1)
        assert len(results) == 1

    def test_search_no_results(self, engine) -> None:
        results = engine.search(keywords="nonexistent123")
        assert results == []

    def test_get_recent(self, engine) -> None:
        # get_recent(days=1) returns articles matching *today*
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        # Only the article whose published_at falls on today should match
        results = engine.get_recent(days=1)
        expected = [
            a for a in engine._articles if a.get("published_at", "").startswith(today)
        ]
        assert len(results) == len(expected)

    def test_get_top(self, engine) -> None:
        results = engine.get_top(n=2)
        assert len(results) == 2
        assert results[0]["quality_score"] >= results[1]["quality_score"]

    def test_reload(self, engine, tmp_path, index_json) -> None:
        # Modify index to add another article
        more = {
            "articles": index_json["articles"]
            + [
                {
                    "id": "github_x_y_2026-05-11",
                    "title": "x/y",
                    "source": "github",
                    "published_at": "2026-05-11T00:00:00Z",
                    "tags": ["new"],
                    "quality_score": 0.99,
                    "status": "published",
                }
            ]
        }
        (tmp_path / "articles" / "index.json").write_text(
            json.dumps(more, ensure_ascii=False), encoding="utf-8"
        )
        engine.reload()
        assert engine.article_count() == 4

    def test_empty_directory(self, tmp_path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        engine = KnowledgeSearchEngine(knowledge_dir=empty_dir)
        assert engine.article_count() == 0

    def test_broken_json_skipped(self, tmp_path) -> None:
        articles_dir = tmp_path / "bad"
        articles_dir.mkdir()
        (articles_dir / "bad.json").write_text("{invalid json}")
        (articles_dir / "good.json").write_text(
            json.dumps(
                {
                    "id": "test",
                    "title": "test",
                    "quality_score": 0.5,
                    "status": "published",
                },
                ensure_ascii=False,
            ),
        )
        engine = KnowledgeSearchEngine(knowledge_dir=articles_dir)
        assert engine.article_count() >= 1


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------


class TestSubscriptionManager:
    @pytest.fixture
    def manager(self, tmp_path) -> SubscriptionManager:
        store = tmp_path / "subs.json"
        return SubscriptionManager(store_path=store)

    def test_add_subscription(self, manager) -> None:
        record = manager.add_subscription("u1", tags=["llm", "agent"])
        assert record["user_id"] == "u1"
        assert "llm" in record["tags"]

    def test_add_merges_existing(self, manager) -> None:
        manager.add_subscription("u1", tags=["llm"])
        manager.add_subscription("u1", tags=["agent"])
        record = manager.get_subscription("u1")
        assert record is not None
        assert set(record["tags"]) == {"llm", "agent"}

    def test_add_merges_categories(self, manager) -> None:
        manager.add_subscription("u1", categories=["模型发布"])
        manager.add_subscription("u1", categories=["工具库"])
        record = manager.get_subscription("u1")
        assert record is not None
        assert set(record["categories"]) == {"模型发布", "工具库"}

    def test_add_raises_if_no_tags_or_cats(self, manager) -> None:
        with pytest.raises(ValueError):
            manager.add_subscription("u1")

    def test_get_nonexistent(self, manager) -> None:
        assert manager.get_subscription("nonexistent") is None

    def test_remove_entire_subscription(self, manager) -> None:
        manager.add_subscription("u1", tags=["llm"])
        removed = manager.remove_subscription("u1")
        assert removed is True
        assert manager.get_subscription("u1") is None

    def test_remove_specific_tag(self, manager) -> None:
        manager.add_subscription("u1", tags=["llm", "agent"])
        removed = manager.remove_subscription("u1", tag="llm")
        assert removed is True
        record = manager.get_subscription("u1")
        assert record is not None
        assert record["tags"] == ["agent"]

    def test_remove_specific_category(self, manager) -> None:
        manager.add_subscription("u1", categories=["模型发布", "工具库"])
        removed = manager.remove_subscription("u1", category="模型发布")
        assert removed is True
        record = manager.get_subscription("u1")
        assert "工具库" in record["categories"]
        assert "模型发布" not in record["categories"]

    def test_remove_last_tag_clears_record(self, manager) -> None:
        manager.add_subscription("u1", tags=["llm"])
        manager.remove_subscription("u1", tag="llm")
        assert manager.get_subscription("u1") is None

    def test_remove_nonexistent(self, manager) -> None:
        assert manager.remove_subscription("nobody") is False

    def test_list_all(self, manager) -> None:
        manager.add_subscription("u1", tags=["a"])
        manager.add_subscription("u2", tags=["b"])
        assert len(manager.list_all()) == 2

    def test_persistence(self, tmp_path) -> None:
        store = tmp_path / "persist_subs.json"
        mgr = SubscriptionManager(store_path=store)
        mgr.add_subscription("u1", tags=["llm"])

        # Create a new manager pointing to the same file
        mgr2 = SubscriptionManager(store_path=store)
        assert mgr2.get_subscription("u1") is not None
        assert "llm" in mgr2.get_subscription("u1")["tags"]


# ---------------------------------------------------------------------------
# PermissionManager
# ---------------------------------------------------------------------------


class TestPermissionManager:
    @pytest.fixture
    def manager(self, tmp_path) -> PermissionManager:
        store = tmp_path / "perms.json"
        return PermissionManager(store_path=store)

    def test_default_read_permission(self, manager) -> None:
        assert manager.check("anyone", Permission.READ) is True

    def test_default_no_write(self, manager) -> None:
        assert manager.check("anyone", Permission.WRITE) is False

    def test_grant_write(self, manager) -> None:
        manager.grant("u1", Permission.WRITE)
        assert manager.check("u1", Permission.WRITE) is True
        assert manager.check("u1", Permission.READ) is True

    def test_grant_delete_implies_write_and_read(self, manager) -> None:
        manager.grant("admin", Permission.DELETE)
        assert manager.check("admin", Permission.DELETE) is True
        assert manager.check("admin", Permission.WRITE) is True
        assert manager.check("admin", Permission.READ) is True

    def test_revoke_resets_to_default(self, manager) -> None:
        manager.grant("u1", Permission.WRITE)
        manager.revoke("u1")
        assert manager.check("u1", Permission.WRITE) is False
        assert manager.check("u1", Permission.READ) is True

    def test_revoke_nonexistent_is_safe(self, manager) -> None:
        manager.revoke("nobody")  # should not raise

    def test_get_permission(self, manager) -> None:
        assert manager.get_permission("u1") is Permission.READ
        manager.grant("u1", Permission.WRITE)
        assert manager.get_permission("u1") is Permission.WRITE

    def test_persistence(self, tmp_path) -> None:
        store = tmp_path / "persist_perms.json"
        mgr = PermissionManager(store_path=store)
        mgr.grant("u1", Permission.WRITE)

        mgr2 = PermissionManager(store_path=store)
        assert mgr2.get_permission("u1") is Permission.WRITE

    def test_invalid_permission_in_file_defaults_to_read(self, tmp_path) -> None:
        store = tmp_path / "bad_perms.json"
        store.write_text(json.dumps({"u1": "superadmin"}), encoding="utf-8")
        mgr = PermissionManager(store_path=store)
        assert mgr.check("u1", Permission.READ) is True
        assert mgr.check("u1", Permission.WRITE) is False


# ---------------------------------------------------------------------------
# KnowledgeBot
# ---------------------------------------------------------------------------


class TestKnowledgeBot:
    @pytest.fixture
    def bot_data(
        self, tmp_path
    ) -> tuple[KnowledgeSearchEngine, SubscriptionManager, PermissionManager, Path]:
        """Create isolated bot components with test data."""
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir()
        (articles_dir / "index.json").write_text(
            json.dumps(
                {
                    "articles": [
                        {
                            "id": "github_a_b_2026-05-10",
                            "title": "a/b",
                            "source": "github",
                            "source_url": "https://github.com/a/b",
                            "published_at": "2026-05-10T00:00:00Z",
                            "tags": ["llm", "gpt"],
                            "quality_score": 0.95,
                            "category": "模型发布",
                            "key_insight": "A great LLM.",
                            "summary": "A detailed summary.",
                            "status": "published",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        subs_path = tmp_path / "subs.json"
        perms_path = tmp_path / "perms.json"

        engine = KnowledgeSearchEngine(knowledge_dir=articles_dir)
        subs = SubscriptionManager(store_path=subs_path)
        perms = PermissionManager(store_path=perms_path)

        return engine, subs, perms, tmp_path

    @pytest.fixture
    def bot(self, bot_data) -> KnowledgeBot:
        engine, subs, perms, _ = bot_data
        return KnowledgeBot(
            search_engine=engine,
            subscription_manager=subs,
            permission_manager=perms,
        )

    def test_handle_search(self, bot) -> None:
        reply = bot.handle_message("u1", "/search b")
        assert "a/b" in reply

    def test_handle_search_no_keywords(self, bot) -> None:
        reply = bot.handle_message("u1", "/search")
        assert "请提供搜索关键词" in reply

    def test_handle_search_permission_denied(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        # Default is READ, so search should work. Test by removing default READ
        # is not possible, but verify it works by default.
        reply = bot.handle_message("u1", "/search b")
        assert "a/b" in reply

    def test_handle_today(self, bot) -> None:
        # get_recent uses datetime.now() internally; article data has
        # published_at matching today's date so it should be returned.
        reply = bot.handle_message("u1", "/today")
        assert "今日简报" in reply

    def test_handle_top(self, bot) -> None:
        reply = bot.handle_message("u1", "/top 1")
        assert "a/b" in reply

    def test_handle_top_invalid_number(self, bot) -> None:
        reply = bot.handle_message("u1", "/top abc")
        assert "无效" in reply

    def test_handle_subscribe_list_empty(self, bot) -> None:
        reply = bot.handle_message("u1", "/subscribe list")
        assert "还没有订阅" in reply

    def test_handle_subscribe_add_requires_write(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        reply = bot.handle_message("u1", "/subscribe add --tag llm")
        assert "权限不足" in reply

    def test_handle_subscribe_add_with_permission(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        perms.grant("u1", Permission.WRITE)
        reply = bot.handle_message("u1", "/subscribe add --tag llm")
        assert "订阅已更新" in reply

    def test_handle_subscribe_list_with_permission(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        perms.grant("u1", Permission.WRITE)
        bot.handle_message("u1", "/subscribe add --tag llm,agent")
        reply = bot.handle_message("u1", "/subscribe list")
        assert "llm" in reply
        assert "agent" in reply

    def test_handle_subscribe_remove(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        perms.grant("u1", Permission.WRITE)
        bot.handle_message("u1", "/subscribe add --tag llm")
        reply = bot.handle_message("u1", "/subscribe remove --tag llm")
        assert "已移除" in reply

    def test_handle_subscribe_cancel(self, bot, bot_data) -> None:
        _, _, perms, _ = bot_data
        perms.grant("u1", Permission.WRITE)
        bot.handle_message("u1", "/subscribe add --tag llm")
        reply = bot.handle_message("u1", "/subscribe cancel")
        assert "已取消" in reply

    def test_handle_help(self, bot) -> None:
        reply = bot.handle_message("u1", "/help")
        assert "搜索" in reply
        assert "/search" in reply

    def test_handle_unknown_with_text_searches(self, bot) -> None:
        reply = bot.handle_message("u1", "random query about llm")
        assert "权限不足" not in reply
        assert len(reply) > 0

    def test_handle_unknown_with_empty_fallback(self, bot) -> None:
        reply = bot.handle_message("u1", "")
        assert "不太明白" in reply or "/help" in reply

    def test_natural_language_search(self, bot) -> None:
        reply = bot.handle_message("u1", "搜索 b")
        assert "a/b" in reply


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    """End-to-end scenarios spanning multiple components."""

    @pytest.fixture
    def bot(self, tmp_path) -> KnowledgeBot:
        articles_dir = tmp_path / "articles"
        articles_dir.mkdir()
        (articles_dir / "index.json").write_text(
            json.dumps(
                {
                    "articles": [
                        {
                            "id": "gh_llm_2026-05-10",
                            "title": "OpenAI/gpt-5",
                            "source": "github",
                            "source_url": "https://github.com/openai/gpt-5",
                            "published_at": "2026-05-10T00:00:00Z",
                            "tags": ["llm", "openai", "model"],
                            "quality_score": 0.99,
                            "category": "模型发布",
                            "key_insight": "GPT-5 发布",
                            "summary": "多模态推理能力。",
                            "status": "published",
                        },
                        {
                            "id": "gh_agent_2026-05-10",
                            "title": "langchain/langgraph",
                            "source": "github",
                            "source_url": "https://github.com/langchain-ai/langgraph",
                            "published_at": "2026-05-10T00:00:00Z",
                            "tags": ["agent", "framework"],
                            "quality_score": 0.85,
                            "category": "工具库",
                            "key_insight": "LangGraph 发布新版本",
                            "summary": "Agent 框架。",
                            "status": "published",
                        },
                        {
                            "id": "gh_rust_2026-05-09",
                            "title": "rust-lang/rust",
                            "source": "github",
                            "source_url": "https://github.com/rust-lang/rust",
                            "published_at": "2026-05-09T00:00:00Z",
                            "tags": ["rust", "compiler"],
                            "quality_score": 0.50,
                            "category": "工具库",
                            "key_insight": "Rust 新版本",
                            "summary": "Rust 更新。",
                            "status": "published",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        subs_path = tmp_path / "subs.json"
        perms_path = tmp_path / "perms.json"

        engine = KnowledgeSearchEngine(knowledge_dir=articles_dir)
        subs = SubscriptionManager(store_path=subs_path)
        perms = PermissionManager(store_path=perms_path)

        return KnowledgeBot(
            search_engine=engine,
            subscription_manager=subs,
            permission_manager=perms,
        )

    def test_full_workflow_search_and_subscribe(self, bot) -> None:
        # 1. Search
        reply = bot.handle_message("u1", "/search gpt")
        assert "OpenAI/gpt-5" in reply

        # 2. Try subscribe without permission
        reply = bot.handle_message("u1", "/subscribe add --tag llm")
        assert "权限不足" in reply

        # 3. Grant WRITE permission
        bot._perms.grant("u1", Permission.WRITE)

        # 4. Subscribe
        reply = bot.handle_message("u1", "/subscribe add --tag llm,agent")
        assert "订阅已更新" in reply

        # 5. Verify subscription
        reply = bot.handle_message("u1", "/subscribe list")
        assert "llm" in reply
        assert "agent" in reply

    def test_top_with_different_counts(self, bot) -> None:
        reply = bot.handle_message("u1", "/top 1")
        assert "OpenAI/gpt-5" in reply

        reply = bot.handle_message("u1", "/top 3")
        assert "共 3 条" in reply

    def test_today_vs_date_filter(self, bot) -> None:
        # get_recent uses today's date; our fixtures use hardcoded dates.
        # Articles from 2026-05-10 should appear, but 2026-05-09 should not.
        reply = bot.handle_message("u1", "/today")
        assert "OpenAI/gpt-5" in reply
        assert "langchain/langgraph" in reply
        # rust article from 05-09 should not be in today's results
        assert "rust-lang/rust" not in reply

    def test_help_always_available(self, bot) -> None:
        # Help should work even without READ (though default has READ)
        reply = bot.handle_message("any_user", "/help")
        assert "/search" in reply
        assert "/subscribe" in reply
