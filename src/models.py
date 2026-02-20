from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class Mode(str, Enum):
    TEST = "TEST"
    LIVE = "LIVE"


class EngineStatus(str, Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    TRADING = "TRADING"
    HALTED = "HALTED"
    ERROR = "ERROR"


class TokenCandidate(BaseModel):
    token_address: str
    symbol: str
    name: str
    created_at: datetime
    liquidity_usd: float
    buy_tax_pct: float
    sell_tax_pct: float
    mint_authority_revoked: bool
    freeze_authority_revoked: bool
    is_honeypot: bool = False
    can_sell: bool = True
    deployer_address: Optional[str] = None

    # Flow / trading behavior
    buys_5m: int = 0
    sells_5m: int = 0
    volume_usd_5m: float = 0.0

    # Holder distribution
    top_holder_pct: float = 0.0
    holder_count: int = 0


class SafetyResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    risk_score: float = 0.0


class ConfidenceComponents(BaseModel):
    contract_safety_score: float = 0.0
    liquidity_score: float = 0.0
    flow_score: float = 0.0
    holder_score: float = 0.0
    slippage_score: float = 0.0
    meta_score: float = 0.0

    @property
    def total_score(self) -> float:
        return (
            self.contract_safety_score
            + self.liquidity_score
            + self.flow_score
            + self.holder_score
            + self.slippage_score
            + self.meta_score
        )


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Position(BaseModel):
    id: str
    token: TokenCandidate
    opened_at: datetime
    size_sol: float
    entry_price: float
    entry_price_usd: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    realized_pnl_sol: float = 0.0
    realized_pnl_usd: float = 0.0
    exit_price_usd: float = 0.0
    exit_reason: Optional[str] = None
    closed_at: Optional[datetime] = None

    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    principal_recovered: bool = False


class TradeLogEntry(BaseModel):
    id: str
    position_id: str
    token_address: str
    side: str  # BUY / SELL
    size_sol: float
    price: float
    timestamp: datetime
    realized_pnl_sol: float = 0.0
    realized_pnl_usd: float = 0.0
    note: Optional[str] = None


class EngineState(BaseModel):
    status: EngineStatus = EngineStatus.IDLE
    mode: Mode = Mode.TEST
    last_heartbeat: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None
    last_error: Optional[str] = None

    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    daily_realized_pnl_sol: float = 0.0
    daily_realized_pnl_usd: float = 0.0
    loss_streak: int = 0
    halted_reason: Optional[str] = None


class AuditRecord(BaseModel):
    timestamp: datetime
    chain: str
    token_address: str
    token_symbol: str
    reason_codes: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    decision: str
    next_actions: list[str] = Field(default_factory=list)


class OrderRequest(BaseModel):
    token: TokenCandidate
    side: str
    size_sol: float
    score: float


class FillResult(BaseModel):
    filled: bool
    requested_size_sol: float
    filled_size_sol: float
    avg_price: float
    fee_sol: float = 0.0
    slippage_bps: float = 0.0
    reason_code: str = ""
    venue: str = ""
