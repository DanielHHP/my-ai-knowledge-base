"""LLM client wrapper providing chat() and chat_json() for workflow nodes.

Exposes a simplified API on top of pipeline/model_client:
  - chat(prompt, system=...) -> (text, usage_dict)
  - chat_json(prompt, system=...) -> (parsed_dict, usage_dict)
  - accumulate_usage(tracker, usage) -> updated tracker dict
"""

import json
import logging
import os
import re
from typing import Any

from pipeline.model_client import CNY_PRICES, create_provider, chat_with_retry
from tests.cost_guard import BudgetExceededError, CostGuard

logger = logging.getLogger(__name__)

_provider = None
_cost_guard: CostGuard | None = None


def get_cost_guard() -> CostGuard:
    """Lazy-load singleton CostGuard for budget enforcement.

    Reads budget_yuan from BUDGET_YUAN env var on first call.
    Subsequent calls return the same instance.
    """
    global _cost_guard
    if _cost_guard is None:
        budget_yuan = float(os.environ.get("BUDGET_YUAN", "1.0"))
        _cost_guard = CostGuard(budget_yuan=budget_yuan)
    return _cost_guard


def _get_provider():
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def chat(
    prompt: str,
    system: str | None = None,
    node_name: str = "unknown",
    **kwargs: Any,
) -> tuple[str, dict]:
    """Send a text prompt to LLM and return (response_text, usage_dict).

    Args:
        prompt: User message content.
        system: Optional system prompt.
        node_name: Calling workflow node for cost tracking (default "unknown").
        **kwargs: Forwarded to chat_with_retry (model, temperature, max_tokens, ...).

    Returns:
        Tuple of (response text, usage dict with prompt/completion/total_tokens).
    """
    provider = _get_provider()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = chat_with_retry(provider, messages=messages, **kwargs)

    usage = {
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
        "total_tokens": resp.usage.total_tokens,
    }

    cost_guard = get_cost_guard()
    cost_guard.record(node_name, usage, model=resp.model)
    cost_guard.check()

    return resp.content, usage


def chat_json(
    prompt: str,
    system: str | None = None,
    node_name: str = "unknown",
    **kwargs: Any,
) -> tuple[Any, dict]:
    """Send a prompt expecting JSON response. Returns (parsed_data, usage_dict).

    Strips markdown code fences before parsing.

    Args:
        prompt: User message content.
        system: Optional system prompt.
        node_name: Calling workflow node for cost tracking (default "unknown").
        **kwargs: Forwarded to chat_with_retry.

    Returns:
        Tuple of (parsed JSON data, usage dict).

    Raises:
        json.JSONDecodeError: If response is not valid JSON.
    """
    text, usage = chat(prompt, system=system, node_name=node_name, **kwargs)

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    parsed = json.loads(text)
    return parsed, usage


def accumulate_usage(tracker: dict | None, usage: dict) -> dict:
    """Accumulate token usage into a tracker dict.

    Tracker format::
        {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
         "estimated_cost": 0.0}

    Args:
        tracker: Existing tracker dict or None to create a new one.
        usage: Usage dict from chat() or chat_json().

    Returns:
        Updated tracker dict.
    """
    if tracker is None:
        tracker = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0,
        }

    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    tracker["prompt_tokens"] += prompt
    tracker["completion_tokens"] += completion
    tracker["total_tokens"] += usage.get("total_tokens", 0)

    # CNYA cost: ¥/million tokens (matches CostGuard default pricing)
    provider_name = _get_provider().provider_name
    pricing = CNY_PRICES.get(provider_name, CNY_PRICES["deepseek"])
    tracker["estimated_cost"] += (
        prompt / 1_000_000 * pricing["input"]
        + completion / 1_000_000 * pricing["output"]
    )
    return tracker
