import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import validate_mode_or_raise
from src.engine import MemeSniprEngine
from src.models import EngineStatus, TokenCandidate


def _mk_token() -> TokenCandidate:
    now = datetime.now(timezone.utc)
    return TokenCandidate(
        token_address="TEST_TOKEN_1",
        symbol="TST",
        name="Test",
        created_at=now,
        liquidity_usd=600_000,
        buy_tax_pct=1.0,
        sell_tax_pct=1.0,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        is_honeypot=False,
        can_sell=True,
        safety_data_verified=True,
        buys_5m=100,
        sells_5m=20,
        volume_usd_5m=100_000,
        top_holder_pct=5.0,
        holder_count=250,
    )


def test_paper_trade_path_writes_audit_and_trade_log(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setattr(config.settings, "MODE", "TEST")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(config.settings, "PAPER_BROKER_SEED", 42)

    engine = MemeSniprEngine()

    asyncio.run(engine._process_candidate(_mk_token()))

    assert engine.state.daily_trades == 1
    audit_lines = Path(config.settings.AUDIT_LOG_PATH).read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    first = json.loads(audit_lines[0])
    assert first["decision"] == "PAPER_BUY"
    assert "PAPER_FILLED" in first["reason_codes"]


def test_live_mode_requires_env_vars(monkeypatch):
    from src import config

    monkeypatch.setattr(config.settings, "MODE", "LIVE")
    monkeypatch.setattr(config.settings, "LIVE_WALLET_PRIVATE_KEY", None)
    monkeypatch.setattr(config.settings, "LIVE_WALLET_PUBLIC_KEY", None)

    try:
        validate_mode_or_raise()
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "LIVE_WALLET_PRIVATE_KEY" in str(exc)
        assert "LIVE_WALLET_PUBLIC_KEY" in str(exc)


def test_kill_switch_halts_tick(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setenv("KILL_SWITCH", "true")
    monkeypatch.setattr(config.settings, "MODE", "TEST")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    engine = MemeSniprEngine()
    asyncio.run(engine._tick())

    assert engine.state.status == EngineStatus.HALTED
    assert engine.state.halted_reason == "Kill switch enabled"


def test_tick_writes_scan_and_decision_audits(monkeypatch, tmp_path):
    from src import config

    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setattr(config.settings, "MODE", "TEST")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    engine = MemeSniprEngine()
    asyncio.run(engine._tick())

    audit_lines = Path(config.settings.AUDIT_LOG_PATH).read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in audit_lines]
    decisions = [r["decision"] for r in records]

    assert "SCAN_STARTED" in decisions
    assert "SCAN_COMPLETED" in decisions
    assert any(d in {"PAPER_BUY", "REJECT"} for d in decisions)



def test_candidate_rejected_when_risk_score_exceeds_threshold(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setattr(config.settings, "MODE", "TEST")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    engine = MemeSniprEngine()
    token = _mk_token()
    token.freeze_authority_revoked = False
    token.mint_authority_revoked = False
    asyncio.run(engine._process_candidate(token))

    records = [
        json.loads(line)
        for line in Path(config.settings.AUDIT_LOG_PATH).read_text(encoding="utf-8").strip().splitlines()
    ]
    assert records[-1]["decision"] == "REJECT"
    assert "RISK_SCORE_TOO_HIGH" in records[-1]["reason_codes"]


def test_live_mode_uses_same_order_pipeline_but_live_send_differs(monkeypatch, tmp_path):
    from src import config

    monkeypatch.setattr(config.settings, "MODE", "LIVE")
    monkeypatch.setattr(config.settings, "LIVE_WALLET_PRIVATE_KEY", "x")
    monkeypatch.setattr(config.settings, "LIVE_WALLET_PUBLIC_KEY", "y")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    engine = MemeSniprEngine()
    asyncio.run(engine._process_candidate(_mk_token()))

    records = [
        json.loads(line)
        for line in Path(config.settings.AUDIT_LOG_PATH).read_text(encoding="utf-8").strip().splitlines()
    ]
    assert records[-1]["decision"] == "REJECT"
    assert "LIVE_SEND_NOT_IMPLEMENTED" in records[-1]["reason_codes"]
