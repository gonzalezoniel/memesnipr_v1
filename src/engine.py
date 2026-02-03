# src/engine.py
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
    Mode,
)
from .safety import evaluate_safety
from .scoring import compute_confidence_components
from .risk import (
    compute_position_size_sol,
    compute_max_open_exposure_pct,
    is_trading_halted,
    get_wallet_balance_sol,
)
from .storage import load_engine_state, save_engine_state, append_trade_logs


class MemeSniprEngine:
    def __init__(self):
        self.state: EngineState = load_engine_state()

        # 🔑 RESET DAILY COUNTERS IN TEST MODE
        if self.state.mode == Mode.TEST:
            logger.warning("Resetting daily counters (TEST mode)")
            self.state.daily_trades = 0
            self.state.daily_wins = 0
            self.state.daily_losses = 0
            self.state.loss_streak = 0
            self.state.halted_reason = None
            save_engine_state(self.state)

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

            await asyncio.sleep(10)

    async def _tick(self):
        self._update_heartbeat()

        if is_trading_halted(self.state):
            self.state.status = EngineStatus.HALTED
            save_engine_state(self.state)
            return

        if self.state.daily_trades >= settings.MAX_TRADES_PER_DAY:
            logger.info("Daily trade cap reached, idling")
            self.state.status = EngineStatus.IDLE
            save_engine_state(self.state)
            return

        self.state.status = EngineStatus.SCANNING
        save_engine_state(self.state)

        for token in await self.scan_candidates():
            await self._process_candidate(token)

        self.state.status = EngineStatus.IDLE
        save_engine_state(self.state)

    def _update_heartbeat(self):
        self.state.last_heartbeat = datetime.now(timezone.utc)

    async def scan_candidates(self) -> List[TokenCandidate]:
        logger.warning("scan_candidates() CALLED")

        now = datetime.now(timezone.utc)

        return [
            TokenCandidate(
                token_address="FAKE_TEST_MEME",
                symbol="TESTMEME",
                name="Test Meme Token",
                created_at=now,
                liquidity_usd=settings.MIN_LIQUIDITY_USD * 2,
                buy_tax_pct=5.0,
                sell_tax_pct=5.0,
                mint_authority_revoked=True,
                freeze_authority_revoked=True,
                is_honeypot=False,
                can_sell=True,
                buys_5m=60,
                sells_5m=10,
                volume_usd_5m=50000,
                top_holder_pct=8.0,
                holder_count=300,
            )
        ]

    async def _process_candidate(self, token: TokenCandidate):
        if not evaluate_safety(token).passed:
            return

        score = compute_confidence_components(token).total_score
        if score < settings.MIN_SCORE_TO_TRADE:
            return

        size_sol = compute_position_size_sol(self.state, score)
        await self._open_position(token, size_sol, score)

    async def _open_position(self, token: TokenCandidate, size_sol: float, score: float):
        pos_id = str(uuid.uuid4())
        self.positions[pos_id] = Position(
            id=pos_id,
            token=token,
            opened_at=datetime.now(timezone.utc),
            size_sol=size_sol,
            entry_price=1.0,
        )

        self.state.daily_trades += 1

        logger.success(
            "SIM BUY {} | {:.6f} SOL | score {:.1f}",
            token.symbol,
            size_sol,
            score,
        )

        append_trade_logs([
            TradeLogEntry(
                id=str(uuid.uuid4()),
                position_id=pos_id,
                token_address=token.token_address,
                side="BUY",
                size_sol=size_sol,
                price=1.0,
                timestamp=datetime.now(timezone.utc),
                note=f"SIM BUY score={score:.1f}",
            )
        ])

        save_engine_state(self.state)


engine = MemeSniprEngine()
