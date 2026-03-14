"""
Self-Learning Trade Memory System (Section 11).

For every trade, stores comprehensive data and groups trades by setup type.
Computes per-setup metrics: win rate, profit factor, average hold time, expectancy.
Automatically reduces score weighting for setups that consistently lose money.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from loguru import logger
from pydantic import BaseModel, Field

from .config import settings


class TradeMemoryRecord(BaseModel):
    """Complete record of a single trade for memory analysis."""
    token_name: str
    token_address: str
    entry_score: float = 0.0
    social_score: float = 0.0
    wallet_cluster_signals: bool = False
    wallet_score: float = 0.0
    liquidity: float = 0.0
    token_age_seconds: float = 0.0
    launch_phase: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    hold_duration_seconds: float = 0.0
    pnl_pct: float = 0.0
    pnl_sol: float = 0.0
    setup_type: str = ""
    trap_score: float = 0.0
    momentum_score: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # v5: additional fields for signal-level performance tracking
    v5_signal_score: float = 0.0
    v5_signal_components: dict[str, float] = Field(default_factory=dict)
    v5_runner_mode: bool = False
    v5_entry_reasons: list[str] = Field(default_factory=list)


class SetupStats(BaseModel):
    """Aggregated statistics for a specific setup type."""
    setup_type: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    profit_factor: float = 0.0
    avg_hold_time_seconds: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    expectancy: float = 0.0
    score_adjustment: float = 1.0  # multiplier applied to scoring


class V5SignalWeights(BaseModel):
    """v5: Dynamic signal weights adjusted by historical performance."""
    smart_wallet_cluster: float = 3.0
    volume_spike: float = 2.0
    liquidity_injection: float = 2.0
    holder_acceleration: float = 1.0
    social_sentiment: float = 1.0


class TradeMemory:
    """
    Manages trade memory for self-learning capabilities.

    Persists trade records and computes per-setup statistics
    to automatically adjust scoring weights.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.TRADE_MEMORY_PATH
        self._records: list[TradeMemoryRecord] = []
        self._setup_stats: dict[str, SetupStats] = {}
        self._v5_signal_weights = V5SignalWeights()
        self._v5_signal_stats: dict[str, SetupStats] = {}  # per-signal type stats
        self._load_db()

    def _load_db(self) -> None:
        """Load trade memory from disk."""
        if not os.path.exists(self._db_path):
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            records_raw = data.get("records", [])
            for raw in records_raw:
                self._records.append(TradeMemoryRecord.model_validate(raw))
            stats_raw = data.get("setup_stats", {})
            for setup_type, stat_raw in stats_raw.items():
                self._setup_stats[setup_type] = SetupStats.model_validate(stat_raw)
            logger.info(
                "Loaded {} trade memory records, {} setup types from {}",
                len(self._records), len(self._setup_stats), self._db_path,
            )
        except Exception as exc:
            logger.warning("Failed to load trade memory: {}", exc)

    def save_db(self) -> None:
        """Persist trade memory to disk."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        try:
            data = {
                "records": [r.model_dump(mode="json") for r in self._records[-1000:]],
                "setup_stats": {
                    k: v.model_dump(mode="json") for k, v in self._setup_stats.items()
                },
            }
            with open(self._db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, default=str, indent=2)
        except Exception as exc:
            logger.warning("Failed to save trade memory: {}", exc)

    def record_trade(self, record: TradeMemoryRecord) -> None:
        """Record a completed trade and update setup statistics."""
        self._records.append(record)
        self._update_setup_stats(record)
        # Periodically save
        if len(self._records) % 10 == 0:
            self.save_db()

    def _update_setup_stats(self, record: TradeMemoryRecord) -> None:
        """Update aggregated stats for the trade's setup type."""
        setup_type = record.setup_type or "unknown"
        if setup_type not in self._setup_stats:
            self._setup_stats[setup_type] = SetupStats(setup_type=setup_type)

        stats = self._setup_stats[setup_type]
        stats.total_trades += 1

        if record.pnl_pct >= 0:
            stats.wins += 1
            stats.total_profit += record.pnl_sol
        else:
            stats.losses += 1
            stats.total_loss += abs(record.pnl_sol)

        stats.win_rate = (stats.wins / stats.total_trades) * 100.0 if stats.total_trades > 0 else 0.0

        if stats.total_loss > 0:
            stats.profit_factor = stats.total_profit / stats.total_loss
        elif stats.total_profit > 0:
            stats.profit_factor = 999.99
        else:
            stats.profit_factor = 0.0

        # Update average hold time
        all_records = [r for r in self._records if (r.setup_type or "unknown") == setup_type]
        if all_records:
            stats.avg_hold_time_seconds = sum(
                r.hold_duration_seconds for r in all_records
            ) / len(all_records)

            win_records = [r for r in all_records if r.pnl_pct >= 0]
            loss_records = [r for r in all_records if r.pnl_pct < 0]

            stats.avg_win_pct = (
                sum(r.pnl_pct for r in win_records) / len(win_records)
                if win_records else 0.0
            )
            stats.avg_loss_pct = (
                sum(r.pnl_pct for r in loss_records) / len(loss_records)
                if loss_records else 0.0
            )

        # Compute expectancy: (win_rate * avg_win) - (loss_rate * avg_loss)
        win_rate_frac = stats.win_rate / 100.0
        loss_rate_frac = 1.0 - win_rate_frac
        stats.expectancy = (
            win_rate_frac * stats.avg_win_pct
            + loss_rate_frac * stats.avg_loss_pct  # avg_loss_pct is negative
        )

        # Auto-adjust score weighting for consistently losing setups
        if stats.total_trades >= settings.TRADE_MEMORY_MIN_TRADES_FOR_ADJUSTMENT:
            if stats.win_rate < settings.TRADE_MEMORY_PENALTY_THRESHOLD_WIN_RATE:
                stats.score_adjustment = settings.TRADE_MEMORY_PENALTY_FACTOR
                logger.warning(
                    "Trade memory: setup '{}' penalized (win_rate={:.1f}%, "
                    "adjustment={:.2f})",
                    setup_type, stats.win_rate, stats.score_adjustment,
                )
            elif stats.win_rate > 60.0 and stats.profit_factor > 1.5:
                # Boost setups that are consistently profitable
                stats.score_adjustment = min(1.3, 1.0 + (stats.win_rate - 50.0) / 100.0)
            else:
                stats.score_adjustment = 1.0

    def get_setup_adjustment(self, setup_type: str) -> float:
        """Get the score adjustment multiplier for a setup type."""
        stats = self._setup_stats.get(setup_type or "unknown")
        if stats is None:
            return 1.0
        return stats.score_adjustment

    def get_all_setup_stats(self) -> dict[str, SetupStats]:
        """Get all setup statistics."""
        return dict(self._setup_stats)

    def get_setup_profitability_summary(self) -> list[dict]:
        """Get a summary of setup profitability for the dashboard."""
        summaries = []
        for setup_type, stats in self._setup_stats.items():
            summaries.append({
                "setup_type": setup_type,
                "trades": stats.total_trades,
                "win_rate": round(stats.win_rate, 1),
                "profit_factor": round(stats.profit_factor, 2),
                "expectancy": round(stats.expectancy, 2),
                "avg_hold_min": round(stats.avg_hold_time_seconds / 60.0, 1),
                "score_adjustment": round(stats.score_adjustment, 2),
            })
        return sorted(summaries, key=lambda x: x["expectancy"], reverse=True)

    def classify_setup_type(
        self,
        social_score: float,
        wallet_cluster: bool,
        launch_phase: str,
        momentum_score: float,
    ) -> str:
        """Classify the current trade setup into a type for memory grouping."""
        parts: list[str] = []

        # Phase component
        if launch_phase:
            parts.append(launch_phase)
        else:
            parts.append("unknown_phase")

        # Signal strength component
        signal_count = 0
        if social_score >= 5.0:
            signal_count += 1
        if wallet_cluster:
            signal_count += 1
        if momentum_score > 50.0:
            signal_count += 1

        if signal_count >= 3:
            parts.append("multi_signal")
        elif signal_count == 2:
            parts.append("dual_signal")
        elif signal_count == 1:
            parts.append("single_signal")
        else:
            parts.append("base_signal")

        return "_".join(parts)

    # --- v5: Dynamic Signal Weight Adjustment ---

    def get_v5_signal_weights(self) -> V5SignalWeights:
        """Get the current v5 signal weights (dynamically adjusted)."""
        return self._v5_signal_weights

    def record_v5_trade(
        self,
        record: TradeMemoryRecord,
    ) -> None:
        """Record a v5 trade and update per-signal performance stats."""
        if not record.v5_signal_components:
            return

        # Update per-signal stats
        for signal_name, signal_value in record.v5_signal_components.items():
            if signal_value <= 0:
                continue
            if signal_name not in self._v5_signal_stats:
                self._v5_signal_stats[signal_name] = SetupStats(
                    setup_type=f"v5_{signal_name}"
                )
            stats = self._v5_signal_stats[signal_name]
            stats.total_trades += 1
            if record.pnl_pct >= 0:
                stats.wins += 1
                stats.total_profit += record.pnl_sol
            else:
                stats.losses += 1
                stats.total_loss += abs(record.pnl_sol)
            stats.win_rate = (
                (stats.wins / stats.total_trades) * 100.0
                if stats.total_trades > 0 else 0.0
            )
            if stats.total_loss > 0:
                stats.profit_factor = stats.total_profit / stats.total_loss
            elif stats.total_profit > 0:
                stats.profit_factor = 999.99

        # Dynamically adjust weights if enough data
        if settings.V5_DYNAMIC_WEIGHT_ADJUSTMENT:
            self._adjust_v5_weights()

    def _adjust_v5_weights(self) -> None:
        """Adjust v5 signal weights based on historical signal performance."""
        min_trades = settings.V5_MIN_TRADES_FOR_WEIGHT_ADJUST
        default_weights = V5SignalWeights()

        weight_map = {
            "smart_wallet_cluster": default_weights.smart_wallet_cluster,
            "volume_spike": default_weights.volume_spike,
            "liquidity_injection": default_weights.liquidity_injection,
            "holder_acceleration": default_weights.holder_acceleration,
            "social_sentiment": default_weights.social_sentiment,
        }

        for signal_name, base_weight in weight_map.items():
            stats = self._v5_signal_stats.get(signal_name)
            if stats is None or stats.total_trades < min_trades:
                continue

            # Adjust weight based on profitability
            if stats.profit_factor >= 2.0 and stats.win_rate >= 60.0:
                adjusted = min(base_weight * 1.5, base_weight + 2.0)
            elif stats.profit_factor >= 1.2 and stats.win_rate >= 50.0:
                adjusted = min(base_weight * 1.2, base_weight + 1.0)
            elif stats.win_rate < 40.0 or stats.profit_factor < 0.8:
                adjusted = max(base_weight * 0.5, 0.5)
            else:
                adjusted = base_weight

            setattr(self._v5_signal_weights, signal_name, round(adjusted, 2))

        logger.info(
            "V5 signal weights adjusted: {}",
            self._v5_signal_weights.model_dump(),
        )

    def get_v5_signal_performance(self) -> list[dict]:
        """Get v5 per-signal performance summary for dashboard."""
        summaries = []
        for signal_name, stats in self._v5_signal_stats.items():
            summaries.append({
                "signal": signal_name,
                "trades": stats.total_trades,
                "win_rate": round(stats.win_rate, 1),
                "profit_factor": round(stats.profit_factor, 2),
                "current_weight": getattr(
                    self._v5_signal_weights, signal_name,
                    0.0,
                ),
            })
        return summaries


# Module-level singleton
_memory_instance: TradeMemory | None = None


def get_trade_memory() -> TradeMemory:
    """Get or create the singleton TradeMemory."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = TradeMemory()
    return _memory_instance
