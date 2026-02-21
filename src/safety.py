from datetime import datetime, timezone
import math
from typing import Set

from .config import settings
from .models import TokenCandidate, SafetyResult


# In a real implementation you would maintain this in a DB or file
BAD_DEPLOYERS: Set[str] = set()


def evaluate_safety(token: TokenCandidate) -> SafetyResult:
    reasons: list[str] = []
    reason_codes: list[str] = []

    def _add_reason(code: str, reason: str):
        reason_codes.append(code)
        reasons.append(reason)

    def _is_unknown_number(value: float) -> bool:
        return math.isnan(value) or math.isinf(value)

    if settings.REJECT_ON_UNKNOWN_SIGNALS:
        if not token.token_address.strip():
            _add_reason("UNKNOWN_TOKEN_ADDRESS", "Token address missing")
        if not token.symbol.strip():
            _add_reason("UNKNOWN_TOKEN_SYMBOL", "Token symbol missing")
        if _is_unknown_number(token.liquidity_usd):
            _add_reason("UNKNOWN_LIQUIDITY", "Liquidity is unknown")
        if _is_unknown_number(token.buy_tax_pct):
            _add_reason("UNKNOWN_BUY_TAX", "Buy tax is unknown")
        if _is_unknown_number(token.sell_tax_pct):
            _add_reason("UNKNOWN_SELL_TAX", "Sell tax is unknown")
        if _is_unknown_number(token.top_holder_pct):
            _add_reason("UNKNOWN_HOLDER_CONCENTRATION", "Top holder concentration is unknown")
        if _is_unknown_number(token.volume_usd_5m):
            _add_reason("UNKNOWN_VOLUME", "Recent volume is unknown")

    if not token.safety_data_verified:
        if not token.mint_authority_revoked:
            _add_reason(
                "UNVERIFIED_MINT_AUTHORITY",
                "Mint authority status not verified on-chain — assuming active",
            )
        if not token.freeze_authority_revoked:
            _add_reason(
                "UNVERIFIED_FREEZE_AUTHORITY",
                "Freeze authority status not verified on-chain — assuming active",
            )

    age_seconds = (datetime.now(timezone.utc) - token.created_at).total_seconds()
    age_minutes = age_seconds / 60.0

    # Token age check
    if age_minutes < 0:
        _add_reason("INVALID_TOKEN_AGE", "Token creation time is in the future")
    if age_minutes > settings.MAX_TOKEN_AGE_MINUTES:
        _add_reason(
            "TOKEN_TOO_OLD",
            f"Token too old for snipe: {age_minutes:.1f} min > {settings.MAX_TOKEN_AGE_MINUTES}",
        )

    # Hard blocks
    if not token.mint_authority_revoked:
        _add_reason("MINT_AUTHORITY_ACTIVE", "Mint authority not revoked")
    if not token.freeze_authority_revoked:
        _add_reason("FREEZE_AUTHORITY_ACTIVE", "Freeze authority not revoked")

    # Liquidity
    if token.liquidity_usd < settings.MIN_LIQUIDITY_USD:
        _add_reason(
            "LOW_LIQUIDITY",
            f"Liquidity too low: ${token.liquidity_usd:.0f} < ${settings.MIN_LIQUIDITY_USD:.0f}",
        )

    # Taxes
    if token.buy_tax_pct > settings.MAX_BUY_TAX_PCT:
        _add_reason("HIGH_BUY_TAX", f"Buy tax too high: {token.buy_tax_pct:.1f}%")
    if token.sell_tax_pct > settings.MAX_SELL_TAX_PCT:
        _add_reason("HIGH_SELL_TAX", f"Sell tax too high: {token.sell_tax_pct:.1f}%")

    # Honeypot / sellability
    if token.is_honeypot or not token.can_sell:
        _add_reason("HONEYPOT_OR_CANNOT_SELL", "Token appears to be honeypot / cannot sell")

    # Early launch + weird holder distribution hard block
    if (
        0 <= age_seconds <= settings.SUSPICIOUS_LAUNCH_WINDOW_SECONDS
        and token.top_holder_pct >= settings.SUSPICIOUS_MAX_TOP_HOLDER_PCT
        and token.holder_count <= settings.SUSPICIOUS_MAX_HOLDER_COUNT
    ):
        _add_reason(
            "SUSPICIOUS_EARLY_DISTRIBUTION",
            "Very new token has concentrated holders and low holder count",
        )

    # Known bad deployers
    if token.deployer_address and token.deployer_address in BAD_DEPLOYERS:
        _add_reason("BAD_DEPLOYER", "Deployer address flagged as bad")

    risk_score = min(float(len(reason_codes) * 20), 100.0)

    return SafetyResult(
        passed=len(reason_codes) == 0,
        reasons=reasons,
        reason_codes=reason_codes,
        risk_score=risk_score,
    )
