from datetime import datetime, timezone

from src.broker import LiveBroker, PaperBroker
from src.models import OrderRequest, TokenCandidate


def _order(size: float = 0.01) -> OrderRequest:
    token = TokenCandidate(
        token_address="TKN",
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
        buys_5m=10,
        sells_5m=2,
        volume_usd_5m=10000,
        top_holder_pct=5.0,
        holder_count=200,
    )
    return OrderRequest(token=token, side="BUY", size_sol=size, score=90)


def test_paper_broker_is_deterministic_with_seed(monkeypatch):
    from src import config

    monkeypatch.setattr(config.settings, "PAPER_FILL_PROBABILITY", 1.0)
    monkeypatch.setattr(config.settings, "PAPER_MAX_SLIPPAGE_BPS", 50.0)
    monkeypatch.setattr(config.settings, "PAPER_FEE_BPS", 30.0)
    monkeypatch.setattr(config.settings, "PAPER_BASE_PRICE", 1.0)

    b1 = PaperBroker(seed=7)
    b2 = PaperBroker(seed=7)

    r1 = b1.send_order(_order())
    r2 = b2.send_order(_order())

    assert r1.filled and r2.filled
    assert r1.avg_price == r2.avg_price
    assert r1.slippage_bps == r2.slippage_bps
    assert r1.fee_sol == r2.fee_sol


def test_live_broker_only_differs_at_final_send():
    result = LiveBroker().send_order(_order())
    assert not result.filled
    assert result.reason_code == "LIVE_SEND_NOT_IMPLEMENTED"
    assert result.venue == "live"
