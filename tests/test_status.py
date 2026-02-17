import asyncio

from dashboard.main import health, status
from src.models import AuditRecord, EngineState, EngineStatus, Mode
from src.storage import append_audit_records


def test_status_endpoint_reports_decision_counts(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    append_audit_records([
        AuditRecord(
            timestamp="2026-01-01T00:00:00Z",
            chain="solana",
            token_address="A",
            token_symbol="A",
            reason_codes=["LOW_CONFIDENCE_SCORE"],
            scores={},
            thresholds={},
            decision="REJECT",
            next_actions=["skip"],
        ),
        AuditRecord(
            timestamp="2026-01-01T00:00:01Z",
            chain="solana",
            token_address="B",
            token_symbol="B",
            reason_codes=["PAPER_BUY_EXECUTED"],
            scores={},
            thresholds={},
            decision="PAPER_BUY",
            next_actions=["monitor"],
        ),
    ])

    payload = asyncio.run(status())

    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 1
    assert payload["last_decision"]["decision"] == "PAPER_BUY"
    assert payload["top_rejection_reasons"][0]["code"] == "LOW_CONFIDENCE_SCORE"


def test_health_endpoint_returns_plain_mode_and_status(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))

    payload = asyncio.run(health())

    assert payload["mode"] == "TEST"
    assert payload["status"] in {"IDLE", "SCANNING", "TRADING", "HALTED", "ERROR"}


def test_health_endpoint_sets_ok_false_when_engine_error(monkeypatch, tmp_path):
    from src import storage

    monkeypatch.setattr(storage.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    storage.save_engine_state(EngineState(mode=Mode.TEST, status=EngineStatus.ERROR, last_error="boom"))

    payload = asyncio.run(health())

    assert payload["status"] == "ERROR"
    assert payload["ok"] is False
