"""LLM client wrapper providing chat() and chat_json() for workflow nodes.

Exposes a simplified API on top of pipeline/model_client:
  - chat(prompt, system=...) -> (text, usage_dict)
  - chat_json(prompt, system=...) -> (parsed_dict, usage_dict)
  - accumulate_usage(tracker, usage) -> updated tracker dict
"""

import json
import logging
import re
from typing import Any

from pipeline.model_client import create_provider, chat_with_retry

logger = logging.getLogger(__name__)

_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def chat(
    prompt: str,
    system: str | None = None,
    **kwargs: Any,
) -> tuple[str, dict]:
    """Send a text prompt to LLM and return (response_text, usage_dict).

    Args:
        prompt: User message content.
        system: Optional system prompt.
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
    return resp.content, usage


def chat_json(
    prompt: str,
    system: str | None = None,
    **kwargs: Any,
) -> tuple[Any, dict]:
    """Send a prompt expecting JSON response. Returns (parsed_data, usage_dict).

    Strips markdown code fences before parsing.

    Args:
        prompt: User message content.
        system: Optional system prompt.
        **kwargs: Forwarded to chat_with_retry.

    Returns:
        Tuple of (parsed JSON data, usage dict).

    Raises:
        json.JSONDecodeError: If response is not valid JSON.
    """
    text, usage = chat(prompt, system=system, **kwargs)

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

    tracker["prompt_tokens"] += usage.get("prompt_tokens", 0)
    tracker["completion_tokens"] += usage.get("completion_tokens", 0)
    tracker["total_tokens"] += usage.get("total_tokens", 0)
    return tracker
