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
            self.state.status = EngineStatus.IDLE
            save_engine_state(self.state)
            return

        self.state.status = EngineStatus.SCANNING
        save_engine_state(self.state)

        candidates = await self.scan_candidates()

        for token in candidates:
            await self._process_candidate(token)

        self.state.status = EngineStatus.IDLE
        save_engine_state(self.state)

    def _update_heartbeat(self):
        self.state.last_heartbeat = datetime.now(timezone.utc)

    async def scan_candidates(self) -> List[TokenCandidate]:
        logger.warning("scan_candidates() CALLED")

        now = datetime.now(timezone.utc)

        fake = TokenCandidate(
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
            buys_5m=50,
            sells_5m=5,
            volume_usd_5m=50000,
            top_holder_pct=8.0,
            holder_count=300,
        )

        return [fake]

    async def _process_candidate(self, token: TokenCandidate):
        safety = evaluate_safety(token)
        if not safety.passed:
            return

        score = compute_confidence_components(token).total_score
        if score < settings.MIN_SCORE_TO_TRADE:
            return

        # 🔑 SIM MODE: ignore exposure limits entirely
        if self.state.mode == Mode.LIVE:
            wallet_balance = get_wallet_balance_sol(self.state.mode)
            open_exposure = sum(
                p.size_sol * p.entry_price
                for p in self.positions.values()
                if p.status == PositionStatus.OPEN
            )
            max_exposure = wallet_balance * (
                compute_max_open_exposure_pct(self.state) / 100.0
            )
            if open_exposure >= max_exposure:
                return

        size_sol = compute_position_size_sol(self.state, score)
        await self._open_position(token, size_sol, score)

    async def _open_position(self, token: TokenCandidate, size_sol: float, score: float):
        pos_id = str(uuid.uuid4())
        position = Position(
            id=pos_id,
            token=token,
            opened_at=datetime.now(timezone.utc),
            size_sol=size_sol,
            entry_price=1.0,
        )

        self.positions[pos_id] = position
        self.state.daily_trades += 1

        logger.success(
            "SIM BUY {} | size {:.6f} SOL | score {:.1f}",
            token.symbol,
            size_sol,
            score,
        )

        trade = TradeLogEntry(
            id=str(uuid.uuid4()),
            position_id=pos_id,
            token_address=token.token_address,
            side="BUY",
            size_sol=size_sol,
            price=1.0,
            timestamp=datetime.now(timezone.utc),
            note=f"SIM BUY score={score:.1f}",
        )

        append_trade_logs([trade])
        save_engine_state(self.state)


engine = MemeSniprEngine()
