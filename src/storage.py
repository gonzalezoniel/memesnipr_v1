from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Iterable

from loguru import logger

from .config import settings
from .models import EngineState, TradeLogEntry, EngineStatus, Mode


def load_engine_state() -> EngineState:
    path = settings.ENGINE_STATE_PATH
    if not os.path.exists(path):
        state = EngineState(
            status=EngineStatus.IDLE,
            mode=Mode.TEST,
            last_heartbeat=None,
        )
        save_engine_state(state)
        return state

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return EngineState.parse_obj(raw)
    except Exception as e:
        logger.exception("Failed to load engine state: {}", e)
        state = EngineState(status=EngineStatus.ERROR, last_error=str(e))
        save_engine_state(state)
        return state


def save_engine_state(state: EngineState) -> None:
    os.makedirs(os.path.dirname(settings.ENGINE_STATE_PATH), exist_ok=True)
    with open(settings.ENGINE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state.dict(), f, default=_json_default, indent=2)


def append_trade_logs(entries: Iterable[TradeLogEntry]) -> None:
    if not entries:
        return
    os.makedirs(os.path.dirname(settings.TRADES_LOG_PATH), exist_ok=True)
    with open(settings.TRADES_LOG_PATH, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry.dict(), default=_json_default) + "\n")


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
