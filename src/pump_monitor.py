"""
Pump Platform Monitoring Module (Section 5).

Monitors memecoin launch platforms (e.g. pump.fun) for:
- Newly launched tokens
- Tokens gaining early traction
- Tokens with rapid buyer growth

Scores tokens based on:
- wallet_growth (new unique buyers over time)
- liquidity_injection_speed (how fast liquidity is added)
- buy_pressure (buyer dominance ratio)

Data is sourced from the centralized Social Signal Engine and
DexScreener new-pair feeds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .config import settings


@dataclass
class PumpSignalResult:
    """Signal from pump platform monitoring."""
    is_new_launch: bool = False
    buyer_count: int = 0
    buyer_growth_rate: float = 0.0  # buyers/min
    liquidity_injection_speed: float = 0.0  # USD/min added
    buy_pressure_ratio: float = 0.0  # buys / (buys + sells)
    has_early_traction: bool = False
    has_rapid_growth: bool = False
    pump_signal_score: float = 0.0  # 0-100

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_new_launch": self.is_new_launch,
            "buyer_count": self.buyer_count,
            "buyer_growth_rate": round(self.buyer_growth_rate, 2),
            "liquidity_injection_speed": round(self.liquidity_injection_speed, 2),
            "buy_pressure_ratio": round(self.buy_pressure_ratio, 3),
            "has_early_traction": self.has_early_traction,
            "has_rapid_growth": self.has_rapid_growth,
            "pump_signal_score": round(self.pump_signal_score, 2),
        }


# In-memory cache
_pump_cache: dict[str, PumpSignalResult] = {}
_buyer_history: dict[str, list[tuple[datetime, int]]] = {}


def process_pump_signal(
    symbol: str,
    token_address: str = "",
    token_age_seconds: float = 0.0,
    holder_count: int = 0,
    buys_5m: int = 0,
    sells_5m: int = 0,
    liquidity_usd: float = 0.0,
    previous_liquidity_usd: float = 0.0,
    signal_data: dict[str, Any] | None = None,
) -> PumpSignalResult:
    """
    Process pump platform signal data for a token.

    Uses on-chain data (holder count, buys/sells, liquidity) and
    optional signal engine data to compute a pump signal score.
    """
    result = PumpSignalResult()
    key = symbol.upper()

    if not settings.PUMP_MONITOR_ENABLED:
        return result

    # Determine if this is a new launch (< 10 minutes old)
    result.is_new_launch = token_age_seconds < 600

    # Buyer count and growth rate
    result.buyer_count = holder_count
    now = datetime.now(timezone.utc)

    # Track buyer history for growth rate calculation
    history = _buyer_history.get(key, [])
    history.append((now, holder_count))
    # Keep last 10 entries
    if len(history) > 10:
        history = history[-10:]
    _buyer_history[key] = history

    if len(history) >= 2:
        first_ts, first_count = history[0]
        elapsed_minutes = max((now - first_ts).total_seconds() / 60.0, 0.1)
        growth = holder_count - first_count
        result.buyer_growth_rate = growth / elapsed_minutes

        # Rapid growth detection
        if first_count > 0:
            growth_multiplier = holder_count / max(first_count, 1)
            result.has_rapid_growth = growth_multiplier >= settings.PUMP_RAPID_GROWTH_THRESHOLD

    # Buy pressure ratio
    total_txns = buys_5m + sells_5m
    if total_txns > 0:
        result.buy_pressure_ratio = buys_5m / total_txns

    # Early traction detection
    result.has_early_traction = (
        result.buyer_count >= settings.PUMP_EARLY_TRACTION_MIN_BUYERS
        and result.buy_pressure_ratio >= 0.6
    )

    # Liquidity injection speed
    if previous_liquidity_usd > 0 and liquidity_usd > previous_liquidity_usd:
        liq_increase = liquidity_usd - previous_liquidity_usd
        # Assume 5-min window for the increase
        result.liquidity_injection_speed = liq_increase / 5.0

    # Use pump-specific signal data if available
    if signal_data:
        pump_data = signal_data.get("pump", {})
        if pump_data:
            result.buyer_count = pump_data.get("buyers", result.buyer_count)
            result.buyer_growth_rate = pump_data.get("growth_rate", result.buyer_growth_rate)
            if pump_data.get("rapid_growth"):
                result.has_rapid_growth = True
            if pump_data.get("early_traction"):
                result.has_early_traction = True

    # --- Compute pump_signal_score (0-100) ---
    # 1. Buyer growth score (max 35)
    growth_score = 0.0
    if result.has_rapid_growth:
        growth_score = 35.0
    elif result.buyer_growth_rate >= 5.0:
        growth_score = 25.0
    elif result.buyer_growth_rate >= 2.0:
        growth_score = 18.0
    elif result.buyer_growth_rate > 0:
        growth_score = min(result.buyer_growth_rate * 5.0, 12.0)

    # 2. Buy pressure score (max 25)
    pressure_score = 0.0
    if result.buy_pressure_ratio >= 0.8:
        pressure_score = 25.0
    elif result.buy_pressure_ratio >= 0.7:
        pressure_score = 18.0
    elif result.buy_pressure_ratio >= 0.6:
        pressure_score = 12.0
    elif result.buy_pressure_ratio > 0.5:
        pressure_score = 5.0

    # 3. Liquidity injection score (max 20)
    liq_score = 0.0
    if result.liquidity_injection_speed > 10000:
        liq_score = 20.0
    elif result.liquidity_injection_speed > 5000:
        liq_score = 14.0
    elif result.liquidity_injection_speed > 1000:
        liq_score = 8.0
    elif result.liquidity_injection_speed > 0:
        liq_score = min(result.liquidity_injection_speed / 200.0, 5.0)

    # 4. Early traction bonus (max 10)
    traction_score = 10.0 if result.has_early_traction else 0.0

    # 5. New launch freshness bonus (max 10)
    fresh_score = 0.0
    if result.is_new_launch and result.has_early_traction:
        fresh_score = 10.0
    elif result.is_new_launch:
        fresh_score = 5.0

    result.pump_signal_score = min(
        growth_score + pressure_score + liq_score + traction_score + fresh_score,
        100.0,
    )

    # Cache
    _pump_cache[key] = result
    if token_address:
        _pump_cache[token_address] = result

    logger.debug(
        "Pump signal for {}: score={:.1f}, buyers={}, growth={:.1f}/min, "
        "buy_pressure={:.2f}, early_traction={}, rapid_growth={}",
        symbol, result.pump_signal_score, result.buyer_count,
        result.buyer_growth_rate, result.buy_pressure_ratio,
        result.has_early_traction, result.has_rapid_growth,
    )

    return result


def get_pump_cache_count() -> int:
    """Return number of cached pump signals."""
    return len({k: v for k, v in _pump_cache.items() if v.pump_signal_score > 0})
