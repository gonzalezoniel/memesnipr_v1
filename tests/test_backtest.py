from datetime import datetime, timezone

from src.backtest import (
    BacktestRunner,
    BacktestScenario,
    PriceTick,
    generate_synthetic_scenarios,
)
from src.models import TokenCandidate


def _clean_token(symbol: str = "GOOD", price_usd: float = 0.001) -> TokenCandidate:
    return TokenCandidate(
        token_address=f"BT_{symbol}",
        symbol=symbol,
        name=f"{symbol} Token",
        created_at=datetime.now(timezone.utc),
        liquidity_usd=800_000,
        buy_tax_pct=1.0,
        sell_tax_pct=1.0,
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        is_honeypot=False,
        can_sell=True,
        safety_data_verified=True,
        buys_5m=100,
        sells_5m=15,
        volume_usd_5m=80_000,
        top_holder_pct=4.0,
        holder_count=500,
        price_usd=price_usd,
    )


def _bad_token() -> TokenCandidate:
    return TokenCandidate(
        token_address="BT_BAD",
        symbol="BAD",
        name="Bad Token",
        created_at=datetime.now(timezone.utc),
        liquidity_usd=1_000,
        buy_tax_pct=1.0,
        sell_tax_pct=1.0,
        mint_authority_revoked=False,
        freeze_authority_revoked=False,
        is_honeypot=True,
        can_sell=False,
        buys_5m=5,
        sells_5m=50,
        volume_usd_5m=100,
        top_holder_pct=60.0,
        holder_count=10,
        price_usd=0.001,
    )


def test_bad_token_is_rejected():
    runner = BacktestRunner()
    scenarios = [
        BacktestScenario(label="bad", token=_bad_token(), price_ticks=[]),
    ]
    report = runner.run(scenarios)
    assert report.trades_rejected == 1
    assert report.trades_taken == 0
    assert report.results[0].decision == "REJECT"


def test_clean_token_with_pump_is_accepted():
    runner = BacktestRunner()
    scenarios = [
        BacktestScenario(
            label="pump",
            token=_clean_token(price_usd=0.001),
            price_ticks=[
                PriceTick(offset_seconds=30, price_usd=0.00110),
                PriceTick(offset_seconds=60, price_usd=0.00120),
                PriceTick(offset_seconds=120, price_usd=0.00130),
                PriceTick(offset_seconds=180, price_usd=0.00160),
            ],
        ),
    ]
    report = runner.run(scenarios)
    assert report.trades_taken == 1
    assert report.trades_rejected == 0
    assert report.results[0].decision == "PAPER_BUY"
    assert report.results[0].pnl_sol > 0


def test_stop_loss_triggers():
    runner = BacktestRunner()
    scenarios = [
        BacktestScenario(
            label="dump",
            token=_clean_token(price_usd=0.01),
            price_ticks=[
                PriceTick(offset_seconds=15, price_usd=0.0095),
                PriceTick(offset_seconds=30, price_usd=0.0085),
                PriceTick(offset_seconds=60, price_usd=0.0070),
            ],
        ),
    ]
    report = runner.run(scenarios)
    assert report.trades_taken == 1
    assert report.results[0].exit_reason == "STOP_LOSS"
    assert report.results[0].pnl_sol < 0


def test_report_metrics_calculated():
    runner = BacktestRunner()
    scenarios = [
        BacktestScenario(
            label="win",
            token=_clean_token(symbol="WIN", price_usd=0.001),
            price_ticks=[
                PriceTick(offset_seconds=60, price_usd=0.00120),
                PriceTick(offset_seconds=120, price_usd=0.00160),
            ],
        ),
        BacktestScenario(
            label="loss",
            token=_clean_token(symbol="LOSS", price_usd=0.01),
            price_ticks=[
                PriceTick(offset_seconds=30, price_usd=0.0090),
                PriceTick(offset_seconds=60, price_usd=0.0080),
            ],
        ),
    ]
    report = runner.run(scenarios)
    assert report.scenarios_total == 2
    assert report.wins + report.losses == report.trades_taken
    assert report.win_rate >= 0


def test_synthetic_scenarios_generate_valid_data():
    scenarios = generate_synthetic_scenarios(count=10)
    assert len(scenarios) == 10
    for s in scenarios:
        assert s.token.token_address
        assert s.token.symbol
        assert s.label


def test_mixed_scenarios_produce_report():
    runner = BacktestRunner()
    scenarios = generate_synthetic_scenarios(count=15)
    report = runner.run(scenarios)
    assert report.scenarios_total == 15
    assert report.trades_taken + report.trades_rejected == 15
    assert len(report.results) == 15
    summary = report.format_summary()
    assert "MEMESNIPR BACKTEST REPORT" in summary
    assert "Win Rate" in summary


def test_empty_scenarios_produce_empty_report():
    runner = BacktestRunner()
    report = runner.run([])
    assert report.scenarios_total == 0
    assert report.trades_taken == 0
    assert report.trades_rejected == 0


def test_trailing_stop_triggers():
    runner = BacktestRunner()
    scenarios = [
        BacktestScenario(
            label="trailing",
            token=_clean_token(price_usd=0.001),
            price_ticks=[
                PriceTick(offset_seconds=30, price_usd=0.00110),
                PriceTick(offset_seconds=60, price_usd=0.00130),
                PriceTick(offset_seconds=90, price_usd=0.00150),
                PriceTick(offset_seconds=120, price_usd=0.00125),
                PriceTick(offset_seconds=180, price_usd=0.00110),
            ],
        ),
    ]
    report = runner.run(scenarios)
    assert report.trades_taken == 1
    result = report.results[0]
    assert result.exit_reason in ("TRAILING_STOP", "TP1_PARTIAL", "TP3_HIT")
    assert result.pnl_sol > 0


def test_unverified_token_accepted_when_signals_strong():
    """An unverified token with strong DexScreener signals should now be
    accepted under the relaxed scalper filters (REJECT_ON_UNKNOWN_SIGNALS=false,
    mint/freeze not hard-blocked when unverified)."""
    token = TokenCandidate(
        token_address="BT_UNVERIFIED",
        symbol="UNVER",
        name="Unverified Token",
        created_at=datetime.now(timezone.utc),
        liquidity_usd=800_000,
        buy_tax_pct=1.0,
        sell_tax_pct=1.0,
        mint_authority_revoked=False,
        freeze_authority_revoked=False,
        is_honeypot=False,
        can_sell=True,
        safety_data_verified=False,
        buys_5m=100,
        sells_5m=15,
        volume_usd_5m=80_000,
        top_holder_pct=4.0,
        holder_count=500,
        price_usd=0.001,
    )
    runner = BacktestRunner()
    scenarios = [BacktestScenario(label="unverified", token=token, price_ticks=[])]
    report = runner.run(scenarios)
    assert report.trades_taken == 1
    assert report.results[0].decision == "PAPER_BUY"
