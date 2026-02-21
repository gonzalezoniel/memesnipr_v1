import asyncio
from datetime import datetime, timezone

from src.engine import MemeSniprEngine
from src.interfaces import Executor, Scanner
from src.models import FillResult, OrderRequest, TokenCandidate
from src.storage import load_recent_audit_records, summarize_audit_records


class TwoTokenScanner(Scanner):
    async def scan_candidates(self) -> list[TokenCandidate]:
        now = datetime.now(timezone.utc)
        reject = TokenCandidate(
            token_address="BAD",
            symbol="BAD",
            name="Bad",
            created_at=now,
            liquidity_usd=1000,
            buy_tax_pct=1.0,
            sell_tax_pct=1.0,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            is_honeypot=False,
            can_sell=True,
            buys_5m=1,
            sells_5m=5,
            volume_usd_5m=100,
            top_holder_pct=50.0,
            holder_count=5,
        )
        accept = TokenCandidate(
            token_address="GOOD",
            symbol="GOOD",
            name="Good",
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
            sells_5m=10,
            volume_usd_5m=80_000,
            top_holder_pct=5.0,
            holder_count=400,
        )
        return [reject, accept]


class AlwaysFillExecutor(Executor):
    def execute(self, request: OrderRequest) -> FillResult:
        return FillResult(
            filled=True,
            requested_size_sol=request.size_sol,
            filled_size_sol=request.size_sol,
            avg_price=1.01,
            fee_sol=request.size_sol * 0.003,
            slippage_bps=25.0,
            reason_code="CUSTOM_EXECUTOR_FILLED",
            venue="custom",
        )


def test_swappable_scanner_and_executor_integration(monkeypatch, tmp_path):
    from src import config

    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setattr(config.settings, "MODE", "TEST")
    monkeypatch.setattr(config.settings, "ENGINE_STATE_PATH", str(tmp_path / "engine_state.json"))
    monkeypatch.setattr(config.settings, "TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setattr(config.settings, "AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    engine = MemeSniprEngine(scanner=TwoTokenScanner(), executor=AlwaysFillExecutor())
    asyncio.run(engine._tick())

    records = load_recent_audit_records(limit=100)
    summary = summarize_audit_records(records)

    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] >= 1
    assert any(r.reason_codes and "CUSTOM_EXECUTOR_FILLED" in r.reason_codes for r in records)
