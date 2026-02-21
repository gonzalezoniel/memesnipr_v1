from __future__ import annotations

from .interfaces import Scorer
from .models import TokenCandidate
from .scoring import compute_confidence_components


class ConfidenceScorer(Scorer):
    def score(self, token: TokenCandidate, features: dict[str, float]) -> dict[str, float]:
        components = compute_confidence_components(token)
        return {
            "total": float(components.total_score),
            "contract_safety": components.contract_safety_score,
            "liquidity": components.liquidity_score,
            "flow": components.flow_score,
            "holder": components.holder_score,
            "slippage": components.slippage_score,
            "meta": components.meta_score,
            "volume_momentum": components.volume_momentum_score,
            **features,
        }
