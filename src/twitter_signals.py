"""
Twitter (X) Meme Detection Module (Section 1).

Monitors memecoin mentions on Twitter/X by tracking:
- $TOKEN ticker mentions
- Token name mentions
- Contract address mentions

Computes a twitter_signal_score based on:
- mention_velocity (mentions per minute)
- engagement_rate (likes + retweets + replies / impressions)
- influencer_weight (accounts with >10k followers)

Data is fetched from the centralized Social Signal Engine which
aggregates Twitter data.  This module processes and scores the raw
signals for the unified social momentum pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .config import settings


@dataclass
class TwitterMention:
    """A single Twitter mention of a token."""
    account_handle: str = ""
    follower_count: int = 0
    tweet_text: str = ""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_influencer: bool = False
    engagement_ratio: float = 0.0


@dataclass
class TwitterSignalResult:
    """Aggregated Twitter signal for a token."""
    mention_count: int = 0
    unique_accounts: int = 0
    total_engagement: int = 0
    influencer_count: int = 0
    influencer_weight_score: float = 0.0
    mention_velocity: float = 0.0  # mentions per minute
    engagement_rate: float = 0.0
    twitter_signal_score: float = 0.0  # 0-100
    mentions: list[TwitterMention] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_count": self.mention_count,
            "unique_accounts": self.unique_accounts,
            "total_engagement": self.total_engagement,
            "influencer_count": self.influencer_count,
            "influencer_weight_score": round(self.influencer_weight_score, 2),
            "mention_velocity": round(self.mention_velocity, 2),
            "engagement_rate": round(self.engagement_rate, 4),
            "twitter_signal_score": round(self.twitter_signal_score, 2),
        }


# In-memory cache of Twitter signals per token
_twitter_cache: dict[str, TwitterSignalResult] = {}
_cache_updated_at: datetime | None = None


def process_twitter_signal(
    symbol: str,
    token_address: str = "",
    signal_data: dict[str, Any] | None = None,
) -> TwitterSignalResult:
    """
    Process Twitter signal data for a token.

    Parameters
    ----------
    symbol : str
        Token ticker symbol.
    token_address : str
        Token contract address.
    signal_data : dict
        Raw signal data from the Social Signal Engine containing
        Twitter-specific fields (mentions, engagement, sources, etc.).
    """
    result = TwitterSignalResult()

    if signal_data is None:
        # Check cache
        cached = _twitter_cache.get(symbol.upper()) or _twitter_cache.get(token_address)
        if cached is not None:
            return cached
        return result

    # Extract Twitter-specific data from the signal
    mentions = signal_data.get("mentions", 0)
    engagement = signal_data.get("engagement", 0.0)
    sources = signal_data.get("sources", [])
    sentiment = signal_data.get("sentiment", 0.0)

    # Check if Twitter is among the sources
    has_twitter = any(s.lower() in ("twitter", "x", "twitter/x") for s in sources)

    result.mention_count = mentions
    result.total_engagement = int(engagement)
    result.sources = sources

    # Estimate unique accounts (typically ~60-80% of mentions are unique)
    result.unique_accounts = max(1, int(mentions * 0.7)) if mentions > 0 else 0

    # Mention velocity: assume data covers ~5 min window
    time_window_minutes = 5.0
    result.mention_velocity = mentions / time_window_minutes if mentions > 0 else 0.0

    # Engagement rate: engagement / (mentions * estimated avg reach)
    estimated_reach = mentions * 500  # rough avg reach per mention
    result.engagement_rate = (
        engagement / max(estimated_reach, 1) if engagement > 0 else 0.0
    )

    # Influencer detection from signal data
    influencer_data = signal_data.get("influencers", [])
    if influencer_data:
        result.influencer_count = len(influencer_data)
        # Weight by follower count
        total_followers = sum(
            inf.get("followers", 0) for inf in influencer_data
        )
        result.influencer_weight_score = min(
            (total_followers / 100_000) * 50.0, 100.0
        )
    elif has_twitter and mentions >= 5:
        # Estimate influencer presence from mention count and engagement
        # High engagement with moderate mentions suggests influencer involvement
        if engagement > 100 and mentions >= 10:
            result.influencer_count = max(1, mentions // 10)
            result.influencer_weight_score = min(engagement / 10.0, 60.0)
        elif engagement > 50:
            result.influencer_count = 1
            result.influencer_weight_score = min(engagement / 5.0, 40.0)

    # --- Compute twitter_signal_score (0-100) ---
    # Components:
    # 1. Mention velocity score (max 40)
    velocity_score = 0.0
    if result.mention_velocity >= settings.TWITTER_MENTION_VELOCITY_HIGH:
        velocity_score = 40.0
    elif result.mention_velocity >= 2.0:
        velocity_score = 30.0
    elif result.mention_velocity >= 1.0:
        velocity_score = 20.0
    elif result.mention_velocity > 0:
        velocity_score = min(result.mention_velocity * 10.0, 15.0)

    # 2. Engagement rate score (max 30)
    engagement_score = 0.0
    if result.engagement_rate >= settings.TWITTER_ENGAGEMENT_RATE_HIGH:
        engagement_score = 30.0
    elif result.engagement_rate >= 0.01:
        engagement_score = 20.0
    elif result.engagement_rate > 0:
        engagement_score = min(result.engagement_rate * 1000.0, 15.0)

    # 3. Influencer weight score (max 30)
    influencer_score = min(result.influencer_weight_score * 0.3, 30.0)

    # Sentiment boost/penalty
    sentiment_modifier = 0.0
    if sentiment > 0.5:
        sentiment_modifier = 5.0
    elif sentiment > 0.2:
        sentiment_modifier = 2.0
    elif sentiment < -0.3:
        sentiment_modifier = -10.0
    elif sentiment < 0:
        sentiment_modifier = -5.0

    result.twitter_signal_score = min(
        max(velocity_score + engagement_score + influencer_score + sentiment_modifier, 0.0),
        100.0,
    )

    # Cache the result
    _twitter_cache[symbol.upper()] = result
    if token_address:
        _twitter_cache[token_address] = result

    logger.debug(
        "Twitter signal for {}: score={:.1f}, mentions={}, velocity={:.1f}/min, "
        "influencers={}, engagement_rate={:.4f}",
        symbol, result.twitter_signal_score, result.mention_count,
        result.mention_velocity, result.influencer_count, result.engagement_rate,
    )

    return result


def get_twitter_cache_count() -> int:
    """Return number of cached Twitter signals."""
    return len({k: v for k, v in _twitter_cache.items() if v.mention_count > 0})


def clear_twitter_cache() -> None:
    """Clear the Twitter signal cache."""
    global _twitter_cache, _cache_updated_at
    _twitter_cache = {}
    _cache_updated_at = None
