from datetime import datetime, timedelta, timezone

from src.models import EngineState, Mode
from src.risk import (
    can_open_new_position,
    compute_open_exposure_pct,
    compute_position_size_sol,
    reset_daily_if_needed,
)


def test_position_size_respects_wallet_percentage():
    state = EngineState(mode=Mode.TEST, loss_streak=0)
    size = compute_position_size_sol(state, confidence_score=95)
    assert size <= 0.01
    assert size > 0


def test_daily_counters_reset_on_new_day():
    state = EngineState(
        mode=Mode.TEST,
        daily_trades=5,
        daily_wins=3,
        daily_losses=2,
        loss_streak=2,
        halted_reason="too many losses",
        last_heartbeat=datetime.now(timezone.utc) - timedelta(days=1),
    )
    updated = reset_daily_if_needed(state, now=datetime.now(timezone.utc))
    assert updated.daily_trades == 0
    assert updated.daily_wins == 0
    assert updated.daily_losses == 0
    assert updated.loss_streak == 0
    assert updated.halted_reason is None


def test_exposure_guard_blocks_oversized_position():
    state = EngineState(mode=Mode.TEST)
    open_exposure = compute_open_exposure_pct(state, open_positions_size_sol=0.008)
    assert open_exposure == 0.8
    allowed = can_open_new_position(state, open_positions_size_sol=0.008, new_size_sol=0.004)
    assert not allowed
