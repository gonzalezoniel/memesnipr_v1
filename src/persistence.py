from __future__ import annotations

from .models import AuditRecord, EngineState, TradeLogEntry
from .storage import append_audit_records, append_trade_logs, load_engine_state, save_engine_state


class JsonPersistence:
    def load_state(self) -> EngineState:
        return load_engine_state()

    def save_state(self, state: EngineState) -> None:
        save_engine_state(state)

    def append_trades(self, trades: list[TradeLogEntry]) -> None:
        append_trade_logs(trades)

    def append_audits(self, records: list[AuditRecord]) -> None:
        append_audit_records(records)
