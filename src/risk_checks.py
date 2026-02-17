from __future__ import annotations

from .interfaces import RiskChecker
from .models import EngineState
from .risk import can_open_new_position


class ExposureRiskChecker(RiskChecker):
    def __init__(self, state: EngineState):
        self._state = state

    def can_open(self, open_positions_size_sol: float, new_size_sol: float) -> bool:
        return can_open_new_position(self._state, open_positions_size_sol, new_size_sol)
