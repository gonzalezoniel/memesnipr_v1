"""
Momentum Confirmation Engine (Section 3).

Validates that a token has real momentum before entry by checking:
- price_change_1m > threshold
- volume_spike > baseline multiplier
- buyers > sellers
- liquidity_increase > threshold
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from .config import settings
from .models import TokenCandidate


@dataclass
class MomentumResult:
    """Result of momentum confirmation check."""
    passed: bool
    price_change_1m_pct: float = 0.0
    volume_spike_ratio: float = 0.0
    buy_sell_ratio: float = 0.0
    liquidity_increase_pct: float = 0.0
    reasons: list[str] | None = None

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def check_momentum(
    token: TokenCandidate,
    baseline_volume: float = 0.0,
    previous_liquidity: float = 0.0,
    price_1m_ago: float = 0.0,
) -> MomentumResult:
    """
    Confirm that a token has real momentum before entering a trade.

    Parameters
    ----------
    token : TokenCandidate
        The token being evaluated.
    baseline_volume : float
        The baseline volume for comparison (e.g., average volume over last hour).
        If 0, uses token.volume_usd_5m / 5 as a rough per-minute baseline.
    previous_liquidity : float
        The liquidity value from the previous check interval.
        If 0, liquidity increase check is skipped (passes by default).
    price_1m_ago : float
        The price 1 minute ago. If 0, price change check uses buy/sell flow
        as a proxy for momentum direction.
    """
    reasons: list[str] = []

    # --- Price change 1m ---
    price_change_1m_pct = 0.0
    if price_1m_ago > 0 and token.price_usd > 0:
        price_change_1m_pct = ((token.price_usd - price_1m_ago) / price_1m_ago) * 100.0
        if price_change_1m_pct < settings.MOMENTUM_PRICE_CHANGE_1M_PCT:
            reasons.append(
                f"price_change_1m={price_change_1m_pct:.2f}% < {settings.MOMENTUM_PRICE_CHANGE_1M_PCT}%"
            )
    else:
        # When historical price data is unavailable, use buy pressure as proxy
        total_txns = token.buys_5m + token.sells_5m
        if total_txns > 0:
            buy_ratio = token.buys_5m / total_txns
            # Strong buy pressure (>70%) is a proxy for positive price momentum
            if buy_ratio < 0.70:
                reasons.append(
                    f"no_price_history: buy_ratio={buy_ratio:.2f} < 0.70 (proxy for momentum)"
                )
            else:
                # Estimate price change from buy pressure
                price_change_1m_pct = (buy_ratio - 0.5) * 20.0  # rough proxy
        else:
            reasons.append("no_transaction_data_for_momentum")

    # --- Volume spike ---
    # When no historical baseline is provided, we cannot meaningfully
    # compare current volume against itself (ratio would always be 1.0).
    # Skip the spike check in that case (pass by default), similar to
    # how liquidity_increase is handled when previous_liquidity is 0.
    has_baseline = baseline_volume > 0 or token.baseline_volume > 0
    effective_baseline = baseline_volume if baseline_volume > 0 else token.baseline_volume

    current_volume_rate = token.volume_usd_5m / 5.0 if token.volume_usd_5m > 0 else 0.0
    volume_spike_ratio = (
        current_volume_rate / max(effective_baseline, 1.0) if has_baseline else 1.0
    )

    if has_baseline and volume_spike_ratio < settings.MOMENTUM_VOLUME_SPIKE_MULTIPLIER:
        reasons.append(
            f"volume_spike={volume_spike_ratio:.2f}x < {settings.MOMENTUM_VOLUME_SPIKE_MULTIPLIER}x"
        )

    # --- Buyers > Sellers ---
    buy_sell_ratio = 0.0
    total_txns = token.buys_5m + token.sells_5m
    if total_txns > 0:
        buy_sell_ratio = token.buys_5m / max(token.sells_5m, 1)
        if token.buys_5m <= token.sells_5m:
            reasons.append(
                f"buyers({token.buys_5m}) <= sellers({token.sells_5m})"
            )
    else:
        reasons.append("no_transaction_data")

    # --- Liquidity increase ---
    liquidity_increase_pct = 0.0
    if previous_liquidity > 0:
        liquidity_increase_pct = (
            (token.liquidity_usd - previous_liquidity) / previous_liquidity
        ) * 100.0
        if liquidity_increase_pct < settings.MOMENTUM_LIQUIDITY_INCREASE_PCT:
            reasons.append(
                f"liquidity_increase={liquidity_increase_pct:.2f}% < {settings.MOMENTUM_LIQUIDITY_INCREASE_PCT}%"
            )
    # If no previous liquidity data, skip this check (pass by default)

    passed = len(reasons) == 0

    if not passed:
        logger.debug(
            "Momentum check FAILED for {}: {}",
            token.symbol, "; ".join(reasons),
        )

    return MomentumResult(
        passed=passed,
        price_change_1m_pct=price_change_1m_pct,
        volume_spike_ratio=volume_spike_ratio,
        buy_sell_ratio=buy_sell_ratio,
        liquidity_increase_pct=liquidity_increase_pct,
        reasons=reasons,
    )
