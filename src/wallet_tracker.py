"""
Wallet Tracker (Section 6-7).

Provides higher-level wallet tracking functions that integrate
with the SmartWalletEngine for accumulation detection and
suspicious wallet filtering.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from .smart_wallet_engine import (
    SmartWalletEngine,
    WalletAccumulationSignal,
    WalletType,
    get_smart_wallet_engine,
)


@dataclass
class WalletAnalysis:
    """Complete wallet analysis result for a token."""
    accumulation_signal: WalletAccumulationSignal | None = None
    wallet_score_contribution: float = 0.0
    entry_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    should_penalize: bool = False
    penalty_amount: float = 0.0


def analyze_token_wallets(
    token_address: str,
    recent_buyers: list[str] | None = None,
    buy_amounts_usd: dict[str, float] | None = None,
    total_supply_usd: float = 0.0,
    engine: SmartWalletEngine | None = None,
) -> WalletAnalysis:
    """
    Perform complete wallet analysis for a token candidate.

    This combines accumulation detection and suspicious wallet filtering
    into a single analysis result.
    """
    engine = engine or get_smart_wallet_engine()
    analysis = WalletAnalysis()

    # Detect accumulation
    signal = engine.detect_accumulation(
        token_address=token_address,
        recent_buyers=recent_buyers,
        buy_amounts_usd=buy_amounts_usd,
        total_supply_usd=total_supply_usd,
    )
    analysis.accumulation_signal = signal
    analysis.entry_reasons = list(signal.entry_reasons)

    # Use accumulation score as wallet contribution (normalized to 0-100)
    analysis.wallet_score_contribution = signal.wallet_accumulation_score

    # Check for suspicious wallet dominance
    total_buyers = len(recent_buyers) if recent_buyers else 0
    if total_buyers > 0 and signal.suspicious_wallet_count > 0:
        suspicious_ratio = signal.suspicious_wallet_count / total_buyers
        if suspicious_ratio > 0.3:
            analysis.should_penalize = True
            analysis.penalty_amount = signal.suspicious_wallet_penalty
            analysis.rejection_reasons.append(
                f"high_suspicious_wallet_ratio ({suspicious_ratio:.0%})"
            )

    logger.debug(
        "Wallet analysis for {}: score={:.1f}, smart={}, suspicious={}, reasons={}",
        token_address[:8],
        analysis.wallet_score_contribution,
        signal.smart_wallet_count,
        signal.suspicious_wallet_count,
        analysis.entry_reasons,
    )

    return analysis


def get_wallet_intelligence_summary(engine: SmartWalletEngine | None = None) -> dict:
    """Get a summary of wallet intelligence for the dashboard."""
    engine = engine or get_smart_wallet_engine()
    stats = engine.get_stats()
    top_wallets = engine.get_top_wallets(limit=10)

    return {
        "smart_wallets_tracked": stats["smart_wallets"],
        "suspicious_wallets": stats["suspicious_wallets"],
        "total_tracked": stats["total_tracked"],
        "top_wallet_scores": [
            {
                "address": w.wallet_address[:8] + "...",
                "score": round(w.wallet_score, 1),
                "type": w.wallet_type.value,
                "win_rate": round(w.win_rate, 1),
                "trades": w.tokens_traded,
            }
            for w in top_wallets
        ],
        "wallet_driven_signals": stats["smart_wallets"],
    }
