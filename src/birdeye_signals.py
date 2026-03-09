"""
Birdeye Trending Data Module (Section 4).

Integrates Birdeye API for Solana trending tokens:
- Trending list rank
- Volume acceleration
- Holder growth rate
- Liquidity expansion

If a token is trending across multiple Solana trackers,
boosts the signal score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from .config import settings

_BIRDEYE_TRENDING_URL = "{base}/defi/token_trending"
_BIRDEYE_TOKEN_URL = "{base}/defi/token_overview"
_HTTP_TIMEOUT = 10.0


@dataclass
class BirdeyeSignalResult:
    """Aggregated Birdeye signal for a token."""
    is_trending: bool = False
    trending_rank: int = 0  # 0 = not trending
    volume_24h_usd: float = 0.0
    volume_change_pct: float = 0.0  # volume acceleration
    holder_count: int = 0
    holder_growth_pct: float = 0.0
    liquidity_usd: float = 0.0
    liquidity_change_pct: float = 0.0
    price_change_24h_pct: float = 0.0
    birdeye_signal_score: float = 0.0  # 0-100
    multi_tracker_trending: bool = False  # trending on both Birdeye + DexScreener

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_trending": self.is_trending,
            "trending_rank": self.trending_rank,
            "volume_24h_usd": round(self.volume_24h_usd, 2),
            "volume_change_pct": round(self.volume_change_pct, 2),
            "holder_count": self.holder_count,
            "holder_growth_pct": round(self.holder_growth_pct, 2),
            "liquidity_usd": round(self.liquidity_usd, 2),
            "liquidity_change_pct": round(self.liquidity_change_pct, 2),
            "birdeye_signal_score": round(self.birdeye_signal_score, 2),
            "multi_tracker_trending": self.multi_tracker_trending,
        }


# In-memory cache of trending tokens
_birdeye_cache: dict[str, BirdeyeSignalResult] = {}
_trending_addresses: set[str] = set()
_last_trending_fetch: datetime | None = None


async def fetch_birdeye_trending() -> list[dict[str, Any]]:
    """
    Fetch trending Solana tokens from Birdeye API.

    Requires BIRDEYE_API_KEY to be set. Returns empty list if not configured.
    """
    global _trending_addresses, _last_trending_fetch

    if not settings.BIRDEYE_API_KEY:
        logger.debug("Birdeye API key not configured, skipping trending fetch")
        return []

    url = _BIRDEYE_TRENDING_URL.format(base=settings.BIRDEYE_API_URL)
    headers = {
        "X-API-KEY": settings.BIRDEYE_API_KEY,
        "x-chain": "solana",
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        tokens = data.get("data", {}).get("items", [])
        _trending_addresses = {t.get("address", "") for t in tokens if t.get("address")}
        _last_trending_fetch = datetime.now(timezone.utc)

        logger.info("Birdeye: fetched {} trending Solana tokens", len(tokens))
        return tokens

    except httpx.HTTPStatusError as e:
        logger.warning("Birdeye API HTTP error: {}", e.response.status_code)
    except httpx.RequestError as e:
        logger.warning("Birdeye API request error: {}", e)
    except Exception as e:
        logger.error("Unexpected error fetching Birdeye trending: {}", e)

    return []


async def fetch_birdeye_token_data(token_address: str) -> dict[str, Any] | None:
    """Fetch detailed token data from Birdeye for a specific token."""
    if not settings.BIRDEYE_API_KEY:
        return None

    url = _BIRDEYE_TOKEN_URL.format(base=settings.BIRDEYE_API_URL)
    headers = {
        "X-API-KEY": settings.BIRDEYE_API_KEY,
        "x-chain": "solana",
    }
    params = {"address": token_address}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        return data.get("data", {})
    except Exception as e:
        logger.debug("Birdeye token fetch failed for {}: {}", token_address[:8], e)
        return None


def process_birdeye_signal(
    symbol: str,
    token_address: str = "",
    signal_data: dict[str, Any] | None = None,
    dex_trending: bool = False,
) -> BirdeyeSignalResult:
    """
    Process Birdeye signal data for a token.

    Parameters
    ----------
    symbol : str
        Token ticker symbol.
    token_address : str
        Token contract address.
    signal_data : dict
        Raw signal data (either from Social Signal Engine or Birdeye API).
    dex_trending : bool
        Whether the token is also trending on DexScreener.
    """
    result = BirdeyeSignalResult()
    key = symbol.upper()

    if signal_data is None:
        cached = _birdeye_cache.get(key) or _birdeye_cache.get(token_address)
        if cached is not None:
            return cached
        return result

    # Check if token is in Birdeye trending list
    result.is_trending = token_address in _trending_addresses

    # Extract Birdeye-specific data
    birdeye_data = signal_data.get("birdeye", {})
    if birdeye_data:
        result.trending_rank = birdeye_data.get("rank", 0)
        result.volume_24h_usd = birdeye_data.get("volume_24h", 0.0)
        result.volume_change_pct = birdeye_data.get("volume_change_pct", 0.0)
        result.holder_count = birdeye_data.get("holders", 0)
        result.holder_growth_pct = birdeye_data.get("holder_growth_pct", 0.0)
        result.liquidity_usd = birdeye_data.get("liquidity", 0.0)
        result.liquidity_change_pct = birdeye_data.get("liquidity_change_pct", 0.0)
        result.price_change_24h_pct = birdeye_data.get("price_change_24h", 0.0)
        if result.trending_rank > 0:
            result.is_trending = True
    else:
        # Use general signal data as fallback
        result.volume_24h_usd = signal_data.get("volume_24h", 0.0)
        result.holder_count = signal_data.get("holders", 0)
        result.liquidity_usd = signal_data.get("liquidity", 0.0)

    # Multi-tracker trending detection
    result.multi_tracker_trending = result.is_trending and dex_trending

    # --- Compute birdeye_signal_score (0-100) ---
    # 1. Trending rank score (max 30)
    trending_score = 0.0
    if result.is_trending:
        if result.trending_rank <= 5:
            trending_score = 30.0
        elif result.trending_rank <= 15:
            trending_score = 22.0
        elif result.trending_rank <= 30:
            trending_score = 15.0
        else:
            trending_score = 10.0

    # 2. Volume acceleration (max 25)
    volume_score = 0.0
    if result.volume_change_pct > 200:
        volume_score = 25.0
    elif result.volume_change_pct > 100:
        volume_score = 18.0
    elif result.volume_change_pct > 50:
        volume_score = 12.0
    elif result.volume_change_pct > 0:
        volume_score = min(result.volume_change_pct * 0.2, 8.0)

    # 3. Holder growth (max 20)
    holder_score = 0.0
    if result.holder_growth_pct > 50:
        holder_score = 20.0
    elif result.holder_growth_pct > 20:
        holder_score = 14.0
    elif result.holder_growth_pct > 10:
        holder_score = 8.0
    elif result.holder_growth_pct > 0:
        holder_score = min(result.holder_growth_pct * 0.5, 6.0)

    # 4. Liquidity expansion (max 15)
    liq_score = 0.0
    if result.liquidity_change_pct > 50:
        liq_score = 15.0
    elif result.liquidity_change_pct > 20:
        liq_score = 10.0
    elif result.liquidity_change_pct > 0:
        liq_score = min(result.liquidity_change_pct * 0.3, 8.0)

    # 5. Multi-tracker bonus (max 10)
    multi_score = 10.0 if result.multi_tracker_trending else 0.0

    result.birdeye_signal_score = min(
        trending_score + volume_score + holder_score + liq_score + multi_score,
        100.0,
    )

    # Cache
    _birdeye_cache[key] = result
    if token_address:
        _birdeye_cache[token_address] = result

    logger.debug(
        "Birdeye signal for {}: score={:.1f}, trending={}, rank={}, "
        "vol_change={:.1f}%, holder_growth={:.1f}%",
        symbol, result.birdeye_signal_score, result.is_trending,
        result.trending_rank, result.volume_change_pct, result.holder_growth_pct,
    )

    return result


def is_birdeye_trending(token_address: str) -> bool:
    """Check if a token is in the Birdeye trending list."""
    return token_address in _trending_addresses


def get_birdeye_cache_count() -> int:
    """Return number of cached Birdeye signals."""
    return len({k: v for k, v in _birdeye_cache.items() if v.birdeye_signal_score > 0})
