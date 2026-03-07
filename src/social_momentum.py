"""
Social Momentum Engine (Section 4).

Creates a Social Momentum Score (SMS) from 0-100 combining:
- twitter_mentions_velocity
- telegram_activity
- reddit_mentions
- dexscreener_trending_rank
- influencer_wallet_activity

Trade eligibility requires SMS >= 65.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from .config import settings
from .social_signals import lookup_token_signal


class SocialMomentumResult:
    """Result of the Social Momentum Score computation."""

    def __init__(
        self,
        sms_score: float = 0.0,
        twitter_score: float = 0.0,
        dex_trending_score: float = 0.0,
        telegram_score: float = 0.0,
        reddit_score: float = 0.0,
        influencer_wallet_score: float = 0.0,
        eligible: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.sms_score = sms_score
        self.twitter_score = twitter_score
        self.dex_trending_score = dex_trending_score
        self.telegram_score = telegram_score
        self.reddit_score = reddit_score
        self.influencer_wallet_score = influencer_wallet_score
        self.eligible = eligible
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "sms_score": round(self.sms_score, 2),
            "sms_eligible": self.eligible,
            "sms_twitter": round(self.twitter_score, 2),
            "sms_dex_trending": round(self.dex_trending_score, 2),
            "sms_telegram": round(self.telegram_score, 2),
            "sms_reddit": round(self.reddit_score, 2),
            "sms_influencer_wallet": round(self.influencer_wallet_score, 2),
        }


def compute_social_momentum_score(
    symbol: str,
    token_address: str = "",
) -> SocialMomentumResult:
    """
    Compute the Social Momentum Score (SMS) for a token.

    The SMS is a weighted score from 0-100 combining multiple social signals.
    Trade eligibility requires SMS >= settings.SMS_MIN_SCORE.
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

    # --- Twitter Mentions Velocity (max 100) ---
    # Higher mentions = stronger twitter signal
    if mentions >= 50:
        twitter_raw = 100.0
    elif mentions >= 20:
        twitter_raw = 80.0
    elif mentions >= 10:
        twitter_raw = 60.0
    elif mentions >= 5:
        twitter_raw = 40.0
    elif mentions >= 2:
        twitter_raw = 20.0
    else:
        twitter_raw = 0.0

    # Boost for positive sentiment
    if sentiment > 0.5:
        twitter_raw = min(twitter_raw * 1.3, 100.0)
    elif sentiment > 0.2:
        twitter_raw = min(twitter_raw * 1.15, 100.0)

    # --- DexScreener Trending (max 100) ---
    # Use trend + engagement as proxy for dex trending rank
    dex_raw = 0.0
    if trend == "rising":
        dex_raw = 70.0
    elif trend == "stable":
        dex_raw = 30.0

    # Engagement boost
    if engagement > 100:
        dex_raw = min(dex_raw + 30.0, 100.0)
    elif engagement > 50:
        dex_raw = min(dex_raw + 20.0, 100.0)
    elif engagement > 10:
        dex_raw = min(dex_raw + 10.0, 100.0)

    # --- Telegram Activity (max 100) ---
    # Use "telegram" in sources as a signal; engagement as proxy
    telegram_raw = 0.0
    if "telegram" in [s.lower() for s in sources]:
        telegram_raw = 50.0
        if engagement > 20:
            telegram_raw = min(telegram_raw + engagement * 0.5, 100.0)
    elif engagement > 0:
        telegram_raw = min(engagement * 0.3, 40.0)

    # --- Reddit Mentions (max 100) ---
    reddit_raw = 0.0
    if "reddit" in [s.lower() for s in sources]:
        reddit_raw = 50.0
        if mentions >= 5:
            reddit_raw = min(reddit_raw + mentions * 2.0, 100.0)
    elif mentions >= 10:
        reddit_raw = min(mentions * 1.5, 40.0)

    # --- Influencer Wallet Activity (max 100) ---
    # This is a placeholder that will use wallet engine data in the future
    # For now, use high engagement + rising trend as proxy
    influencer_raw = 0.0
    if trend == "rising" and engagement > 50 and mentions >= 10:
        influencer_raw = 70.0
    elif trend == "rising" and mentions >= 5:
        influencer_raw = 40.0
    elif engagement > 20:
        influencer_raw = 20.0

    # --- Weighted SMS ---
    sms_score = (
        settings.SMS_TWITTER_WEIGHT * twitter_raw
        + settings.SMS_DEX_TRENDING_WEIGHT * dex_raw
        + settings.SMS_TELEGRAM_WEIGHT * telegram_raw
        + settings.SMS_REDDIT_WEIGHT * reddit_raw
        + settings.SMS_INFLUENCER_WALLET_WEIGHT * influencer_raw
    )
    sms_score = min(max(sms_score, 0.0), 100.0)

    eligible = sms_score >= settings.SMS_MIN_SCORE

    result = SocialMomentumResult(
        sms_score=sms_score,
        twitter_score=twitter_raw,
        dex_trending_score=dex_raw,
        telegram_score=telegram_raw,
        reddit_score=reddit_raw,
        influencer_wallet_score=influencer_raw,
        eligible=eligible,
        details={
            "signal_found": True,
            "mentions": mentions,
            "sentiment": sentiment,
            "trend": trend,
            "engagement": engagement,
            "sources": sources,
        },
    )

    logger.debug(
        "SMS for {}: score={:.1f}, eligible={}, twitter={:.0f}, dex={:.0f}",
        symbol, sms_score, eligible, twitter_raw, dex_raw,
    )

    return result
