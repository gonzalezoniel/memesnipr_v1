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

    # Slightly scale risk up for very high confidence, but capped
    if confidence_score >= settings.HIGH_CONFIDENCE_SCORE:
        risk_pct *= 1.3

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
    # For v1 we won't store last_reset_date; add later if needed.
    # No-op placeholder to keep the shape.
    return state
