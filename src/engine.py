# src/engine.py
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from loguru import logger

from .config import settings
from .config import is_kill_switch_enabled, validate_mode_or_raise
from .execution import make_executor
from .features import DefaultFeatureExtractor
from .ingestion import DexScreenerScanner, MockScanner, fetch_current_prices
from .interfaces import Executor, FeatureExtractor, RiskChecker, Scanner, Scorer
from .models import (
    AuditRecord,
    EngineState,
    EngineStatus,
    TokenCandidate,
    Position,
    PositionStatus,
    TradeLogEntry,
    Mode,
    OrderRequest,
)
from .persistence import JsonPersistence
from .risk_checks import ExposureRiskChecker
from .scorer import ConfidenceScorer
from .safety import evaluate_safety
from .risk import (
    compute_position_size_sol,
    reset_daily_if_needed,
    is_trading_halted,
)


class MemeSniprEngine:
    def __init__(
        self,
        scanner: Scanner | None = None,
        feature_extractor: FeatureExtractor | None = None,
        scorer: Scorer | None = None,
        executor: Executor | None = None,
        risk_checker: RiskChecker | None = None,
        persistence: JsonPersistence | None = None,
    ):
        self.persistence = persistence or JsonPersistence()
        self.state: EngineState = self.persistence.load_state()
        self._loop_task: asyncio.Task | None = None

        # Ensure state mode mirrors settings mode on process boot
        self.state.mode = Mode.TEST if str(settings.MODE).upper() == Mode.TEST.value else Mode.LIVE

        self.scanner = scanner or DexScreenerScanner()
        self.feature_extractor = feature_extractor or DefaultFeatureExtractor()
        self.scorer = scorer or ConfidenceScorer()
        self.executor = executor or make_executor(self.state.mode)

        self.positions: dict[str, Position] = {}
        self.risk_checker = risk_checker or ExposureRiskChecker(self.state)
        self._lock = asyncio.Lock()


    def _ensure_mode_ready(self):
        try:
            validate_mode_or_raise()
        except ValueError as exc:
            self.state.status = EngineStatus.HALTED
            self.state.halted_reason = str(exc)
            self.state.last_error = str(exc)
            self.persistence.save_state(self.state)
            raise

    async def start(self):
        if self._loop_task and not self._loop_task.done():
            logger.warning("Engine loop already running")
            return
        self._ensure_mode_ready()
        logger.info("Starting MEMESNIPR engine in mode {}", self.state.mode)
        self._loop_task = asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                async with self._lock:
                    await self._tick()
            except Exception as e:
                logger.exception("Engine tick failed: {}", e)
                self.state.status = EngineStatus.ERROR
                self.state.last_error = str(e)
                self.persistence.save_state(self.state)

            await asyncio.sleep(10)

    async def _tick(self):
        self.state = reset_daily_if_needed(self.state)
        self._update_heartbeat()

        if is_kill_switch_enabled():
            self.state.status = EngineStatus.HALTED
            self.state.halted_reason = "Kill switch enabled"
            self.persistence.save_state(self.state)
            return

        if is_trading_halted(self.state):
            self.state.status = EngineStatus.HALTED
            self.persistence.save_state(self.state)
            return

        await self._monitor_positions()

        if self.state.daily_trades >= settings.MAX_TRADES_PER_DAY:
            logger.info("Daily trade cap reached, idling")
            self.state.status = EngineStatus.IDLE
            self.persistence.save_state(self.state)
            return

        self.state.status = EngineStatus.SCANNING
        self.state.last_scan_at = datetime.now(timezone.utc)
        self.persistence.save_state(self.state)

        candidates = await self.scanner.scan_candidates()
        self._audit_scan_event("SCAN_STARTED", scanned_count=len(candidates))

        for token in candidates:
            await self._process_candidate(token)

        self._audit_scan_event("SCAN_COMPLETED", scanned_count=len(candidates))

        self.state.status = EngineStatus.IDLE
        self.persistence.save_state(self.state)

    def _update_heartbeat(self):
        self.state.last_heartbeat = datetime.now(timezone.utc)

    async def _process_candidate(self, token: TokenCandidate):
        safety = evaluate_safety(token)
        features = self.feature_extractor.extract(token)
        scores = self.scorer.score(token, features)
        score = scores.get("total", 0.0)

        thresholds = {
            "min_score_to_trade": float(settings.MIN_SCORE_TO_TRADE),
            "min_liquidity_usd": float(settings.MIN_LIQUIDITY_USD),
            "max_buy_tax_pct": float(settings.MAX_BUY_TAX_PCT),
            "max_sell_tax_pct": float(settings.MAX_SELL_TAX_PCT),
            "max_risk_score_to_trade": float(settings.MAX_RISK_SCORE_TO_TRADE),
        }
        scores = {**scores, "safety_risk": float(safety.risk_score)}

        if safety.risk_score > settings.MAX_RISK_SCORE_TO_TRADE:
            self._audit(
                token,
                reason_codes=["RISK_SCORE_TOO_HIGH"],
                scores=scores,
                thresholds=thresholds,
                decision="REJECT",
                next_actions=["skip_token", "continue_scanning", "collect_more_token_data"],
            )
            return

        if not safety.passed:
            self._audit(
                token,
                reason_codes=["SAFETY_GATE_REJECT"] + safety.reason_codes,
                scores=scores,
                thresholds=thresholds,
                decision="REJECT",
                next_actions=["skip_token", "continue_scanning", "collect_more_token_data"],
            )
            return

        if score < settings.MIN_SCORE_TO_TRADE:
            self._audit(
                token,
                reason_codes=["LOW_CONFIDENCE_SCORE"],
                scores=scores,
                thresholds=thresholds,
                decision="REJECT",
                next_actions=["skip_token", "continue_scanning"],
            )
            return

        size_sol = compute_position_size_sol(self.state, score)
        await self._execute_order_pipeline(
            OrderRequest(token=token, side="BUY", size_sol=size_sol, score=score),
            thresholds=thresholds,
            scores=scores,
        )

    async def _execute_order_pipeline(
        self,
        order: OrderRequest,
        thresholds: dict[str, float],
        scores: dict[str, float],
    ):
        open_positions_size_sol = sum(
            p.size_sol for p in self.positions.values() if p.status == PositionStatus.OPEN
        )
        if not self.risk_checker.can_open(open_positions_size_sol, order.size_sol):
            logger.warning(
                "Skipping {}: projected exposure too high ({:.6f} SOL open, +{:.6f} SOL)",
                order.token.symbol,
                open_positions_size_sol,
                order.size_sol,
            )
            self._audit(
                order.token,
                reason_codes=["MAX_EXPOSURE_EXCEEDED"],
                scores=scores,
                thresholds=thresholds,
                decision="REJECT",
                next_actions=["reduce_size", "continue_scanning"],
            )
            return

        fill = self.executor.execute(order)
        scores = {
            **scores,
            "fill_size_sol": fill.filled_size_sol,
            "fill_fee_sol": fill.fee_sol,
            "fill_slippage_bps": fill.slippage_bps,
        }
        if not fill.filled:
            self._audit(
                order.token,
                reason_codes=[fill.reason_code],
                scores=scores,
                thresholds=thresholds,
                decision="REJECT",
                next_actions=["continue_scanning"],
            )
            return

        entry_price_usd = order.token.liquidity_usd / max(order.token.volume_usd_5m, 1.0) if order.token.volume_usd_5m > 0 else fill.avg_price

        pos_id = str(uuid.uuid4())
        self.positions[pos_id] = Position(
            id=pos_id,
            token=order.token,
            opened_at=datetime.now(timezone.utc),
            size_sol=fill.filled_size_sol,
            entry_price=fill.avg_price,
            entry_price_usd=entry_price_usd,
        )

        self.state.daily_trades += 1

        logger.success(
            "SIM BUY {} | {:.6f} SOL | score {:.1f}",
            order.token.symbol,
            fill.filled_size_sol,
            order.score,
        )

        self.persistence.append_trades([
            TradeLogEntry(
                id=str(uuid.uuid4()),
                position_id=pos_id,
                token_address=order.token.token_address,
                side="BUY",
                size_sol=fill.filled_size_sol,
                price=fill.avg_price,
                timestamp=datetime.now(timezone.utc),
                note=f"{fill.venue.upper()} BUY score={order.score:.1f} fee={fill.fee_sol:.6f}",
            )
        ])

        self.persistence.save_state(self.state)
        self._audit(
            order.token,
            reason_codes=[fill.reason_code],
            scores=scores,
            thresholds=thresholds,
            decision="PAPER_BUY" if self.state.mode == Mode.TEST else "BUY",
            next_actions=["monitor_position", "apply_tp_sl_logic"],
        )

    def _audit(
        self,
        token: TokenCandidate,
        reason_codes: list[str],
        scores: dict[str, float],
        thresholds: dict[str, float],
        decision: str,
        next_actions: list[str],
    ) -> None:
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            chain=settings.CHAIN,
            token_address=token.token_address,
            token_symbol=token.symbol,
            reason_codes=reason_codes,
            scores=scores,
            thresholds=thresholds,
            decision=decision,
            next_actions=next_actions,
        )
        self.persistence.append_audits([record])
        self._log_structured("decision_audit", record.model_dump(mode="json"))

    async def _monitor_positions(self) -> None:
        open_positions = [
            (pid, pos) for pid, pos in self.positions.items()
            if pos.status == PositionStatus.OPEN
        ]
        if not open_positions:
            return

        token_addrs = list({pos.token.token_address for _, pos in open_positions})
        prices = await fetch_current_prices(token_addrs)
        if not prices:
            return

        now = datetime.now(timezone.utc)
        for pid, pos in open_positions:
            current_price = prices.get(pos.token.token_address)
            if current_price is None or pos.entry_price_usd <= 0:
                continue

            pct_change = ((current_price - pos.entry_price_usd) / pos.entry_price_usd) * 100.0

            exit_reason = None
            if pct_change <= -settings.STOP_LOSS_PCT:
                exit_reason = "STOP_LOSS"
            elif pct_change >= settings.TP3_PCT:
                exit_reason = "TP3_HIT"
                pos.tp3_hit = True
            elif pct_change >= settings.TP2_PCT:
                exit_reason = "TP2_HIT"
                pos.tp2_hit = True
            elif pct_change >= settings.TP1_PCT:
                exit_reason = "TP1_HIT"
                pos.tp1_hit = True

            if exit_reason is None:
                age_minutes = (now - pos.opened_at).total_seconds() / 60.0
                if age_minutes > settings.MAX_TOKEN_AGE_MINUTES:
                    exit_reason = "MAX_AGE_EXIT"

            if exit_reason is not None:
                pnl_sol = pos.size_sol * (pct_change / 100.0)
                pos.status = PositionStatus.CLOSED
                pos.realized_pnl_sol = pnl_sol
                pos.realized_pnl_usd = pnl_sol * current_price
                pos.exit_price_usd = current_price
                pos.exit_reason = exit_reason
                pos.closed_at = now

                if pnl_sol >= 0:
                    self.state.daily_wins += 1
                    self.state.loss_streak = 0
                else:
                    self.state.daily_losses += 1
                    self.state.loss_streak += 1
                self.state.daily_realized_pnl_sol += pnl_sol

                self.persistence.append_trades([TradeLogEntry(
                    id=str(uuid.uuid4()),
                    position_id=pid,
                    token_address=pos.token.token_address,
                    side="SELL",
                    size_sol=pos.size_sol,
                    price=current_price,
                    timestamp=now,
                    realized_pnl_sol=pnl_sol,
                    note=f"{exit_reason} pct={pct_change:+.1f}% pnl={pnl_sol:+.6f} SOL",
                )])

                logger.success(
                    "SIM SELL {} | {} | pct={:+.1f}% | pnl={:+.6f} SOL",
                    pos.token.symbol, exit_reason, pct_change, pnl_sol,
                )

        self.persistence.save_state(self.state)

    def _audit_scan_event(self, event: str, scanned_count: int) -> None:
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            chain=settings.CHAIN,
            token_address="SYSTEM_SCAN",
            token_symbol="SYSTEM",
            reason_codes=[event],
            scores={"scanned_count": float(scanned_count)},
            thresholds={},
            decision=event,
            next_actions=["continue_scanning"] if event == "SCAN_STARTED" else ["idle_until_next_tick"],
        )
        self.persistence.append_audits([record])
        self._log_structured("scan_audit", record.model_dump(mode="json"))

    def _log_structured(self, event: str, payload: dict) -> None:
        logger.info(json.dumps({"event": event, **payload}, default=str))


engine = MemeSniprEngine()
