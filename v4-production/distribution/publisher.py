#!/usr/bin/env python3
"""Async publishers for Telegram and Feishu channels.

Provides an abstract base class, concrete implementations for Telegram
(MarkdownV2 via Bot API) and Feishu (interactive cards via webhook), and a
unified ``publish_daily_digest()`` async entry point.

Typical usage::

    import asyncio
    from distribution.publisher import publish_daily_digest

    results = asyncio.run(
        publish_daily_digest(channels=["telegram", "feishu"], date="2026-05-10")
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

# Allow running this file directly for smoke testing
if __name__ == "__main__" or __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from distribution.formatter import generate_daily_digest

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# Registry mapping channel name strings to publisher classes
CHANNEL_REGISTRY: dict[str, type[BasePublisher]] = {}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PublishResult:
    """Record of a single publish attempt.

    Attributes:
        channel: The channel name (``"telegram"`` or ``"feishu"``).
        success: Whether the message was sent successfully.
        message_id: Platform-specific message identifier; ``None`` on failure.
        error: Error message string; ``None`` on success.
    """

    channel: str
    success: bool
    message_id: str | None = None
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Abstract base publisher
# ---------------------------------------------------------------------------


class BasePublisher(ABC):
    """Abstract base class for message publishers.

    Concrete implementations must provide ``send_message`` for single
    messages and ``send_digest`` for daily digest delivery.
    """

    channel_name: str = "unknown"

    @abstractmethod
    async def send_message(self, content: Any) -> PublishResult:
        """Send a single message to the channel.

        Args:
            content: Channel-specific message payload.  For Telegram this is a
                MarkdownV2 string; for Feishu this is a card dict.

        Returns:
            ``PublishResult`` indicating success or failure.
        """

    @abstractmethod
    async def send_digest(self, digest: dict[str, Any]) -> list[PublishResult]:
        """Send a daily digest to the channel.

        Args:
            digest: Output dict from :func:`generate_daily_digest`
                (``distribution.formatter``), with keys ``"markdown"``,
                ``"telegram"``, and ``"feishu"``.

        Returns:
            A list of ``PublishResult`` objects, one per message sent.
        """


# ---------------------------------------------------------------------------
# Telegram publisher
# ---------------------------------------------------------------------------


class TelegramPublisher(BasePublisher):
    """Publish messages to a Telegram chat via the Bot API.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from environment
    variables.  Messages are sent in MarkdownV2 parse mode.

    The client session is created lazily on first use and closed via
    ``close()``.

    Args:
        timeout: Request timeout in seconds.
    """

    channel_name = "telegram"

    def __init__(self, timeout: float = _REQUEST_TIMEOUT) -> None:
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    @property
    def _api_url(self) -> str:
        """Construct the full Telegram Bot API endpoint."""
        return TELEGRAM_API_BASE.format(token=self._token)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create or return the shared aiohttp session."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def send_message(self, content: Any) -> PublishResult:
        """Send a single MarkdownV2 message to Telegram.

        Args:
            content: MarkdownV2-formatted text string.

        Returns:
            ``PublishResult`` for this message.

        Raises:
            ValueError: If ``TELEGRAM_BOT_TOKEN`` or ``TELEGRAM_CHAT_ID`` is
                not set.
        """
        if not self._token:
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error="TELEGRAM_BOT_TOKEN is not set",
            )
        if not self._chat_id:
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error="TELEGRAM_CHAT_ID is not set",
            )

        payload = {
            "chat_id": self._chat_id,
            "text": content,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        session = await self._ensure_session()
        try:
            async with session.post(self._api_url, json=payload) as resp:
                data = await resp.json()

                if not resp.ok or not data.get("ok"):
                    description = data.get("description", f"HTTP {resp.status}")
                    logger.error(
                        "Telegram API error: %s (status=%s, payload_len=%d)",
                        description,
                        resp.status,
                        len(str(payload)),
                    )
                    return PublishResult(
                        channel=self.channel_name,
                        success=False,
                        error=description,
                    )

                message_id = str(data["result"]["message_id"])
                logger.info("Telegram message sent: message_id=%s", message_id)
                return PublishResult(
                    channel=self.channel_name,
                    success=True,
                    message_id=message_id,
                )

        except asyncio.TimeoutError:
            logger.error("Telegram API request timed out after %d s", self._timeout)
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error=f"Request timed out after {self._timeout}s",
            )
        except aiohttp.ClientError as exc:
            logger.error("Telegram API client error: %s", exc)
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error=str(exc),
            )

    async def send_digest(self, digest: dict[str, Any]) -> list[PublishResult]:
        """Send the Telegram digest as a single message.

        Uses the ``"telegram"`` key from the digest dict.  If the value is
        empty or signals no-articles, the message is still sent as an
        informational update.

        Args:
            digest: Output dict from :func:`generate_daily_digest`.

        Returns:
            Single-element list of ``PublishResult``.
        """
        telegram_text = digest.get("telegram", "")
        if not telegram_text:
            return [
                PublishResult(
                    channel=self.channel_name,
                    success=False,
                    error="Digest contains no Telegram content",
                )
            ]
        result = await self.send_message(telegram_text)
        return [result]

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session is not None:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Feishu publisher
# ---------------------------------------------------------------------------


class FeishuPublisher(BasePublisher):
    """Publish interactive card messages to a Feishu group via webhook.

    Reads ``FEISHU_WEBHOOK_URL`` from environment variables.
    Each card from the digest is sent as a separate API request.

    The client session is created lazily on first use and closed via
    ``close()``.

    Args:
        timeout: Request timeout in seconds.
    """

    channel_name = "feishu"

    def __init__(self, timeout: float = _REQUEST_TIMEOUT) -> None:
        self._webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create or return the shared aiohttp session."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _build_envelope(self, card: dict[str, Any]) -> dict[str, Any]:
        """Wrap a Feishu Card v2.0 dict into the webhook request body.

        Args:
            card: Card dict as returned by :func:`json_to_feishu`.

        Returns:
            Request body with ``msg_type`` and ``content`` keys.
        """
        return {
            "msg_type": "interactive",
            "card": card,
        }

    async def send_message(self, content: Any) -> PublishResult:
        """Send a single interactive card to the Feishu webhook.

        Args:
            content: Feishu Card v2.0 dict (without ``msg_type`` wrapper).

        Returns:
            ``PublishResult`` for this message.

        Raises:
            ValueError: If ``FEISHU_WEBHOOK_URL`` is not set.
        """
        if not self._webhook_url:
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error="FEISHU_WEBHOOK_URL is not set",
            )

        payload = self._build_envelope(content)
        session = await self._ensure_session()

        try:
            async with session.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                # Feishu webhooks return 200 even on some logical errors;
                # the body contains code / msg.
                data = await resp.json()

                if resp.status == 200 and data.get("code") == 0:
                    logger.info(
                        "Feishu message sent successfully (resp_status=%s)",
                        resp.status,
                    )
                    return PublishResult(
                        channel=self.channel_name,
                        success=True,
                        message_id=data.get("data", {}).get("message_id"),
                    )

                status_msg = data.get("msg", f"HTTP {resp.status}")
                logger.error(
                    "Feishu webhook error: %s (code=%s, resp_status=%s)",
                    status_msg,
                    data.get("code"),
                    resp.status,
                )
                return PublishResult(
                    channel=self.channel_name,
                    success=False,
                    error=status_msg,
                )

        except asyncio.TimeoutError:
            logger.error("Feishu webhook request timed out after %d s", self._timeout)
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error=f"Request timed out after {self._timeout}s",
            )
        except aiohttp.ClientError as exc:
            logger.error("Feishu webhook client error: %s", exc)
            return PublishResult(
                channel=self.channel_name,
                success=False,
                error=str(exc),
            )

    async def send_digest(self, digest: dict[str, Any]) -> list[PublishResult]:
        """Send each Feishu card in the digest as a separate message.

        Cards are sent sequentially with a short delay to respect Feishu
        webhook rate limits.

        Args:
            digest: Output dict from :func:`generate_daily_digest`.

        Returns:
            List of ``PublishResult``, one per card sent.
        """
        feishu_cards: list[dict[str, Any]] = digest.get("feishu", [])

        if not feishu_cards:
            return [
                PublishResult(
                    channel=self.channel_name,
                    success=True,
                    message_id=None,
                    error="No Feishu cards to send (empty digest)",
                )
            ]

        results: list[PublishResult] = []
        for card in feishu_cards:
            result = await self.send_message(card)
            results.append(result)
            if card is not feishu_cards[-1]:
                await asyncio.sleep(0.5)

        return results

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session is not None:
            await self._session.close()
            self._session = None


# ---------------------------------------------------------------------------
# Unified daily digest publish
# ---------------------------------------------------------------------------


CHANNEL_REGISTRY["telegram"] = TelegramPublisher
CHANNEL_REGISTRY["feishu"] = FeishuPublisher


# ---------------------------------------------------------------------------
# Unified daily digest publish
# ---------------------------------------------------------------------------


async def publish_daily_digest(
    channels: list[str] | None = None,
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
    timeout: float = _REQUEST_TIMEOUT,
    min_quality_score: float = 0.0,
) -> list[PublishResult]:
    """Generate and publish the daily knowledge digest to specified channels.

    Calls :func:`generate_daily_digest` to produce Markdown, Telegram, and
    Feishu formatted outputs, then publishes them concurrently to the
    requested channels. Each publisher subclass reads its own credentials
    from environment variables.

    Args:
        channels: List of channel names to publish to (``"telegram"``,
            ``"feishu"``).  Defaults to all registered channels.
        knowledge_dir: Path to the knowledge articles directory.
        date: Date in ``YYYY-MM-DD`` format.  Defaults to today.
        top_n: Maximum number of articles to include.
        timeout: Request timeout in seconds, passed to each publisher.
        min_quality_score: Minimum quality score filter (0.0–1.0).  Articles
            with ``quality_score < min_quality_score`` are excluded.  Defaults
            to 0.0 (no filtering).

    Returns:
        Flat list of ``PublishResult`` objects for all messages sent across
        all channels.  Returns an empty result list when no channels are
        specified or no articles exist.

    Example::

        import asyncio
        results = asyncio.run(
            publish_daily_digest(channels=["telegram", "feishu"])
        )
        for r in results:
            print(f"{r.channel}: {'OK' if r.success else r.error}")
    """
    if date is None:
        date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    digest = generate_daily_digest(
        knowledge_dir=knowledge_dir,
        date=date,
        top_n=top_n,
        min_quality_score=min_quality_score,
    )

    # Resolve channels
    if channels is None:
        channels = list(CHANNEL_REGISTRY)

    publishers: list[BasePublisher] = []
    for name in channels:
        cls = CHANNEL_REGISTRY.get(name)
        if cls is None:
            logger.warning("Unknown channel '%s', skipping", name)
            continue
        try:
            publishers.append(cls(timeout=timeout))
        except Exception as exc:
            logger.error("Failed to create publisher for '%s': %s", name, exc)

    if not publishers:
        logger.warning("No publishers created for daily digest on %s", date)
        return [
            PublishResult(
                channel="all",
                success=False,
                error="No publishers available (check channels and environment variables)",
            )
        ]

    tasks = [pub.send_digest(digest) for pub in publishers]
    nested_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[PublishResult] = []
    for pub, result_or_exc in zip(publishers, nested_results):
        if isinstance(result_or_exc, BaseException):
            logger.error(
                "Publisher %s raised exception: %s",
                pub.channel_name,
                result_or_exc,
            )
            all_results.append(
                PublishResult(
                    channel=pub.channel_name,
                    success=False,
                    error=str(result_or_exc),
                )
            )
        else:
            all_results.extend(result_or_exc)

    # Close sessions
    for pub in publishers:
        await pub.close()

    success_count = sum(1 for r in all_results if r.success)
    logger.info(
        "Daily digest publish complete: %d/%d messages sent successfully",
        success_count,
        len(all_results),
    )

    return all_results


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


async def _run_smoke_test() -> None:
    """Run a basic smoke test of the publisher module.

    Configures logging, verifies that publishers can be instantiated, and
    attempts a dry-run publish (which will fail gracefully if credentials
    are missing).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("--- Publisher smoke test ---")

    results = await publish_daily_digest(
        knowledge_dir='knowledge/articles',
        date='2026-05-09',  # 改成你知识库里有数据的日期
        channels=['feishu','telegram']
    )

    for r in results:
        status = "✅" if r.success else f"❌: {r.error}"
        logger.info("  %s | %s | msg_id=%s", r.channel, status, r.message_id)

    logger.info("Smoke test complete.")


if __name__ == "__main__":
    asyncio.run(_run_smoke_test())
