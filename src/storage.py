from __future__ import annotations

import json
from collections import Counter
import os
import tempfile
from datetime import datetime
from typing import Iterable

from loguru import logger

from .config import settings
from .models import AuditRecord, EngineState, TradeLogEntry, EngineStatus, Mode


def load_engine_state() -> EngineState:
    path = settings.ENGINE_STATE_PATH
    if not os.path.exists(path):
        mode = Mode.TEST if str(settings.MODE).upper() == Mode.TEST.value else Mode.LIVE
        state = EngineState(
            status=EngineStatus.IDLE,
            mode=mode,
            last_heartbeat=None,
        )
        save_engine_state(state)
        return state

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return EngineState.model_validate(raw)
    except Exception as e:
        logger.exception("Failed to load engine state: {}", e)
        state = EngineState(status=EngineStatus.ERROR, last_error=str(e))
        save_engine_state(state)
        return state


def save_engine_state(state: EngineState) -> None:
    state_dir = os.path.dirname(settings.ENGINE_STATE_PATH)
    os.makedirs(state_dir, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=state_dir, prefix="engine_state_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state.model_dump(), f, default=_json_default, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, settings.ENGINE_STATE_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def append_trade_logs(entries: Iterable[TradeLogEntry]) -> None:
    if not entries:
        return
    os.makedirs(os.path.dirname(settings.TRADES_LOG_PATH), exist_ok=True)
    with open(settings.TRADES_LOG_PATH, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry.model_dump(), default=_json_default) + "\n")


def append_audit_records(records: Iterable[AuditRecord]) -> None:
    records = list(records)
    if not records:
        return
    os.makedirs(os.path.dirname(settings.AUDIT_LOG_PATH), exist_ok=True)
    with open(settings.AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.model_dump(), default=_json_default) + "\n")


def load_recent_trades(limit: int = 100) -> list[TradeLogEntry]:
    path = settings.TRADES_LOG_PATH
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    rows = lines[-limit:]
    entries: list[TradeLogEntry] = []
    for row in rows:
        row = row.strip()
        if not row:
            continue
        try:
            entries.append(TradeLogEntry.model_validate(json.loads(row)))
        except Exception as exc:
            logger.warning("Skipping invalid trade row: {}", exc)
    return entries


def load_recent_audit_records(limit: int = 200) -> list[AuditRecord]:
    path = settings.AUDIT_LOG_PATH
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    rows = lines[-limit:]
    records: list[AuditRecord] = []
    for row in rows:
        row = row.strip()
        if not row:
            continue
        try:
            records.append(AuditRecord.model_validate(json.loads(row)))
        except Exception as exc:
            logger.warning("Skipping invalid audit row: {}", exc)
    return records


def summarize_audit_records(records: list[AuditRecord]) -> dict:
    accepted = 0
    rejected = 0
    rejection_reasons: Counter[str] = Counter()

    for rec in records:
        if rec.decision == "REJECT":
            rejected += 1
            for code in rec.reason_codes:
                if code not in {"SAFETY_GATE_REJECT"}:
                    rejection_reasons[code] += 1
        elif rec.decision in {"PAPER_BUY", "BUY"}:
            accepted += 1

    last_decision = records[-1].model_dump(mode="json") if records else None
    top_reasons = [{"code": code, "count": count} for code, count in rejection_reasons.most_common(5)]

    return {
        "accepted_count": accepted,
        "rejected_count": rejected,
        "last_decision": last_decision,
        "top_rejection_reasons": top_reasons,
    }


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
