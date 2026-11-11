"""Local result records. ALL valuations here use public reference prices.

These are run/report objects, not observations passed to a trading strategy.
"""
from dataclasses import dataclass, field
from typing import Any
from models.models import Fill


@dataclass(frozen=True)
class QuoteRecord:
    tick: int
    asset_id: str
    bot_id: str
    reference_price: float | None
    submitted_bid: float | str | None
    submitted_bid_size: int | str
    submitted_ask: float | str | None
    submitted_ask_size: int | str
    accepted_bid: float | None
    accepted_bid_size: int
    accepted_ask: float | None
    accepted_ask_size: int
    accepted_spread: float | None
    runtime_ns: int
    error: str | None = None


@dataclass(frozen=True)
class BookRecord:
    tick: int
    asset_id: str
    reference_price: float | None
    pre_customer: dict[str, Any]
    post_customer: dict[str, Any]
    dealer_quotes: dict[str, Any] = field(default_factory=dict)
    liquidity: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeRecord:
    tick: int
    time: float
    asset_id: str
    bot_id: str
    side: str
    price: float
    quantity: int
    order_id: str
    fee: float
    cash_change: float
    cash_after: float
    position_after: int
    counterparty_kind: str = "unknown"
    liquidity_role: str = "unknown"


@dataclass(frozen=True)
class EquityRecord:
    tick: int
    bot_id: str
    cash: float
    positions: dict[str, int]
    equity: float
    mark_prices: dict[str, float] = field(default_factory=dict)
    mark_age_ticks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BotErrorRecord:
    tick: int
    bot_id: str
    asset_id: str | None
    message: str


@dataclass
class RunLog:
    quotes: list[QuoteRecord] = field(default_factory=list)
    books: list[BookRecord] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    equity: list[EquityRecord] = field(default_factory=list)
    errors: list[BotErrorRecord] = field(default_factory=list)


@dataclass(frozen=True)
class BotResult:
    bot_id: str
    pnl: float
    final_equity: float
    final_cash: float
    final_positions: dict[str, int]
    per_asset_pnl: dict[str, float]
    fees_paid: float
    fill_count: int
    traded_volume: int
    max_drawdown: float
    equity_history: tuple[float, ...]
    peak_abs_position: dict[str, int] = field(default_factory=dict)
    buy_executions: dict[str, int] = field(default_factory=dict)
    sell_executions: dict[str, int] = field(default_factory=dict)
    per_asset_traded_volume: dict[str, int] = field(default_factory=dict)
    average_spread: dict[str, float | None] = field(default_factory=dict)
    ticks_clipped_by_risk: dict[str, int] = field(default_factory=dict)
    median_runtime_us: float | None = None
    p99_runtime_us: float | None = None
    valuation: str = "public_reference"


@dataclass(frozen=True)
class SimulationResult:
    seed: int
    n_ticks: int
    bot_results: dict[str, BotResult]
    valuation: str = "public_reference"


@dataclass(frozen=True)
class SimulationOutput:
    results: SimulationResult
    log: RunLog
    metadata: dict[str, Any] = field(default_factory=dict)
