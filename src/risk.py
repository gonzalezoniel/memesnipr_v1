from __future__ import annotations

from datetime import datetime, timezone

from .config import settings
from .models import EngineState, Mode


def get_wallet_balance_sol(mode: Mode) -> float:
    """Placeholder: wire this to a real Solana wallet balance call.

    For TEST mode you can keep this as a fixed value you set manually.
    For LIVE mode you should query the Phantom wallet via RPC.
    """
    # TODO: integrate actual wallet balance fetch
    return 1.0  # treat as 1 SOL in TEST until wired


def compute_risk_per_trade_pct(state: EngineState) -> float:
    if state.mode == Mode.TEST:
        base = settings.TEST_RISK_PER_TRADE_PCT
    else:
        base = settings.LIVE_RISK_PER_TRADE_PCT

    # Loss streak auto-throttle
    if state.loss_streak >= settings.LOSS_STREAK_HALVE_RISK:
        base *= 0.5

    return base


def compute_max_open_exposure_pct(state: EngineState) -> float:
    if state.mode == Mode.TEST:
        return settings.TEST_MAX_OPEN_EXPOSURE_PCT
    return settings.LIVE_MAX_OPEN_EXPOSURE_PCT


def compute_position_size_sol(state: EngineState, confidence_score: float) -> float:
    balance = get_wallet_balance_sol(state.mode)
    risk_pct = compute_risk_per_trade_pct(state)

    # Small-by-default sizing for early trust building.
    risk_pct *= 0.5

    # Scale only after repeated clean behavior and realized profits.
    if (
        confidence_score >= settings.HIGH_CONFIDENCE_SCORE
        and state.daily_wins >= 2
        and state.daily_realized_pnl_sol > 0
    ):
        risk_pct *= 1.5

    risk_pct = min(risk_pct, 1.0)  # never more than 1% of wallet

    size_sol = balance * (risk_pct / 100.0)
    return max(size_sol, 0.0001)  # ensure non-zero


def is_trading_halted(state: EngineState) -> bool:
    if state.daily_losses >= settings.DAILY_MAX_LOSSES_HALT:
        return True
    if state.halted_reason:
        return True
    return False


def reset_daily_if_needed(state: EngineState, now: datetime | None = None) -> EngineState:
    """Reset daily counters if date changed.

    This is a simple version; you can extend it with explicit date fields later.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    last_heartbeat = state.last_heartbeat
    if last_heartbeat is None:
        return state

    if now.date() == last_heartbeat.date():
        return state

    state.daily_trades = 0
    state.daily_wins = 0
    state.daily_losses = 0
    state.daily_realized_pnl_sol = 0.0
    state.daily_realized_pnl_usd = 0.0
    state.loss_streak = 0
    state.halted_reason = None

    return state


def compute_open_exposure_pct(state: EngineState, open_positions_size_sol: float) -> float:
    balance = get_wallet_balance_sol(state.mode)
    if balance <= 0:
        return 100.0
    return (open_positions_size_sol / balance) * 100.0


def can_open_new_position(state: EngineState, open_positions_size_sol: float, new_size_sol: float) -> bool:
    projected_exposure_pct = compute_open_exposure_pct(
        state,
        open_positions_size_sol + max(new_size_sol, 0.0),
    )
    return projected_exposure_pct <= compute_max_open_exposure_pct(state)
