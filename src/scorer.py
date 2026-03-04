from __future__ import annotations

from .interfaces import Scorer
from .models import TokenCandidate
from .scoring import compute_confidence_components
from .social_signals import compute_social_score


class ConfidenceScorer(Scorer):
    def score(self, token: TokenCandidate, features: dict[str, float]) -> dict[str, float]:
        components = compute_confidence_components(token)

        # Add social signal score from the centralized Signal Engine
        social_score, social_details = compute_social_score(
            symbol=token.symbol,
            token_address=token.token_address,
        )
        components.social_signal_score = social_score

        result = {
            "total": float(components.total_score),
            "contract_safety": components.contract_safety_score,
            "liquidity": components.liquidity_score,
            "flow": components.flow_score,
            "holder": components.holder_score,
            "slippage": components.slippage_score,
            "meta": components.meta_score,
            "volume_momentum": components.volume_momentum_score,
            "social_signal": components.social_signal_score,
            **features,
        }

        # Include social signal metadata in features for audit logging
        for key, value in social_details.items():
            if isinstance(value, (int, float)):
                result[key] = float(value)

        return result
