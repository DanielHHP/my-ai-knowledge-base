"""Unit tests for distribution.formatter.json_to_feishu."""

import json
import sys
from pathlib import Path

import pytest

# Ensure the project root is on the path so we can import distribution.formatter.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from distribution.formatter import json_to_feishu  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_article() -> dict:
    """Absolute-minimum article dict (all fields empty / absent)."""
    return {}


@pytest.fixture
def full_article() -> dict:
    """Article with every known field populated."""
    return {
        "title": "openai/gpt-5",
        "source": "github",
        "source_url": "https://github.com/openai/gpt-5",
        "created_at": "2026-05-10T08:00:00Z",
        "quality_score": 0.92,
        "tags": ["llm", "openai", "model-release"],
        "summary": "OpenAI 发布 GPT-5，支持多模态推理。",
        "key_insight": "GPT-5 首次实现原生多模态",
    }


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------


class TestTopLevelStructure:
    """Tests for the card's top-level keys and their types."""

    def test_has_schema_2_0(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        assert card["schema"] == "2.0"

    def test_has_required_top_level_keys(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        for key in ("schema", "config", "header", "body"):
            assert key in card, f"Missing top-level key: {key}"

    def test_no_msg_type_in_card(self, full_article: dict) -> None:
        """msg_type belongs in the API request envelope, not the card dict."""
        card = json_to_feishu(full_article)
        assert "msg_type" not in card

    def test_is_serializable(self, full_article: dict) -> None:
        """Card must be JSON-serialisable so publisher can do json.dumps()."""
        card = json_to_feishu(full_article)
        serialised = json.dumps(card, ensure_ascii=False)
        roundtrip = json.loads(serialised)
        assert roundtrip == card


# ---------------------------------------------------------------------------
# Config block
# ---------------------------------------------------------------------------


class TestConfig:
    def test_enable_forward_true(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["config"]["enable_forward"] is True

    def test_update_multi_true(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["config"]["update_multi"] is True

    def test_width_mode_fill(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["config"]["width_mode"] == "fill"


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


class TestHeader:
    def test_title_uses_plain_text_tag(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        assert card["header"]["title"]["tag"] == "plain_text"

    def test_title_content_matches(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        assert card["header"]["title"]["content"] == "openai/gpt-5"

    def test_title_fallback_when_missing(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["header"]["title"]["content"] == "Untitled"

    def test_padding_is_set(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["header"]["padding"] == "12px 12px 12px 12px"


# ---------------------------------------------------------------------------
# Header template colour mapping
# ---------------------------------------------------------------------------


class TestHeaderTemplate:
    @pytest.mark.parametrize(
        "score, expected",
        [
            (1.0, "green"),
            (0.95, "green"),
            (0.8, "green"),
            (0.81, "green"),
            (0.799, "yellow"),
            (0.75, "yellow"),
            (0.7, "yellow"),
            (0.6, "yellow"),
            (0.601, "yellow"),
            (0.599, "red"),
            (0.3, "red"),
            (0.0, "red"),
        ],
    )
    def test_color_boundaries(self, score: float, expected: str) -> None:
        card = json_to_feishu({"quality_score": score})
        assert card["header"]["template"] == expected


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


class TestBody:
    def test_body_has_direction_vertical(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["body"]["direction"] == "vertical"

    def test_body_has_padding(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["body"]["padding"] == "12px 12px 12px 12px"


# ---------------------------------------------------------------------------
# Body elements: key_insight
# ---------------------------------------------------------------------------


class TestKeyInsightElement:
    def test_present_when_has_insight(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        elements = card["body"]["elements"]
        insight_el = elements[0]
        assert insight_el["tag"] == "markdown"
        assert "GPT-5" in insight_el["content"]

    def test_absent_when_no_insight(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        elements = card["body"]["elements"]
        tags = [el["tag"] for el in elements]
        assert "markdown" not in tags, "Should not have key_insight markdown element"

    def test_absent_when_insight_empty_string(self) -> None:
        card = json_to_feishu({"key_insight": ""})
        elements = card["body"]["elements"]
        # Only div, action, hr, note should be present
        md_elements = [el for el in elements if el["tag"] == "markdown"]
        assert len(md_elements) == 0


# ---------------------------------------------------------------------------
# Body elements: summary
# ---------------------------------------------------------------------------


class TestSummaryElement:
    def test_present_when_has_summary(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        elements = card["body"]["elements"]
        summary_elements = [e for e in elements if e["tag"] == "markdown" and "OpenAI 发布" in e.get("content", "")]
        assert len(summary_elements) == 1

    def test_absent_when_summary_empty(self) -> None:
        card = json_to_feishu({"summary": ""})
        elements = card["body"]["elements"]
        tags = {el["tag"] for el in elements}
        assert "markdown" not in tags, "Should not have summary markdown element"


# ---------------------------------------------------------------------------
# Body elements: div (fields)
# ---------------------------------------------------------------------------


class TestDivFields:
    def test_div_element_present(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div_elements = [e for e in card["body"]["elements"] if e["tag"] == "div"]
        assert len(div_elements) == 1

    def test_source_field(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        div = _find_div(card)
        source_field = _field_by_content(div, "**来源**")
        assert source_field is not None
        assert "github" in source_field["text"]["content"]

    def test_date_field(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert date_field is not None
        assert "2026-05-10" in date_field["text"]["content"]

    def test_score_field(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        div = _find_div(card)
        score_field = _field_by_content(div, "**相关性**")
        assert score_field is not None
        assert "0.92" in score_field["text"]["content"]

    def test_tags_field_present_when_tags_exist(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        div = _find_div(card)
        tag_field = _field_by_content(div, "**标签**")
        assert tag_field is not None
        assert "llm" in tag_field["text"]["content"]

    def test_tags_field_absent_when_no_tags(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div = _find_div(card)
        tag_field = _field_by_content(div, "**标签**")
        assert tag_field is None

    def test_all_fields_are_short(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div = _find_div(card)
        for field in div["fields"]:
            assert field["is_short"] is True

    def test_fields_use_lark_md_tag(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div = _find_div(card)
        for field in div["fields"]:
            assert field["text"]["tag"] == "lark_md"


# ---------------------------------------------------------------------------
# Body elements: action (button)
# ---------------------------------------------------------------------------


class TestActionButton:
    def test_action_element_present(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        actions = [e for e in card["body"]["elements"] if e["tag"] == "action"]
        assert len(actions) == 1

    def test_button_text(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        action = _find_action(card)
        button = action["actions"][0]
        assert button["text"]["content"] == "查看原文"

    def test_button_type_primary(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        action = _find_action(card)
        button = action["actions"][0]
        assert button["type"] == "primary"

    def test_button_url_matches_source_url(self, full_article: dict) -> None:
        card = json_to_feishu(full_article)
        action = _find_action(card)
        button = action["actions"][0]
        assert button["url"] == "https://github.com/openai/gpt-5"

    def test_button_uses_plain_text_tag(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        action = _find_action(card)
        button = action["actions"][0]
        assert button["text"]["tag"] == "plain_text"

    def test_button_url_empty_when_no_source_url(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        action = _find_action(card)
        button = action["actions"][0]
        assert button["url"] == ""


# ---------------------------------------------------------------------------
# Body elements: hr and note (footer)
# ---------------------------------------------------------------------------


class TestFooter:
    def test_hr_element_present(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        hr_elements = [e for e in card["body"]["elements"] if e["tag"] == "hr"]
        assert len(hr_elements) == 1

    def test_note_element_present(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        note_elements = [e for e in card["body"]["elements"] if e["tag"] == "note"]
        assert len(note_elements) == 1

    def test_note_content(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        note = [e for e in card["body"]["elements"] if e["tag"] == "note"][0]
        assert note["elements"][0]["content"] == "AI 知识库助手自动生成"

    def test_hr_before_note(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        elements = card["body"]["elements"]
        hr_idx = next(i for i, e in enumerate(elements) if e["tag"] == "hr")
        note_idx = next(i for i, e in enumerate(elements) if e["tag"] == "note")
        assert hr_idx + 1 == note_idx, "hr must immediately precede note"

    def test_note_is_last_element(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        elements = card["body"]["elements"]
        assert elements[-1]["tag"] == "note"


# ---------------------------------------------------------------------------
# Date resolution
# ---------------------------------------------------------------------------


class TestDateResolution:
    def test_uses_created_at(self) -> None:
        card = json_to_feishu({"created_at": "2026-01-15T12:00:00Z"})
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert "2026-01-15" in date_field["text"]["content"]

    def test_falls_back_to_collected_at(self) -> None:
        card = json_to_feishu({"collected_at": "2026-02-20T12:00:00Z"})
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert "2026-02-20" in date_field["text"]["content"]

    def test_falls_back_to_published_at(self) -> None:
        card = json_to_feishu({"published_at": "2026-03-10T12:00:00Z"})
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert "2026-03-10" in date_field["text"]["content"]

    def test_created_at_has_priority(self) -> None:
        card = json_to_feishu(
            {
                "created_at": "2026-04-01T12:00:00Z",
                "collected_at": "2026-05-01T12:00:00Z",
                "published_at": "2026-06-01T12:00:00Z",
            }
        )
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert "2026-04-01" in date_field["text"]["content"]

    def test_empty_when_no_date_fields(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div = _find_div(card)
        date_field = _field_by_content(div, "**日期**")
        assert date_field is not None
        # The content should just be "**日期**\n" with empty date
        assert date_field["text"]["content"] == "**日期**\n"


# ---------------------------------------------------------------------------
# Source fallback
# ---------------------------------------------------------------------------


class TestSourceFallback:
    def test_unknown_when_source_missing(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        div = _find_div(card)
        source_field = _field_by_content(div, "**来源**")
        assert "unknown" in source_field["text"]["content"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dict_returns_valid_card(self, minimal_article: dict) -> None:
        card = json_to_feishu(minimal_article)
        assert card["header"]["title"]["content"] == "Untitled"
        assert card["header"]["template"] == "red"
        assert len(card["body"]["elements"]) == 4  # div, action, hr, note

    def test_minimal_card_element_count(self) -> None:
        """No insight, no summary, no tags → div + action + hr + note = 4."""
        card = json_to_feishu({})
        assert len(card["body"]["elements"]) == 4

    def test_maximal_card_element_count(self, full_article: dict) -> None:
        """Insight + summary + tags → insight + summary + div + action + hr + note = 6."""
        card = json_to_feishu(full_article)
        assert len(card["body"]["elements"]) == 6

    def test_long_title_not_truncated(self) -> None:
        long_title = "A" * 200
        card = json_to_feishu({"title": long_title})
        assert card["header"]["title"]["content"] == long_title

    def test_special_characters_in_title(self) -> None:
        card = json_to_feishu({"title": "foo & bar <baz> \"qux\""})
        assert card["header"]["title"]["content"] == "foo & bar <baz> \"qux\""

    def test_empty_tags_list_no_tags_field(self) -> None:
        card = json_to_feishu({"tags": []})
        div = _find_div(card)
        tag_field = _field_by_content(div, "**标签**")
        assert tag_field is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_div(card: dict) -> dict:
    """Return the first ``div`` element from the card body."""
    for element in card["body"]["elements"]:
        if element["tag"] == "div":
            return element
    raise AssertionError("No div element found in card body")


def _find_action(card: dict) -> dict:
    """Return the first ``action`` element from the card body."""
    for element in card["body"]["elements"]:
        if element["tag"] == "action":
            return element
    raise AssertionError("No action element found in card body")


def _field_by_content(div: dict, keyword: str) -> dict | None:
    """Return the field dict whose lark_md content contains *keyword*, or None."""
    for field in div["fields"]:
        if keyword in field["text"]["content"]:
            return field
    return None
