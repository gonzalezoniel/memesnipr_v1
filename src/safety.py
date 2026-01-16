from datetime import datetime, timezone
from typing import Set

from .config import settings
from .models import TokenCandidate, SafetyResult


# In a real implementation you would maintain this in a DB or file
BAD_DEPLOYERS: Set[str] = set()


def evaluate_safety(token: TokenCandidate) -> SafetyResult:
    reasons: list[str] = []

    # Token age check
    age_minutes = (datetime.now(timezone.utc) - token.created_at).total_seconds() / 60.0
    if age_minutes > settings.MAX_TOKEN_AGE_MINUTES:
        reasons.append(f"Token too old for snipe: {age_minutes:.1f} min > {settings.MAX_TOKEN_AGE_MINUTES}")

    # Liquidity
    if token.liquidity_usd < settings.MIN_LIQUIDITY_USD:
        reasons.append(f"Liquidity too low: ${token.liquidity_usd:.0f} < ${settings.MIN_LIQUIDITY_USD:.0f}")

    # Taxes
    if token.buy_tax_pct > settings.MAX_BUY_TAX_PCT:
        reasons.append(f"Buy tax too high: {token.buy_tax_pct:.1f}%")
    if token.sell_tax_pct > settings.MAX_SELL_TAX_PCT:
        reasons.append(f"Sell tax too high: {token.sell_tax_pct:.1f}%")

    # Authorities
    if not token.mint_authority_revoked:
        reasons.append("Mint authority not revoked")
    if not token.freeze_authority_revoked:
        reasons.append("Freeze authority not revoked")

    # Honeypot / sellability
    if token.is_honeypot or not token.can_sell:
        reasons.append("Token appears to be honeypot / cannot sell")

    # Known bad deployers
    if token.deployer_address and token.deployer_address in BAD_DEPLOYERS:
        reasons.append("Deployer address flagged as bad")

    return SafetyResult(passed=len(reasons) == 0, reasons=reasons)
