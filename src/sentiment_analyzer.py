"""
Sentiment Analysis Module (Section 9).

Analyzes message sentiment using keyword-based NLP to detect
positive and negative signals in social media messages about tokens.

Positive signals: "moon", "send", "next 100x", "apes", "buy now", etc.
Negative signals: "rug", "dev dump", "honeypot", "scam", etc.

Adjusts social_score based on aggregate sentiment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .config import settings

# --- Keyword dictionaries ---
# Positive keywords with weights (higher = stronger signal)
_POSITIVE_KEYWORDS: list[tuple[str, float]] = [
    (r"\bmoon\b", 1.0),
    (r"\bmooning\b", 1.2),
    (r"\bto the moon\b", 1.5),
    (r"\bsend\b", 0.8),
    (r"\bsend it\b", 1.0),
    (r"\bnext 100x\b", 2.0),
    (r"\b100x\b", 1.8),
    (r"\b1000x\b", 2.0),
    (r"\b10x\b", 1.0),
    (r"\b50x\b", 1.5),
    (r"\bapes\b", 0.8),
    (r"\bape in\b", 1.0),
    (r"\baping\b", 1.0),
    (r"\bbuy now\b", 1.2),
    (r"\bbullish\b", 1.0),
    (r"\bgem\b", 1.0),
    (r"\bhidden gem\b", 1.5),
    (r"\bearly\b", 0.8),
    (r"\bpump\b", 0.7),
    (r"\bpumping\b", 1.0),
    (r"\brocket\b", 0.8),
    (r"\blambo\b", 0.8),
    (r"\blfg\b", 0.8),
    (r"\blets go\b", 0.6),
    (r"\blet's go\b", 0.6),
    (r"\bfomo\b", 0.7),
    (r"\bbased\b", 0.7),
    (r"\bdegen\b", 0.5),
    (r"\bsolana gem\b", 1.2),
    (r"\bnext solana\b", 1.0),
]

# Negative keywords with weights (higher magnitude = stronger negative signal)
_NEGATIVE_KEYWORDS: list[tuple[str, float]] = [
    (r"\brug\b", 2.0),
    (r"\brugged\b", 2.5),
    (r"\brug pull\b", 3.0),
    (r"\bdev dump\b", 2.5),
    (r"\bdev sold\b", 2.0),
    (r"\bhoneypot\b", 3.0),
    (r"\bscam\b", 2.0),
    (r"\bscammer\b", 2.0),
    (r"\bstay away\b", 1.5),
    (r"\bavoid\b", 1.0),
    (r"\bdump\b", 1.0),
    (r"\bdumping\b", 1.5),
    (r"\bdead\b", 1.0),
    (r"\bdead coin\b", 1.5),
    (r"\bno liquidity\b", 2.0),
    (r"\blocked lp\b", -0.5),  # actually positive
    (r"\bmint enabled\b", 2.0),
    (r"\bwarn\b", 1.0),
    (r"\bwarning\b", 1.2),
    (r"\bfake\b", 1.5),
    (r"\bfraud\b", 2.0),
    (r"\bselling\b", 0.5),
    (r"\bcrash\b", 1.0),
    (r"\bcrashing\b", 1.5),
    (r"\btax\b", 0.8),
    (r"\bhigh tax\b", 1.5),
    (r"\binsider\b", 1.2),
]

# Pre-compile patterns for performance
_COMPILED_POSITIVE = [(re.compile(pat, re.IGNORECASE), w) for pat, w in _POSITIVE_KEYWORDS]
_COMPILED_NEGATIVE = [(re.compile(pat, re.IGNORECASE), w) for pat, w in _NEGATIVE_KEYWORDS]


@dataclass
class SentimentResult:
    """Result of sentiment analysis for a token."""
    positive_score: float = 0.0
    negative_score: float = 0.0
    net_sentiment: float = 0.0  # -1.0 to 1.0
    positive_keywords_found: list[str] = field(default_factory=list)
    negative_keywords_found: list[str] = field(default_factory=list)
    message_count_analyzed: int = 0
    sentiment_label: str = "neutral"  # positive, negative, neutral
    sentiment_adjustment: float = 0.0  # adjustment to apply to social score

    def to_dict(self) -> dict[str, Any]:
        return {
            "positive_score": round(self.positive_score, 2),
            "negative_score": round(self.negative_score, 2),
            "net_sentiment": round(self.net_sentiment, 3),
            "positive_keywords": self.positive_keywords_found[:10],
            "negative_keywords": self.negative_keywords_found[:10],
            "message_count_analyzed": self.message_count_analyzed,
            "sentiment_label": self.sentiment_label,
            "sentiment_adjustment": round(self.sentiment_adjustment, 2),
        }


def analyze_sentiment(
    messages: list[str] | None = None,
    signal_sentiment: float = 0.0,
    signal_data: dict[str, Any] | None = None,
) -> SentimentResult:
    """
    Analyze sentiment from social media messages or signal data.

    Parameters
    ----------
    messages : list[str]
        Raw messages to analyze for sentiment keywords.
    signal_sentiment : float
        Pre-computed sentiment from the Signal Engine (-1 to 1).
    signal_data : dict
        Raw signal data that may contain sentiment info.
    """
    result = SentimentResult()

    # Analyze raw messages if provided
    if messages:
        result.message_count_analyzed = len(messages)
        total_positive = 0.0
        total_negative = 0.0
        pos_keywords_set: set[str] = set()
        neg_keywords_set: set[str] = set()

        for msg in messages:
            # Check positive keywords
            for pattern, weight in _COMPILED_POSITIVE:
                if pattern.search(msg):
                    total_positive += weight * settings.SENTIMENT_POSITIVE_WEIGHT
                    pos_keywords_set.add(pattern.pattern.strip(r"\b"))

            # Check negative keywords
            for pattern, weight in _COMPILED_NEGATIVE:
                if pattern.search(msg):
                    if weight < 0:
                        # Negative weight in negative list = actually positive
                        total_positive += abs(weight) * settings.SENTIMENT_POSITIVE_WEIGHT
                    else:
                        total_negative += weight * abs(settings.SENTIMENT_NEGATIVE_WEIGHT)
                    neg_keywords_set.add(pattern.pattern.strip(r"\b"))

        result.positive_score = total_positive
        result.negative_score = total_negative
        result.positive_keywords_found = list(pos_keywords_set)
        result.negative_keywords_found = list(neg_keywords_set)

        # Compute net sentiment
        total = total_positive + total_negative
        if total > 0:
            result.net_sentiment = (total_positive - total_negative) / total
        else:
            result.net_sentiment = 0.0

    # Use Signal Engine sentiment as fallback or supplement
    if signal_data:
        engine_sentiment = signal_data.get("sentiment", signal_sentiment)
        if result.message_count_analyzed == 0:
            # No messages analyzed, use engine sentiment directly
            result.net_sentiment = max(-1.0, min(1.0, engine_sentiment))
            if engine_sentiment > 0:
                result.positive_score = engine_sentiment * 10.0
            else:
                result.negative_score = abs(engine_sentiment) * 10.0
        else:
            # Blend message-based and engine sentiment (70/30 weight)
            result.net_sentiment = 0.7 * result.net_sentiment + 0.3 * engine_sentiment
    elif signal_sentiment != 0.0 and result.message_count_analyzed == 0:
        result.net_sentiment = max(-1.0, min(1.0, signal_sentiment))
        if signal_sentiment > 0:
            result.positive_score = signal_sentiment * 10.0
        else:
            result.negative_score = abs(signal_sentiment) * 10.0

    # Classify sentiment
    if result.net_sentiment > 0.3:
        result.sentiment_label = "positive"
    elif result.net_sentiment < -0.2:
        result.sentiment_label = "negative"
    else:
        result.sentiment_label = "neutral"

    # Compute score adjustment for social_score
    # Positive sentiment: boost up to +1.5 on the 0-10 scale
    # Negative sentiment: penalize up to -3.0 (negatives matter more)
    if result.net_sentiment > 0.5:
        result.sentiment_adjustment = 1.5
    elif result.net_sentiment > 0.3:
        result.sentiment_adjustment = 1.0
    elif result.net_sentiment > 0.1:
        result.sentiment_adjustment = 0.5
    elif result.net_sentiment < -0.5:
        result.sentiment_adjustment = -3.0
    elif result.net_sentiment < -0.3:
        result.sentiment_adjustment = -2.0
    elif result.net_sentiment < -0.1:
        result.sentiment_adjustment = -1.0
    else:
        result.sentiment_adjustment = 0.0

    logger.debug(
        "Sentiment analysis: net={:.3f}, label={}, adjustment={:+.1f}, "
        "pos_kw={}, neg_kw={}",
        result.net_sentiment, result.sentiment_label, result.sentiment_adjustment,
        len(result.positive_keywords_found), len(result.negative_keywords_found),
    )

    return result


def analyze_text_sentiment(text: str) -> float:
    """
    Quick sentiment score for a single text string.

    Returns a value from -1.0 (very negative) to 1.0 (very positive).
    """
    result = analyze_sentiment(messages=[text])
    return result.net_sentiment
