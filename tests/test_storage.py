import json
from pathlib import Path

from src.models import AuditRecord, EngineState, EngineStatus, Mode
from src.storage import append_audit_records, load_engine_state, save_engine_state


def test_load_state_uses_settings_mode_when_file_missing(monkeypatch, tmp_path):
    state_path = tmp_path / "engine_state.json"

    from src import storage

    monkeypatch.setattr(storage.settings, "ENGINE_STATE_PATH", str(state_path))
    monkeypatch.setattr(storage.settings, "MODE", "LIVE")

    state = load_engine_state()

    assert state.mode == Mode.LIVE
    assert state.status == EngineStatus.IDLE


def test_save_state_writes_valid_json(monkeypatch, tmp_path):
    state_path = tmp_path / "engine_state.json"

    from src import storage

    monkeypatch.setattr(storage.settings, "ENGINE_STATE_PATH", str(state_path))

    save_engine_state(EngineState(mode=Mode.TEST, status=EngineStatus.SCANNING))

    raw = json.loads(Path(state_path).read_text(encoding="utf-8"))
    assert raw["mode"] == "TEST"
    assert raw["status"] == "SCANNING"


def test_append_audit_records_supports_filename_only_path(monkeypatch, tmp_path):
    from src import storage

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(storage.settings, "AUDIT_LOG_PATH", "audit.jsonl")

    append_audit_records([
        AuditRecord(
            timestamp="2026-01-01T00:00:00Z",
            chain="solana",
            token_address="A",
            token_symbol="A",
            reason_codes=["SCAN_STARTED"],
            scores={"scanned_count": 1.0},
            thresholds={},
            decision="SCAN_STARTED",
            next_actions=["continue_scanning"],
        )
    ])

    assert Path("audit.jsonl").exists()
    payload = json.loads(Path("audit.jsonl").read_text(encoding="utf-8").strip())
    assert payload["decision"] == "SCAN_STARTED"
