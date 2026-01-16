from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Modes: TEST (test wallet, tiny size) or LIVE (your Phantom wallet)
    MODE: str = "TEST"

    # Solana RPC endpoint (can be a public or private node)
    SOL_RPC_URL: str = "https://api.mainnet-beta.solana.com"

    # Wallets (set via environment variables in Render, never hardcode)
    TEST_WALLET_PRIVATE_KEY: str | None = None
    TEST_WALLET_PUBLIC_KEY: str | None = None
    LIVE_WALLET_PRIVATE_KEY: str | None = None
    LIVE_WALLET_PUBLIC_KEY: str | None = None

    # Safety thresholds
    MIN_LIQUIDITY_USD: float = 50_000
    MAX_BUY_TAX_PCT: float = 10.0
    MAX_SELL_TAX_PCT: float = 10.0
    MAX_TOKEN_AGE_MINUTES: int = 30

    # Risk parameters (percent of wallet)
    TEST_RISK_PER_TRADE_PCT: float = 0.10
    TEST_MAX_OPEN_EXPOSURE_PCT: float = 1.0
    LIVE_RISK_PER_TRADE_PCT: float = 0.50
    LIVE_MAX_OPEN_EXPOSURE_PCT: float = 3.0

    MAX_TRADES_PER_DAY: int = 10
    LOSS_STREAK_HALVE_RISK: int = 2
    DAILY_MAX_LOSSES_HALT: int = 4

    # Profit ladder & stops
    STOP_LOSS_PCT: float = 15.0
    TP1_PCT: float = 15.0
    TP2_PCT: float = 30.0
    TP3_PCT: float = 60.0
    TRAILING_STOP_PCT: float = 18.0

    # Confidence score thresholds
    MIN_SCORE_TO_TRADE: int = 70
    HIGH_CONFIDENCE_SCORE: int = 90

    # Storage paths
    ENGINE_STATE_PATH: str = "data/engine_state.json"
    TRADES_LOG_PATH: str = "data/trades_log.jsonl"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
