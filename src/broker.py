from __future__ import annotations

import random

from .config import settings
from .models import FillResult, Mode, OrderRequest


class BaseBroker:
    def send_order(self, request: OrderRequest) -> FillResult:
        raise NotImplementedError


class PaperBroker(BaseBroker):
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed if seed is not None else settings.PAPER_BROKER_SEED)

    def send_order(self, request: OrderRequest) -> FillResult:
        fill_roll = self._rng.random()
        if fill_roll > settings.PAPER_FILL_PROBABILITY:
            return FillResult(
                filled=False,
                requested_size_sol=request.size_sol,
                filled_size_sol=0.0,
                avg_price=settings.PAPER_BASE_PRICE,
                reason_code="PAPER_NOT_FILLED",
                venue="paper",
            )

        slip_fraction = self._rng.uniform(0.0, settings.PAPER_MAX_SLIPPAGE_BPS / 10_000.0)
        fee_fraction = settings.PAPER_FEE_BPS / 10_000.0

        avg_price = settings.PAPER_BASE_PRICE * (1.0 + slip_fraction)
        fee_sol = request.size_sol * fee_fraction

        return FillResult(
            filled=True,
            requested_size_sol=request.size_sol,
            filled_size_sol=request.size_sol,
            avg_price=avg_price,
            fee_sol=fee_sol,
            slippage_bps=slip_fraction * 10_000.0,
            reason_code="PAPER_FILLED",
            venue="paper",
        )


class LiveBroker(BaseBroker):
    def send_order(self, request: OrderRequest) -> FillResult:
        # Final-send leg placeholder. Shared order pipeline calls here in LIVE.
        return FillResult(
            filled=False,
            requested_size_sol=request.size_sol,
            filled_size_sol=0.0,
            avg_price=settings.PAPER_BASE_PRICE,
            reason_code="LIVE_SEND_NOT_IMPLEMENTED",
            venue="live",
        )


def make_broker(mode: Mode, seed: int | None = None) -> BaseBroker:
    if mode == Mode.TEST:
        return PaperBroker(seed=seed)
    return LiveBroker()
