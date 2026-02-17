from __future__ import annotations

from .interfaces import FeatureExtractor
from .models import TokenCandidate


class DefaultFeatureExtractor(FeatureExtractor):
    def extract(self, token: TokenCandidate) -> dict[str, float]:
        total = max(1, token.buys_5m + token.sells_5m)
        buy_ratio = token.buys_5m / total
        return {
            "buy_ratio_5m": float(buy_ratio),
            "volume_usd_5m": float(token.volume_usd_5m),
            "holder_count": float(token.holder_count),
            "top_holder_pct": float(token.top_holder_pct),
            "liquidity_usd": float(token.liquidity_usd),
        }
