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
from .scoring import compute_confidence_components
from .risk import (
    compute_position_size_sol,
    compute_max_open_exposure_pct,
    is_trading_halted,
    get_wallet_balance_sol,
)
from .storage import load_engine_state, save_engine_state, append_trade_logs


class MemeSniprEngine:
    """
    Core MEMESNIPR engine.

    v1 focuses on structure + simulation:

    - Background loop every 10s
    - "Scans" for tokens (currently simulated)
    - Runs safety + scoring
    - Decides whether to (simulated) buy
    - Maintains EngineState heartbeat for the dashboard

    Later you will:
    - Replace `scan_candidates()` with a real Solana DEX feed
    - Wire `_open_position` / `_update_positions` to real wallet & prices
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
            if self.state.status != EngineStatus.HALTED:
                logger.warning(
                    "Trading halted. daily_losses={}, halted_reason={}",
                    self.state.daily_losses,
                    self.state.halted_reason,
                )
            self.state.status = EngineStatus.HALTED
            save_engine_state(self.state)
            return

        # Respect a max trades per day guard as well
        if self.state.daily_trades >= settings.MAX_TRADES_PER_DAY:
            if self.state.status != EngineStatus.IDLE:
                logger.info(
                    "Max trades per day reached ({}). Engine idling.",
                    settings.MAX_TRADES_PER_DAY,
                )
            self.state.status = EngineStatus.IDLE
            save_engine_state(self.state)
            return

        self.state.status = EngineStatus.SCANNING
        save_engine_state(self.state)

        # 1) Scan for new opportunities
        candidates = await self.scan_candidates()

        # 2) Evaluate each candidate
        for token in candidates:
            await self._process_candidate(token)

        # 3) Manage open positions (stub)
        await self._update_positions()

        self.state.status = EngineStatus.IDLE
        save_engine_state(self.state)

    def _update_heartbeat(self):
        self.state.last_heartbeat = datetime.now(timezone.utc)

    async def scan_candidates(self) -> List[TokenCandidate]:
        """
        Simulated scanner for v1.

        This is here to prove the full pipeline is working:
        - You see logs in Render
        - `daily_trades` increments
        - `data/trades_log.jsonl` fills up

        Later, replace this with:
        - Raydium / Solana DEX feed
        - Dexscreener / BirdEye / etc.
        """
        # If we've already hit the trade cap, don't even simulate
        if self.state.daily_trades >= settings.MAX_TRADES_PER_DAY:
            logger.debug("scan_candidates: daily trade cap reached, returning no candidates.")
            return []

        now = datetime.now(timezone.utc)

        # Simulated meme token that should pass your safety & scoring rules
        fake = TokenCandidate(
            token_address="FAKE_TEST_MEME",
            symbol="TESTMEME",
            name="Test Meme Token",
            created_at=now,  # brand new
            liquidity_usd=settings.MIN_LIQUIDITY_USD * 2,  # safely above min
            buy_tax_pct=min(settings.MAX_BUY_TAX_PCT - 1.0, settings.MAX_BUY_TAX_PCT),
            sell_tax_pct=min(settings.MAX_SELL_TAX_PCT - 1.0, settings.MAX_SELL_TAX_PCT),
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            deployer_address=None,
            buys_5m=60,
            sells_5m=10,
            volume_usd_5m=settings.MIN_LIQUIDITY_USD * 0.5,
            top_holder_pct=8.0,
            holder_count=250,
        )

        logger.info("Scanner produced 1 simulated candidate: {}", fake.symbol)
        return [fake]

    async def _process_candidate(self, token: TokenCandidate) -> None:
        logger.info("Evaluating token {}", token.symbol)

        # Safety filter
        safety = evaluate_safety(token)
        if not safety.passed:
            logger.info(
                "Token {} failed safety: {}",
                token.symbol,
                "; ".join(safety.reasons) or "unknown reason",
            )
            return

        # Confidence scoring
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

        # Respect max trades per day
        if self.state.daily_trades >= settings.MAX_TRADES_PER_DAY:
            logger.info(
                "Max trades per day reached ({}), skipping new position.",
                settings.MAX_TRADES_PER_DAY,
            )
            return

        # Exposure limit
        wallet_balance = get_wallet_balance_sol(self.state.mode)
        open_exposure = sum(
            p.size_sol * p.entry_price
            for p in self.positions.values()
            if p.status == PositionStatus.OPEN
        )
        max_exposure = wallet_balance * (compute_max_open_exposure_pct(self.state) / 100.0)

        if open_exposure >= max_exposure:
            logger.info(
                "Exposure limit reached: open_exposure={:.6f}, max_exposure={:.6f}. Skipping.",
                open_exposure,
                max_exposure,
            )
            return

        # Position sizing
        size_sol = compute_position_size_sol(self.state, score)
        await self._open_position(token, size_sol, score)

    async def _open_position(self, token: TokenCandidate, size_sol: float, score: float):
        """
        Simulated BUY; later this will call the real wallet / DEX.

        For now we:
        - create a Position at a fake price
        - bump daily_trades
        - append a TradeLogEntry
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
        logger.info(
            "Opened simulated position {} on {} size {:.6f} SOL (score {:.1f})",
            pos_id,
            token.symbol,
            size_sol,
            score,
        )

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
        """
        Placeholder for TP/SL/TSL logic.

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
