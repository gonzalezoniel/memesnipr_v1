"""
Social Momentum Engine (Sections 3, 7, 8).

Creates a Social Momentum Score (SMS) from 0-100 combining:
- twitter_signal_score  (30%)
- dexscreener_trending  (20%)
- birdeye_trending      (15%)
- telegram_activity     (15%)
- reddit_mentions       (10%)
- wallet_social_overlap (10%)

Also detects Social Momentum Events (Section 8):
If mentions increase >3x within 10 minutes, flags as a momentum event
and boosts entry confidence.

Produces a unified social_score 0-10 for the scoring pipeline.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .config import settings
from .social_signals import lookup_token_signal
from .twitter_signals import process_twitter_signal, TwitterSignalResult
from .telegram_signals import process_telegram_signal, TelegramSignalResult
from .birdeye_signals import process_birdeye_signal, BirdeyeSignalResult
from .pump_monitor import process_pump_signal, PumpSignalResult
from .sentiment_analyzer import analyze_sentiment, SentimentResult
from .spam_filter import check_spam, SpamCheckResult


class SocialMomentumResult:
    """Result of the Social Momentum Score computation."""

    def __init__(
        self,
        sms_score: float = 0.0,
        twitter_score: float = 0.0,
        dex_trending_score: float = 0.0,
        birdeye_score: float = 0.0,
        telegram_score: float = 0.0,
        reddit_score: float = 0.0,
        influencer_wallet_score: float = 0.0,
        wallet_overlap_score: float = 0.0,
        pump_score: float = 0.0,
        eligible: bool = False,
        social_score_unified: float = 0.0,
        is_momentum_event: bool = False,
        momentum_event_multiplier: float = 1.0,
        sentiment_result: SentimentResult | None = None,
        spam_result: SpamCheckResult | None = None,
        twitter_result: TwitterSignalResult | None = None,
        telegram_result: TelegramSignalResult | None = None,
        birdeye_result: BirdeyeSignalResult | None = None,
        pump_result: PumpSignalResult | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.sms_score = sms_score
        self.twitter_score = twitter_score
        self.dex_trending_score = dex_trending_score
        self.birdeye_score = birdeye_score
        self.telegram_score = telegram_score
        self.reddit_score = reddit_score
        self.influencer_wallet_score = influencer_wallet_score
        self.wallet_overlap_score = wallet_overlap_score
        self.pump_score = pump_score
        self.eligible = eligible
        self.social_score_unified = social_score_unified
        self.is_momentum_event = is_momentum_event
        self.momentum_event_multiplier = momentum_event_multiplier
        self.sentiment_result = sentiment_result
        self.spam_result = spam_result
        self.twitter_result = twitter_result
        self.telegram_result = telegram_result
        self.birdeye_result = birdeye_result
        self.pump_result = pump_result
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        result = {
            "sms_score": round(self.sms_score, 2),
            "sms_eligible": self.eligible,
            "social_score_unified": round(self.social_score_unified, 2),
            "sms_twitter": round(self.twitter_score, 2),
            "sms_dex_trending": round(self.dex_trending_score, 2),
            "sms_birdeye": round(self.birdeye_score, 2),
            "sms_telegram": round(self.telegram_score, 2),
            "sms_reddit": round(self.reddit_score, 2),
            "sms_influencer_wallet": round(self.influencer_wallet_score, 2),
            "sms_wallet_overlap": round(self.wallet_overlap_score, 2),
            "sms_pump": round(self.pump_score, 2),
            "is_momentum_event": self.is_momentum_event,
            "momentum_event_multiplier": round(self.momentum_event_multiplier, 2),
        }
        if self.sentiment_result:
            result["sentiment"] = self.sentiment_result.to_dict()
        if self.spam_result:
            result["spam_filter"] = self.spam_result.to_dict()
        return result


# --- Momentum Event Detection (Section 8) ---
# Track mention counts per token over time for velocity detection
_mention_history: dict[str, deque[tuple[datetime, int]]] = {}
_MAX_HISTORY_SIZE = 60  # keep last 60 data points


def _detect_momentum_event(
    symbol: str,
    current_mentions: int,
) -> tuple[bool, float]:
    """
    Detect if mentions have increased >3x within the configured window.

    Returns (is_event, multiplier).
    """
    key = symbol.upper()
    now = datetime.now(timezone.utc)
    window_seconds = settings.SOCIAL_MOMENTUM_EVENT_WINDOW_SECONDS
    threshold = settings.SOCIAL_MOMENTUM_EVENT_MULTIPLIER

    if key not in _mention_history:
        _mention_history[key] = deque(maxlen=_MAX_HISTORY_SIZE)

    history = _mention_history[key]

    # Prune entries older than the window
    while history and (now - history[0][0]).total_seconds() > window_seconds:
        history.popleft()

    # Add current data point
    history.append((now, current_mentions))

    if len(history) < 2:
        return False, 1.0

    # Compare current to oldest in window
    baseline_mentions = history[0][1]
    if baseline_mentions <= 0:
        # If baseline was 0 and we now have mentions, that's significant
        if current_mentions >= 5:
            return True, float(current_mentions)
        return False, 1.0

    multiplier = current_mentions / baseline_mentions
    is_event = multiplier >= threshold

    if is_event:
        logger.info(
            "SOCIAL MOMENTUM EVENT for {}: {:.1f}x increase in mentions "
            "({} -> {} in {}s window)",
            symbol, multiplier, baseline_mentions, current_mentions,
            window_seconds,
        )

    return is_event, multiplier


def compute_social_momentum_score(
    symbol: str,
    token_address: str = "",
    wallet_accumulation_score: float = 0.0,
    dex_trending: bool = False,
    token_age_seconds: float = 0.0,
    holder_count: int = 0,
    buys_5m: int = 0,
    sells_5m: int = 0,
    liquidity_usd: float = 0.0,
    previous_liquidity_usd: float = 0.0,
) -> SocialMomentumResult:
    """
    Compute the Social Momentum Score (SMS) for a token.

    The SMS is a weighted score from 0-100 combining multiple social signals.
    Also produces a unified social_score (0-10) for the scoring pipeline.
    Trade eligibility requires SMS >= settings.SMS_MIN_SCORE.

    v4 upgrade: integrates Twitter, Telegram, Birdeye, Pump Platform,
    sentiment analysis, spam filtering, and momentum event detection.
    """
    signal = lookup_token_signal(symbol, token_address)

    if signal is None:
        return SocialMomentumResult(
            sms_score=0.0,
            eligible=False,
            details={"signal_found": False},
        )

    mentions = signal.get("mentions", 0)
    sentiment = signal.get("sentiment", 0.0)
    trend = signal.get("trend", "unknown")
    engagement = signal.get("engagement", 0.0)
    sources = signal.get("sources", [])

    # --- Section 1: Twitter Signal Processing ---
    twitter_result = process_twitter_signal(
        symbol=symbol,
        token_address=token_address,
        signal_data=signal,
    )
    twitter_raw = twitter_result.twitter_signal_score  # 0-100

    # --- Section 3: DexScreener Trending (Improved) ---
    # Enhanced: now considers volume spikes, new pair listings, and liquidity changes
    dex_raw = 0.0
    if trend == "rising":
        dex_raw = 70.0
    elif trend == "stable":
        dex_raw = 30.0

    # Engagement boost (proxy for DexScreener trending activity)
    if engagement > 100:
        dex_raw = min(dex_raw + 30.0, 100.0)
    elif engagement > 50:
        dex_raw = min(dex_raw + 20.0, 100.0)
    elif engagement > 10:
        dex_raw = min(dex_raw + 10.0, 100.0)

    # v4: Volume spike detection for DexScreener
    volume_data = signal.get("volume", {})
    if isinstance(volume_data, dict):
        vol_change = volume_data.get("change_pct", 0.0)
        if vol_change > 200:
            dex_raw = min(dex_raw + 20.0, 100.0)
        elif vol_change > 100:
            dex_raw = min(dex_raw + 10.0, 100.0)

    # v4: Liquidity change tracking
    liq_data = signal.get("liquidity", {})
    if isinstance(liq_data, dict):
        liq_change = liq_data.get("change_pct", 0.0)
        if liq_change > 50:
            dex_raw = min(dex_raw + 10.0, 100.0)

    # Token is confirmed trending on DexScreener
    if dex_trending:
        dex_raw = max(dex_raw, 60.0)

    # --- Section 4: Birdeye Trending Data ---
    birdeye_result = process_birdeye_signal(
        symbol=symbol,
        token_address=token_address,
        signal_data=signal,
        dex_trending=dex_trending,
    )
    birdeye_raw = birdeye_result.birdeye_signal_score  # 0-100

    # Multi-tracker trending bonus (on both Birdeye + DexScreener)
    if birdeye_result.multi_tracker_trending:
        dex_raw = min(dex_raw + 15.0, 100.0)

    # --- Section 2: Telegram Activity ---
    telegram_result = process_telegram_signal(
        symbol=symbol,
        token_address=token_address,
        signal_data=signal,
    )
    telegram_raw = telegram_result.telegram_signal_score  # 0-100

    # --- Reddit Mentions (max 100) ---
    reddit_raw = 0.0
    sources_lower = [s.lower() for s in sources]
    if "reddit" in sources_lower:
        reddit_raw = 50.0
        if mentions >= 5:
            reddit_raw = min(reddit_raw + mentions * 2.0, 100.0)
    elif mentions >= 10:
        reddit_raw = min(mentions * 1.5, 40.0)

    # --- Section 5: Pump Platform Monitoring ---
    pump_result = process_pump_signal(
        symbol=symbol,
        token_address=token_address,
        token_age_seconds=token_age_seconds,
        holder_count=holder_count,
        buys_5m=buys_5m,
        sells_5m=sells_5m,
        liquidity_usd=liquidity_usd,
        previous_liquidity_usd=previous_liquidity_usd,
        signal_data=signal,
    )

    # --- Section 6: Wallet Social Overlap ---
    # Combine wallet accumulation score with social signals
    wallet_overlap_raw = 0.0
    if wallet_accumulation_score > 0:
        # Scale wallet score (0-100) to component score
        wallet_overlap_raw = min(wallet_accumulation_score, 100.0)
        # Boost if both social and wallet signals are strong
        if wallet_overlap_raw >= 50.0 and twitter_raw >= 40.0:
            wallet_overlap_raw = min(wallet_overlap_raw * 1.3, 100.0)

    # --- Influencer Wallet Activity (legacy, kept for backward compat) ---
    influencer_raw = 0.0
    if trend == "rising" and engagement > 50 and mentions >= 10:
        influencer_raw = 70.0
    elif trend == "rising" and mentions >= 5:
        influencer_raw = 40.0
    elif engagement > 20:
        influencer_raw = 20.0

    # --- Section 9: Sentiment Analysis ---
    sentiment_result = analyze_sentiment(
        signal_sentiment=sentiment,
        signal_data=signal,
    )

    # --- Section 10: Spam Filtering ---
    spam_result = check_spam(
        symbol=symbol,
        signal_data=signal,
    )

    # Apply spam quality multiplier to raw scores
    quality_mult = spam_result.quality_multiplier
    twitter_raw *= quality_mult
    telegram_raw *= quality_mult

    # --- Section 7: Weighted SMS (unified scoring) ---
    # Weights: Twitter 30%, DexScreener 20%, Birdeye 15%, Telegram 15%,
    #          Reddit 10%, Wallet overlap 10%
    sms_score = (
        settings.SMS_TWITTER_WEIGHT * twitter_raw
        + settings.SMS_DEX_TRENDING_WEIGHT * dex_raw
        + settings.SMS_BIRDEYE_WEIGHT * birdeye_raw
        + settings.SMS_TELEGRAM_WEIGHT * telegram_raw
        + settings.SMS_REDDIT_WEIGHT * reddit_raw
        + settings.SMS_WALLET_OVERLAP_WEIGHT * wallet_overlap_raw
    )

    # Apply sentiment adjustment (+/- up to 10 points on 0-100 scale)
    sms_score += sentiment_result.sentiment_adjustment * (100.0 / 10.0)

    sms_score = min(max(sms_score, 0.0), 100.0)

    # --- Section 8: Social Momentum Event Detection ---
    is_momentum_event, momentum_multiplier = _detect_momentum_event(
        symbol=symbol,
        current_mentions=mentions,
    )

    # Momentum event boosts the SMS score
    if is_momentum_event:
        sms_score = min(sms_score * 1.2, 100.0)

    eligible = sms_score >= settings.SMS_MIN_SCORE

    # --- Unified social_score (0-10) ---
    # Direct mapping from SMS 0-100 to 0-10
    social_score_unified = sms_score / 10.0

    result = SocialMomentumResult(
        sms_score=sms_score,
        twitter_score=twitter_raw,
        dex_trending_score=dex_raw,
        birdeye_score=birdeye_raw,
        telegram_score=telegram_raw,
        reddit_score=reddit_raw,
        influencer_wallet_score=influencer_raw,
        wallet_overlap_score=wallet_overlap_raw,
        pump_score=pump_result.pump_signal_score,
        eligible=eligible,
        social_score_unified=social_score_unified,
        is_momentum_event=is_momentum_event,
        momentum_event_multiplier=momentum_multiplier,
        sentiment_result=sentiment_result,
        spam_result=spam_result,
        twitter_result=twitter_result,
        telegram_result=telegram_result,
        birdeye_result=birdeye_result,
        pump_result=pump_result,
        details={
            "signal_found": True,
            "mentions": mentions,
            "sentiment": sentiment,
            "trend": trend,
            "engagement": engagement,
            "sources": sources,
            "quality_multiplier": quality_mult,
        },
    )

    logger.debug(
        "SMS for {}: score={:.1f}, unified={:.1f}, eligible={}, "
        "twitter={:.0f}, dex={:.0f}, birdeye={:.0f}, telegram={:.0f}, "
        "momentum_event={}, sentiment={}",
        symbol, sms_score, social_score_unified, eligible,
        twitter_raw, dex_raw, birdeye_raw, telegram_raw,
        is_momentum_event, sentiment_result.sentiment_label,
    )

    return result
