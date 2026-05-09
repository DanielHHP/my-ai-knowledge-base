"""规划节点：根据目标采集量输出策略计划，供下游节点调整执行参数。"""

import logging
import os

from workflows.state import KBState

logger = logging.getLogger(__name__)

_TIER_CONFIG = {
    "lite": {
        "per_source_limit": 5,
        "relevance_threshold": 0.7,
        "max_iterations": 1,
        "rationale": "目标量较小，使用精简策略：低并发 + 高相关性阈值 + 单次迭代，优先保证质量而非数量",
    },
    "standard": {
        "per_source_limit": 10,
        "relevance_threshold": 0.5,
        "max_iterations": 2,
        "rationale": "标准采集量，采用均衡策略：中等并发 + 适中阈值 + 两次迭代，兼顾覆盖度与成本",
    },
    "full": {
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale": "全量采集，使用宽松策略：高并发 + 低阈值 + 三次迭代，最大化信息覆盖率",
    },
}


def plan_strategy(target_count: int = None) -> dict:
    """根据目标采集量生成策略计划。

    Args:
        target_count: 目标采集条数。为 None 时从环境变量
            ``PLANNER_TARGET_COUNT`` 读取，默认 10。

    Returns:
        策略 dict，包含 per_source_limit、relevance_threshold、
        max_iterations、rationale 字段。
    """
    if target_count is None:
        target_count = int(os.environ.get("PLANNER_TARGET_COUNT", "10"))

    if target_count < 10:
        tier = "lite"
    elif target_count < 20:
        tier = "standard"
    else:
        tier = "full"

    plan = {
        "target_count": target_count,
        "tier": tier,
        **_TIER_CONFIG[tier],
    }

    logger.info(
        "[Planner] target_count=%d → tier=%s (limit=%d, threshold=%.1f, iterations=%d)",
        target_count,
        tier,
        plan["per_source_limit"],
        plan["relevance_threshold"],
        plan["max_iterations"],
    )

    return plan


def planner_node(state: KBState) -> dict:
    """LangGraph 规划节点，读取当前状态后生成策略计划。

    Args:
        state: 当前工作流状态。

    Returns:
        Partial state update，包含 ``plan`` 字段。
    """
    plan = plan_strategy()
    return {"plan": plan}
