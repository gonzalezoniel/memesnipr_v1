from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List

from loguru import logger

from .config import settings
from .models import (
    EngineState,
    EngineStatus,
    TokenCandidate,
    Position,
    PositionStatus,
    TradeLogEntry,
)
from .safety import evaluate_safety
from .scoring import compute_confidence_score, compute_confidence_components
from .risk import (
    compute_position_size_sol,
    compute_max_open_exposure_pct,
    is_trading_halted,
)
from .storage import load_engine_state, save_engine_state, append_trade_logs


class MemeSniprEngine:
    """Core MEMESNIPR engine.

    v1 focuses on structure:

    - Periodically "scans" for new tokens (currently stubbed)
    - Runs safety + scoring
    - Decides whether to (simulated) buy
    - Manages profit ladder & stop logic (simulated)
    - Maintains an EngineState heartbeat for the dashboard

    You will later wire real Solana DEX + wallet calls
    into the `scan_candidates` and `execute_buy/sell` methods.
    """

    def __init__(self):
        self.state: EngineState = load_engine_state()
        self.positions: dict[str, Position] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        logger.info("Starting MEMESNIPR engine in mode {}", self.state.mode)
        asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                async with self._lock:
                    await self._tick()
            except Exception as e:
                logger.exception("Engine tick failed: {}", e)
                self.state.status = EngineStatus.ERROR
                self.state.last_error = str(e)
                save_engine_state(self.state)

            await asyncio.sleep(10)  # main heartbeat interval

    async def _tick(self):
        self._update_heartbeat()

        if is_trading_halted(self.state):
            self.state.status = EngineStatus.HALTED
            save_engine_state(self.state)
            return

        self.state.status = EngineStatus.SCANNING
        save_engine_state(self.state)

        # 1) Scan for new opportunities (stub for now)
        candidates = await self.scan_candidates()

        # 2) Evaluate each candidate
        for token in candidates:
            await self._process_candidate(token)

        # 3) Manage open positions (stubbed logic)
        await self._update_positions()

        self.state.status = EngineStatus.IDLE
        save_engine_state(self.state)

    def _update_heartbeat(self):
        self.state.last_heartbeat = datetime.now(timezone.utc)

    async def scan_candidates(self) -> List[TokenCandidate]:
        """Stubbed scanner.

        Replace this with actual integration to Solana DEX / Raydium new pools.
        For now, it returns an empty list so the engine is safe to run while
        you deploy & confirm the dashboard.
        """
        return []

    async def _process_candidate(self, token: TokenCandidate) -> None:
        from .risk import get_wallet_balance_sol  # lazy import to avoid cycles

        logger.info("Evaluating token {}", token.symbol)

        safety = evaluate_safety(token)
        if not safety.passed:
            logger.info("Token {} failed safety: {}", token.symbol, "; ".join(safety.reasons))
            return

        components = compute_confidence_components(token)
        score = components.total_score

        if score < settings.MIN_SCORE_TO_TRADE:
            logger.info(
                "Token {} score too low: {:.1f} < {}",
                token.symbol,
                score,
                settings.MIN_SCORE_TO_TRADE,
            )
            return

        # Check exposure limit
        wallet_balance = get_wallet_balance_sol(self.state.mode)
        open_exposure = sum(p.size_sol * p.entry_price for p in self.positions.values() if p.status == PositionStatus.OPEN)
        max_exposure = wallet_balance * (compute_max_open_exposure_pct(self.state) / 100.0)

        if open_exposure >= max_exposure:
            logger.info("Exposure limit reached, skipping new position")
            return

        # Compute position size
        size_sol = compute_position_size_sol(self.state, score)
        await self._open_position(token, size_sol, components.total_score)

    async def _open_position(self, token: TokenCandidate, size_sol: float, score: float):
        """Simulated BUY; later this will actually call the wallet / DEX.

        For now we just create an in-memory + logged position at a fake price.
        """
        fake_price = 1.0  # TODO: replace with real on-chain price
        pos_id = str(uuid.uuid4())
        position = Position(
            id=pos_id,
            token=token,
            opened_at=datetime.now(timezone.utc),
            size_sol=size_sol,
            entry_price=fake_price,
        )
        self.positions[pos_id] = position

        self.state.daily_trades += 1
        logger.info("Opened simulated position {} on {} size {:.6f} SOL", pos_id, token.symbol, size_sol)

        trade_log = TradeLogEntry(
            id=str(uuid.uuid4()),
            position_id=pos_id,
            token_address=token.token_address,
            side="BUY",
            size_sol=size_sol,
            price=fake_price,
            timestamp=datetime.now(timezone.utc),
            note=f"Simulated BUY, score={score:.1f}",
        )
        append_trade_logs([trade_log])
        save_engine_state(self.state)

    async def _update_positions(self):
        """Placeholder for TP/SL/TSL logic.

        In v1 this does nothing other than keep the structure in place.
        Later you will:
        - Fetch current price
        - Apply stop loss, TPs, trailing stop
        - Compute realized PnL
        - Close positions + log SELL trades
        - Update daily wins/losses, loss_streak
        """
        return


engine = MemeSniprEngine()
