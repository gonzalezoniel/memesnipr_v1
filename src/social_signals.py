"""
Social Signal Engine client for MemeSnipr.

Fetches memecoin social signals from the centralized Social Signal Engine
and provides social sentiment data for token scoring and candidate filtering.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from loguru import logger

SIGNAL_ENGINE_URL = os.getenv(
    "SOCIAL_SIGNAL_ENGINE_URL", "https://app-sgvdyzun.fly.dev"
).rstrip("/")

_TIMEOUT = 10.0

# In-memory cache of latest social signals (token_symbol -> signal dict)
_cached_signals: dict[str, dict[str, Any]] = {}
_last_fetch: Optional[datetime] = None


async def fetch_memecoin_signals() -> list[dict[str, Any]]:
    """
    Fetch memecoin social signals from the Signal Engine.

    Returns a list of dicts with keys:
        token, contract, mentions, sentiment, trend, engagement, sources
    Also updates the in-memory lookup cache.
    """
    global _cached_signals, _last_fetch

    url = f"{SIGNAL_ENGINE_URL}/api/signals/memecoins"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        signals = data.get("memecoins", [])

        # Build lookup cache by token symbol (uppercase) and contract address
        new_cache: dict[str, dict[str, Any]] = {}
        for sig in signals:
            token = sig.get("token", "").upper()
            if token:
                new_cache[token] = sig
            contract = sig.get("contract", "")
            if contract:
                new_cache[contract] = sig

        _cached_signals = new_cache
        _last_fetch = datetime.now(timezone.utc)
        logger.info("Fetched {} memecoin social signals from Signal Engine", len(signals))
        return signals

    except httpx.HTTPStatusError as e:
        logger.warning("Signal Engine HTTP error: {}", e.response.status_code)
    except httpx.RequestError as e:
        logger.warning("Signal Engine request error: {}", e)
    except Exception as e:
        logger.error("Unexpected error fetching social signals: {}", e)

    return list({s.get("token", ""): s for s in _cached_signals.values()}.values())


def lookup_token_signal(
    symbol: str,
    token_address: str = "",
) -> Optional[dict[str, Any]]:
    """
    Look up cached social signal for a token by symbol or contract address.

    Returns the signal dict or None if no match found.
    """
    # Try symbol match first (uppercase)
    result = _cached_signals.get(symbol.upper())
    if result is not None:
        return result

    # Try contract address match
    if token_address:
        result = _cached_signals.get(token_address)
        if result is not None:
            return result

    return None


def compute_social_score(
    symbol: str,
    token_address: str = "",
    max_score: float = 8.0,
) -> tuple[float, dict[str, Any]]:
    """
    Compute a social signal score for a token candidate.

    Returns (score, details) where:
        score: 0.0 to max_score based on social signal strength
        details: dict with social signal metadata for audit logging

    Scoring breakdown (max 8.0):
        - mentions >= 10: +3.0, >= 5: +2.0, >= 2: +1.0
        - sentiment > 0.3: +2.0, > 0.1: +1.5, > 0: +1.0
        - trend == 'rising': +2.0, 'stable': +1.0
        - engagement > 0: +1.0
    """
    signal = lookup_token_signal(symbol, token_address)

    details: dict[str, Any] = {
        "social_signal_found": signal is not None,
        "social_mentions": 0,
        "social_sentiment": 0.0,
        "social_trend": "unknown",
    }

    if signal is None:
        return 0.0, details

    mentions = signal.get("mentions", 0)
    sentiment = signal.get("sentiment", 0.0)
    trend = signal.get("trend", "stable")
    engagement = signal.get("engagement", 0.0)

    details.update({
        "social_mentions": mentions,
        "social_sentiment": sentiment,
        "social_trend": trend,
        "social_engagement": engagement,
        "social_sources": signal.get("sources", []),
    })

    score = 0.0

    # Mentions component (max 3.0)
    if mentions >= 10:
        score += 3.0
    elif mentions >= 5:
        score += 2.0
    elif mentions >= 2:
        score += 1.0

    # Sentiment component (max 2.0)
    if sentiment > 0.3:
        score += 2.0
    elif sentiment > 0.1:
        score += 1.5
    elif sentiment > 0:
        score += 1.0

    # Trend component (max 2.0)
    if trend == "rising":
        score += 2.0
    elif trend == "stable":
        score += 1.0

    # Engagement component (max 1.0)
    if engagement > 0:
        score += 1.0

    # Cap at max_score
    score = min(score, max_score)

    return score, details


def get_cached_signal_count() -> int:
    """Return number of cached unique token signals."""
    return len({v.get("token", ""): v for v in _cached_signals.values()})


def get_last_fetch_time() -> Optional[datetime]:
    """Return the timestamp of the last successful fetch."""
    return _last_fetch
