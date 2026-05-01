from typing import TypedDict


class KBState(TypedDict):
    """LangGraph 工作流共享状态，遵循报告式通信原则——所有字段均为结构化摘要。"""

    sources: list[dict]
    """采集阶段输出：各数据源的结构化摘要列表。
       每项含 platform, title, url, description, metadata 等摘要字段。"""

    analyses: list[dict]
    """分析阶段输出：LLM 对每条原始数据生成的标注结果。
       每项含 id, summary, tags, category, quality_score 等结构化字段。"""

    articles: list[dict]
    """整理阶段输出：去重、格式化后的最终知识条目列表。
       每项符合 knowledge/articles/ 下的 JSON schema 规范。"""

    review_feedback: str
    """审核反馈意见，由 curator 或人工审核填写，指导分析 Agent 迭代改进。"""

    review_passed: bool
    """审核是否通过。False 时触发新一轮分析-整理循环。"""

    iteration: int
    """当前审核循环次数（0 起始，上限 3），超限后强制结束工作流。"""

    cost_tracker: dict
    """Token 及费用追踪摘要。
       含 {total_tokens, prompt_tokens, completion_tokens, estimated_cost} 等字段。"""
