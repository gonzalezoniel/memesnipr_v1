from .config import settings
from .models import TokenCandidate, ConfidenceComponents


def compute_confidence_components(token: TokenCandidate) -> ConfidenceComponents:
    c = ConfidenceComponents()

    # Contract safety: binary-ish for now
    if token.mint_authority_revoked and token.freeze_authority_revoked and token.can_sell and not token.is_honeypot:
        c.contract_safety_score = 35.0
    else:
        c.contract_safety_score = 10.0

    # Liquidity score
    # Scale liquidity from MIN_LIQUIDITY_USD to, say, 10x that
    liq = token.liquidity_usd
    if liq <= settings.MIN_LIQUIDITY_USD:
        c.liquidity_score = 0.0
    else:
        # simple clamp
        max_liq = settings.MIN_LIQUIDITY_USD * 10
        norm = min(liq, max_liq) / max_liq
        c.liquidity_score = 20.0 * norm

    # Flow score based on buys vs sells and volume
    if token.buys_5m + token.sells_5m > 0:
        buy_ratio = token.buys_5m / max(1, token.buys_5m + token.sells_5m)
    else:
        buy_ratio = 0.0

    if buy_ratio > 0.65 and token.volume_usd_5m > settings.MIN_LIQUIDITY_USD * 0.1:
        c.flow_score = 12.0
    elif buy_ratio > 0.55:
        c.flow_score = 8.0
    else:
        c.flow_score = 2.0

    # Holder distribution: reward if no giga-whale
    if token.top_holder_pct < 10 and token.holder_count > 100:
        c.holder_score = 8.0
    elif token.top_holder_pct < 20:
        c.holder_score = 5.0
    else:
        c.holder_score = 1.0

    # Slippage / tradability: placeholder for now
    # In a real implementation this would use pool depth & price impact
    c.slippage_score = 8.0

    # Meta score left small & static until we wire sentiment
    c.meta_score = 2.0

    return c


def compute_confidence_score(token: TokenCandidate) -> float:
    return compute_confidence_components(token).total_score
