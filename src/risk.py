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


def compute_position_size_sol(
    state: EngineState,
    confidence_score: float,
    social_signal_score: float = 0.0,
    wallet_cluster_signal: bool = False,
    liquidity_usd: float = 0.0,
    phase_multiplier: float = 1.0,
    trap_score: float = 0.0,
) -> float:
    """v3 Adaptive Position Sizing (Section 9).

    Position size adapts based on:
    - confidence score (technical + social + wallet)
    - social signal strength
    - wallet cluster signals
    - liquidity depth
    - token lifecycle phase (via phase_multiplier)
    - current drawdown / recent performance
    - trap score (reduce size for suspicious tokens)

    Strong signals -> 1.4x base size
    Moderate signals -> 0.8x size
    Weak signals -> 0.35x size
    """
    if confidence_score < settings.MIN_SCORE_TO_TRADE:
        return 0.0  # skip trade

    base_sol = settings.POSITION_SIZE_BASE_SOL

    # Determine signal strength multiplier
    if confidence_score >= 85:
        signal_multiplier = settings.POSITION_SIZE_STRONG_MULTIPLIER
    elif confidence_score >= 78:
        signal_multiplier = settings.POSITION_SIZE_MODERATE_MULTIPLIER
    else:
        signal_multiplier = settings.POSITION_SIZE_WEAK_MULTIPLIER

    # Wallet cluster boost
    if wallet_cluster_signal:
        signal_multiplier *= 1.3  # +30% for cluster signal

    # Social signal boost
    if social_signal_score >= 7.0:
        signal_multiplier *= 1.15
    elif social_signal_score >= 5.0:
        signal_multiplier *= 1.05

    # Apply phase multiplier
    signal_multiplier *= phase_multiplier

    # Reduce size for high trap scores
    if trap_score > 30.0:
        trap_reduction = max(0.5, 1.0 - (trap_score - 30.0) / 60.0)
        signal_multiplier *= trap_reduction

    size_sol = base_sol * signal_multiplier

    # Loss streak auto-throttle: halve size after streak
    if state.loss_streak >= settings.LOSS_STREAK_HALVE_RISK:
        size_sol *= 0.5

    # Progressive daily-loss throttle
    if state.daily_losses > 0:
        loss_factor = max(0.3, 1.0 - (state.daily_losses * 0.15))
        size_sol *= loss_factor

    # Consecutive loss throttle (v3)
    if state.consecutive_losses >= 5:
        size_sol *= 0.3
    elif state.consecutive_losses >= 3:
        size_sol *= 0.5

    # Liquidity impact cap: never exceed safe liquidity impact
    if liquidity_usd > 0:
        max_size_by_liq = (
            liquidity_usd * settings.POSITION_SIZE_MAX_LIQUIDITY_IMPACT_PCT / 100.0
        )
        # Convert USD limit to approximate SOL (rough: assume ~$150/SOL)
        max_sol_by_liq = max_size_by_liq / 150.0
        size_sol = min(size_sol, max_sol_by_liq)

    return max(size_sol, 0.0001)  # ensure non-zero


def is_trading_halted(state: EngineState) -> bool:
    if state.daily_losses >= settings.DAILY_MAX_LOSSES_HALT:
        return True
    if state.halted_reason:
        return True
    return False


def check_trade_frequency(state: EngineState, open_position_count: int) -> tuple[bool, str]:
    """v3 Trade Frequency Controls (Section 10).

    Returns (can_trade, reason) tuple.

    Includes loss streak pause system:
    - 3 consecutive losses -> pause 10 minutes
    - 5 consecutive losses -> pause 30 minutes
    """
    # Max open positions
    if open_position_count >= settings.MAX_OPEN_POSITIONS:
        return False, f"max_open_positions ({settings.MAX_OPEN_POSITIONS}) reached"

    # Max trades per hour
    if state.hourly_trades >= settings.MAX_TRADES_PER_HOUR:
        return False, f"max_trades_per_hour ({settings.MAX_TRADES_PER_HOUR}) reached"

    now = datetime.now(timezone.utc)

    # v3: Loss streak pause system (Section 10)
    if state.pause_until is not None:
        if now < state.pause_until:
            remaining = (state.pause_until - now).total_seconds()
            return False, f"loss_streak_pause ({remaining:.0f}s remaining)"
        else:
            # Pause expired, clear it
            state.pause_until = None

    # v3: Check consecutive losses and apply pauses
    if state.consecutive_losses >= 5:
        if state.last_loss_at is not None:
            from datetime import timedelta
            pause_end = state.last_loss_at + timedelta(
                seconds=settings.LOSS_STREAK_PAUSE_5_SECONDS
            )
            if now < pause_end:
                state.pause_until = pause_end
                remaining = (pause_end - now).total_seconds()
                return False, f"5_loss_streak_pause ({remaining:.0f}s remaining)"
    elif state.consecutive_losses >= 3:
        if state.last_loss_at is not None:
            from datetime import timedelta
            pause_end = state.last_loss_at + timedelta(
                seconds=settings.LOSS_STREAK_PAUSE_3_SECONDS
            )
            if now < pause_end:
                state.pause_until = pause_end
                remaining = (pause_end - now).total_seconds()
                return False, f"3_loss_streak_pause ({remaining:.0f}s remaining)"

    # Cooldown after loss
    if state.last_loss_at is not None:
        elapsed = (now - state.last_loss_at).total_seconds()
        if elapsed < settings.COOLDOWN_AFTER_LOSS_SECONDS:
            remaining = settings.COOLDOWN_AFTER_LOSS_SECONDS - elapsed
            return False, f"cooldown_after_loss ({remaining:.0f}s remaining)"

    return True, ""


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
