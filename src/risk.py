from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from loguru import logger

from .config import settings
from .models import EngineState, Mode

_balance_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL = 30.0


def get_wallet_balance_sol(mode: Mode) -> float:
    if mode == Mode.TEST:
        pubkey = settings.TEST_WALLET_PUBLIC_KEY
    else:
        pubkey = settings.LIVE_WALLET_PUBLIC_KEY

    if not pubkey or not pubkey.strip():
        return 1.0

    now = time.monotonic()
    cached = _balance_cache.get(pubkey)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        resp = httpx.post(
            str(settings.SOL_RPC_URL),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [pubkey],
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        lamports = resp.json().get("result", {}).get("value", 0)
        balance = lamports / 1_000_000_000
        if balance <= 0:
            return 1.0
        _balance_cache[pubkey] = (balance, now)
        return balance
    except Exception as exc:
        logger.warning("Wallet balance fetch failed, using fallback: {}", exc)
        return 1.0


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

    # Confidence-proportional sizing: higher score → bigger position.
    # Floor at 0.6x for low-confidence entries, scale up to 1.4x for high.
    conf_multiplier = 0.6 + 0.8 * min(confidence_score / 100.0, 1.0)
    risk_pct *= conf_multiplier

    # Win-streak momentum: scale up after consecutive profitable trades.
    # 1 win = base, 2 wins + green day = 1.3x, 3+ wins = 1.5x
    if state.daily_wins >= 3 and state.daily_realized_pnl_sol > 0:
        risk_pct *= 1.5
    elif state.daily_wins >= 1 and state.daily_realized_pnl_sol > 0:
        risk_pct *= 1.3

    # Hard cap: never risk more than 5% of wallet on a single position
    risk_pct = min(risk_pct, 5.0)

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
