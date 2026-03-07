"""
Smart Wallet Tracking Engine (Sections 5-7).

Tracks wallets that repeatedly buy successful meme coins early.
Computes wallet scores, detects accumulation patterns, and
classifies wallets as smart/neutral/suspicious.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from .config import settings


class WalletType(str, Enum):
    SMART = "smart"
    NEUTRAL = "neutral"
    SUSPICIOUS = "suspicious"


class WalletTradeRecord(BaseModel):
    """Record of a single trade by a tracked wallet."""
    token_address: str
    token_symbol: str
    action: str  # BUY / SELL
    timestamp: datetime
    price_usd: float = 0.0
    size_usd: float = 0.0
    pnl_pct: float = 0.0
    hold_time_seconds: float = 0.0
    was_rug: bool = False
    was_early_entry: bool = False


class WalletProfile(BaseModel):
    """Profile for a tracked wallet with metrics."""
    wallet_address: str
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Trade metrics
    tokens_traded: int = 0
    trades: list[WalletTradeRecord] = Field(default_factory=list)

    # Performance metrics
    average_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    early_entry_rate: float = 0.0
    rug_exposure_rate: float = 0.0
    hold_time_quality: float = 0.0
    consistency_score: float = 0.0

    # Computed score
    wallet_score: float = 0.0
    wallet_type: WalletType = WalletType.NEUTRAL

    def recompute_metrics(self) -> None:
        """Recompute all derived metrics from trade records."""
        if not self.trades:
            return

        self.tokens_traded = len(set(t.token_address for t in self.trades))

        # Filter to trades with PnL data (sells)
        pnl_trades = [t for t in self.trades if t.action == "SELL" and t.pnl_pct != 0.0]
        if not pnl_trades:
            return

        # Average and median return
        returns = [t.pnl_pct for t in pnl_trades]
        self.average_return = sum(returns) / len(returns)
        sorted_returns = sorted(returns)
        mid = len(sorted_returns) // 2
        if len(sorted_returns) % 2 == 0:
            self.median_return = (sorted_returns[mid - 1] + sorted_returns[mid]) / 2.0
        else:
            self.median_return = sorted_returns[mid]

        # Win rate
        wins = sum(1 for r in returns if r > 0)
        self.win_rate = (wins / len(returns)) * 100.0

        # Early entry rate
        early_entries = sum(1 for t in self.trades if t.was_early_entry)
        buy_trades = [t for t in self.trades if t.action == "BUY"]
        self.early_entry_rate = (
            (early_entries / len(buy_trades)) * 100.0 if buy_trades else 0.0
        )

        # Rug exposure rate
        rug_trades = sum(1 for t in self.trades if t.was_rug)
        self.rug_exposure_rate = (
            (rug_trades / len(buy_trades)) * 100.0 if buy_trades else 0.0
        )

        # Hold time quality: reward holding 2-30 min, penalize <30s or >2hr
        hold_times = [t.hold_time_seconds for t in pnl_trades if t.hold_time_seconds > 0]
        if hold_times:
            quality_scores = []
            for ht in hold_times:
                if 120 <= ht <= 1800:
                    quality_scores.append(1.0)
                elif 60 <= ht < 120:
                    quality_scores.append(0.7)
                elif 1800 < ht <= 7200:
                    quality_scores.append(0.5)
                elif ht < 60:
                    quality_scores.append(0.2)
                else:
                    quality_scores.append(0.3)
            self.hold_time_quality = sum(quality_scores) / len(quality_scores)
        else:
            self.hold_time_quality = 0.5

        # Consistency score: low variance in returns = more consistent
        if len(returns) >= 3:
            mean_ret = self.average_return
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            # Normalize: lower std_dev = higher consistency
            self.consistency_score = max(0.0, min(1.0, 1.0 - (std_dev / 100.0)))
        else:
            self.consistency_score = 0.5

        # Compute wallet score (0-100)
        self._compute_wallet_score()

        # Classify wallet
        self._classify_wallet()

    def _compute_wallet_score(self) -> None:
        """
        wallet_score =
            0.25 * early_entry_score +
            0.20 * average_return_score +
            0.15 * win_rate_score +
            0.15 * consistency_score +
            0.15 * rug_avoidance_score +
            0.10 * hold_time_quality
        """
        # Normalize each component to 0-100
        early_entry_score = min(self.early_entry_rate, 100.0)
        avg_return_score = min(max(self.average_return, 0.0), 100.0)
        win_rate_score = min(self.win_rate, 100.0)
        consistency = self.consistency_score * 100.0
        rug_avoidance = max(0.0, 100.0 - self.rug_exposure_rate * 10.0)
        hold_quality = self.hold_time_quality * 100.0

        self.wallet_score = (
            0.25 * early_entry_score
            + 0.20 * avg_return_score
            + 0.15 * win_rate_score
            + 0.15 * consistency
            + 0.15 * rug_avoidance
            + 0.10 * hold_quality
        )
        self.wallet_score = min(max(self.wallet_score, 0.0), 100.0)

    def _classify_wallet(self) -> None:
        """Classify wallet as smart/neutral/suspicious."""
        buy_trades = [t for t in self.trades if t.action == "BUY"]

        # Suspicious indicators
        suspicious_flags = 0
        if self.rug_exposure_rate > 30.0:
            suspicious_flags += 1
        if self.hold_time_quality < 0.25:
            suspicious_flags += 1
        # Frequent dump patterns: many sells with large negative PnL
        dump_trades = [t for t in self.trades if t.action == "SELL" and t.pnl_pct < -50]
        if len(dump_trades) > len(buy_trades) * 0.3:
            suspicious_flags += 1

        if suspicious_flags >= 2:
            self.wallet_type = WalletType.SUSPICIOUS
        elif (
            self.wallet_score >= settings.SMART_WALLET_MIN_SCORE
            and len(buy_trades) >= settings.SMART_WALLET_MIN_TRADES
        ):
            self.wallet_type = WalletType.SMART
        else:
            self.wallet_type = WalletType.NEUTRAL

    @property
    def is_smart(self) -> bool:
        return self.wallet_type == WalletType.SMART

    @property
    def is_suspicious(self) -> bool:
        return self.wallet_type == WalletType.SUSPICIOUS


class WalletAccumulationSignal(BaseModel):
    """Signal from wallet accumulation detection for a given token."""
    token_address: str
    smart_wallet_count: int = 0
    wallet_accumulation_velocity: float = 0.0  # wallets/minute buying
    smart_wallet_buy_pressure: float = 0.0  # total USD bought by smart wallets
    percent_supply_bought_by_smart_wallets: float = 0.0
    wallet_accumulation_score: float = 0.0
    suspicious_wallet_count: int = 0
    suspicious_wallet_penalty: float = 0.0

    entry_reasons: list[str] = Field(default_factory=list)


class SmartWalletEngine:
    """
    Manages wallet tracking, scoring, and accumulation detection.

    Persists wallet data to JSON for learning over time.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.WALLET_DB_PATH
        self._wallets: dict[str, WalletProfile] = {}
        self._load_db()

    def _load_db(self) -> None:
        """Load wallet database from disk."""
        if not os.path.exists(self._db_path):
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for addr, raw in data.items():
                self._wallets[addr] = WalletProfile.model_validate(raw)
            logger.info("Loaded {} wallet profiles from {}", len(self._wallets), self._db_path)
        except Exception as exc:
            logger.warning("Failed to load wallet DB: {}", exc)

    def save_db(self) -> None:
        """Persist wallet database to disk."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        try:
            data = {
                addr: profile.model_dump(mode="json")
                for addr, profile in self._wallets.items()
            }
            with open(self._db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, default=str, indent=2)
        except Exception as exc:
            logger.warning("Failed to save wallet DB: {}", exc)

    def record_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        action: str,
        price_usd: float = 0.0,
        size_usd: float = 0.0,
        pnl_pct: float = 0.0,
        hold_time_seconds: float = 0.0,
        was_rug: bool = False,
        was_early_entry: bool = False,
    ) -> None:
        """Record a trade for a wallet and update its profile."""
        if wallet_address not in self._wallets:
            self._wallets[wallet_address] = WalletProfile(
                wallet_address=wallet_address,
            )

        profile = self._wallets[wallet_address]
        profile.last_seen = datetime.now(timezone.utc)
        profile.trades.append(WalletTradeRecord(
            token_address=token_address,
            token_symbol=token_symbol,
            action=action,
            timestamp=datetime.now(timezone.utc),
            price_usd=price_usd,
            size_usd=size_usd,
            pnl_pct=pnl_pct,
            hold_time_seconds=hold_time_seconds,
            was_rug=was_rug,
            was_early_entry=was_early_entry,
        ))
        profile.recompute_metrics()

    def get_wallet(self, wallet_address: str) -> Optional[WalletProfile]:
        """Get wallet profile by address."""
        return self._wallets.get(wallet_address)

    def get_smart_wallets(self) -> list[WalletProfile]:
        """Get all wallets classified as smart."""
        return [w for w in self._wallets.values() if w.is_smart]

    def get_suspicious_wallets(self) -> list[WalletProfile]:
        """Get all wallets classified as suspicious."""
        return [w for w in self._wallets.values() if w.is_suspicious]

    def get_top_wallets(self, limit: int = 20) -> list[WalletProfile]:
        """Get top wallets by score."""
        sorted_wallets = sorted(
            self._wallets.values(),
            key=lambda w: w.wallet_score,
            reverse=True,
        )
        return sorted_wallets[:limit]

    def detect_accumulation(
        self,
        token_address: str,
        recent_buyers: list[str] | None = None,
        buy_amounts_usd: dict[str, float] | None = None,
        total_supply_usd: float = 0.0,
        time_window_minutes: float = 5.0,
    ) -> WalletAccumulationSignal:
        """
        Detect smart wallet accumulation for a token.

        Parameters
        ----------
        token_address : str
            The token being analyzed.
        recent_buyers : list[str]
            Wallet addresses that recently bought this token.
        buy_amounts_usd : dict[str, float]
            Amount each wallet bought in USD.
        total_supply_usd : float
            Total token supply in USD (for % supply calculation).
        time_window_minutes : float
            Time window of the recent buys.
        """
        recent_buyers = recent_buyers or []
        buy_amounts_usd = buy_amounts_usd or {}

        signal = WalletAccumulationSignal(token_address=token_address)
        entry_reasons: list[str] = []

        smart_buyers: list[str] = []
        suspicious_buyers: list[str] = []
        smart_buy_total = 0.0

        for buyer in recent_buyers:
            profile = self._wallets.get(buyer)
            if profile is None:
                continue
            if profile.is_smart:
                smart_buyers.append(buyer)
                smart_buy_total += buy_amounts_usd.get(buyer, 0.0)
            elif profile.is_suspicious:
                suspicious_buyers.append(buyer)

        signal.smart_wallet_count = len(smart_buyers)
        signal.suspicious_wallet_count = len(suspicious_buyers)

        # Accumulation velocity: smart wallets per minute
        if time_window_minutes > 0:
            signal.wallet_accumulation_velocity = (
                len(smart_buyers) / time_window_minutes
            )

        signal.smart_wallet_buy_pressure = smart_buy_total

        # Percent supply bought
        if total_supply_usd > 0 and smart_buy_total > 0:
            signal.percent_supply_bought_by_smart_wallets = (
                (smart_buy_total / total_supply_usd) * 100.0
            )

        # Build entry reasons
        if signal.smart_wallet_count >= 2:
            entry_reasons.append(
                f"smart_wallet_accumulation_detected ({signal.smart_wallet_count} wallets)"
            )
        if signal.wallet_accumulation_velocity > 0.5:
            entry_reasons.append("high_accumulation_velocity")
        if signal.percent_supply_bought_by_smart_wallets > 1.0:
            entry_reasons.append(
                f"smart_wallets_buying_supply ({signal.percent_supply_bought_by_smart_wallets:.1f}%)"
            )

        # Compute accumulation score (0-100)
        count_score = min(signal.smart_wallet_count / 5.0, 1.0) * 40.0
        velocity_score = min(signal.wallet_accumulation_velocity / 1.0, 1.0) * 25.0
        pressure_score = min(signal.smart_wallet_buy_pressure / 10000.0, 1.0) * 20.0
        supply_score = min(signal.percent_supply_bought_by_smart_wallets / 5.0, 1.0) * 15.0

        signal.wallet_accumulation_score = min(
            count_score + velocity_score + pressure_score + supply_score, 100.0
        )

        # Suspicious wallet penalty
        if signal.suspicious_wallet_count > 0:
            signal.suspicious_wallet_penalty = min(
                signal.suspicious_wallet_count * 10.0, 30.0
            )
            signal.wallet_accumulation_score = max(
                0.0, signal.wallet_accumulation_score - signal.suspicious_wallet_penalty
            )

        signal.entry_reasons = entry_reasons
        return signal

    def get_stats(self) -> dict[str, int]:
        """Get summary statistics for the wallet engine."""
        smart = sum(1 for w in self._wallets.values() if w.is_smart)
        suspicious = sum(1 for w in self._wallets.values() if w.is_suspicious)
        neutral = len(self._wallets) - smart - suspicious
        return {
            "total_tracked": len(self._wallets),
            "smart_wallets": smart,
            "suspicious_wallets": suspicious,
            "neutral_wallets": neutral,
        }


# Module-level singleton for the engine
_engine_instance: SmartWalletEngine | None = None


def get_smart_wallet_engine() -> SmartWalletEngine:
    """Get or create the singleton SmartWalletEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SmartWalletEngine()
    return _engine_instance
