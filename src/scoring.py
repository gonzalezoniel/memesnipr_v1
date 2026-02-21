import math

from .config import settings
from .models import TokenCandidate, ConfidenceComponents


def _is_unknown(value: float) -> bool:
    return math.isnan(value) or math.isinf(value)


def compute_confidence_components(token: TokenCandidate) -> ConfidenceComponents:
    c = ConfidenceComponents()

    if token.mint_authority_revoked and token.freeze_authority_revoked and token.can_sell and not token.is_honeypot:
        c.contract_safety_score = 32.0
    elif token.safety_data_verified:
        c.contract_safety_score = 10.0
    else:
        c.contract_safety_score = 0.0

    liq = token.liquidity_usd
    if _is_unknown(liq) or liq <= settings.MIN_LIQUIDITY_USD:
        c.liquidity_score = 0.0
    else:
        max_liq = settings.MIN_LIQUIDITY_USD * 10
        norm = min(liq, max_liq) / max_liq
        c.liquidity_score = 18.0 * norm

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

    if _is_unknown(token.top_holder_pct) or token.holder_count == 0:
        c.holder_score = 0.0
    elif token.top_holder_pct < 10 and token.holder_count > 100:
        c.holder_score = 8.0
    elif token.top_holder_pct < 20:
        c.holder_score = 5.0
    else:
        c.holder_score = 1.0

    if _is_unknown(liq) or liq <= 0:
        c.slippage_score = 0.0
    else:
        depth_ratio = min(liq / (settings.MIN_LIQUIDITY_USD * 5), 1.0)
        c.slippage_score = 8.0 * depth_ratio

    if not token.safety_data_verified:
        c.meta_score = -5.0
    else:
        c.meta_score = 2.0

    vol = token.volume_usd_5m
    total_txns = token.buys_5m + token.sells_5m
    if _is_unknown(vol) or vol <= 0 or total_txns < 5:
        c.volume_momentum_score = 0.0
    else:
        vol_ratio = min(vol / (settings.MIN_LIQUIDITY_USD * 2), 1.0)
        txn_density = min(total_txns / 100.0, 1.0)
        c.volume_momentum_score = 7.0 * (vol_ratio * 0.6 + txn_density * 0.4)

    return c


def compute_confidence_score(token: TokenCandidate) -> float:
    return compute_confidence_components(token).total_score
