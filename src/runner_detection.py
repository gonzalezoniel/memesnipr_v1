"""
Runner Detection Mode (v5).

Detects potential large runners (multi-x trades).

Runner conditions:
  - price increase >25%
  - volume increasing
  - holder growth continuing
  - no dev sells detected

When runner mode activates:
  - move stop loss to entry price
  - activate trailing stop (25%)
  - allow trade to continue until trailing stop triggers

Exposes: runner_mode_active, trailing_stop_level.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from .holder_tracker import HolderTracker, get_holder_tracker
from .volume_detector import VolumeDetector, get_volume_detector


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_RUNNER_PRICE_INCREASE_PCT = 25.0   # minimum price increase to trigger
_RUNNER_TRAILING_STOP_PCT = 25.0    # trailing stop percentage
_RUNNER_MIN_VOLUME_MOMENTUM = 3.0   # minimum volume momentum score (0-10)


class RunnerState(BaseModel):
    """State of runner detection for a single position."""
    position_id: str
    token_address: str
    activated: bool = False
    activated_at: Optional[datetime] = None
    entry_price: float = 0.0
    peak_price: float = 0.0
    trailing_stop_level: float = 0.0
    stop_at_entry: bool = False
    price_increase_pct: float = 0.0
    volume_increasing: bool = False
    holder_growing: bool = False
    no_dev_sells: bool = True

    @property
    def is_runner(self) -> bool:
        """Whether runner mode is confirmed active."""
        return self.activated

    @property
    def stop_at_entry_active(self) -> bool:
        """Whether stop-at-entry is active."""
        return self.stop_at_entry

    def check_trailing_stop_triggered(self, current_price: float) -> bool:
        """Check whether the trailing stop has been triggered."""
        if not self.activated or self.trailing_stop_level <= 0:
            return False
        return current_price <= self.trailing_stop_level


class RunnerDetector:
    """
    Monitors open positions and detects potential runners.
    """

    def __init__(
        self,
        holder_tracker: HolderTracker | None = None,
        volume_detector: VolumeDetector | None = None,
    ) -> None:
        self._holder_tracker = holder_tracker or get_holder_tracker()
        self._volume_detector = volume_detector or get_volume_detector()
        self._runner_states: dict[str, RunnerState] = {}

    def check_runner_conditions(
        self,
        position_id: str,
        token_address: str,
        entry_price: float,
        current_price: float,
        peak_price: float,
        dev_sold: bool = False,
    ) -> RunnerState:
        """
        Check if a position qualifies for runner mode.

        Parameters
        ----------
        position_id : str
            Unique position identifier.
        token_address : str
            Token address for volume/holder lookups.
        entry_price : float
            Entry price of the position.
        current_price : float
            Current price of the token.
        peak_price : float
            Peak price since entry.
        dev_sold : bool
            Whether the dev wallet has sold.
        """
        if position_id not in self._runner_states:
            self._runner_states[position_id] = RunnerState(
                position_id=position_id,
                token_address=token_address,
                entry_price=entry_price,
            )

        state = self._runner_states[position_id]

        # Update price tracking
        if current_price > state.peak_price:
            state.peak_price = current_price

        # Calculate price increase from entry
        if entry_price > 0:
            state.price_increase_pct = (
                (current_price - entry_price) / entry_price
            ) * 100.0

        # Check volume momentum
        vol_momentum = self._volume_detector.get_momentum_score(token_address)
        state.volume_increasing = vol_momentum >= _RUNNER_MIN_VOLUME_MOMENTUM

        # Check holder growth
        state.holder_growing = self._holder_tracker.is_growing(token_address)

        # Check dev sells
        state.no_dev_sells = not dev_sold

        # Evaluate runner conditions
        conditions_met = (
            state.price_increase_pct >= _RUNNER_PRICE_INCREASE_PCT
            and state.volume_increasing
            and state.holder_growing
            and state.no_dev_sells
        )

        if conditions_met and not state.activated:
            state.activated = True
            state.activated_at = datetime.now(timezone.utc)
            state.stop_at_entry = True

            logger.info(
                "RUNNER MODE ACTIVATED: {} | price +{:.1f}% | "
                "vol_momentum={:.1f} | holders_growing={} | no_dev_sells={}",
                token_address[:8], state.price_increase_pct,
                vol_momentum, state.holder_growing, state.no_dev_sells,
            )

        # Update trailing stop level
        if state.activated and state.peak_price > 0:
            state.trailing_stop_level = state.peak_price * (
                1.0 - _RUNNER_TRAILING_STOP_PCT / 100.0
            )

        return state

    def should_exit_runner(
        self,
        position_id: str,
        current_price: float,
    ) -> tuple[bool, str]:
        """
        Check if a runner position should be exited.

        Returns (should_exit, reason).
        """
        state = self._runner_states.get(position_id)
        if state is None or not state.activated:
            return False, ""

        # Update peak price
        if current_price > state.peak_price:
            state.peak_price = current_price
            state.trailing_stop_level = state.peak_price * (
                1.0 - _RUNNER_TRAILING_STOP_PCT / 100.0
            )

        # Check trailing stop
        if current_price <= state.trailing_stop_level and state.trailing_stop_level > 0:
            drop_pct = (
                (state.peak_price - current_price) / state.peak_price
            ) * 100.0
            logger.info(
                "RUNNER TRAILING STOP: {} | peak={:.8f} | current={:.8f} | "
                "drop={:.1f}% | trailing_level={:.8f}",
                state.token_address[:8], state.peak_price, current_price,
                drop_pct, state.trailing_stop_level,
            )
            return True, "RUNNER_TRAILING_STOP"

        return False, ""

    def is_runner_active(self, position_id: str) -> bool:
        """Check if runner mode is active for a position."""
        state = self._runner_states.get(position_id)
        return state is not None and state.activated

    def get_runner_state(self, position_id: str) -> Optional[RunnerState]:
        """Get the runner state for a position."""
        return self._runner_states.get(position_id)

    def remove_position(self, position_id: str) -> None:
        """Clean up runner state when a position is closed."""
        self._runner_states.pop(position_id, None)

    def evaluate(
        self,
        position_id: str,
        token_address: str,
        pct_change: float,
        current_price: float,
        entry_price: float,
        peak_price: float,
        volume_detector: VolumeDetector | None = None,
        holder_tracker: HolderTracker | None = None,
        dev_sold: bool = False,
    ) -> RunnerState | None:
        """Evaluate runner conditions and return updated state.

        This is the main entry point used by the engine's _monitor_positions.
        """
        state = self.check_runner_conditions(
            position_id=position_id,
            token_address=token_address,
            entry_price=entry_price,
            current_price=current_price,
            peak_price=peak_price,
            dev_sold=dev_sold,
        )

        # Check if trailing stop triggered
        if state.activated and state.trailing_stop_level > 0:
            if current_price <= state.trailing_stop_level:
                # Mark as triggered by returning state (caller checks)
                # We set a transient flag via a new field approach
                state.trailing_stop_level = state.trailing_stop_level  # keep level
                # Return state - caller checks current_price vs trailing_stop_level
                pass

        return state

    def get_metrics(self) -> dict:
        """Get dashboard metrics."""
        active_runners = sum(
            1 for s in self._runner_states.values() if s.activated
        )
        runner_details = []
        for state in self._runner_states.values():
            if state.activated:
                runner_details.append({
                    "position_id": state.position_id[:8] + "...",
                    "token": state.token_address[:8] + "...",
                    "price_increase_pct": round(state.price_increase_pct, 1),
                    "trailing_stop_level": round(state.trailing_stop_level, 8),
                    "peak_price": round(state.peak_price, 8),
                })

        return {
            "runner_mode_active": active_runners,
            "trailing_stop_level": (
                runner_details[0]["trailing_stop_level"]
                if runner_details else 0.0
            ),
            "active_runners": runner_details,
        }


# Module-level singleton
_detector_instance: RunnerDetector | None = None


def get_runner_detector() -> RunnerDetector:
    """Get or create the singleton RunnerDetector."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = RunnerDetector()
    return _detector_instance
