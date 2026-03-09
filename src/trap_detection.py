"""
Market Microstructure Trap Detection (Section 7).

Scores tokens based on red-flag indicators:
- Abnormal wick behavior
- Single wallet volume dominance
- Fake volume spikes
- Shallow liquidity pools
- Abnormal slippage risk
- Rapid sell pressure after micro pumps
- Wallet churn without real holder growth

If trap_score exceeds threshold, block the trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from .config import settings
from .models import TokenCandidate


@dataclass
class TrapDetectionResult:
    """Result of trap detection analysis."""
    trap_score: float = 0.0
    is_trap: bool = False
    signals: list[str] = field(default_factory=list)
    component_scores: dict[str, float] = field(default_factory=dict)


def detect_trap(token: TokenCandidate) -> TrapDetectionResult:
    """
    Analyze a token for market microstructure trap signals.

    Returns a TrapDetectionResult with a composite trap_score (0-100).
    If trap_score >= TRAP_SCORE_THRESHOLD, the trade should be blocked.
    """
    result = TrapDetectionResult()
    components: dict[str, float] = {}

    # --- 1. Abnormal Wick Behavior (high wick_ratio = manipulation) ---
    wick_score = 0.0
    if token.wick_ratio > 0:
        if token.wick_ratio > 5.0:
            wick_score = 100.0
            result.signals.append(f"extreme_wick_ratio={token.wick_ratio:.1f}")
        elif token.wick_ratio > 3.0:
            wick_score = 70.0
            result.signals.append(f"high_wick_ratio={token.wick_ratio:.1f}")
        elif token.wick_ratio > 2.0:
            wick_score = 40.0
            result.signals.append(f"elevated_wick_ratio={token.wick_ratio:.1f}")
        else:
            wick_score = max(0.0, (token.wick_ratio - 1.0) * 40.0)
    components["wick"] = wick_score

    # --- 2. Single Wallet Volume Dominance ---
    single_wallet_score = 0.0
    if token.single_wallet_volume_pct > 0:
        if token.single_wallet_volume_pct > 60.0:
            single_wallet_score = 100.0
            result.signals.append(
                f"single_wallet_dominance={token.single_wallet_volume_pct:.0f}%"
            )
        elif token.single_wallet_volume_pct > 40.0:
            single_wallet_score = 70.0
            result.signals.append(
                f"high_single_wallet_volume={token.single_wallet_volume_pct:.0f}%"
            )
        elif token.single_wallet_volume_pct > 25.0:
            single_wallet_score = 40.0
        else:
            single_wallet_score = max(0.0, (token.single_wallet_volume_pct - 10.0) * 2.67)
    components["single_wallet"] = single_wallet_score

    # --- 3. Fake Volume Spikes ---
    fake_volume_score = 0.0
    if token.volume_avg_5m > 0 and token.volume_1m > 0:
        volume_ratio = token.volume_1m / token.volume_avg_5m
        # Very high spike with low holder count = suspect
        if volume_ratio > 10.0 and token.holder_count < 50:
            fake_volume_score = 90.0
            result.signals.append(
                f"suspicious_volume_spike={volume_ratio:.1f}x_low_holders={token.holder_count}"
            )
        elif volume_ratio > 8.0 and token.holder_count < 100:
            fake_volume_score = 60.0
            result.signals.append("high_volume_spike_low_holders")
        elif volume_ratio > 5.0:
            # High volume ratio alone is somewhat suspicious
            buy_ratio = token.buys_5m / max(1, token.buys_5m + token.sells_5m)
            if buy_ratio < 0.3:
                fake_volume_score = 50.0
                result.signals.append("volume_spike_sell_dominated")
    elif token.volume_usd_5m > 0 and token.holder_count < 20:
        # High volume with very few holders
        vol_per_holder = token.volume_usd_5m / max(1, token.holder_count)
        if vol_per_holder > 5000:
            fake_volume_score = 60.0
            result.signals.append(f"concentrated_volume_per_holder=${vol_per_holder:.0f}")
    components["fake_volume"] = fake_volume_score

    # --- 4. Shallow Liquidity Pools ---
    shallow_liq_score = 0.0
    if token.liquidity_usd > 0:
        if token.liquidity_usd < 10_000:
            shallow_liq_score = 90.0
            result.signals.append(f"very_shallow_liquidity=${token.liquidity_usd:.0f}")
        elif token.liquidity_usd < 25_000:
            shallow_liq_score = 50.0
            result.signals.append(f"shallow_liquidity=${token.liquidity_usd:.0f}")
        elif token.liquidity_usd < 50_000:
            shallow_liq_score = 20.0
        # Check volume-to-liquidity ratio (high ratio = slippage risk)
        if token.volume_usd_5m > 0:
            vol_liq_ratio = token.volume_usd_5m / token.liquidity_usd
            if vol_liq_ratio > 2.0:
                shallow_liq_score = min(100.0, shallow_liq_score + 30.0)
                result.signals.append(f"high_vol_to_liq_ratio={vol_liq_ratio:.1f}")
    else:
        shallow_liq_score = 100.0
        result.signals.append("no_liquidity_data")
    components["shallow_liquidity"] = shallow_liq_score

    # --- 5. Abnormal Slippage Risk ---
    slippage_score = 0.0
    if token.liquidity_usd > 0 and token.volume_usd_5m > 0:
        # Estimated slippage: if volume >> liquidity, slippage is high
        impact_ratio = token.volume_usd_5m / (token.liquidity_usd * 5.0)
        if impact_ratio > 1.0:
            slippage_score = min(100.0, impact_ratio * 50.0)
            if slippage_score > 50:
                result.signals.append(f"high_slippage_risk={impact_ratio:.2f}")
    components["slippage"] = slippage_score

    # --- 6. Rapid Sell Pressure After Micro Pumps ---
    sell_pressure_score = 0.0
    if token.sell_pressure_after_pump > 0:
        if token.sell_pressure_after_pump > 0.7:
            sell_pressure_score = 90.0
            result.signals.append("extreme_sell_pressure_after_pump")
        elif token.sell_pressure_after_pump > 0.5:
            sell_pressure_score = 60.0
            result.signals.append("high_sell_pressure_after_pump")
        elif token.sell_pressure_after_pump > 0.3:
            sell_pressure_score = 30.0
    else:
        # Use buy/sell ratio as proxy
        total_txns = token.buys_5m + token.sells_5m
        if total_txns > 10:
            sell_ratio = token.sells_5m / total_txns
            if sell_ratio > 0.6:
                sell_pressure_score = 40.0
                result.signals.append(f"high_sell_ratio={sell_ratio:.2f}")
    components["sell_pressure"] = sell_pressure_score

    # --- 7. Wallet Churn Without Real Holder Growth ---
    churn_score = 0.0
    if token.holder_growth_rate >= 0:
        total_txns = token.buys_5m + token.sells_5m
        if total_txns > 20 and token.holder_growth_rate < 0.1:
            churn_score = 70.0
            result.signals.append("high_txns_no_holder_growth")
        elif total_txns > 10 and token.holder_growth_rate < 0.5:
            churn_score = 40.0
        elif total_txns > 5 and token.holder_count < 30:
            churn_score = 30.0
    components["churn"] = churn_score

    # --- Compute weighted trap score ---
    result.trap_score = (
        settings.TRAP_WICK_WEIGHT * components.get("wick", 0.0)
        + settings.TRAP_SINGLE_WALLET_WEIGHT * components.get("single_wallet", 0.0)
        + settings.TRAP_FAKE_VOLUME_WEIGHT * components.get("fake_volume", 0.0)
        + settings.TRAP_SHALLOW_LIQ_WEIGHT * components.get("shallow_liquidity", 0.0)
        + settings.TRAP_SLIPPAGE_WEIGHT * components.get("slippage", 0.0)
        + settings.TRAP_SELL_PRESSURE_WEIGHT * components.get("sell_pressure", 0.0)
        + settings.TRAP_CHURN_WEIGHT * components.get("churn", 0.0)
    )
    result.trap_score = min(max(result.trap_score, 0.0), 100.0)
    result.is_trap = result.trap_score >= settings.TRAP_SCORE_THRESHOLD
    result.component_scores = components

    if result.is_trap:
        logger.warning(
            "TRAP DETECTED for {}: score={:.1f}, signals={}",
            token.symbol, result.trap_score, result.signals,
        )
    else:
        logger.debug(
            "Trap check for {}: score={:.1f} (threshold={:.0f})",
            token.symbol, result.trap_score, settings.TRAP_SCORE_THRESHOLD,
        )

    return result
