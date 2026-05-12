#!/usr/bin/env python3
"""Daily AI knowledge digest push entry point.

Filters articles by quality_score >= 0.6, generates the daily digest,
and publishes to all configured channels (Telegram, Feishu).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from distribution.formatter import generate_daily_digest
from distribution.publisher import publish_daily_digest

load_dotenv()

logger = logging.getLogger(__name__)

MIN_QUALITY_SCORE = 0.6


async def run_daily_digest(
    knowledge_dir: str = "knowledge/articles",
    date: str | None = None,
    top_n: int = 5,
    min_quality_score: float = MIN_QUALITY_SCORE,
) -> int:
    """Run the daily digest workflow: filter, format, publish.

    Args:
        knowledge_dir: Path to knowledge articles directory.
        date: Date string in ``YYYY-MM-DD`` format.  Defaults to today.
        top_n: Maximum number of articles to include in the digest.
        min_quality_score: Minimum quality score threshold for articles.

    Returns:
        Exit code: ``0`` on success, ``1`` on skip (no articles above
        threshold), ``2`` on partial push failure.
    """
    # Step 1: Check if high-quality articles exist
    digest = generate_daily_digest(
        knowledge_dir=knowledge_dir,
        date=date,
        top_n=top_n,
        min_quality_score=min_quality_score,
    )

    # Step 2: Skip if no articles meet the quality threshold
    if digest["markdown"].startswith("\U0001f4ed"):
        from datetime import datetime, timezone

        date_str = date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        warning_msg = (
            f"\u26a0\ufe0f  {date_str}: "
            f"No articles with quality_score >= {min_quality_score}. "
            f"Skipping push."
        )
        print(warning_msg)
        logger.warning(
            "No high-quality articles found (threshold >=%.0f%%), "
            "skipping push",
            min_quality_score * 100,
        )
        return 1

    # Step 3: Publish to all configured channels
    results = await publish_daily_digest(
        knowledge_dir=knowledge_dir,
        date=date,
        top_n=top_n,
        min_quality_score=min_quality_score,
    )

    # Step 4: Print push result summary
    total = len(results)
    success_count = sum(1 for r in results if r.success)
    failed_count = total - success_count

    channels_ok: set[str] = set()
    channels_err: set[str] = set()
    for r in results:
        if r.success:
            channels_ok.add(r.channel)
        else:
            channels_err.add(r.channel)

    print(f"\n=== Push Result Summary ===")
    print(f"Success: {success_count}/{total} messages")
    print(f"Success channels: {', '.join(sorted(channels_ok)) if channels_ok else 'none'}")
    print(f"Failed channels: {', '.join(sorted(channels_err)) if channels_err else 'none'}")

    if failed_count > 0:
        for r in results:
            if not r.success:
                print(f"  \u274c [{r.channel}] {r.error}")
        return 2

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    exit_code = asyncio.run(run_daily_digest())
    sys.exit(exit_code)
