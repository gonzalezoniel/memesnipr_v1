from __future__ import annotations

from .broker import BaseBroker, make_broker
from .interfaces import Executor
from .models import FillResult, Mode, OrderRequest


class BrokerExecutor(Executor):
    def __init__(self, broker: BaseBroker):
        self._broker = broker

    def execute(self, request: OrderRequest) -> FillResult:
        return self._broker.send_order(request)


def make_executor(mode: Mode) -> Executor:
    return BrokerExecutor(make_broker(mode))
