"""
Liquidity Injection Detector (v5).

Monitors liquidity pool changes and triggers a signal when
liquidity increases >30% within 5 minutes.

Exposes metrics: liquidity_spike_events, liquidity_growth_rate.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from loguru import logger
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_LIQUIDITY_SPIKE_THRESHOLD_PCT = 30.0   # trigger at >30% increase
_LIQUIDITY_WINDOW_SECONDS = 300         # 5-minute window
_MAX_HISTORY_SIZE = 120                 # keep last 120 data points per token


class LiquiditySnapshot(BaseModel):
    """A single liquidity data point."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    liquidity_usd: float = 0.0


class LiquiditySpikeEvent(BaseModel):
    """Event when liquidity spikes above threshold."""
    token_address: str
    growth_rate_pct: float = 0.0
    from_liquidity: float = 0.0
    to_liquidity: float = 0.0
    window_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_boost: float = 2.0  # +2 to signal score per spec


class LiquidityDetector:
    """
    Monitors liquidity changes per token and detects injection spikes.
    """

    def __init__(self) -> None:
        self._history: dict[str, deque[LiquiditySnapshot]] = {}
        self._spike_events: list[LiquiditySpikeEvent] = []

    def record_liquidity(
        self,
        token_address: str,
        liquidity_usd: float,
    ) -> LiquiditySpikeEvent | None:
        """
        Record a liquidity observation and check for spike.

        Returns a LiquiditySpikeEvent if a spike is detected.
        """
        now = datetime.now(timezone.utc)
        snapshot = LiquiditySnapshot(timestamp=now, liquidity_usd=liquidity_usd)

        if token_address not in self._history:
            self._history[token_address] = deque(maxlen=_MAX_HISTORY_SIZE)

        history = self._history[token_address]

        # Prune old entries outside window
        cutoff = now.timestamp() - _LIQUIDITY_WINDOW_SECONDS
        while history and history[0].timestamp.timestamp() < cutoff:
            history.popleft()

        history.append(snapshot)

        if len(history) < 2:
            return None

        # Compare current to earliest in window
        baseline = history[0].liquidity_usd
        if baseline <= 0:
            return None

        growth_pct = ((liquidity_usd - baseline) / baseline) * 100.0

        if growth_pct >= _LIQUIDITY_SPIKE_THRESHOLD_PCT:
            window_elapsed = (now - history[0].timestamp).total_seconds()
            event = LiquiditySpikeEvent(
                token_address=token_address,
                growth_rate_pct=growth_pct,
                from_liquidity=baseline,
                to_liquidity=liquidity_usd,
                window_seconds=window_elapsed,
                timestamp=now,
            )
            self._spike_events.append(event)
            logger.info(
                "LIQUIDITY SPIKE: {} +{:.1f}% (${:.0f} -> ${:.0f}) in {:.0f}s",
                token_address[:8], growth_pct, baseline, liquidity_usd, window_elapsed,
            )
            return event

        return None

    def check_token(self, token_address: str) -> float:
        """Get the current liquidity growth rate for a token (percent)."""
        history = self._history.get(token_address)
        if not history or len(history) < 2:
            return 0.0

        baseline = history[0].liquidity_usd
        current = history[-1].liquidity_usd
        if baseline <= 0:
            return 0.0

        return ((current - baseline) / baseline) * 100.0

    def get_recent_events(self, limit: int = 50) -> list[LiquiditySpikeEvent]:
        """Get recent spike events for the dashboard."""
        return self._spike_events[-limit:]

    def get_monitored_token_count(self) -> int:
        """Get the number of tokens being monitored."""
        return len(self._history)

    def get_metrics(self) -> dict:
        """Get dashboard metrics."""
        # Compute average growth rate across all tracked tokens
        growth_rates = []
        for token_addr in self._history:
            rate = self.check_token(token_addr)
            if rate != 0.0:
                growth_rates.append(rate)

        avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0.0

        return {
            "liquidity_spike_events": len(self._spike_events),
            "liquidity_growth_rate": round(avg_growth, 2),
            "tokens_monitored": len(self._history),
        }


# Module-level singleton
_detector_instance: LiquidityDetector | None = None


def get_liquidity_detector() -> LiquidityDetector:
    """Get or create the singleton LiquidityDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = LiquidityDetector()
    return _detector_instance
