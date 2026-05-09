"""AI 知识库评估测试模块。

包含本地结构校验和 LLM-as-Judge 评估测试。
"""

import json
import logging
import os
import re
import sys
import warnings

import pytest
from dotenv import load_dotenv

# ── 环境变量加载 & 警告抑制 ────────────────────────────────────

load_dotenv()

warnings.filterwarnings("ignore", category=pytest.PytestUnknownMarkWarning)

logger = logging.getLogger(__name__)

# 确保项目根目录在 sys.path 中，使 workflows 等模块可被导入
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── 导入依赖 ───────────────────────────────────────────────────

from workflows.model_client import chat, chat_json


# ── 评估用例 ───────────────────────────────────────────────────

EVAL_CASES = [
    {
        "name": "positive_tech_article",
        "input": {
            "title": "LangChain发布v0.3版本，新增Agent记忆管理模块",
            "description": (
                "LangChain是用于构建LLM应用的流行框架，此次更新引入了持久化记忆管理、"
                "多Agent协作等关键特性，大幅提升了构建复杂AI应用的能力"
            ),
        },
        "expected": [
            ("summary_length >= 50", lambda r: len(r.get("summary", "")) >= 50),
            ("summary_length <= 300", lambda r: len(r.get("summary", "")) <= 300),
            ("tags_count >= 2", lambda r: len(r.get("tags", [])) >= 2),
            (
                "category is valid",
                lambda r: r.get("category", "")
                in ["模型发布", "工具库", "论文", "行业动态", "综合技术"],
            ),
            ("quality_score >= 0.3", lambda r: r.get("quality_score", 0) >= 0.3),
            ("quality_score <= 1.0", lambda r: r.get("quality_score", 0) <= 1.0),
            (
                "at least 2 AI keywords in summary",
                lambda r: sum(
                    1
                    for kw in ["LangChain", "LLM", "Agent", "记忆", "框架"]
                    if kw in r.get("summary", "")
                )
                >= 2,
            ),
        ],
    },
    {
        "name": "negative_irrelevant_content",
        "input": {
            "title": "菜谱分享：如何制作正宗红烧肉",
            "description": (
                "本文详细介绍了红烧肉的制作步骤，包括选料、焯水、炒糖色等关键环节，"
                "适合家庭烹饪爱好者参考"
            ),
        },
        "expected": [
            (
                "category is valid",
                lambda r: r.get("category", "")
                in ["模型发布", "工具库", "论文", "行业动态", "综合技术"],
            ),
            ("quality_score <= 0.4", lambda r: r.get("quality_score", 1.0) <= 0.4),
            ("quality_score >= 0.0", lambda r: r.get("quality_score", 0) >= 0.0),
        ],
    },
    {
        "name": "boundary_short_input",
        "input": {
            "title": "AI",
            "description": "ML",
        },
        "expected": [
            ("summary_length >= 1 (no crash)", lambda r: len(r.get("summary", "")) >= 1),
            ("quality_score >= 0.0", lambda r: r.get("quality_score", 0) >= 0.0),
            ("quality_score <= 1.0", lambda r: r.get("quality_score", 1.0) <= 1.0),
        ],
    },
    {
        "name": "positive_open_source_tool",
        "input": {
            "title": "vLLM v0.7.0 发布，推理效率提升300%",
            "description": (
                "vLLM是一个高性能的大语言模型推理引擎，此次更新引入PagedAttention优化、"
                "连续批处理等特性，在GPU利用率方面实现重大突破"
            ),
        },
        "expected": [
            ("summary_length >= 50", lambda r: len(r.get("summary", "")) >= 50),
            ("tags_count >= 2", lambda r: len(r.get("tags", [])) >= 2),
            (
                "category is valid",
                lambda r: r.get("category", "")
                in ["模型发布", "工具库", "论文", "行业动态", "综合技术"],
            ),
            ("quality_score >= 0.3", lambda r: r.get("quality_score", 0) >= 0.3),
        ],
    },
]


# ── 辅助函数 ───────────────────────────────────────────────────

ANALYSIS_SYSTEM = (
    "You are an AI technology content analyst. "
    "Return ONLY valid JSON. No markdown, no extra text, no code fences."
)

ANALYSIS_PROMPT = """Analyze this AI-related repository:

Title: {title}
Description: {description}

Return a JSON object with these fields:
- "summary": Chinese summary (100-200 characters)
- "tags": array of 3-5 English lowercase tags
- "category": one of ["模型发布", "工具库", "论文", "行业动态", "综合技术"]
- "quality_score": float between 0 and 1
- "score_reason": brief Chinese explanation for the score"""


def _analyze(title: str, description: str) -> dict:
    """Run LLM analysis on a tech item, return structured JSON result.

    Args:
        title: Item title.
        description: Item description text.

    Returns:
        Parsed JSON dict with summary, tags, category, quality_score, score_reason.
        Returns a minimal valid dict on parse failure.
    """
    prompt = ANALYSIS_PROMPT.format(title=title, description=description)
    try:
        result, _usage = chat_json(prompt, system=ANALYSIS_SYSTEM)
        return result
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("JSON parse failed, falling back to raw text: %s", exc)
        try:
            text, _usage = chat(prompt, system=ANALYSIS_SYSTEM)
            text = text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except Exception:
            logger.error("Analysis completely failed for title=%s", title)
            return {"summary": "", "tags": [], "category": "", "quality_score": 0.0}


def _judge(analysis_result: dict) -> int:
    """LLM-as-Judge: score the analysis result quality on a 1-10 scale.

    Args:
        analysis_result: The analysis output dict.

    Returns:
        Integer score from 1 to 10. Returns 0 on parse failure.
    """
    judge_prompt = f"""Evaluate this AI analysis result on a scale of 1-10.

Analysis:
- Summary: {analysis_result.get("summary", "")}
- Tags: {json.dumps(analysis_result.get("tags", []), ensure_ascii=False)}
- Category: {analysis_result.get("category", "")}
- Quality Score: {analysis_result.get("quality_score", 0.0)}
- Score Reason: {analysis_result.get("score_reason", "")}

Criteria:
1. Summary relevance and clarity
2. Tag appropriateness
3. Category correctness
4. Overall usefulness

Return ONLY a single integer between 1 and 10. No other text."""

    judge_system = (
        "You are a strict but fair AI evaluation judge. "
        "Return ONLY an integer 1-10."
    )
    text, _usage = chat(judge_prompt, system=judge_system)

    match = re.search(r"\d+", text)
    if match:
        score = int(match.group())
        return max(1, min(10, score))
    logger.warning("Failed to parse judge score from: %s", text[:100])
    return 0


def _skip_if_no_api_key() -> None:
    """Skip the current test if no LLM API key is configured."""
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    key_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "QWEN_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_key = key_map.get(provider, "DEEPSEEK_API_KEY")
    if not os.environ.get(env_key):
        pytest.skip(f"No API key found ({env_key})")


# ── 测试 1: 本地结构验证（不调用 LLM） ─────────────────────────

def test_validate_eval_cases_structure():
    """验证 EVAL_CASES 数据结构完整性和约束条件。

    不调用 LLM，不访问网络。纯本地数据结构检查。
    """
    assert len(EVAL_CASES) >= 3, (
        f"EVAL_CASES 至少需要 3 个场景，当前为 {len(EVAL_CASES)}"
    )

    for case in EVAL_CASES:
        # 每个用例必须有 name, input, expected
        assert "name" in case, "case missing 'name'"
        assert "input" in case, "case missing 'input'"
        assert "expected" in case, "case missing 'expected'"

        # input 必须包含 title 和 description
        assert "title" in case["input"], f"{case['name']}: input missing 'title'"
        assert "description" in case["input"], f"{case['name']}: input missing 'description'"

        # title 和 description 必须是非空字符串
        title = case["input"]["title"]
        desc = case["input"]["description"]
        assert isinstance(title, str) and len(title) >= 1, (
            f"{case['name']}: title must be non-empty string, got {title!r}"
        )
        assert isinstance(desc, str) and len(desc) >= 1, (
            f"{case['name']}: description must be non-empty string, got {desc!r}"
        )

        # expected 必须是非空列表
        expected = case["expected"]
        assert isinstance(expected, list) and len(expected) >= 1, (
            f"{case['name']}: expected must be a non-empty list"
        )

        # 每个 expected 条目是 (名称, 可调用) 元组
        for idx, item in enumerate(expected):
            assert isinstance(item, tuple) and len(item) == 2, (
                f"{case['name']}: expected[{idx}] 必须是 (name, callable) 元组"
            )
            assert isinstance(item[0], str) and len(item[0]) >= 1, (
                f"{case['name']}: expected[{idx}] 名称必须是非空字符串"
            )
            assert callable(item[1]), (
                f"{case['name']}: expected[{idx}] 检查项必须是可调用对象"
            )

        # 检查名称不重复
        names = [item[0] for item in expected]
        assert len(names) == len(set(names)), (
            f"{case['name']}: expected 中存在重复的检查名称: {names}"
        )


# ── 测试 2: 评估用例 LLM 分析测试 ──────────────────────────────

@pytest.mark.slow
def test_eval_cases():
    """对所有 EVAL_CASES 执行 LLM 分析并验证预期条件。

    使用范围断言（>=、<=、in），不使用精确匹配。
    可通过 ``pytest -m "not slow"`` 跳过。
    """
    _skip_if_no_api_key()

    for case in EVAL_CASES:
        result = _analyze(case["input"]["title"], case["input"]["description"])

        for check_name, check_fn in case["expected"]:
            assert check_fn(result), (
                f"[{case['name']}] 检查失败: {check_name}\n"
                f"  分析结果: {json.dumps(result, ensure_ascii=False)}"
            )


# ── 测试 3: LLM-as-Judge 评分 ──────────────────────────────────

@pytest.mark.slow
def test_llm_judge():
    """LLM-as-Judge: 让 LLM 对分析结果打分（1-10），断言分数 >= 5。

    选取第一个正面案例，先执行分析生成结果，再交由评判 LLM 打分。
    可通过 ``pytest -m "not slow"`` 跳过。
    """
    _skip_if_no_api_key()

    # 选取第一个名称含 "positive" 的用例
    pos_case = next(
        (c for c in EVAL_CASES if "positive" in c["name"]),
        EVAL_CASES[0],
    )
    result = _analyze(
        pos_case["input"]["title"], pos_case["input"]["description"]
    )

    score = _judge(result)
    assert score >= 5, (
        f"LLM Judge 评分过低: {score}/10 (预期 >= 5)\n"
        f"  分析结果: {json.dumps(result, ensure_ascii=False, indent=2)}"
    )
