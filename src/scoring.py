import math

from .config import settings
from .models import TokenCandidate, ConfidenceComponents


def _is_unknown(value: float) -> bool:
    return math.isnan(value) or math.isinf(value)


def compute_confidence_components(token: TokenCandidate) -> ConfidenceComponents:
    """Score a token candidate for scalp-trading suitability.

    Weights are tuned for DexScreener-sourced data where on-chain safety
    fields (mint/freeze authority, holder concentration) are often unknown.
    The heaviest weights go to signals DexScreener *does* provide reliably:
    liquidity, buy/sell flow, volume momentum, and order-book depth.

    Component max values (total ≈ 100):
        contract_safety  : 15   (full marks need on-chain verification)
        liquidity        : 25   (key scalper signal — can we get in/out?)
        flow             : 22   (buy-side pressure)
        volume_momentum  : 18   (recent activity & txn density)
        slippage         : 12   (depth relative to min liquidity)
        holder           :  5   (bonus when holder data available)
        meta             : -3…3 (minor adjustment for verification status)
    """
    c = ConfidenceComponents()

    # --- contract safety (max 15) ---
    if token.mint_authority_revoked and token.freeze_authority_revoked and token.can_sell and not token.is_honeypot:
        c.contract_safety_score = 15.0
    elif token.safety_data_verified:
        c.contract_safety_score = 8.0
    elif token.can_sell and not token.is_honeypot:
        # Unverified but at least tradeable per DexScreener
        c.contract_safety_score = 5.0
    else:
        c.contract_safety_score = 0.0

    # --- liquidity (max 25) ---
    liq = token.liquidity_usd
    if _is_unknown(liq) or liq <= settings.MIN_LIQUIDITY_USD:
        c.liquidity_score = 0.0
    else:
        max_liq = settings.MIN_LIQUIDITY_USD * 10
        norm = min(liq, max_liq) / max_liq
        c.liquidity_score = 25.0 * norm

    # --- buy/sell flow (max 22) ---
    if token.buys_5m + token.sells_5m > 0:
        buy_ratio = token.buys_5m / max(1, token.buys_5m + token.sells_5m)
    else:
        buy_ratio = 0.0

    if buy_ratio > 0.70 and token.volume_usd_5m > settings.MIN_LIQUIDITY_USD * 0.1:
        c.flow_score = 22.0
    elif buy_ratio > 0.65 and token.volume_usd_5m > settings.MIN_LIQUIDITY_USD * 0.05:
        c.flow_score = 17.0
    elif buy_ratio > 0.55:
        c.flow_score = 10.0
    elif buy_ratio > 0.45:
        c.flow_score = 4.0
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

    # --- slippage / depth (max 12) ---
    if _is_unknown(liq) or liq <= 0:
        c.slippage_score = 0.0
    else:
        depth_ratio = min(liq / (settings.MIN_LIQUIDITY_USD * 5), 1.0)
        c.slippage_score = 12.0 * depth_ratio

    # --- meta / verification status (range -1 … +3) ---
    # Reduced penalty for unverified tokens: DexScreener candidates rarely
    # have on-chain verification, so a heavy penalty here blocked almost
    # every candidate from reaching the confidence threshold.
    if not token.safety_data_verified:
        c.meta_score = -1.0
    else:
        c.meta_score = 3.0

    # --- volume momentum (max 18) ---
    vol = token.volume_usd_5m
    total_txns = token.buys_5m + token.sells_5m
    if _is_unknown(vol) or vol <= 0 or total_txns < 5:
        c.volume_momentum_score = 0.0
    else:
        vol_ratio = min(vol / (settings.MIN_LIQUIDITY_USD * 2), 1.0)
        txn_density = min(total_txns / 80.0, 1.0)
        c.volume_momentum_score = 18.0 * (vol_ratio * 0.6 + txn_density * 0.4)

    return c


def compute_confidence_score(token: TokenCandidate) -> float:
    return compute_confidence_components(token).total_score
