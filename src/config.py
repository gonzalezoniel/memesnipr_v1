from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict
from pydantic import model_validator


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

    # Emergency controls
    KILL_SWITCH: bool = False
    REJECT_ON_UNKNOWN_SIGNALS: bool = False

    # Metadata
    CHAIN: str = "solana"

    # Safety thresholds
    MIN_LIQUIDITY_USD: float = 15_000
    MAX_BUY_TAX_PCT: float = 12.0
    MAX_SELL_TAX_PCT: float = 12.0
    MAX_TOKEN_AGE_MINUTES: int = 45

    # Risk parameters — conservative for consistent profitability
    # ~2% per trade = ~$4 per position, selective entries only
    TEST_RISK_PER_TRADE_PCT: float = 2.0
    TEST_MAX_OPEN_EXPOSURE_PCT: float = 15.0
    LIVE_RISK_PER_TRADE_PCT: float = 2.0
    LIVE_MAX_OPEN_EXPOSURE_PCT: float = 15.0

    # Asymmetric risk control — cut losses fast, protect winners
    BREAKEVEN_AFTER_TP1: bool = True

    MAX_TRADES_PER_DAY: int = 30
    LOSS_STREAK_HALVE_RISK: int = 3
    DAILY_MAX_LOSSES_HALT: int = 8

    # --- v2 Risk Management (Section 1) ---
    SOFT_STOP_PCT: float = 4.0
    MAX_STOP_PCT: float = 6.0

    # --- v2 Breakeven Stop (Section 2) ---
    BREAKEVEN_TRIGGER_PCT: float = 10.0

    # Profit ladder & stops — v2 updated tiers
    STOP_LOSS_PCT: float = 6.0
    TP1_PCT: float = 15.0
    TP1_SELL_PCT: float = 30.0
    TP2_PCT: float = 25.0
    TP2_SELL_PCT: float = 30.0
    TP3_PCT: float = 40.0
    TP3_SELL_PCT: float = 20.0
    TRAILING_STOP_PCT: float = 8.0
    TRAILING_STOP_ACTIVATION_PCT: float = 20.0
    TRAILING_STOP_AFTER_TP1_PCT: float = 5.0
    TRAILING_STOP_AFTER_TP2_PCT: float = 4.0

    # Confidence score thresholds — selective entry, quality over quantity
    MIN_SCORE_TO_TRADE: int = 60
    MAX_RISK_SCORE_TO_TRADE: int = 30
    HIGH_CONFIDENCE_SCORE: int = 75

    # Engine speed
    SCAN_INTERVAL_SECONDS: int = 5

    # Trade pacing — prevent burst-trading at day start
    MAX_NEW_POSITIONS_PER_SCAN: int = 3
    MIN_SECONDS_BETWEEN_TRADES: int = 10

    # --- v2 Trade Frequency Controls (Section 10) ---
    MAX_OPEN_POSITIONS: int = 3
    MAX_TRADES_PER_HOUR: int = 6
    COOLDOWN_AFTER_LOSS_SECONDS: int = 300

    # --- v2 Dynamic Position Sizing (Section 11) ---
    POSITION_SIZE_HIGH_SOL: float = 0.05
    POSITION_SIZE_MED_SOL: float = 0.03
    POSITION_SIZE_LOW_SOL: float = 0.015

    # Minimum quality filters for candidates
    MIN_BUY_RATIO: float = 0.55
    MIN_VOLUME_USD_5M: float = 1_000.0
    MIN_TRANSACTIONS_5M: int = 5

    # --- v2 Momentum Confirmation (Section 3) ---
    MOMENTUM_PRICE_CHANGE_1M_PCT: float = 4.0
    MOMENTUM_VOLUME_SPIKE_MULTIPLIER: float = 2.5
    MOMENTUM_LIQUIDITY_INCREASE_PCT: float = 10.0

    # Early-launch trap heuristics
    SUSPICIOUS_LAUNCH_WINDOW_SECONDS: int = 120
    SUSPICIOUS_MAX_TOP_HOLDER_PCT: float = 35.0
    SUSPICIOUS_MAX_HOLDER_COUNT: int = 50

    # --- v2 Rug Pull Safety Filters (Section 9) ---
    MAX_TOP_HOLDER_PCT: float = 12.0
    MIN_CONTRACT_AGE_SECONDS: int = 60
    MAX_TOP_3_WALLETS_SUPPLY_PCT: float = 25.0

    # --- v2 Social Momentum Engine (Section 4) ---
    SOCIAL_SIGNAL_ENGINE_URL: str = "https://app-sgvdyzun.fly.dev"
    SOCIAL_SIGNAL_WEIGHT: float = 8.0
    SMS_MIN_SCORE: int = 65
    SMS_TWITTER_WEIGHT: float = 0.35
    SMS_DEX_TRENDING_WEIGHT: float = 0.25
    SMS_TELEGRAM_WEIGHT: float = 0.15
    SMS_REDDIT_WEIGHT: float = 0.10
    SMS_INFLUENCER_WALLET_WEIGHT: float = 0.15

    # --- v2 Smart Wallet Tracking (Sections 5-7) ---
    SMART_WALLET_MIN_SCORE: int = 70
    SMART_WALLET_MIN_TRADES: int = 5
    WALLET_DB_PATH: str = "data/wallet_db.json"

    # --- v2 Updated Scoring Weights (Section 8) ---
    SCORE_WEIGHT_LIQUIDITY: float = 0.25
    SCORE_WEIGHT_MOMENTUM: float = 0.20
    SCORE_WEIGHT_SOCIAL: float = 0.20
    SCORE_WEIGHT_WALLET: float = 0.20
    SCORE_WEIGHT_HOLDER: float = 0.10
    SCORE_WEIGHT_AGE: float = 0.05

    # Storage paths
    ENGINE_STATE_PATH: str = "data/engine_state.json"
    TRADES_LOG_PATH: str = "data/trades_log.jsonl"
    AUDIT_LOG_PATH: str = "data/audit_log.jsonl"

    # Paper broker simulation parameters
    PAPER_BROKER_SEED: int = 1337
    PAPER_BASE_PRICE: float = 1.0
    PAPER_FEE_BPS: float = 30.0
    PAPER_MAX_SLIPPAGE_BPS: float = 80.0
    PAPER_FILL_PROBABILITY: float = 1.0

    @property
    def normalized_mode(self) -> str:
        return str(self.MODE).upper().strip()

    @model_validator(mode="after")
    def validate_env(self):
        errors: list[str] = []

        if self.normalized_mode not in {"TEST", "LIVE"}:
            errors.append("MODE must be either TEST or LIVE")

        if not str(self.SOL_RPC_URL).strip():
            errors.append("SOL_RPC_URL is required and cannot be empty")

        if not (0 <= self.PAPER_FILL_PROBABILITY <= 1):
            errors.append("PAPER_FILL_PROBABILITY must be between 0 and 1")

        if self.PAPER_FEE_BPS < 0:
            errors.append("PAPER_FEE_BPS must be >= 0")

        if self.PAPER_MAX_SLIPPAGE_BPS < 0:
            errors.append("PAPER_MAX_SLIPPAGE_BPS must be >= 0")

        if not (0 <= self.MAX_RISK_SCORE_TO_TRADE <= 100):
            errors.append("MAX_RISK_SCORE_TO_TRADE must be between 0 and 100")

        if not (0 <= self.MIN_SCORE_TO_TRADE <= 100):
            errors.append("MIN_SCORE_TO_TRADE must be between 0 and 100")

        if self.SUSPICIOUS_LAUNCH_WINDOW_SECONDS < 0:
            errors.append("SUSPICIOUS_LAUNCH_WINDOW_SECONDS must be >= 0")

        if self.normalized_mode == "LIVE":
            if not str(self.LIVE_WALLET_PRIVATE_KEY or "").strip():
                errors.append("LIVE_WALLET_PRIVATE_KEY is required when MODE=LIVE")
            if not str(self.LIVE_WALLET_PUBLIC_KEY or "").strip():
                errors.append("LIVE_WALLET_PUBLIC_KEY is required when MODE=LIVE")

        if errors:
            raise ValueError("Invalid MEMESNIPR environment configuration: " + "; ".join(errors))

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()


def is_kill_switch_enabled() -> bool:
    """Runtime kill switch check; allows toggling by env without code changes."""
    import os

    runtime_override = os.environ.get("KILL_SWITCH")
    if runtime_override is not None:
        return _env_truthy(runtime_override)
    return settings.KILL_SWITCH


def validate_mode_or_raise() -> None:
    # Construction-time validation already enforces selected mode requirements.
    # Keep this explicit runtime hook for engine startup checks and clear intent.
    settings.validate_env()
