"""
Signal Scoring Engine (v5).

Creates a composite scoring system for each token.

Scoring rules:
  Smart wallet cluster  +3
  Volume spike          +2
  Liquidity injection   +2
  Holder acceleration   +1
  Social sentiment      +1

Trade execution rules:
  Score >= 5  -> trade
  Score >= 7  -> larger position size
  Score >= 8  -> enable runner detection mode

Exposes: signal_score, signal_components.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from .smart_wallet_intelligence import (
    SmartWalletIntelligence,
    WalletClusterEvent,
    get_smart_wallet_intelligence,
)
from .liquidity_detector import LiquidityDetector, get_liquidity_detector
from .volume_detector import VolumeDetector, get_volume_detector
from .holder_tracker import HolderTracker, get_holder_tracker


# ---------------------------------------------------------------------------
# Score thresholds
# ---------------------------------------------------------------------------
SCORE_TRADE_THRESHOLD = 5
SCORE_LARGE_POSITION_THRESHOLD = 7
SCORE_RUNNER_MODE_THRESHOLD = 8

# Component weights
WEIGHT_SMART_WALLET_CLUSTER = 3.0
WEIGHT_VOLUME_SPIKE = 2.0
WEIGHT_LIQUIDITY_INJECTION = 2.0
WEIGHT_HOLDER_ACCELERATION = 1.0
WEIGHT_SOCIAL_SENTIMENT = 1.0

MAX_SIGNAL_SCORE = 9.0  # 3 + 2 + 2 + 1 + 1


class SignalComponents(BaseModel):
    """Breakdown of signal score components."""
    smart_wallet_cluster: float = 0.0
    volume_spike: float = 0.0
    liquidity_injection: float = 0.0
    holder_acceleration: float = 0.0
    social_sentiment: float = 0.0


class SignalScoringResult(BaseModel):
    """Result of the v5 signal scoring engine."""
    signal_score: float = 0.0
    total_score: float = 0.0  # alias for signal_score (used by engine)
    components: SignalComponents = Field(default_factory=SignalComponents)
    should_trade: bool = False
    larger_position: bool = False
    runner_mode: bool = False
    entry_reasons: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SignalScoringEngine:
    """
    v5 Composite signal scoring engine.

    Combines signals from all detectors into a single score.
    """

    def __init__(
        self,
        wallet_intel: SmartWalletIntelligence | None = None,
        liquidity_detector: LiquidityDetector | None = None,
        volume_detector: VolumeDetector | None = None,
        holder_tracker: HolderTracker | None = None,
    ) -> None:
        self._wallet_intel = wallet_intel or get_smart_wallet_intelligence()
        self._liquidity_detector = liquidity_detector or get_liquidity_detector()
        self._volume_detector = volume_detector or get_volume_detector()
        self._holder_tracker = holder_tracker or get_holder_tracker()
        self._recent_results: list[SignalScoringResult] = []

    def score_token(
        self,
        token_address: str,
        liquidity_usd: float = 0.0,
        volume_usd: float = 0.0,
        holder_count: int = 0,
        social_sentiment_score: float = 0.0,
    ) -> SignalScoringResult:
        """
        Score a token using all v5 signal detectors.

        Parameters
        ----------
        token_address : str
            The token to score.
        liquidity_usd : float
            Current liquidity in USD.
        volume_usd : float
            Current volume observation.
        holder_count : int
            Current holder count.
        social_sentiment_score : float
            Social sentiment score (0-10 scale, from SMS engine).
        """
        components = SignalComponents()
        entry_reasons: list[str] = []

        # 1. Smart Wallet Cluster (+3)
        cluster_event = self._wallet_intel.check_token_cluster(token_address)
        if cluster_event is not None:
            components.smart_wallet_cluster = WEIGHT_SMART_WALLET_CLUSTER
            entry_reasons.append(
                f"smart_wallet_cluster ({cluster_event.wallet_count} wallets)"
            )

        # 2. Volume Spike (+2)
        volume_event = self._volume_detector.record_volume(token_address, volume_usd)
        if volume_event is not None:
            components.volume_spike = WEIGHT_VOLUME_SPIKE
            entry_reasons.append(
                f"volume_spike ({volume_event.spike_ratio:.1f}x)"
            )
        else:
            # Check existing momentum even without a new event
            momentum = self._volume_detector.get_momentum_score(token_address)
            if momentum >= 7.0:  # Strong momentum
                components.volume_spike = WEIGHT_VOLUME_SPIKE
                entry_reasons.append(f"volume_momentum ({momentum:.1f}/10)")

        # 3. Liquidity Injection (+2)
        liq_event = self._liquidity_detector.record_liquidity(token_address, liquidity_usd)
        if liq_event is not None:
            components.liquidity_injection = WEIGHT_LIQUIDITY_INJECTION
            entry_reasons.append(
                f"liquidity_injection (+{liq_event.growth_rate_pct:.1f}%)"
            )
        else:
            # Check existing growth rate
            liq_growth = self._liquidity_detector.check_token(token_address)
            if liq_growth >= 30.0:
                components.liquidity_injection = WEIGHT_LIQUIDITY_INJECTION
                entry_reasons.append(f"liquidity_growth (+{liq_growth:.1f}%)")

        # 4. Holder Acceleration (+1)
        holder_event = self._holder_tracker.record_holders(token_address, holder_count)
        if holder_event is not None:
            components.holder_acceleration = WEIGHT_HOLDER_ACCELERATION
            entry_reasons.append(
                f"holder_growth (+{holder_event.growth_rate_pct:.1f}%)"
            )
        else:
            holder_growth = self._holder_tracker.get_growth_rate(token_address)
            if holder_growth >= 15.0:
                components.holder_acceleration = WEIGHT_HOLDER_ACCELERATION
                entry_reasons.append(f"holder_momentum (+{holder_growth:.1f}%)")

        # 5. Social Sentiment (+1)
        if social_sentiment_score >= 5.0:  # Positive social sentiment
            components.social_sentiment = WEIGHT_SOCIAL_SENTIMENT
            entry_reasons.append(f"social_sentiment ({social_sentiment_score:.1f})")

        # Compute total score
        signal_score = (
            components.smart_wallet_cluster
            + components.volume_spike
            + components.liquidity_injection
            + components.holder_acceleration
            + components.social_sentiment
        )

        # Determine trade actions
        should_trade = signal_score >= SCORE_TRADE_THRESHOLD
        larger_position = signal_score >= SCORE_LARGE_POSITION_THRESHOLD
        runner_mode = signal_score >= SCORE_RUNNER_MODE_THRESHOLD

        if should_trade:
            logger.info(
                "SIGNAL SCORE {}: {:.0f}/9 | components={} | larger={} | runner={}",
                token_address[:8], signal_score,
                ", ".join(entry_reasons), larger_position, runner_mode,
            )

        result = SignalScoringResult(
            signal_score=signal_score,
            total_score=signal_score,
            components=components,
            should_trade=should_trade,
            larger_position=larger_position,
            runner_mode=runner_mode,
            entry_reasons=entry_reasons,
        )
        self._recent_results.append(result)
        # Keep only last 100 results
        if len(self._recent_results) > 100:
            self._recent_results = self._recent_results[-100:]
        return result

    def compute_score(
        self,
        token_address: str,
        wallet_intelligence: SmartWalletIntelligence | None = None,
        liquidity_detector: LiquidityDetector | None = None,
        volume_detector: VolumeDetector | None = None,
        holder_tracker: HolderTracker | None = None,
        social_score: float = 0.0,
        liquidity_usd: float = 0.0,
        volume_usd: float = 0.0,
        holder_count: int = 0,
    ) -> SignalScoringResult:
        """Convenience wrapper for engine integration."""
        return self.score_token(
            token_address=token_address,
            social_sentiment_score=social_score,
            liquidity_usd=liquidity_usd,
            volume_usd=volume_usd,
            holder_count=holder_count,
        )

    def get_recent_scores(self) -> list[dict]:
        """Get recent scoring results for dashboard."""
        return [
            {
                "signal_score": r.signal_score,
                "should_trade": r.should_trade,
                "runner_mode": r.runner_mode,
                "components": r.components.model_dump(),
                "timestamp": r.timestamp.isoformat(),
            }
            for r in self._recent_results[-20:]
        ]

    def get_active_signal_count(self) -> int:
        """Count recent results that qualified for trading."""
        return sum(1 for r in self._recent_results[-50:] if r.should_trade)


# Module-level singleton
_engine_instance: SignalScoringEngine | None = None


def get_signal_scoring_engine() -> SignalScoringEngine:
    """Get or create the singleton SignalScoringEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SignalScoringEngine()
    return _engine_instance
