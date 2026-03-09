"""
Token Launch Phase Detection (Section 8).

Classifies tokens into lifecycle phases:
  Phase 1: Fresh launch (< 5 min)
  Phase 2: Early breakout (5-30 min, strong momentum)
  Phase 3: First pullback (30 min - 2 hr, retracing)
  Phase 4: Secondary trend (2-8 hr, renewed interest)
  Phase 5: Exhaustion (> 8 hr or declining metrics)

Uses: token age, liquidity growth rate, holder growth rate,
price momentum, retracement depth.

Adjusts trade behavior and position sizing by phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .config import settings
from .models import TokenCandidate


class LaunchPhase(str, Enum):
    FRESH_LAUNCH = "fresh_launch"
    EARLY_BREAKOUT = "early_breakout"
    FIRST_PULLBACK = "first_pullback"
    SECONDARY_TREND = "secondary_trend"
    EXHAUSTION = "exhaustion"


@dataclass
class PhaseDetectionResult:
    """Result of launch phase detection."""
    phase: LaunchPhase
    phase_label: str
    size_multiplier: float
    should_avoid: bool
    confidence: float  # 0-100 confidence in phase classification
    reasons: list[str]


def detect_launch_phase(
    token: TokenCandidate,
    now: datetime | None = None,
) -> PhaseDetectionResult:
    """
    Classify a token into its lifecycle phase and return sizing adjustments.

    Parameters
    ----------
    token : TokenCandidate
        The token being evaluated.
    now : datetime, optional
        Current time (defaults to UTC now).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    age_seconds = max(0.0, (now - token.created_at).total_seconds())
    reasons: list[str] = []

    # Compute momentum indicators
    total_txns = token.buys_5m + token.sells_5m
    buy_ratio = token.buys_5m / max(1, total_txns) if total_txns > 0 else 0.0

    # Liquidity growth indicator
    liq_growth = 0.0
    if token.previous_liquidity > 0:
        liq_growth = (
            (token.liquidity_usd - token.previous_liquidity) / token.previous_liquidity
        ) * 100.0

    # Price momentum indicator
    price_momentum = 0.0
    if token.price_1m_ago > 0 and token.price_usd > 0:
        price_momentum = (
            (token.price_usd - token.price_1m_ago) / token.price_1m_ago
        ) * 100.0

    # Holder growth indicator
    holder_growth = token.holder_growth_rate

    # Retracement depth
    retracement = token.retracement_depth_pct

    # --- Phase Classification ---

    # Phase 5: Exhaustion - declining metrics or very old
    if age_seconds > settings.PHASE_SECONDARY_MAX_AGE_SECONDS:
        reasons.append(f"token_age={age_seconds/3600:.1f}hr_exceeds_secondary_max")
        return PhaseDetectionResult(
            phase=LaunchPhase.EXHAUSTION,
            phase_label="Exhaustion",
            size_multiplier=settings.PHASE_EXHAUSTION_SIZE_MULTIPLIER,
            should_avoid=True,
            confidence=85.0,
            reasons=reasons,
        )

    # Check for exhaustion signals even in younger tokens
    exhaustion_signals = 0
    if buy_ratio < 0.35:
        exhaustion_signals += 1
        reasons.append(f"low_buy_ratio={buy_ratio:.2f}")
    if liq_growth < -20.0:
        exhaustion_signals += 1
        reasons.append(f"liquidity_declining={liq_growth:.1f}%")
    if price_momentum < -10.0:
        exhaustion_signals += 1
        reasons.append(f"price_declining={price_momentum:.1f}%")
    if holder_growth < -1.0:
        exhaustion_signals += 1
        reasons.append(f"holders_declining={holder_growth:.1f}/min")

    if exhaustion_signals >= 3 and age_seconds > settings.PHASE_EARLY_MAX_AGE_SECONDS:
        return PhaseDetectionResult(
            phase=LaunchPhase.EXHAUSTION,
            phase_label="Exhaustion",
            size_multiplier=settings.PHASE_EXHAUSTION_SIZE_MULTIPLIER,
            should_avoid=True,
            confidence=70.0,
            reasons=reasons,
        )

    # Phase 1: Fresh Launch
    if age_seconds <= settings.PHASE_FRESH_MAX_AGE_SECONDS:
        reasons.append(f"fresh_launch_age={age_seconds:.0f}s")
        confidence = 90.0 if age_seconds < 120 else 75.0
        return PhaseDetectionResult(
            phase=LaunchPhase.FRESH_LAUNCH,
            phase_label="Fresh Launch",
            size_multiplier=settings.PHASE_FRESH_SIZE_MULTIPLIER,
            should_avoid=False,
            confidence=confidence,
            reasons=reasons,
        )

    # Phase 2: Early Breakout
    if age_seconds <= settings.PHASE_EARLY_MAX_AGE_SECONDS:
        is_breaking_out = (
            buy_ratio > 0.6
            and (price_momentum > 0 or liq_growth > 0)
        )
        if is_breaking_out:
            reasons.append(f"early_breakout: buy_ratio={buy_ratio:.2f}, momentum={price_momentum:.1f}%")
            return PhaseDetectionResult(
                phase=LaunchPhase.EARLY_BREAKOUT,
                phase_label="Early Breakout",
                size_multiplier=settings.PHASE_EARLY_SIZE_MULTIPLIER,
                should_avoid=False,
                confidence=80.0,
                reasons=reasons,
            )
        # If not breaking out but still young, classify as fresh
        reasons.append(f"early_phase_no_breakout: buy_ratio={buy_ratio:.2f}")
        return PhaseDetectionResult(
            phase=LaunchPhase.FRESH_LAUNCH,
            phase_label="Fresh Launch",
            size_multiplier=settings.PHASE_FRESH_SIZE_MULTIPLIER,
            should_avoid=False,
            confidence=65.0,
            reasons=reasons,
        )

    # Phase 3: First Pullback
    if age_seconds <= settings.PHASE_PULLBACK_MAX_AGE_SECONDS:
        is_pulling_back = retracement > 10.0 or price_momentum < -3.0
        is_recovering = buy_ratio > 0.5 and (liq_growth > -5.0)

        if is_pulling_back and is_recovering:
            reasons.append(
                f"first_pullback_recovery: retracement={retracement:.1f}%, "
                f"buy_ratio={buy_ratio:.2f}"
            )
            return PhaseDetectionResult(
                phase=LaunchPhase.FIRST_PULLBACK,
                phase_label="First Pullback",
                size_multiplier=settings.PHASE_PULLBACK_SIZE_MULTIPLIER,
                should_avoid=False,
                confidence=75.0,
                reasons=reasons,
            )
        elif is_pulling_back:
            reasons.append(f"first_pullback_no_recovery: retracement={retracement:.1f}%")
            return PhaseDetectionResult(
                phase=LaunchPhase.FIRST_PULLBACK,
                phase_label="First Pullback",
                size_multiplier=settings.PHASE_PULLBACK_SIZE_MULTIPLIER * 0.5,
                should_avoid=False,
                confidence=60.0,
                reasons=reasons,
            )
        # Still in early breakout territory
        reasons.append(f"extended_early_breakout: age={age_seconds/60:.0f}min")
        return PhaseDetectionResult(
            phase=LaunchPhase.EARLY_BREAKOUT,
            phase_label="Early Breakout",
            size_multiplier=settings.PHASE_EARLY_SIZE_MULTIPLIER,
            should_avoid=False,
            confidence=55.0,
            reasons=reasons,
        )

    # Phase 4: Secondary Trend
    if age_seconds <= settings.PHASE_SECONDARY_MAX_AGE_SECONDS:
        has_renewed_interest = (
            buy_ratio > 0.55
            and total_txns > 5
            and token.volume_usd_5m > 500
        )
        if has_renewed_interest:
            reasons.append(
                f"secondary_trend: buy_ratio={buy_ratio:.2f}, "
                f"volume=${token.volume_usd_5m:.0f}"
            )
            return PhaseDetectionResult(
                phase=LaunchPhase.SECONDARY_TREND,
                phase_label="Secondary Trend",
                size_multiplier=settings.PHASE_SECONDARY_SIZE_MULTIPLIER,
                should_avoid=False,
                confidence=65.0,
                reasons=reasons,
            )
        reasons.append("secondary_phase_weak_interest")
        return PhaseDetectionResult(
            phase=LaunchPhase.SECONDARY_TREND,
            phase_label="Secondary Trend",
            size_multiplier=settings.PHASE_SECONDARY_SIZE_MULTIPLIER * 0.5,
            should_avoid=False,
            confidence=50.0,
            reasons=reasons,
        )

    # Default: Exhaustion
    reasons.append(f"default_exhaustion: age={age_seconds/3600:.1f}hr")
    return PhaseDetectionResult(
        phase=LaunchPhase.EXHAUSTION,
        phase_label="Exhaustion",
        size_multiplier=settings.PHASE_EXHAUSTION_SIZE_MULTIPLIER,
        should_avoid=True,
        confidence=60.0,
        reasons=reasons,
    )
