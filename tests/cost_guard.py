"""Multi-Agent 预算守卫模块。

提供 LLM 调用成本追踪、预算预警与超限保护三重机制。
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """预算超限异常，当累计成本超过设定预算时抛出。"""

    def __init__(self, total_cost: float, budget: float, message: str = ""):
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(
            message or f"预算超限: 累计成本 {total_cost:.6f} 元 >= 预算 {budget} 元"
        )


@dataclass
class CostRecord:
    """单次 LLM 调用成本记录。"""

    timestamp: datetime
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class CostGuard:
    """多 Agent 预算守卫，提供追踪、预览、超限保护三重机制。

    Attributes:
        budget_yuan: 预算上限 (元)
        alert_threshold: 预警比例 (0-1)
        input_price_per_million: 输入 token 单价 (元/百万 token)
        output_price_per_million: 输出 token 单价 (元/百万 token)
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ):
        if budget_yuan <= 0:
            raise ValueError("budget_yuan 必须大于 0")
        if not 0 < alert_threshold <= 1.0:
            raise ValueError("alert_threshold 必须在 (0, 1.0] 范围内")

        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self._records: list[CostRecord] = []

    def record(
        self,
        node_name: str,
        usage: dict,
        model: str = "",
    ) -> None:
        """记录一次 LLM 调用。

        Args:
            node_name: 调用节点名称 (如 "analyzer", "collector")
            usage: token 用量，格式 {"prompt_tokens": int, "completion_tokens": int}
            model: 模型名称 (可选)
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        cost_yuan = (
            prompt_tokens / 1_000_000 * self.input_price_per_million
            + completion_tokens / 1_000_000 * self.output_price_per_million
        )

        record = CostRecord(
            timestamp=datetime.now(timezone.utc),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost_yuan,
            model=model,
        )
        self._records.append(record)
        logger.debug(
            "记录调用: node=%s, prompt=%d, completion=%d, cost=%.6f",
            node_name,
            prompt_tokens,
            completion_tokens,
            cost_yuan,
        )

    def _total_cost(self) -> float:
        return sum(r.cost_yuan for r in self._records)

    def _total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self._records)

    def _total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self._records)

    def check(self) -> dict:
        """检查预算状态。

        Returns:
            dict: 包含 status, total_cost, budget, usage_ratio, message

        Raises:
            BudgetExceededError: 累计成本超过预算上限时抛出
        """
        total_cost = self._total_cost()
        usage_ratio = total_cost / self.budget_yuan

        if total_cost >= self.budget_yuan:
            raise BudgetExceededError(
                total_cost=total_cost,
                budget=self.budget_yuan,
                message=f"预算超限: 累计成本 {total_cost:.6f} 元 / {self.budget_yuan} 元 ({usage_ratio:.1%})",
            )

        if usage_ratio >= self.alert_threshold:
            status = "warning"
            message = f"预算预警: 已使用 {usage_ratio:.1%} (阈值 {self.alert_threshold:.0%})"
        else:
            status = "ok"
            message = f"预算正常: 已使用 {usage_ratio:.1%}"

        return {
            "status": status,
            "total_cost": round(total_cost, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(usage_ratio, 4),
            "message": message,
        }

    def get_report(self) -> dict:
        """生成按节点分组的成本报告。

        Returns:
            dict: 包含 summary (总计) 和 nodes (按 node_name 分组) 的完整报告
        """
        nodes: dict[str, dict] = {}
        for r in self._records:
            if r.node_name not in nodes:
                nodes[r.node_name] = {
                    "call_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_cost_yuan": 0.0,
                }
            entry = nodes[r.node_name]
            entry["call_count"] += 1
            entry["prompt_tokens"] += r.prompt_tokens
            entry["completion_tokens"] += r.completion_tokens
            entry["total_cost_yuan"] = round(
                entry["total_cost_yuan"] + r.cost_yuan, 6
            )

        usage_ratio = round(self._total_cost() / self.budget_yuan, 4)

        return {
            "summary": {
                "total_calls": len(self._records),
                "total_prompt_tokens": self._total_prompt_tokens(),
                "total_completion_tokens": self._total_completion_tokens(),
                "total_cost_yuan": round(self._total_cost(), 6),
                "budget_yuan": self.budget_yuan,
                "usage_ratio": usage_ratio,
            },
            "nodes": nodes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save_report(self, path: Optional[str] = None) -> str:
        """保存成本报告到 JSON 文件。

        Args:
            path: 输出文件路径，默认为 cost_report_{timestamp}.json

        Returns:
            str: 实际保存的文件路径
        """
        if path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"cost_report_{timestamp}.json"

        report = self.get_report()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("成本报告已保存至: %s", path)
        return path

    @property
    def total_cost_yuan(self) -> float:
        return self._total_cost()

    @property
    def total_prompt_tokens(self) -> int:
        return self._total_prompt_tokens()

    @property
    def total_completion_tokens(self) -> int:
        return self._total_completion_tokens()


if __name__ == "__main__":
    import sys

    failed = 0
    passed = 0

    def test_assert(condition, name):
        global passed, failed
        if condition:
            passed += 1
            print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name}")

    # ── 测试 1: 成本追踪正确 ──
    guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
    guard.record(
        "collector",
        {"prompt_tokens": 100_000, "completion_tokens": 50_000},
        model="gpt-4",
    )
    guard.record(
        "analyzer",
        {"prompt_tokens": 200_000, "completion_tokens": 100_000},
        model="gpt-4",
    )

    # 预期成本:
    # collector: 100000/1M * 1.0 + 50000/1M * 2.0 = 0.1 + 0.1 = 0.2
    # analyzer:  200000/1M * 1.0 + 100000/1M * 2.0 = 0.2 + 0.2 = 0.4
    # 总计: 0.6
    expected_cost = 0.6
    expected_tokens = 300_000
    test_assert(
        abs(guard.total_cost_yuan - expected_cost) < 0.001,
        f"total_cost_yuan = {guard.total_cost_yuan:.4f} (预期 {expected_cost})",
    )
    test_assert(
        guard.total_prompt_tokens == expected_tokens,
        f"total_prompt_tokens = {guard.total_prompt_tokens} (预期 {expected_tokens})",
    )
    test_assert(
        len(guard._records) == 2,
        f"records count = {len(guard._records)} (预期 2)",
    )

    # ── 测试 2: 预算预警触发 ──
    # 再追加一次调用，使累计成本达到 0.8 (>= 0.8 阈值, < 1.0 预算)
    guard.record(
        "collector",
        {"prompt_tokens": 100_000, "completion_tokens": 50_000},
        model="gpt-4",
    )
    # 累计成本: 0.6 + 0.2 = 0.8
    status = guard.check()
    test_assert(
        status["status"] == "warning",
        f"status = {status['status']} (预期 'warning')",
    )
    test_assert(
        status["usage_ratio"] >= 0.8,
        f"usage_ratio = {status['usage_ratio']} (预期 >= 0.8)",
    )

    # ── 测试 3: 预算超限检测 ──
    guard.record(
        "distributor",
        {"prompt_tokens": 500_000, "completion_tokens": 250_000},
        model="gpt-4",
    )
    # 新增成本: 0.5 + 0.5 = 1.0, 累计 0.6+0.2+1.0=1.8 > 1.0
    try:
        guard.check()
        test_assert(False, "BudgetExceededError 未能抛出")
    except BudgetExceededError as e:
        test_assert(
            abs(e.total_cost - 1.8) < 0.001,
            f"异常携带 total_cost = {e.total_cost:.4f} (预期 1.8)",
        )
        test_assert(e.budget == 1.0, "异常携带 budget = 1.0")

    # ── 测试 4: get_report 按节点分组 ──
    guard2 = CostGuard(budget_yuan=5.0, alert_threshold=0.8)
    guard2.record("collector", {"prompt_tokens": 10, "completion_tokens": 0})
    guard2.record("collector", {"prompt_tokens": 20, "completion_tokens": 0})
    guard2.record("analyzer", {"prompt_tokens": 30, "completion_tokens": 0})

    report = guard2.get_report()
    test_assert(report["summary"]["total_calls"] == 3, "report total_calls = 3")
    test_assert(
        "collector" in report["nodes"] and "analyzer" in report["nodes"],
        "report nodes 包含 collector 和 analyzer",
    )
    test_assert(
        report["nodes"]["collector"]["call_count"] == 2,
        "collector call_count = 2",
    )
    test_assert(
        report["nodes"]["analyzer"]["call_count"] == 1,
        "analyzer call_count = 1",
    )

    # ── 测试 5: save_report ──
    path = guard2.save_report("/tmp/test_cost_report.json")
    test_assert(os.path.exists(path), f"报告文件已生成: {path}")
    with open(path) as f:
        saved = json.load(f)
    test_assert(saved["summary"]["total_calls"] == 3, "保存的报告 total_calls = 3")
    os.remove(path)  # 清理

    # ── 测试 6: 构造函数参数验证 ──
    try:
        CostGuard(budget_yuan=0)
        test_assert(False, "budget_yuan=0 未能抛出 ValueError")
    except ValueError:
        test_assert(True, "budget_yuan=0 正确抛出 ValueError")

    try:
        CostGuard(alert_threshold=0)
        test_assert(False, "alert_threshold=0 未能抛出 ValueError")
    except ValueError:
        test_assert(True, "alert_threshold=0 正确抛出 ValueError")

    # ── 测试 7: 空记录状态 ──
    guard3 = CostGuard()
    status = guard3.check()
    test_assert(status["status"] == "ok", "空记录 status = ok")
    test_assert(status["usage_ratio"] == 0.0, "空记录 usage_ratio = 0.0")

    # ── 汇总 ──
    total = passed + failed
    print(f"\n{'='*40}")
    print(f"测试完成: {passed}/{total} 通过" + (f", {failed} 失败" if failed else ""))
    sys.exit(0 if failed == 0 else 1)
