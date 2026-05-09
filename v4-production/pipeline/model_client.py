#!/usr/bin/env python3
"""Unified LLM client supporting DeepSeek, Qwen, and OpenAI via OpenAI-compatible API.

Provides abstract base class, httpx-based implementation, retry logic,
token estimation, cost calculation, and a convenience quick_chat() function.

Typical usage::

    from pipeline.model_client import quick_chat
    reply = quick_chat("What is the capital of France?")
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

# Domestic (CNY) price table: yuan per million tokens
CNY_PRICES: dict[str, dict[str, float]] = {
    "deepseek": {"input": 1, "output": 2},
    "qwen": {"input": 4, "output": 12},
    "openai": {"input": 150, "output": 600},
}

PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "pricing": {"input": 0.27, "output": 1.10},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "env_key": "QWEN_API_KEY",
        "pricing": {"input": 0.80, "output": 2.00},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "pricing": {"input": 0.15, "output": 0.60},
    },
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """Token usage statistics for an LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Calculate estimated cost in USD based on provider pricing."""
        return 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class LLMResponse:
    """Standardised response from any LLM provider."""

    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a structured response.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model identifier; falls back to provider default when
                ``None``.
            temperature: Sampling temperature (0-2). Provider default when
                ``None``.
            max_tokens: Maximum completion tokens. Provider default when
                ``None``.

        Returns:
            Parsed LLMResponse with content, usage metadata, and model info.
        """


# ---------------------------------------------------------------------------
# OpenAI-compatible implementation
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider using OpenAI-compatible REST API via httpx.

    Args:
        provider_name: One of ``"deepseek"``, ``"qwen"``, ``"openai"``.
        api_key: API key. Falls back to the corresponding environment variable.
        base_url: Custom base URL. Falls back to the default for the provider.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        provider_name: str = "",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._provider_name = provider_name or os.environ.get("LLM_PROVIDER", "deepseek")

        if self._provider_name not in PROVIDER_CONFIG:
            raise ValueError(
                f"Unknown provider '{self._provider_name}'. "
                f"Supported: {list(PROVIDER_CONFIG)}"
            )

        cfg = PROVIDER_CONFIG[self._provider_name]

        resolved_key = api_key or os.environ.get(cfg["env_key"])
        if not resolved_key:
            raise ValueError(
                f"API key not provided and {cfg['env_key']} env var is not set"
            )
        self._api_key: str = resolved_key

        self._base_url = (base_url or cfg["base_url"]).rstrip("/")
        self._default_model: str = cfg["default_model"]
        self._pricing: dict[str, float] = cfg["pricing"]
        self._timeout = timeout

        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self._timeout),
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def pricing(self) -> dict[str, float]:
        return dict(self._pricing)

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token for English/Chinese text."""
        return max(1, len(text) // 4)

    def _calculate_usage(
        self,
        raw: dict[str, Any],
        request_messages: list[dict[str, str]],
        response_text: str,
    ) -> Usage:
        """Extract or estimate usage from the API response."""
        usage_data = raw.get("usage")
        if usage_data:
            return Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

        prompt_text = " ".join(m.get("content", "") for m in request_messages)
        prompt_tokens = self._estimate_tokens(prompt_text)
        completion_tokens = self._estimate_tokens(response_text)
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    def calculate_cost(self, usage: Usage) -> float:
        """Calculate estimated USD cost for a given Usage object.

        Args:
            usage: Token usage statistics.

        Returns:
            Estimated cost in USD.
        """
        return (
            usage.prompt_tokens / 1_000_000 * self._pricing["input"]
            + usage.completion_tokens / 1_000_000 * self._pricing["output"]
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to the OpenAI-compatible API.

        Args:
            messages: List of message dicts with ``role`` and ``content``.
            model: Model name; defaults to the provider default.
            temperature: Sampling temperature.
            max_tokens: Max tokens in the response.

        Returns:
            LLMResponse with generated content and usage metadata.

        Raises:
            httpx.HTTPStatusError: On non-2xx API response.
        """
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        usage = self._calculate_usage(data, messages, content)

        response = LLMResponse(
            content=content,
            usage=usage,
            model=data.get("model", ""),
            provider=self._provider_name,
        )
        tracker.record(usage, self._provider_name)
        return response

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def create_provider(
    provider_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> OpenAICompatibleProvider:
    """Create and return an LLM provider instance.

    Args:
        provider_name: Provider name ``"deepseek"``, ``"qwen"``, or
            ``"openai"``. Falls back to ``LLM_PROVIDER`` env var, then
            ``"deepseek"``.
        api_key: API key. Falls back to the corresponding environment variable.
        base_url: Custom base URL. Falls back to the provider default.
        timeout: Request timeout in seconds.

    Returns:
        An initialized :class:`OpenAICompatibleProvider` instance.

    Example::

        provider = create_provider()
        resp = chat_with_retry(provider, messages=[...])
        provider.close()
    """
    resolved = provider_name or os.environ.get("LLM_PROVIDER", "deepseek")
    return OpenAICompatibleProvider(
        provider_name=resolved,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int = MAX_RETRIES,
    base_delay: float = RETRY_BASE_DELAY,
) -> LLMResponse:
    """Call ``provider.chat()`` with exponential-backoff retry logic.

    Retries on any exception up to ``max_retries`` times, with delay
    calculated as ``base_delay * 2 ** attempt``.

    Args:
        provider: An LLMProvider instance.
        messages: Chat messages.
        model: Model identifier.
        temperature: Sampling temperature.
        max_tokens: Max completion tokens.
        max_retries: Number of retry attempts (default 3).
        base_delay: Initial delay in seconds (default 2.0).

    Returns:
        LLMResponse from the first successful call.

    Raises:
        RuntimeError: If all retry attempts fail, wrapping the last exception.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * 2**attempt
                logger.warning(
                    "Chat attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "All %d chat attempts failed. Last error: %s",
                    max_retries + 1,
                    exc,
                )

    raise RuntimeError(
        f"Chat failed after {max_retries + 1} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def quick_chat(
    prompt: str,
    system_prompt: str | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> LLMResponse:
    """One-shot chat: build messages and call the LLM with retry.

    Args:
        prompt: The user's input message.
        system_prompt: Optional system message prepended to the conversation.
        provider_name: Provider name (default from ``LLM_PROVIDER`` env).
        model: Model name (default from provider config).
        **kwargs: Extra arguments forwarded to ``chat_with_retry``.

    Returns:
        LLMResponse containing the model reply.

    Example::

        resp = quick_chat("What is LangGraph?")
        print(resp.content)
    """
    provider = create_provider(provider_name=provider_name)

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = chat_with_retry(provider, messages=messages, model=model, **kwargs)
    finally:
        provider.close()

    prices = CNY_PRICES.get(provider.provider_name, {"input": 0, "output": 0})
    cost = (
        resp.usage.prompt_tokens / 1_000_000 * prices["input"]
        + resp.usage.completion_tokens / 1_000_000 * prices["output"]
    )
    print(
        f"[Cost] {provider.provider_name}: {resp.usage.total_tokens} tokens, "
        f"¥{cost:.4f}",
    )
    return resp


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------


class CostTracker:
    """Tracks LLM API call token usage and estimates costs in CNY.

    Records token consumption per provider and provides cost estimation
    based on the domestically-oriented :data:`CNY_PRICES` table.

    Attributes:
        records: Mapping of provider name to list of :class:`Usage` records.
    """

    def __init__(self) -> None:
        self.records: dict[str, list[Usage]] = {}

    def record(self, usage: Usage, provider: str) -> None:
        """Record a single API call's token usage.

        Args:
            usage: Token usage statistics from the API response.
            provider: Provider name (e.g. ``"deepseek"``, ``"qwen"``).
        """
        self.records.setdefault(provider, []).append(usage)

    def _total_usage(self, provider: str | None = None) -> dict[str, Usage]:
        """Aggregate usage per provider.

        Args:
            provider: If specified, only return for this provider.

        Returns:
            Dict of provider -> summed :class:`Usage`.
        """
        if provider:
            usage_list = self.records.get(provider, [])
            total = sum(usage_list, Usage())
            return {provider: total}

        result = {}
        for prov, usages in self.records.items():
            result[prov] = sum(usages, Usage())
        return result

    def estimated_cost(self, provider: str | None = None) -> dict[str, float]:
        """Calculate estimated cost in CNY for recorded calls.

        Args:
            provider: If specified, only calculate for this provider.
                If ``None``, calculate for all providers.

        Returns:
            Dict mapping provider name to estimated cost in CNY.
        """
        totals = self._total_usage(provider)
        costs: dict[str, float] = {}
        for prov, usage in totals.items():
            prices = CNY_PRICES.get(prov, {"input": 0, "output": 0})
            cost = (
                usage.prompt_tokens / 1_000_000 * prices["input"]
                + usage.completion_tokens / 1_000_000 * prices["output"]
            )
            costs[prov] = cost
        return costs

    def report(self, provider: str | None = None) -> None:
        """Print a formatted cost report via the module logger.

        Args:
            provider: If specified, only show this provider's report.
                If ``None``, show all providers.
        """
        totals = self._total_usage(provider)
        costs = self.estimated_cost(provider)

        if not totals:
            logger.info("[CostTracker] No usage records.")
            return

        grand_total = 0.0
        for prov in sorted(totals):
            usage = totals[prov]
            cost = costs.get(prov, 0.0)
            grand_total += cost
            logger.info(
                "[CostTracker] %s: %d prompt + %d completion = %d tokens, cost ¥%.4f",
                prov,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
                cost,
            )

        if len(totals) > 1:
            logger.info(
                "[CostTracker] Total: ¥%.4f across %d providers",
                grand_total,
                len(totals),
            )


# Global tracker instance
tracker = CostTracker()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


def format_cost(usd: float) -> str:
    """Format a USD cost value into a human-readable string."""
    if usd < 0.01:
        return f"${usd:.6f}"
    if usd < 1.0:
        return f"${usd:.4f}"
    return f"${usd:.2f}"


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def _run_smoke_test() -> None:
    """Run basic smoke tests against all configured providers.

    Requires the corresponding environment variables to be set.
    Tests are skipped for providers whose API key is not found.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    test_message = "Say 'Hello from the LLM client' and nothing else."
    test_messages = [{"role": "user", "content": test_message}]

    for name, cfg in PROVIDER_CONFIG.items():
        api_key = os.environ.get(cfg["env_key"])
        if not api_key:
            logger.info("Skipping '%s' (no %s env var)", name, cfg["env_key"])
            continue

        logger.info("--- Testing provider: %s (model: %s) ---", name, cfg["default_model"])
        provider = create_provider(provider_name=name)
        try:
            resp = chat_with_retry(provider, messages=test_messages)
            cost = provider.calculate_cost(resp.usage)
            logger.info("Response: %s", resp.content[:120])
            logger.info("Usage  : %s", resp.usage)
            logger.info("Cost   : %s", format_cost(cost))
        except Exception as exc:
            logger.error("Error with %s: %s", name, exc)
        finally:
            provider.close()

    logger.info("--- Testing quick_chat ---")
    try:
        resp = quick_chat("Reply with only the word 'OK'.")
        logger.info("quick_chat response: %s", resp.content)
    except Exception as exc:
        logger.error("quick_chat error: %s", exc)

    logger.info("Smoke test complete.")


if __name__ == "__main__":
    _run_smoke_test()
