from __future__ import annotations

from typing import Protocol

from .models import FillResult, OrderRequest, TokenCandidate


class Scanner(Protocol):
    async def scan_candidates(self) -> list[TokenCandidate]:
        ...


class FeatureExtractor(Protocol):
    def extract(self, token: TokenCandidate) -> dict[str, float]:
        ...


class Scorer(Protocol):
    def score(self, token: TokenCandidate, features: dict[str, float]) -> dict[str, float]:
        ...


class RiskChecker(Protocol):
    def can_open(self, open_positions_size_sol: float, new_size_sol: float) -> bool:
        ...


class Executor(Protocol):
    def execute(self, request: OrderRequest) -> FillResult:
        ...
