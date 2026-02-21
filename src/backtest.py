from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

from loguru import logger
from pydantic import BaseModel, Field

from .broker import PaperBroker
from .config import settings
from .features import DefaultFeatureExtractor
from .interfaces import FeatureExtractor, Scorer
from .models import (
    EngineState,
    EngineStatus,
    Mode,
    OrderRequest,
    TokenCandidate,
)
from .risk import (
    can_open_new_position,
    compute_position_size_sol,
    is_trading_halted,
)
from .safety import evaluate_safety
from .scorer import ConfidenceScorer


class PriceTick(BaseModel):
    offset_seconds: float
    price_usd: float


class BacktestScenario(BaseModel):
    token: TokenCandidate
    price_ticks: list[PriceTick] = Field(default_factory=list)
    label: str = ""


class TradeResult(BaseModel):
    scenario_label: str
    token_symbol: str
    token_address: str
    decision: str
    rejection_reasons: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    safety_risk_score: float = 0.0
    entry_price_usd: float = 0.0
    exit_price_usd: float = 0.0
    size_sol: float = 0.0
    pnl_sol: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: Optional[str] = None
    hold_seconds: float = 0.0


class BacktestReport(BaseModel):
    scenarios_total: int = 0
    trades_taken: int = 0
    trades_rejected: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl_sol: float = 0.0
    avg_pnl_sol: float = 0.0
    max_drawdown_sol: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    results: list[TradeResult] = Field(default_factory=list)

    def format_summary(self) -> str:
        lines = [
            "=" * 60,
            "MEMESNIPR BACKTEST REPORT",
            "=" * 60,
            f"Scenarios:        {self.scenarios_total}",
            f"Trades Taken:     {self.trades_taken}",
            f"Trades Rejected:  {self.trades_rejected}",
            f"Wins:             {self.wins}",
            f"Losses:           {self.losses}",
            f"Win Rate:         {self.win_rate:.1f}%",
            f"Total PnL:        {self.total_pnl_sol:+.6f} SOL",
            f"Avg PnL/Trade:    {self.avg_pnl_sol:+.6f} SOL",
            f"Max Drawdown:     {self.max_drawdown_sol:.6f} SOL",
            f"Profit Factor:    {self.profit_factor:.2f}",
            f"Sharpe Ratio:     {self.sharpe_ratio:.2f}",
            "=" * 60,
            "",
            "PER-SCENARIO BREAKDOWN:",
            "-" * 60,
        ]

        for r in self.results:
            if r.decision == "REJECT":
                lines.append(
                    f"  [{r.scenario_label}] {r.token_symbol} -> REJECT "
                    f"(reasons: {', '.join(r.rejection_reasons[:3])})"
                )
            else:
                pnl_sign = "+" if r.pnl_sol >= 0 else ""
                lines.append(
                    f"  [{r.scenario_label}] {r.token_symbol} -> {r.decision} | "
                    f"PnL: {pnl_sign}{r.pnl_sol:.6f} SOL ({r.pnl_pct:+.1f}%) | "
                    f"Exit: {r.exit_reason or 'N/A'} | "
                    f"Hold: {r.hold_seconds:.0f}s"
                )

        lines.append("-" * 60)
        return "\n".join(lines)


class BacktestRunner:
    def __init__(
        self,
        feature_extractor: FeatureExtractor | None = None,
        scorer: Scorer | None = None,
        broker_seed: int = 42,
        wallet_balance_sol: float = 1.0,
    ):
        self._feature_extractor = feature_extractor or DefaultFeatureExtractor()
        self._scorer = scorer or ConfidenceScorer()
        self._broker = PaperBroker(seed=broker_seed)
        self._wallet_balance_sol = wallet_balance_sol
        self._open_exposure_sol = 0.0

    def run(self, scenarios: list[BacktestScenario]) -> BacktestReport:
        state = EngineState(
            status=EngineStatus.IDLE,
            mode=Mode.TEST,
            last_heartbeat=datetime.now(timezone.utc),
        )

        results: list[TradeResult] = []
        self._open_exposure_sol = 0.0

        def _fixed_balance(_mode: Mode) -> float:
            return self._wallet_balance_sol

        for idx, scenario in enumerate(scenarios):
            label = scenario.label or f"scenario_{idx}"
            with patch("src.risk.get_wallet_balance_sol", _fixed_balance):
                result = self._run_scenario(state, scenario, label)
            results.append(result)

            if result.decision not in ("REJECT",):
                if result.pnl_sol >= 0:
                    state.daily_wins += 1
                    state.loss_streak = 0
                else:
                    state.daily_losses += 1
                    state.loss_streak += 1
                state.daily_trades += 1
                state.daily_realized_pnl_sol += result.pnl_sol

                if is_trading_halted(state):
                    logger.info("Trading halted after scenario {}", label)
                    for remaining_idx in range(idx + 1, len(scenarios)):
                        remaining_label = scenarios[remaining_idx].label or f"scenario_{remaining_idx}"
                        results.append(TradeResult(
                            scenario_label=remaining_label,
                            token_symbol=scenarios[remaining_idx].token.symbol,
                            token_address=scenarios[remaining_idx].token.token_address,
                            decision="REJECT",
                            rejection_reasons=["TRADING_HALTED"],
                        ))
                    break

        return self._build_report(results, len(scenarios))

    def _run_scenario(
        self,
        state: EngineState,
        scenario: BacktestScenario,
        label: str,
    ) -> TradeResult:
        token = scenario.token

        safety = evaluate_safety(token)
        if safety.risk_score > settings.MAX_RISK_SCORE_TO_TRADE:
            return TradeResult(
                scenario_label=label,
                token_symbol=token.symbol,
                token_address=token.token_address,
                decision="REJECT",
                rejection_reasons=["RISK_SCORE_TOO_HIGH"],
                safety_risk_score=safety.risk_score,
            )

        if not safety.passed:
            return TradeResult(
                scenario_label=label,
                token_symbol=token.symbol,
                token_address=token.token_address,
                decision="REJECT",
                rejection_reasons=["SAFETY_GATE_REJECT"] + safety.reason_codes,
                safety_risk_score=safety.risk_score,
            )

        features = self._feature_extractor.extract(token)
        scores = self._scorer.score(token, features)
        score = scores.get("total", 0.0)

        if score < settings.MIN_SCORE_TO_TRADE:
            return TradeResult(
                scenario_label=label,
                token_symbol=token.symbol,
                token_address=token.token_address,
                decision="REJECT",
                rejection_reasons=["LOW_CONFIDENCE_SCORE"],
                confidence_score=score,
                safety_risk_score=safety.risk_score,
            )

        size_sol = compute_position_size_sol(state, score)

        if not can_open_new_position(state, self._open_exposure_sol, size_sol):
            return TradeResult(
                scenario_label=label,
                token_symbol=token.symbol,
                token_address=token.token_address,
                decision="REJECT",
                rejection_reasons=["MAX_EXPOSURE_EXCEEDED"],
                confidence_score=score,
                safety_risk_score=safety.risk_score,
            )

        order = OrderRequest(token=token, side="BUY", size_sol=size_sol, score=score)
        fill = self._broker.send_order(order)

        if not fill.filled:
            return TradeResult(
                scenario_label=label,
                token_symbol=token.symbol,
                token_address=token.token_address,
                decision="REJECT",
                rejection_reasons=[fill.reason_code],
                confidence_score=score,
                safety_risk_score=safety.risk_score,
            )

        self._open_exposure_sol += fill.filled_size_sol

        entry_price_usd = token.price_usd if token.price_usd > 0 else 1.0

        exit_price_usd, exit_reason, hold_seconds = self._simulate_position(
            entry_price_usd, scenario.price_ticks
        )

        if exit_price_usd is not None and entry_price_usd > 0:
            pct_change = ((exit_price_usd - entry_price_usd) / entry_price_usd) * 100.0
            pnl_sol = fill.filled_size_sol * (pct_change / 100.0)
        else:
            pct_change = 0.0
            pnl_sol = 0.0
            exit_price_usd = entry_price_usd
            exit_reason = exit_reason or "NO_PRICE_DATA"

        self._open_exposure_sol = max(0.0, self._open_exposure_sol - fill.filled_size_sol)

        return TradeResult(
            scenario_label=label,
            token_symbol=token.symbol,
            token_address=token.token_address,
            decision="PAPER_BUY",
            confidence_score=score,
            safety_risk_score=safety.risk_score,
            entry_price_usd=entry_price_usd,
            exit_price_usd=exit_price_usd,
            size_sol=fill.filled_size_sol,
            pnl_sol=pnl_sol,
            pnl_pct=pct_change,
            exit_reason=exit_reason,
            hold_seconds=hold_seconds,
        )

    def _simulate_position(
        self,
        entry_price_usd: float,
        price_ticks: list[PriceTick],
    ) -> tuple[float | None, str | None, float]:
        if not price_ticks:
            return None, "NO_PRICE_DATA", 0.0

        max_age_seconds = settings.MAX_TOKEN_AGE_MINUTES * 60.0

        for tick in price_ticks:
            if entry_price_usd <= 0:
                continue

            pct = ((tick.price_usd - entry_price_usd) / entry_price_usd) * 100.0

            if pct <= -settings.STOP_LOSS_PCT:
                return tick.price_usd, "STOP_LOSS", tick.offset_seconds

            if pct >= settings.TP3_PCT:
                return tick.price_usd, "TP3_HIT", tick.offset_seconds

            if pct >= settings.TP2_PCT:
                return tick.price_usd, "TP2_HIT", tick.offset_seconds

            if pct >= settings.TP1_PCT:
                return tick.price_usd, "TP1_HIT", tick.offset_seconds

            if tick.offset_seconds >= max_age_seconds:
                return tick.price_usd, "MAX_AGE_EXIT", tick.offset_seconds

        last = price_ticks[-1]
        return last.price_usd, "END_OF_DATA", last.offset_seconds

    def _build_report(
        self,
        results: list[TradeResult],
        total_scenarios: int,
    ) -> BacktestReport:
        traded = [r for r in results if r.decision != "REJECT"]
        rejected = [r for r in results if r.decision == "REJECT"]

        wins = [r for r in traded if r.pnl_sol >= 0]
        losses = [r for r in traded if r.pnl_sol < 0]

        total_pnl = sum(r.pnl_sol for r in traded)
        avg_pnl = total_pnl / len(traded) if traded else 0.0

        gross_profit = sum(r.pnl_sol for r in wins)
        gross_loss = abs(sum(r.pnl_sol for r in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 0.0
        )

        equity_curve: list[float] = []
        running = 0.0
        for r in traded:
            running += r.pnl_sol
            equity_curve.append(running)

        max_dd = 0.0
        peak = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd

        pnl_values = [r.pnl_sol for r in traded]
        if len(pnl_values) >= 2:
            mean_pnl = statistics.mean(pnl_values)
            std_pnl = statistics.stdev(pnl_values)
            sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        win_rate = (len(wins) / len(traded) * 100.0) if traded else 0.0

        if math.isinf(profit_factor):
            profit_factor = 999.99

        return BacktestReport(
            scenarios_total=total_scenarios,
            trades_taken=len(traded),
            trades_rejected=len(rejected),
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            total_pnl_sol=total_pnl,
            avg_pnl_sol=avg_pnl,
            max_drawdown_sol=max_dd,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            results=results,
        )


def generate_synthetic_scenarios(count: int = 20) -> list[BacktestScenario]:
    now = datetime.now(timezone.utc)
    scenarios: list[BacktestScenario] = []

    scenarios.append(BacktestScenario(
        label="strong_pump_clean_token",
        token=TokenCandidate(
            token_address="SYN_PUMP_001",
            symbol="PUMP",
            name="Pump Token",
            created_at=now,
            liquidity_usd=800_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=120,
            sells_5m=15,
            volume_usd_5m=90_000,
            top_holder_pct=4.0,
            holder_count=500,
            price_usd=0.001,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.00105),
            PriceTick(offset_seconds=60, price_usd=0.00112),
            PriceTick(offset_seconds=120, price_usd=0.00118),
            PriceTick(offset_seconds=180, price_usd=0.00125),
            PriceTick(offset_seconds=300, price_usd=0.00135),
            PriceTick(offset_seconds=600, price_usd=0.00160),
            PriceTick(offset_seconds=900, price_usd=0.00170),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="rug_pull",
        token=TokenCandidate(
            token_address="SYN_RUG_001",
            symbol="RUG",
            name="Rug Token",
            created_at=now,
            liquidity_usd=600_000,
            buy_tax_pct=2.0,
            sell_tax_pct=2.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=80,
            sells_5m=20,
            volume_usd_5m=60_000,
            top_holder_pct=6.0,
            holder_count=300,
            price_usd=0.005,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.0052),
            PriceTick(offset_seconds=60, price_usd=0.0048),
            PriceTick(offset_seconds=120, price_usd=0.0040),
            PriceTick(offset_seconds=180, price_usd=0.0030),
            PriceTick(offset_seconds=300, price_usd=0.0010),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="honeypot_reject",
        token=TokenCandidate(
            token_address="SYN_HONEY_001",
            symbol="HONEY",
            name="Honeypot Token",
            created_at=now,
            liquidity_usd=500_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=True,
            can_sell=False,
            buys_5m=200,
            sells_5m=5,
            volume_usd_5m=100_000,
            top_holder_pct=3.0,
            holder_count=600,
            price_usd=0.01,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="low_liquidity_reject",
        token=TokenCandidate(
            token_address="SYN_LOWLIQ_001",
            symbol="LOWLIQ",
            name="Low Liq Token",
            created_at=now,
            liquidity_usd=5_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=50,
            sells_5m=10,
            volume_usd_5m=2_000,
            top_holder_pct=8.0,
            holder_count=100,
            price_usd=0.0001,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="mint_active_reject",
        token=TokenCandidate(
            token_address="SYN_MINT_001",
            symbol="MINTY",
            name="Mint Active Token",
            created_at=now,
            liquidity_usd=700_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=False,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=100,
            sells_5m=20,
            volume_usd_5m=80_000,
            top_holder_pct=5.0,
            holder_count=300,
            price_usd=0.002,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="slow_bleed",
        token=TokenCandidate(
            token_address="SYN_BLEED_001",
            symbol="BLEED",
            name="Slow Bleed Token",
            created_at=now,
            liquidity_usd=650_000,
            buy_tax_pct=2.0,
            sell_tax_pct=2.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=70,
            sells_5m=25,
            volume_usd_5m=55_000,
            top_holder_pct=7.0,
            holder_count=250,
            price_usd=0.003,
        ),
        price_ticks=[
            PriceTick(offset_seconds=60, price_usd=0.00298),
            PriceTick(offset_seconds=120, price_usd=0.00290),
            PriceTick(offset_seconds=300, price_usd=0.00280),
            PriceTick(offset_seconds=600, price_usd=0.00270),
            PriceTick(offset_seconds=900, price_usd=0.00265),
            PriceTick(offset_seconds=1200, price_usd=0.00260),
            PriceTick(offset_seconds=1800, price_usd=0.00255),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="tp1_hit_exit",
        token=TokenCandidate(
            token_address="SYN_TP1_001",
            symbol="TP1",
            name="TP1 Token",
            created_at=now,
            liquidity_usd=750_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=90,
            sells_5m=15,
            volume_usd_5m=70_000,
            top_holder_pct=5.0,
            holder_count=350,
            price_usd=0.002,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.00205),
            PriceTick(offset_seconds=60, price_usd=0.00210),
            PriceTick(offset_seconds=120, price_usd=0.00220),
            PriceTick(offset_seconds=180, price_usd=0.00230),
            PriceTick(offset_seconds=300, price_usd=0.00232),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="tp2_hit_exit",
        token=TokenCandidate(
            token_address="SYN_TP2_001",
            symbol="TP2",
            name="TP2 Token",
            created_at=now,
            liquidity_usd=900_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=110,
            sells_5m=12,
            volume_usd_5m=95_000,
            top_holder_pct=4.0,
            holder_count=450,
            price_usd=0.001,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.00105),
            PriceTick(offset_seconds=60, price_usd=0.00115),
            PriceTick(offset_seconds=120, price_usd=0.00125),
            PriceTick(offset_seconds=180, price_usd=0.00130),
            PriceTick(offset_seconds=300, price_usd=0.00132),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="whale_concentration_reject",
        token=TokenCandidate(
            token_address="SYN_WHALE_001",
            symbol="WHALE",
            name="Whale Token",
            created_at=now - timedelta(seconds=60),
            liquidity_usd=600_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=50,
            sells_5m=5,
            volume_usd_5m=40_000,
            top_holder_pct=40.0,
            holder_count=30,
            price_usd=0.005,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="volatile_recovery",
        token=TokenCandidate(
            token_address="SYN_VOLATILE_001",
            symbol="VOLA",
            name="Volatile Token",
            created_at=now,
            liquidity_usd=700_000,
            buy_tax_pct=1.5,
            sell_tax_pct=1.5,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=95,
            sells_5m=18,
            volume_usd_5m=75_000,
            top_holder_pct=5.0,
            holder_count=400,
            price_usd=0.004,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.0038),
            PriceTick(offset_seconds=60, price_usd=0.0035),
            PriceTick(offset_seconds=120, price_usd=0.0042),
            PriceTick(offset_seconds=180, price_usd=0.0048),
            PriceTick(offset_seconds=300, price_usd=0.0055),
            PriceTick(offset_seconds=600, price_usd=0.0065),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="high_tax_reject",
        token=TokenCandidate(
            token_address="SYN_HIGHTAX_001",
            symbol="TAXED",
            name="High Tax Token",
            created_at=now,
            liquidity_usd=600_000,
            buy_tax_pct=15.0,
            sell_tax_pct=15.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=60,
            sells_5m=10,
            volume_usd_5m=50_000,
            top_holder_pct=5.0,
            holder_count=200,
            price_usd=0.003,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="sideways_max_age_exit",
        token=TokenCandidate(
            token_address="SYN_SIDE_001",
            symbol="SIDE",
            name="Sideways Token",
            created_at=now,
            liquidity_usd=650_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=75,
            sells_5m=20,
            volume_usd_5m=60_000,
            top_holder_pct=6.0,
            holder_count=280,
            price_usd=0.002,
        ),
        price_ticks=[
            PriceTick(offset_seconds=60, price_usd=0.00201),
            PriceTick(offset_seconds=300, price_usd=0.00199),
            PriceTick(offset_seconds=600, price_usd=0.00202),
            PriceTick(offset_seconds=1200, price_usd=0.00198),
            PriceTick(offset_seconds=1800, price_usd=0.00200),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="mega_pump_tp3",
        token=TokenCandidate(
            token_address="SYN_MEGA_001",
            symbol="MEGA",
            name="Mega Pump",
            created_at=now,
            liquidity_usd=1_200_000,
            buy_tax_pct=0.5,
            sell_tax_pct=0.5,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=200,
            sells_5m=10,
            volume_usd_5m=150_000,
            top_holder_pct=3.0,
            holder_count=800,
            price_usd=0.001,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.00110),
            PriceTick(offset_seconds=60, price_usd=0.00125),
            PriceTick(offset_seconds=120, price_usd=0.00140),
            PriceTick(offset_seconds=180, price_usd=0.00155),
            PriceTick(offset_seconds=300, price_usd=0.00165),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="freeze_active_reject",
        token=TokenCandidate(
            token_address="SYN_FREEZE_001",
            symbol="FREEZE",
            name="Freeze Active Token",
            created_at=now,
            liquidity_usd=700_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=False,
            is_honeypot=False,
            can_sell=True,
            buys_5m=80,
            sells_5m=15,
            volume_usd_5m=65_000,
            top_holder_pct=5.0,
            holder_count=300,
            price_usd=0.003,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="low_score_reject",
        token=TokenCandidate(
            token_address="SYN_LOWSCORE_001",
            symbol="LSCORE",
            name="Low Score Token",
            created_at=now,
            liquidity_usd=55_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=10,
            sells_5m=30,
            volume_usd_5m=3_000,
            top_holder_pct=25.0,
            holder_count=50,
            price_usd=0.0005,
        ),
        price_ticks=[],
    ))

    scenarios.append(BacktestScenario(
        label="quick_stop_loss",
        token=TokenCandidate(
            token_address="SYN_QSL_001",
            symbol="QSL",
            name="Quick Stop Loss",
            created_at=now,
            liquidity_usd=600_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=85,
            sells_5m=15,
            volume_usd_5m=65_000,
            top_holder_pct=5.0,
            holder_count=320,
            price_usd=0.01,
        ),
        price_ticks=[
            PriceTick(offset_seconds=15, price_usd=0.0098),
            PriceTick(offset_seconds=30, price_usd=0.0092),
            PriceTick(offset_seconds=45, price_usd=0.0084),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="gradual_climb_tp1",
        token=TokenCandidate(
            token_address="SYN_CLIMB_001",
            symbol="CLIMB",
            name="Gradual Climb",
            created_at=now,
            liquidity_usd=700_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=100,
            sells_5m=18,
            volume_usd_5m=80_000,
            top_holder_pct=4.0,
            holder_count=400,
            price_usd=0.005,
        ),
        price_ticks=[
            PriceTick(offset_seconds=60, price_usd=0.00510),
            PriceTick(offset_seconds=120, price_usd=0.00530),
            PriceTick(offset_seconds=240, price_usd=0.00555),
            PriceTick(offset_seconds=360, price_usd=0.00570),
            PriceTick(offset_seconds=480, price_usd=0.00580),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="double_top_stop_loss",
        token=TokenCandidate(
            token_address="SYN_DTOP_001",
            symbol="DTOP",
            name="Double Top",
            created_at=now,
            liquidity_usd=650_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=90,
            sells_5m=20,
            volume_usd_5m=70_000,
            top_holder_pct=5.0,
            holder_count=350,
            price_usd=0.008,
        ),
        price_ticks=[
            PriceTick(offset_seconds=30, price_usd=0.00850),
            PriceTick(offset_seconds=60, price_usd=0.00880),
            PriceTick(offset_seconds=120, price_usd=0.00860),
            PriceTick(offset_seconds=180, price_usd=0.00820),
            PriceTick(offset_seconds=300, price_usd=0.00750),
            PriceTick(offset_seconds=600, price_usd=0.00670),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="small_gain_end_of_data",
        token=TokenCandidate(
            token_address="SYN_SMALL_001",
            symbol="SMALL",
            name="Small Gain",
            created_at=now,
            liquidity_usd=600_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=80,
            sells_5m=15,
            volume_usd_5m=60_000,
            top_holder_pct=6.0,
            holder_count=280,
            price_usd=0.003,
        ),
        price_ticks=[
            PriceTick(offset_seconds=60, price_usd=0.00305),
            PriceTick(offset_seconds=120, price_usd=0.00310),
            PriceTick(offset_seconds=300, price_usd=0.00315),
        ],
    ))

    scenarios.append(BacktestScenario(
        label="old_token_reject",
        token=TokenCandidate(
            token_address="SYN_OLD_001",
            symbol="OLD",
            name="Old Token",
            created_at=now - timedelta(hours=2),
            liquidity_usd=800_000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=100,
            sells_5m=20,
            volume_usd_5m=80_000,
            top_holder_pct=4.0,
            holder_count=400,
            price_usd=0.002,
        ),
        price_ticks=[],
    ))

    return scenarios[:count]


def load_scenarios_from_json(path: str) -> list[BacktestScenario]:
    import json

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    scenarios: list[BacktestScenario] = []
    for item in raw:
        scenarios.append(BacktestScenario.model_validate(item))
    return scenarios
