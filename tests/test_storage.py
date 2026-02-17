import json
from pathlib import Path

from src.models import EngineState, EngineStatus, Mode
from src.storage import load_engine_state, save_engine_state


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
