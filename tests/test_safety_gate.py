from datetime import datetime, timezone

from src.models import TokenCandidate
from src.safety import evaluate_safety


def _base_token() -> TokenCandidate:
    return TokenCandidate(
        token_address="TOKEN_ADDR",
        symbol="TKN",
        name="Token",
        created_at=datetime.now(timezone.utc),
        liquidity_usd=100_000,
        buy_tax_pct=1.0,
        sell_tax_pct=1.0,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        is_honeypot=False,
        can_sell=True,
        safety_data_verified=True,
        buys_5m=10,
        sells_5m=3,
        volume_usd_5m=10_000,
        top_holder_pct=8.0,
        holder_count=200,
    )


def test_safety_gate_passes_clean_token():
    result = evaluate_safety(_base_token())
    assert result.passed
    assert result.reason_codes == []
    assert result.risk_score == 0.0


def test_safety_gate_rejects_unknown_signals_when_enabled(monkeypatch):
    from src import config

    monkeypatch.setattr(config.settings, "REJECT_ON_UNKNOWN_SIGNALS", True)

    token = _base_token()
    token.token_address = ""
    token.symbol = ""
    token.liquidity_usd = float("nan")

    result = evaluate_safety(token)

    assert not result.passed
    assert "UNKNOWN_TOKEN_ADDRESS" in result.reason_codes
    assert "UNKNOWN_TOKEN_SYMBOL" in result.reason_codes
    assert "UNKNOWN_LIQUIDITY" in result.reason_codes
    assert result.risk_score >= 60.0


def test_safety_gate_rejects_honeypot_with_reason_code():
    token = _base_token()
    token.is_honeypot = True

    result = evaluate_safety(token)

    assert not result.passed
    assert "HONEYPOT_OR_CANNOT_SELL" in result.reason_codes


def test_safety_gate_rejects_suspicious_early_distribution():
    token = _base_token()
    token.top_holder_pct = 60.0
    token.holder_count = 12

    result = evaluate_safety(token)

    assert not result.passed
    assert "SUSPICIOUS_EARLY_DISTRIBUTION" in result.reason_codes
