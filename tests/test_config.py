import pytest

from src.config import Settings


def test_settings_valid_in_test_mode_with_required_defaults():
    s = Settings(MODE="TEST", SOL_RPC_URL="https://rpc.example")
    assert s.normalized_mode == "TEST"


def test_settings_fails_for_invalid_mode():
    with pytest.raises(ValueError, match="MODE must be either TEST or LIVE"):
        Settings(MODE="DEMO", SOL_RPC_URL="https://rpc.example")


def test_settings_fails_fast_for_live_missing_wallet_envs():
    with pytest.raises(ValueError, match="LIVE_WALLET_PRIVATE_KEY is required when MODE=LIVE"):
        Settings(MODE="LIVE", SOL_RPC_URL="https://rpc.example", LIVE_WALLET_PUBLIC_KEY="pub-only")


def test_settings_fails_for_invalid_paper_fill_probability():
    with pytest.raises(ValueError, match="PAPER_FILL_PROBABILITY must be between 0 and 1"):
        Settings(MODE="TEST", SOL_RPC_URL="https://rpc.example", PAPER_FILL_PROBABILITY=1.2)


def test_settings_fails_for_invalid_risk_threshold():
    with pytest.raises(ValueError, match="MAX_RISK_SCORE_TO_TRADE must be between 0 and 100"):
        Settings(MODE="TEST", SOL_RPC_URL="https://rpc.example", MAX_RISK_SCORE_TO_TRADE=101)
