"""
Holder Growth Tracker (v5).

Tracks holder count changes using on-chain data.

Signal rule:
  Holder growth >15% within 10 minutes.

Exposes metrics: holder_growth_rate, holder_momentum_events.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from loguru import logger
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_HOLDER_GROWTH_THRESHOLD_PCT = 15.0   # trigger at >15% growth
_HOLDER_WINDOW_SECONDS = 600          # 10-minute window
_MAX_HISTORY_SIZE = 120               # keep last 120 data points per token


class HolderSnapshot(BaseModel):
    """A single holder count observation."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    holder_count: int = 0


class HolderMomentumEvent(BaseModel):
    """Event when holder count grows above threshold."""
    token_address: str
    growth_rate_pct: float = 0.0
    from_holders: int = 0
    to_holders: int = 0
    window_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_boost: float = 1.0  # +1 to signal score per spec


class HolderTracker:
    """
    Monitors holder count changes per token and detects growth momentum.
    """

    def __init__(self) -> None:
        self._history: dict[str, deque[HolderSnapshot]] = {}
        self._momentum_events: list[HolderMomentumEvent] = []

    def record_holders(
        self,
        token_address: str,
        holder_count: int,
    ) -> HolderMomentumEvent | None:
        """
        Record a holder count observation and check for growth spike.

        Returns a HolderMomentumEvent if growth threshold is met.
        """
        now = datetime.now(timezone.utc)
        snapshot = HolderSnapshot(timestamp=now, holder_count=holder_count)

        if token_address not in self._history:
            self._history[token_address] = deque(maxlen=_MAX_HISTORY_SIZE)

        history = self._history[token_address]

        # Prune old entries outside window
        cutoff = now.timestamp() - _HOLDER_WINDOW_SECONDS
        while history and history[0].timestamp.timestamp() < cutoff:
            history.popleft()

        history.append(snapshot)

        if len(history) < 2:
            return None

        # Compare current to earliest in window
        baseline = history[0].holder_count
        if baseline <= 0:
            return None

        growth_pct = ((holder_count - baseline) / baseline) * 100.0

        if growth_pct >= _HOLDER_GROWTH_THRESHOLD_PCT:
            window_elapsed = (now - history[0].timestamp).total_seconds()
            event = HolderMomentumEvent(
                token_address=token_address,
                growth_rate_pct=growth_pct,
                from_holders=baseline,
                to_holders=holder_count,
                window_seconds=window_elapsed,
                timestamp=now,
            )
            self._momentum_events.append(event)
            logger.info(
                "HOLDER GROWTH: {} +{:.1f}% ({} -> {} holders) in {:.0f}s",
                token_address[:8], growth_pct, baseline, holder_count, window_elapsed,
            )
            return event

        return None

    def get_growth_rate(self, token_address: str) -> float:
        """Get the current holder growth rate for a token (percent)."""
        history = self._history.get(token_address)
        if not history or len(history) < 2:
            return 0.0

        baseline = history[0].holder_count
        current = history[-1].holder_count
        if baseline <= 0:
            return 0.0

        return ((current - baseline) / baseline) * 100.0

    def is_growing(self, token_address: str) -> bool:
        """Check if holder count is currently growing for a token."""
        return self.get_growth_rate(token_address) > 0.0

    def get_recent_events(self, limit: int = 50) -> list[HolderMomentumEvent]:
        """Get recent momentum events for the dashboard."""
        return self._momentum_events[-limit:]

    def get_monitored_token_count(self) -> int:
        """Get the number of tokens being monitored."""
        return len(self._history)

    def get_metrics(self) -> dict:
        """Get dashboard metrics."""
        growth_rates = []
        for token_addr in self._history:
            rate = self.get_growth_rate(token_addr)
            if rate != 0.0:
                growth_rates.append(rate)

        avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0.0

        return {
            "holder_growth_rate": round(avg_growth, 2),
            "holder_momentum_events": len(self._momentum_events),
            "tokens_monitored": len(self._history),
        }


# Module-level singleton
_tracker_instance: HolderTracker | None = None


def get_holder_tracker() -> HolderTracker:
    """Get or create the singleton HolderTracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = HolderTracker()
    return _tracker_instance
