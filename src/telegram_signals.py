"""
Telegram Meme Group Monitoring Module (Section 2).

Monitors popular Solana meme trading groups for:
- Token mentions and contract address sharing
- Repeated hype messages
- Sudden message spikes

Measures mention_frequency, unique_posters, and velocity spikes.
If mention velocity increases rapidly within 5 minutes, boosts the
social signal score.

Data is sourced from the centralized Social Signal Engine which
aggregates Telegram group activity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from .config import settings


@dataclass
class TelegramSignalResult:
    """Aggregated Telegram signal for a token."""
    mention_count: int = 0
    unique_posters: int = 0
    message_velocity: float = 0.0  # messages per minute
    velocity_spike: bool = False  # True if velocity increased rapidly
    velocity_multiplier: float = 1.0  # current vs baseline velocity
    hype_message_count: int = 0  # repeated hype/shill messages
    group_count: int = 0  # number of groups mentioning token
    telegram_signal_score: float = 0.0  # 0-100
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_count": self.mention_count,
            "unique_posters": self.unique_posters,
            "message_velocity": round(self.message_velocity, 2),
            "velocity_spike": self.velocity_spike,
            "velocity_multiplier": round(self.velocity_multiplier, 2),
            "hype_message_count": self.hype_message_count,
            "group_count": self.group_count,
            "telegram_signal_score": round(self.telegram_signal_score, 2),
        }


# In-memory cache and velocity history
_telegram_cache: dict[str, TelegramSignalResult] = {}
_velocity_history: dict[str, list[tuple[datetime, float]]] = {}


def process_telegram_signal(
    symbol: str,
    token_address: str = "",
    signal_data: dict[str, Any] | None = None,
) -> TelegramSignalResult:
    """
    Process Telegram signal data for a token.

    Parameters
    ----------
    symbol : str
        Token ticker symbol.
    token_address : str
        Token contract address.
    signal_data : dict
        Raw signal data from the Social Signal Engine.
    """
    result = TelegramSignalResult()
    key = symbol.upper()

    if signal_data is None:
        cached = _telegram_cache.get(key) or _telegram_cache.get(token_address)
        if cached is not None:
            return cached
        return result

    sources = signal_data.get("sources", [])
    has_telegram = any(s.lower() == "telegram" for s in sources)

    mentions = signal_data.get("mentions", 0)
    engagement = signal_data.get("engagement", 0.0)

    # Extract Telegram-specific data if available
    tg_data = signal_data.get("telegram", {})
    if tg_data:
        result.mention_count = tg_data.get("mention_count", mentions)
        result.unique_posters = tg_data.get("unique_posters", 0)
        result.group_count = tg_data.get("group_count", 0)
        result.hype_message_count = tg_data.get("hype_messages", 0)
    elif has_telegram:
        result.mention_count = mentions
        result.unique_posters = max(1, int(mentions * 0.5))
        result.group_count = 1
    else:
        # No Telegram data - use general engagement as weak proxy
        if engagement > 10:
            result.mention_count = max(1, int(engagement * 0.1))
            result.unique_posters = max(1, result.mention_count // 2)

    result.sources = sources

    # Message velocity (messages per minute, assume 5-min window)
    time_window_minutes = 5.0
    result.message_velocity = (
        result.mention_count / time_window_minutes if result.mention_count > 0 else 0.0
    )

    # --- Velocity spike detection ---
    now = datetime.now(timezone.utc)
    history = _velocity_history.get(key, [])

    # Prune old entries (keep last 10 minutes)
    cutoff_seconds = settings.SOCIAL_MOMENTUM_EVENT_WINDOW_SECONDS
    history = [
        (ts, vel) for ts, vel in history
        if (now - ts).total_seconds() < cutoff_seconds
    ]
    history.append((now, result.message_velocity))
    _velocity_history[key] = history

    if len(history) >= 2:
        # Compare current velocity to oldest in window
        baseline_velocity = history[0][1]
        if baseline_velocity > 0:
            result.velocity_multiplier = result.message_velocity / baseline_velocity
            if result.velocity_multiplier >= settings.TELEGRAM_VELOCITY_SPIKE_MULTIPLIER:
                result.velocity_spike = True
                logger.info(
                    "Telegram velocity SPIKE for {}: {:.1f}x increase in velocity",
                    symbol, result.velocity_multiplier,
                )

    # --- Compute telegram_signal_score (0-100) ---
    # Components:
    # 1. Mention frequency score (max 35)
    mention_score = 0.0
    if result.mention_count >= 50:
        mention_score = 35.0
    elif result.mention_count >= 20:
        mention_score = 25.0
    elif result.mention_count >= 10:
        mention_score = 18.0
    elif result.mention_count >= 5:
        mention_score = 10.0
    elif result.mention_count > 0:
        mention_score = min(result.mention_count * 2.0, 8.0)

    # 2. Unique posters score (max 25) - more unique posters = more organic
    poster_score = 0.0
    if result.unique_posters >= 20:
        poster_score = 25.0
    elif result.unique_posters >= 10:
        poster_score = 18.0
    elif result.unique_posters >= 5:
        poster_score = 12.0
    elif result.unique_posters > 0:
        poster_score = min(result.unique_posters * 2.0, 8.0)

    # 3. Velocity spike bonus (max 25)
    spike_score = 0.0
    if result.velocity_spike:
        spike_score = min(result.velocity_multiplier * 5.0, 25.0)

    # 4. Multi-group bonus (max 15)
    group_score = 0.0
    if result.group_count >= 5:
        group_score = 15.0
    elif result.group_count >= 3:
        group_score = 10.0
    elif result.group_count >= 2:
        group_score = 5.0

    result.telegram_signal_score = min(
        mention_score + poster_score + spike_score + group_score, 100.0
    )

    # Cache
    _telegram_cache[key] = result
    if token_address:
        _telegram_cache[token_address] = result

    logger.debug(
        "Telegram signal for {}: score={:.1f}, mentions={}, velocity={:.1f}/min, spike={}",
        symbol, result.telegram_signal_score, result.mention_count,
        result.message_velocity, result.velocity_spike,
    )

    return result


def get_telegram_cache_count() -> int:
    """Return number of cached Telegram signals."""
    return len({k: v for k, v in _telegram_cache.items() if v.mention_count > 0})


def clear_telegram_cache() -> None:
    """Clear Telegram caches."""
    global _telegram_cache, _velocity_history
    _telegram_cache = {}
    _velocity_history = {}
