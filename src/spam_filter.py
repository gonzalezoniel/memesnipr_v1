"""
Spam Filter Module (Section 10).

Filters out spam signals from social data to ensure only genuine
community interest is scored. Detects and filters:

- Bot accounts (low engagement ratio, new accounts)
- Repeated copy-paste messages
- Low engagement posts
- Suspicious posting patterns

Uses engagement ratios and account age to filter spam.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .config import settings


@dataclass
class SpamCheckResult:
    """Result of spam filtering for a set of social signals."""
    total_signals: int = 0
    spam_signals: int = 0
    clean_signals: int = 0
    spam_ratio: float = 0.0
    bot_account_count: int = 0
    duplicate_message_count: int = 0
    low_engagement_count: int = 0
    spam_score: float = 0.0  # 0-100 (higher = more spam)
    is_spam_dominated: bool = False
    quality_multiplier: float = 1.0  # 0-1, applied to signal scores

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_signals": self.total_signals,
            "spam_signals": self.spam_signals,
            "clean_signals": self.clean_signals,
            "spam_ratio": round(self.spam_ratio, 3),
            "bot_account_count": self.bot_account_count,
            "duplicate_message_count": self.duplicate_message_count,
            "low_engagement_count": self.low_engagement_count,
            "spam_score": round(self.spam_score, 2),
            "is_spam_dominated": self.is_spam_dominated,
            "quality_multiplier": round(self.quality_multiplier, 3),
        }


@dataclass
class SocialPost:
    """A single social media post/message for spam checking."""
    text: str = ""
    account_age_days: int = 0
    follower_count: int = 0
    following_count: int = 0
    engagement_count: int = 0  # likes + retweets + replies
    impression_count: int = 0
    is_repost: bool = False
    source: str = ""  # twitter, telegram, reddit


# In-memory dedup tracking
_message_hashes: dict[str, Counter[str]] = {}  # token -> hash counter


def _hash_message(text: str) -> str:
    """Create a normalized hash of a message for dedup detection."""
    # Normalize: lowercase, strip whitespace, remove special chars
    normalized = text.lower().strip()
    # Remove common variations (emojis, extra spaces)
    normalized = " ".join(normalized.split())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def check_spam(
    symbol: str,
    posts: list[SocialPost] | None = None,
    signal_data: dict[str, Any] | None = None,
) -> SpamCheckResult:
    """
    Check social signals for spam patterns.

    Parameters
    ----------
    symbol : str
        Token ticker symbol.
    posts : list[SocialPost]
        Individual social posts to check for spam.
    signal_data : dict
        Raw signal data from the Social Signal Engine.
    """
    result = SpamCheckResult()
    key = symbol.upper()

    if posts:
        result.total_signals = len(posts)
        spam_count = 0

        # Get or create message hash counter for this token
        if key not in _message_hashes:
            _message_hashes[key] = Counter()
        hash_counter = _message_hashes[key]

        for post in posts:
            is_spam = False

            # 1. Bot account detection: new account + low engagement
            if (
                post.account_age_days < settings.SPAM_MIN_ACCOUNT_AGE_DAYS
                and post.follower_count < 100
            ):
                is_spam = True
                result.bot_account_count += 1

            # 2. Low engagement ratio detection
            if post.impression_count > 0:
                engagement_ratio = post.engagement_count / post.impression_count
                if engagement_ratio < settings.SPAM_MIN_ENGAGEMENT_RATIO:
                    is_spam = True
                    result.low_engagement_count += 1
            elif post.follower_count > 1000 and post.engagement_count == 0:
                # High follower count but zero engagement = likely bot
                is_spam = True
                result.bot_account_count += 1

            # 3. Duplicate message detection
            if post.text:
                msg_hash = _hash_message(post.text)
                hash_counter[msg_hash] += 1
                if hash_counter[msg_hash] >= settings.SPAM_DUPLICATE_MESSAGE_THRESHOLD:
                    is_spam = True
                    result.duplicate_message_count += 1

            # 4. Suspicious follower/following ratio
            if (
                post.following_count > 0
                and post.follower_count > 0
                and post.following_count / post.follower_count > 10.0
            ):
                is_spam = True
                result.bot_account_count += 1

            if is_spam:
                spam_count += 1

        result.spam_signals = spam_count
        result.clean_signals = result.total_signals - spam_count

    # Use signal data to estimate spam if no raw posts available
    elif signal_data:
        mentions = signal_data.get("mentions", 0)
        engagement = signal_data.get("engagement", 0.0)
        sources = signal_data.get("sources", [])

        result.total_signals = mentions

        # Heuristic: very high mentions with very low engagement = likely spam
        if mentions > 20 and engagement < 5:
            estimated_spam = int(mentions * 0.6)
            result.spam_signals = estimated_spam
            result.clean_signals = mentions - estimated_spam
            result.low_engagement_count = estimated_spam
        elif mentions > 10 and engagement < mentions * 0.5:
            estimated_spam = int(mentions * 0.3)
            result.spam_signals = estimated_spam
            result.clean_signals = mentions - estimated_spam
        else:
            result.clean_signals = mentions

    # Compute spam metrics
    if result.total_signals > 0:
        result.spam_ratio = result.spam_signals / result.total_signals

    # Compute spam score (0-100)
    result.spam_score = min(result.spam_ratio * 100.0, 100.0)

    # Add penalties for specific spam types
    if result.bot_account_count > 5:
        result.spam_score = min(result.spam_score + 15.0, 100.0)
    if result.duplicate_message_count > 10:
        result.spam_score = min(result.spam_score + 20.0, 100.0)

    # Determine if spam-dominated
    result.is_spam_dominated = result.spam_ratio > 0.5 or result.spam_score > 60.0

    # Quality multiplier: reduces signal score based on spam level
    # No spam = 1.0, half spam = 0.6, all spam = 0.1
    if result.spam_ratio <= 0.1:
        result.quality_multiplier = 1.0
    elif result.spam_ratio <= 0.3:
        result.quality_multiplier = 0.85
    elif result.spam_ratio <= 0.5:
        result.quality_multiplier = 0.6
    elif result.spam_ratio <= 0.7:
        result.quality_multiplier = 0.35
    else:
        result.quality_multiplier = 0.1

    logger.debug(
        "Spam check for {}: score={:.1f}, spam_ratio={:.2f}, bots={}, "
        "dupes={}, low_eng={}, quality_mult={:.2f}",
        symbol, result.spam_score, result.spam_ratio, result.bot_account_count,
        result.duplicate_message_count, result.low_engagement_count,
        result.quality_multiplier,
    )

    return result


def get_spam_stats() -> dict[str, int]:
    """Get global spam filter statistics."""
    total_tokens = len(_message_hashes)
    total_hashes = sum(len(c) for c in _message_hashes.values())
    return {
        "tokens_tracked": total_tokens,
        "unique_messages_tracked": total_hashes,
    }
