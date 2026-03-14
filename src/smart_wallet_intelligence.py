"""
Smart Wallet Intelligence Module (v5).

Identifies profitable wallets using strict qualification rules:
- minimum 10 historical trades
- win rate > 60%
- average ROI > 2x
- profitable on multiple meme tokens

Monitors real-time purchases and detects cluster events:
- If 3+ smart wallets buy the same token within 120 seconds, increase signal score.

Exposes metrics: smart_wallets_tracked, smart_wallet_signals, wallet_cluster_events.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from .config import settings
from .smart_wallet_engine import SmartWalletEngine, WalletProfile, get_smart_wallet_engine


# ---------------------------------------------------------------------------
# Qualification thresholds (v5)
# ---------------------------------------------------------------------------
_V5_MIN_TRADES = 10
_V5_MIN_WIN_RATE = 60.0      # percent
_V5_MIN_AVG_ROI = 2.0        # 2x
_V5_MIN_PROFITABLE_TOKENS = 2
_V5_CLUSTER_WINDOW_SECONDS = 120
_V5_CLUSTER_MIN_WALLETS = 3


class QualifiedWallet(BaseModel):
    """A wallet that passes v5 qualification rules."""
    wallet_address: str
    total_trades: int = 0
    win_rate: float = 0.0
    avg_roi: float = 0.0
    profitable_token_count: int = 0
    wallet_score: float = 0.0


class SmartWalletPurchase(BaseModel):
    """Record of a smart wallet purchase for cluster detection."""
    wallet_address: str
    token_address: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    size_usd: float = 0.0


class WalletClusterEvent(BaseModel):
    """Event triggered when 3+ smart wallets buy the same token within 120s."""
    token_address: str
    wallet_count: int = 0
    wallets: list[str] = Field(default_factory=list)
    first_buy_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_buy_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_boost: float = 0.0


class SmartWalletIntelligence:
    """
    v5 Smart Wallet Intelligence system.

    Qualifies wallets with strict criteria, monitors purchases,
    and detects cluster events for signal boosting.
    """

    def __init__(self, engine: SmartWalletEngine | None = None) -> None:
        self._engine = engine or get_smart_wallet_engine()
        self._qualified_wallets: dict[str, QualifiedWallet] = {}
        self._recent_purchases: list[SmartWalletPurchase] = []
        self._cluster_events: list[WalletClusterEvent] = []
        self._signal_count: int = 0
        self._refresh_qualified_wallets()

    def _refresh_qualified_wallets(self) -> None:
        """Re-evaluate all tracked wallets against v5 qualification rules."""
        self._qualified_wallets.clear()
        for profile in self._engine._wallets.values():
            qualified = self._check_qualification(profile)
            if qualified is not None:
                self._qualified_wallets[profile.wallet_address] = qualified

    def _check_qualification(self, profile: WalletProfile) -> Optional[QualifiedWallet]:
        """Check if a wallet meets v5 qualification criteria."""
        buy_trades = [t for t in profile.trades if t.action == "BUY"]
        sell_trades = [t for t in profile.trades if t.action == "SELL" and t.pnl_pct != 0.0]

        total_trades = len(buy_trades) + len(sell_trades)
        if total_trades < _V5_MIN_TRADES:
            return None

        if not sell_trades:
            return None

        # Win rate
        wins = sum(1 for t in sell_trades if t.pnl_pct > 0)
        win_rate = (wins / len(sell_trades)) * 100.0
        if win_rate < _V5_MIN_WIN_RATE:
            return None

        # Average ROI (as multiplier: 2x means +100%)
        avg_pnl_pct = sum(t.pnl_pct for t in sell_trades) / len(sell_trades)
        avg_roi = 1.0 + (avg_pnl_pct / 100.0)
        if avg_roi < _V5_MIN_AVG_ROI:
            return None

        # Profitable on multiple tokens
        token_pnl: dict[str, float] = defaultdict(float)
        for t in sell_trades:
            token_pnl[t.token_address] += t.pnl_pct
        profitable_tokens = sum(1 for pnl in token_pnl.values() if pnl > 0)
        if profitable_tokens < _V5_MIN_PROFITABLE_TOKENS:
            return None

        return QualifiedWallet(
            wallet_address=profile.wallet_address,
            total_trades=total_trades,
            win_rate=win_rate,
            avg_roi=avg_roi,
            profitable_token_count=profitable_tokens,
            wallet_score=profile.wallet_score,
        )

    def record_purchase(
        self,
        wallet_address: str,
        token_address: str,
        size_usd: float = 0.0,
    ) -> Optional[WalletClusterEvent]:
        """
        Record a smart wallet purchase and check for cluster events.

        Returns a WalletClusterEvent if a cluster is detected, else None.
        """
        # Only track purchases from qualified wallets
        if wallet_address not in self._qualified_wallets:
            return None

        now = datetime.now(timezone.utc)
        purchase = SmartWalletPurchase(
            wallet_address=wallet_address,
            token_address=token_address,
            timestamp=now,
            size_usd=size_usd,
        )
        self._recent_purchases.append(purchase)
        self._signal_count += 1

        # Prune old purchases outside the cluster window
        cutoff = now.timestamp() - _V5_CLUSTER_WINDOW_SECONDS
        self._recent_purchases = [
            p for p in self._recent_purchases
            if p.timestamp.timestamp() >= cutoff
        ]

        # Check for cluster event on this token
        return self._check_cluster(token_address, now)

    def _check_cluster(
        self,
        token_address: str,
        now: datetime,
    ) -> Optional[WalletClusterEvent]:
        """Check if 3+ qualified wallets bought the same token within 120s."""
        cutoff = now.timestamp() - _V5_CLUSTER_WINDOW_SECONDS
        token_purchases = [
            p for p in self._recent_purchases
            if p.token_address == token_address and p.timestamp.timestamp() >= cutoff
        ]

        # Deduplicate by wallet address
        unique_wallets = list({p.wallet_address for p in token_purchases})
        if len(unique_wallets) < _V5_CLUSTER_MIN_WALLETS:
            return None

        timestamps = [p.timestamp for p in token_purchases]
        event = WalletClusterEvent(
            token_address=token_address,
            wallet_count=len(unique_wallets),
            wallets=unique_wallets,
            first_buy_at=min(timestamps),
            last_buy_at=max(timestamps),
            signal_boost=3.0,  # +3 to signal score per spec
        )
        self._cluster_events.append(event)

        logger.info(
            "WALLET CLUSTER EVENT: {} qualified wallets bought {} within {}s",
            len(unique_wallets), token_address[:8], _V5_CLUSTER_WINDOW_SECONDS,
        )

        return event

    def check_token_cluster(self, token_address: str) -> Optional[WalletClusterEvent]:
        """Check if there's an active cluster event for a token."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - _V5_CLUSTER_WINDOW_SECONDS

        # Check recent purchases for this token
        token_purchases = [
            p for p in self._recent_purchases
            if p.token_address == token_address and p.timestamp.timestamp() >= cutoff
        ]
        unique_wallets = list({p.wallet_address for p in token_purchases})
        if len(unique_wallets) >= _V5_CLUSTER_MIN_WALLETS:
            timestamps = [p.timestamp for p in token_purchases]
            return WalletClusterEvent(
                token_address=token_address,
                wallet_count=len(unique_wallets),
                wallets=unique_wallets,
                first_buy_at=min(timestamps),
                last_buy_at=max(timestamps),
                signal_boost=3.0,
            )
        return None

    def get_metrics(self) -> dict:
        """Get dashboard metrics."""
        return {
            "smart_wallets_tracked": len(self._qualified_wallets),
            "smart_wallet_signals": self._signal_count,
            "wallet_cluster_events": len(self._cluster_events),
            "qualified_wallet_addresses": [
                w.wallet_address[:8] + "..."
                for w in sorted(
                    self._qualified_wallets.values(),
                    key=lambda w: w.wallet_score,
                    reverse=True,
                )[:10]
            ],
        }

    def get_qualified_wallets(self) -> list[QualifiedWallet]:
        """Get all qualified wallets."""
        return list(self._qualified_wallets.values())

    def get_tracked_wallet_count(self) -> int:
        """Get the number of tracked qualified wallets."""
        return len(self._qualified_wallets)

    def get_recent_cluster_events(self, limit: int = 50) -> list[WalletClusterEvent]:
        """Get recent cluster events for the dashboard."""
        return self._cluster_events[-limit:]

    def get_signal_count(self) -> int:
        """Get the total number of smart wallet signals recorded."""
        return self._signal_count


# Module-level singleton
_intelligence_instance: SmartWalletIntelligence | None = None


def get_smart_wallet_intelligence() -> SmartWalletIntelligence:
    """Get or create the singleton SmartWalletIntelligence."""
    global _intelligence_instance
    if _intelligence_instance is None:
        _intelligence_instance = SmartWalletIntelligence()
    return _intelligence_instance
