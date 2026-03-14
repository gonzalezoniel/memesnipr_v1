"""
Volume Acceleration Detector (v5).

Calculates short-term volume momentum.

Signal rule:
  3-minute volume > 3x the average volume of the previous 15 minutes.

Exposes metrics: volume_spike_events, momentum_score.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from loguru import logger
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SHORT_WINDOW_SECONDS = 180     # 3 minutes
_LONG_WINDOW_SECONDS = 900      # 15 minutes
_SPIKE_MULTIPLIER = 3.0         # 3x threshold
_MAX_HISTORY_SIZE = 300          # keep last 300 data points per token


class VolumeSnapshot(BaseModel):
    """A single volume observation."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    volume_usd: float = 0.0


class VolumeSpikeEvent(BaseModel):
    """Event when short-term volume spikes above threshold."""
    token_address: str
    short_volume: float = 0.0
    long_avg_volume: float = 0.0
    spike_ratio: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_boost: float = 2.0  # +2 to signal score per spec


class VolumeDetector:
    """
    Monitors volume per token and detects acceleration spikes.
    """

    def __init__(self) -> None:
        self._history: dict[str, deque[VolumeSnapshot]] = {}
        self._spike_events: list[VolumeSpikeEvent] = []

    def record_volume(
        self,
        token_address: str,
        volume_usd: float,
    ) -> VolumeSpikeEvent | None:
        """
        Record a volume observation and check for spike.

        Returns a VolumeSpikeEvent if volume acceleration is detected.
        """
        now = datetime.now(timezone.utc)
        snapshot = VolumeSnapshot(timestamp=now, volume_usd=volume_usd)

        if token_address not in self._history:
            self._history[token_address] = deque(maxlen=_MAX_HISTORY_SIZE)

        history = self._history[token_address]

        # Prune entries older than the long window
        cutoff = now.timestamp() - _LONG_WINDOW_SECONDS
        while history and history[0].timestamp.timestamp() < cutoff:
            history.popleft()

        history.append(snapshot)

        if len(history) < 2:
            return None

        # Compute short window volume (last 3 minutes)
        short_cutoff = now.timestamp() - _SHORT_WINDOW_SECONDS
        short_snapshots = [
            s for s in history if s.timestamp.timestamp() >= short_cutoff
        ]
        short_volume = sum(s.volume_usd for s in short_snapshots)

        # Compute long window average (previous 15 minutes, excluding last 3)
        long_snapshots = [
            s for s in history if s.timestamp.timestamp() < short_cutoff
        ]

        if not long_snapshots:
            return None

        long_total = sum(s.volume_usd for s in long_snapshots)
        # Normalize long window to 3-minute equivalent for fair comparison
        long_window_actual = max(
            (short_cutoff - history[0].timestamp.timestamp()), 1.0
        )
        long_avg_per_3min = (long_total / long_window_actual) * _SHORT_WINDOW_SECONDS

        if long_avg_per_3min <= 0:
            return None

        spike_ratio = short_volume / long_avg_per_3min

        if spike_ratio >= _SPIKE_MULTIPLIER:
            event = VolumeSpikeEvent(
                token_address=token_address,
                short_volume=short_volume,
                long_avg_volume=long_avg_per_3min,
                spike_ratio=spike_ratio,
                timestamp=now,
            )
            self._spike_events.append(event)
            logger.info(
                "VOLUME SPIKE: {} {:.1f}x (3min=${:.0f} vs 15min_avg=${:.0f})",
                token_address[:8], spike_ratio, short_volume, long_avg_per_3min,
            )
            return event

        return None

    def get_momentum_score(self, token_address: str) -> float:
        """Get the current momentum score for a token (spike ratio, 0-10 scale)."""
        history = self._history.get(token_address)
        if not history or len(history) < 2:
            return 0.0

        now = datetime.now(timezone.utc)
        short_cutoff = now.timestamp() - _SHORT_WINDOW_SECONDS

        short_snapshots = [
            s for s in history if s.timestamp.timestamp() >= short_cutoff
        ]
        long_snapshots = [
            s for s in history if s.timestamp.timestamp() < short_cutoff
        ]

        short_volume = sum(s.volume_usd for s in short_snapshots)
        if not long_snapshots:
            return 0.0

        long_total = sum(s.volume_usd for s in long_snapshots)
        long_window_actual = max(
            (short_cutoff - history[0].timestamp.timestamp()), 1.0
        )
        long_avg_per_3min = (long_total / long_window_actual) * _SHORT_WINDOW_SECONDS

        if long_avg_per_3min <= 0:
            return 0.0

        ratio = short_volume / long_avg_per_3min
        # Normalize to 0-10 scale: ratio of 3x = 10
        return min(ratio / _SPIKE_MULTIPLIER * 10.0, 10.0)

    def get_recent_events(self, limit: int = 50) -> list[VolumeSpikeEvent]:
        """Get recent spike events for the dashboard."""
        return self._spike_events[-limit:]

    def get_monitored_token_count(self) -> int:
        """Get the number of tokens being monitored."""
        return len(self._history)

    def get_metrics(self) -> dict:
        """Get dashboard metrics."""
        # Compute average momentum across tracked tokens
        scores = []
        for token_addr in self._history:
            score = self.get_momentum_score(token_addr)
            if score > 0:
                scores.append(score)

        avg_momentum = sum(scores) / len(scores) if scores else 0.0

        return {
            "volume_spike_events": len(self._spike_events),
            "momentum_score": round(avg_momentum, 2),
            "tokens_monitored": len(self._history),
        }


# Module-level singleton
_detector_instance: VolumeDetector | None = None


def get_volume_detector() -> VolumeDetector:
    """Get or create the singleton VolumeDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = VolumeDetector()
    return _detector_instance
