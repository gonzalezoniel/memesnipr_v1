import math

from .config import settings
from .models import TokenCandidate, ConfidenceComponents


def _is_unknown(value: float) -> bool:
    return math.isnan(value) or math.isinf(value)


def compute_confidence_components(token: TokenCandidate) -> ConfidenceComponents:
    """Score a token candidate for aggressive meme-token sniping.

    Weights are tuned for DexScreener-sourced data where on-chain safety
    fields (mint/freeze authority, holder concentration) are often unknown.
    Heavily rewards momentum and buy-side pressure — the two strongest
    predictors of short-term meme-token price action.

    Component max values (total ≈ 100):
        contract_safety  : 10   (reduced — most DexScreener tokens unverified)
        liquidity        : 20   (need enough to get in/out)
        flow             : 28   (HEAVY — buy pressure is the #1 signal)
        volume_momentum  : 25   (HEAVY — momentum drives meme pumps)
        slippage         : 10   (depth relative to min liquidity)
        holder           :  5   (bonus when holder data available)
        meta             : -1…2 (minor adjustment)
    """
    c = ConfidenceComponents()

    # --- contract safety (max 10) ---
    if token.mint_authority_revoked and token.freeze_authority_revoked and token.can_sell and not token.is_honeypot:
        c.contract_safety_score = 10.0
    elif token.safety_data_verified:
        c.contract_safety_score = 6.0
    elif token.can_sell and not token.is_honeypot:
        # Unverified but at least tradeable per DexScreener
        c.contract_safety_score = 5.0
    else:
        c.contract_safety_score = 0.0

    # --- liquidity (max 20) ---
    liq = token.liquidity_usd
    if _is_unknown(liq) or liq <= settings.MIN_LIQUIDITY_USD:
        c.liquidity_score = 0.0
    else:
        max_liq = settings.MIN_LIQUIDITY_USD * 15
        norm = min(liq, max_liq) / max_liq
        c.liquidity_score = 20.0 * norm

    # --- buy/sell flow (max 28) — primary signal for meme sniping ---
    if token.buys_5m + token.sells_5m > 0:
        buy_ratio = token.buys_5m / max(1, token.buys_5m + token.sells_5m)
    else:
        buy_ratio = 0.0

    if buy_ratio > 0.75 and token.volume_usd_5m > settings.MIN_LIQUIDITY_USD * 0.1:
        c.flow_score = 28.0
    elif buy_ratio > 0.65 and token.volume_usd_5m > settings.MIN_LIQUIDITY_USD * 0.05:
        c.flow_score = 22.0
    elif buy_ratio > 0.55:
        c.flow_score = 14.0
    elif buy_ratio > 0.45:
        c.flow_score = 6.0
    else:
        c.flow_score = 0.0

    # --- holder distribution (max 5, bonus when data available) ---
    if _is_unknown(token.top_holder_pct) or token.holder_count == 0:
        c.holder_score = 0.0
    elif token.top_holder_pct < 10 and token.holder_count > 100:
        c.holder_score = 5.0
    elif token.top_holder_pct < 20:
        c.holder_score = 3.0
    else:
        c.holder_score = 1.0

    # --- slippage / depth (max 10) ---
    if _is_unknown(liq) or liq <= 0:
        c.slippage_score = 0.0
    else:
        depth_ratio = min(liq / (settings.MIN_LIQUIDITY_USD * 5), 1.0)
        c.slippage_score = 10.0 * depth_ratio

    # --- meta / verification status (range -1 … +2) ---
    if not token.safety_data_verified:
        c.meta_score = -1.0
    else:
        c.meta_score = 2.0

    # --- volume momentum (max 25) — key momentum signal ---
    vol = token.volume_usd_5m
    total_txns = token.buys_5m + token.sells_5m
    if _is_unknown(vol) or vol <= 0 or total_txns < 3:
        c.volume_momentum_score = 0.0
    else:
        vol_ratio = min(vol / (settings.MIN_LIQUIDITY_USD * 2), 1.0)
        txn_density = min(total_txns / 50.0, 1.0)
        c.volume_momentum_score = 25.0 * (vol_ratio * 0.5 + txn_density * 0.5)

    return c


def compute_confidence_score(token: TokenCandidate) -> float:
    return compute_confidence_components(token).total_score
