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

    # --- v3 Risk Management (Section 1) ---
    SOFT_STOP_PCT: float = 6.0
    MAX_STOP_PCT: float = 6.0

    # --- v3 Breakeven & Trailing Stops (Section 1) ---
    BREAKEVEN_TRIGGER_PCT: float = 8.0
    TRAILING_ACTIVATE_15_PCT: float = 15.0
    TRAILING_STOP_AT_15_PCT: float = 8.0
    TRAILING_ACTIVATE_30_PCT: float = 30.0
    TRAILING_STOP_AT_30_PCT: float = 12.0
    TRAILING_ACTIVATE_60_PCT: float = 60.0
    TRAILING_STOP_AT_60_PCT: float = 18.0

    # Profit ladder & stops — v3 updated tiers
    STOP_LOSS_PCT: float = 6.0
    TP1_PCT: float = 20.0
    TP1_SELL_PCT: float = 40.0
    TP2_PCT: float = 40.0
    TP2_SELL_PCT: float = 30.0
    TP3_PCT: float = 80.0
    TP3_SELL_PCT: float = 30.0
    TRAILING_STOP_PCT: float = 8.0
    TRAILING_STOP_ACTIVATION_PCT: float = 15.0
    TRAILING_STOP_AFTER_TP1_PCT: float = 8.0
    TRAILING_STOP_AFTER_TP2_PCT: float = 12.0

    # Confidence score thresholds — v3: quality over quantity
    MIN_SCORE_TO_TRADE: int = 72
    MAX_RISK_SCORE_TO_TRADE: int = 30
    HIGH_CONFIDENCE_SCORE: int = 80

    # --- v3 Entry Quality Filter (Section 2) ---
    ENTRY_MIN_CONDITIONS: int = 2
    ENTRY_SOCIAL_SCORE_MIN: float = 5.0
    ENTRY_VOLUME_SPIKE_MIN: float = 2.0
    ENTRY_LIQUIDITY_MIN_USD: float = 25_000.0

    # --- v3 Social Signal Influence (Section 6) ---
    SOCIAL_CONFIDENCE_BOOST_6: float = 10.0
    SOCIAL_CONFIDENCE_BOOST_7: float = 18.0
    SOCIAL_BLOCK_BELOW: float = 3.0

    # --- v3 Trap Detection (Section 7) ---
    TRAP_SCORE_THRESHOLD: float = 60.0
    TRAP_WICK_WEIGHT: float = 0.15
    TRAP_SINGLE_WALLET_WEIGHT: float = 0.20
    TRAP_FAKE_VOLUME_WEIGHT: float = 0.20
    TRAP_SHALLOW_LIQ_WEIGHT: float = 0.15
    TRAP_SLIPPAGE_WEIGHT: float = 0.10
    TRAP_SELL_PRESSURE_WEIGHT: float = 0.10
    TRAP_CHURN_WEIGHT: float = 0.10

    # --- v3 Phase Detection (Section 8) ---
    PHASE_FRESH_MAX_AGE_SECONDS: int = 300
    PHASE_EARLY_MAX_AGE_SECONDS: int = 1800
    PHASE_PULLBACK_MAX_AGE_SECONDS: int = 7200
    PHASE_SECONDARY_MAX_AGE_SECONDS: int = 28800
    PHASE_FRESH_SIZE_MULTIPLIER: float = 0.5
    PHASE_EARLY_SIZE_MULTIPLIER: float = 1.0
    PHASE_PULLBACK_SIZE_MULTIPLIER: float = 1.2
    PHASE_SECONDARY_SIZE_MULTIPLIER: float = 0.7
    PHASE_EXHAUSTION_SIZE_MULTIPLIER: float = 0.0

    # Engine speed
    SCAN_INTERVAL_SECONDS: int = 5

    # Trade pacing — prevent burst-trading at day start
    MAX_NEW_POSITIONS_PER_SCAN: int = 3
    MIN_SECONDS_BETWEEN_TRADES: int = 10

    # --- v3 Trade Frequency Controls (Section 10) ---
    MAX_OPEN_POSITIONS: int = 3
    MAX_TRADES_PER_HOUR: int = 6
    COOLDOWN_AFTER_LOSS_SECONDS: int = 300
    LOSS_STREAK_PAUSE_3_SECONDS: int = 600
    LOSS_STREAK_PAUSE_5_SECONDS: int = 1800

    # --- v3 Adaptive Position Sizing (Section 9) ---
    POSITION_SIZE_BASE_SOL: float = 0.03
    POSITION_SIZE_STRONG_MULTIPLIER: float = 1.4
    POSITION_SIZE_MODERATE_MULTIPLIER: float = 0.8
    POSITION_SIZE_WEAK_MULTIPLIER: float = 0.35
    POSITION_SIZE_MAX_LIQUIDITY_IMPACT_PCT: float = 2.0

    # Legacy sizing (kept for backward compat)
    POSITION_SIZE_HIGH_SOL: float = 0.05
    POSITION_SIZE_MED_SOL: float = 0.03
    POSITION_SIZE_LOW_SOL: float = 0.015

    # --- v3 Trade Memory (Section 11) ---
    TRADE_MEMORY_PATH: str = "data/trade_memory.json"
    TRADE_MEMORY_MIN_TRADES_FOR_ADJUSTMENT: int = 10
    TRADE_MEMORY_PENALTY_THRESHOLD_WIN_RATE: float = 35.0
    TRADE_MEMORY_PENALTY_FACTOR: float = 0.7

    # Minimum quality filters for candidates
    MIN_BUY_RATIO: float = 0.55
    MIN_VOLUME_USD_5M: float = 1_000.0
    MIN_TRANSACTIONS_5M: int = 5

    # --- v3 Momentum Confirmation (Section 3) ---
    MOMENTUM_PRICE_CHANGE_1M_PCT: float = 3.0
    MOMENTUM_VOLUME_SPIKE_MULTIPLIER: float = 1.8
    MOMENTUM_LIQUIDITY_INCREASE_PCT: float = 10.0

    # Early-launch trap heuristics
    SUSPICIOUS_LAUNCH_WINDOW_SECONDS: int = 120
    SUSPICIOUS_MAX_TOP_HOLDER_PCT: float = 35.0
    SUSPICIOUS_MAX_HOLDER_COUNT: int = 50

    # --- v2 Rug Pull Safety Filters (Section 9) ---
    MAX_TOP_HOLDER_PCT: float = 12.0
    MIN_CONTRACT_AGE_SECONDS: int = 60
    MAX_TOP_3_WALLETS_SUPPLY_PCT: float = 25.0

    # --- v5 Rug Protection Filters ---
    V5_RUG_DEV_WALLET_MAX_PCT: float = 15.0        # reject if dev owns >15%
    V5_RUG_DEV_SELL_WINDOW_SECONDS: int = 300       # reject if dev sells within 5 min
    V5_RUG_MIN_LIQUIDITY_USD: float = 40_000.0      # reject if liquidity < $40k
    V5_RUG_REJECT_UNLOCKABLE_LIQ: bool = True       # reject if liquidity unlockable

    # --- v5 Signal Scoring Engine ---
    V5_SIGNAL_TRADE_THRESHOLD: int = 5
    V5_SIGNAL_LARGE_POSITION_THRESHOLD: int = 7
    V5_SIGNAL_RUNNER_MODE_THRESHOLD: int = 8

    # --- v5 Dynamic Position Sizing ---
    V5_POSITION_SIZE_SCORE_5_MULTIPLIER: float = 1.0
    V5_POSITION_SIZE_SCORE_6_MULTIPLIER: float = 1.5
    V5_POSITION_SIZE_SCORE_7_MULTIPLIER: float = 2.0

    # --- v5 Runner Detection ---
    V5_RUNNER_PRICE_INCREASE_PCT: float = 25.0
    V5_RUNNER_TRAILING_STOP_PCT: float = 25.0
    V5_RUNNER_MIN_VOLUME_MOMENTUM: float = 3.0

    # --- v5 Smart Wallet Intelligence ---
    V5_SMART_WALLET_MIN_TRADES: int = 10
    V5_SMART_WALLET_MIN_WIN_RATE: float = 60.0
    V5_SMART_WALLET_MIN_AVG_ROI: float = 2.0
    V5_SMART_WALLET_MIN_PROFITABLE_TOKENS: int = 2
    V5_CLUSTER_WINDOW_SECONDS: int = 120
    V5_CLUSTER_MIN_WALLETS: int = 3

    # --- v5 Liquidity Detector ---
    V5_LIQUIDITY_SPIKE_THRESHOLD_PCT: float = 30.0
    V5_LIQUIDITY_WINDOW_SECONDS: int = 300

    # --- v5 Volume Detector ---
    V5_VOLUME_SHORT_WINDOW_SECONDS: int = 180
    V5_VOLUME_LONG_WINDOW_SECONDS: int = 900
    V5_VOLUME_SPIKE_MULTIPLIER: float = 3.0

    # --- v5 Holder Tracker ---
    V5_HOLDER_GROWTH_THRESHOLD_PCT: float = 15.0
    V5_HOLDER_WINDOW_SECONDS: int = 600

    # --- v5 Performance Logging ---
    V5_PERFORMANCE_LOG_PATH: str = "data/v5_performance_log.json"
    V5_DYNAMIC_WEIGHT_ADJUSTMENT: bool = True
    V5_MIN_TRADES_FOR_WEIGHT_ADJUST: int = 20

    # --- v2/v4 Social Momentum Engine ---
    SOCIAL_SIGNAL_ENGINE_URL: str = "https://app-sgvdyzun.fly.dev"
    SOCIAL_SIGNAL_WEIGHT: float = 8.0
    SMS_MIN_SCORE: int = 65

    # v4 unified social momentum weights (Section 7)
    SMS_TWITTER_WEIGHT: float = 0.30
    SMS_DEX_TRENDING_WEIGHT: float = 0.20
    SMS_BIRDEYE_WEIGHT: float = 0.15
    SMS_TELEGRAM_WEIGHT: float = 0.15
    SMS_REDDIT_WEIGHT: float = 0.10
    SMS_WALLET_OVERLAP_WEIGHT: float = 0.10

    # v4 Twitter signal settings (Section 1)
    TWITTER_INFLUENCER_MIN_FOLLOWERS: int = 10_000
    TWITTER_MENTION_VELOCITY_HIGH: float = 5.0  # mentions/min = high signal
    TWITTER_ENGAGEMENT_RATE_HIGH: float = 0.03  # 3% engagement = high
    TWITTER_SIGNAL_CACHE_TTL_SECONDS: int = 300

    # v4 Telegram signal settings (Section 2)
    TELEGRAM_VELOCITY_SPIKE_WINDOW_SECONDS: int = 300  # 5 min window
    TELEGRAM_VELOCITY_SPIKE_MULTIPLIER: float = 3.0  # 3x spike = boost
    TELEGRAM_SIGNAL_CACHE_TTL_SECONDS: int = 300

    # v4 Birdeye settings (Section 4)
    BIRDEYE_API_KEY: str = ""
    BIRDEYE_API_URL: str = "https://public-api.birdeye.so"
    BIRDEYE_SIGNAL_CACHE_TTL_SECONDS: int = 300

    # v4 Pump platform settings (Section 5)
    PUMP_MONITOR_ENABLED: bool = True
    PUMP_EARLY_TRACTION_MIN_BUYERS: int = 10
    PUMP_RAPID_GROWTH_THRESHOLD: float = 2.0  # 2x buyer growth in 5 min

    # v4 Smart wallet social overlap (Section 6)
    WALLET_SOCIAL_CONFIDENCE_BOOST: float = 15.0  # boost when both signals align

    # v4 Social momentum event detection (Section 8)
    SOCIAL_MOMENTUM_EVENT_WINDOW_SECONDS: int = 600  # 10 min window
    SOCIAL_MOMENTUM_EVENT_MULTIPLIER: float = 3.0  # 3x increase = event
    SOCIAL_MOMENTUM_EVENT_CONFIDENCE_BOOST: float = 12.0

    # v4 Sentiment analysis (Section 9)
    SENTIMENT_POSITIVE_WEIGHT: float = 1.0
    SENTIMENT_NEGATIVE_WEIGHT: float = -2.0  # negatives weigh more

    # v4 Spam filter (Section 10)
    SPAM_MIN_ACCOUNT_AGE_DAYS: int = 7
    SPAM_MIN_ENGAGEMENT_RATIO: float = 0.005  # 0.5% minimum engagement
    SPAM_DUPLICATE_MESSAGE_THRESHOLD: int = 3  # flag after 3 identical msgs

    # Legacy weight kept for backward compat
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
