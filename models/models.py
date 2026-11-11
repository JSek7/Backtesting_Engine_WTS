"""Public bot API and execution models, trimmed from the organiser's models.

Do not redefine QuoteAction in a submitted bot: import this shared class.
"""
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class QuoteAction:
    bid_price: float | None
    bid_size: int
    ask_price: float | None
    ask_size: int


@dataclass(frozen=True)
class BotSubmission:
    bot_id: str
    quotes: dict[str, QuoteAction]
    runtime_ns: int


@dataclass
class BookOrder:
    order_id: str
    owner_type: str
    owner_id: str
    side: str
    price: float
    remaining: int
    time: float
    sequence: int
    time_in_force: str
    flow_type: str = "unknown"


@dataclass(frozen=True)
class Fill:
    asset_id: str
    time: float
    price: float
    quantity: int
    buyer_bot: str | None
    seller_bot: str | None
    buy_order_id: str
    sell_order_id: str
    buyer_kind: str = "unknown"
    seller_kind: str = "unknown"
    taker_side: str | None = None


@dataclass
class BotAccount:
    cash: float = 0.0
    positions: dict[str, int] = field(default_factory=dict)
    fees_paid: float = 0.0


@dataclass(frozen=True)
class OwnFill:
    time: float
    side: str
    price: float
    quantity: int
    order_id: str


@dataclass(frozen=True)
class AssetObservation:
    price_history: tuple[float | None, ...]
    book: dict
    position: int
    recent_fills: tuple[OwnFill, ...]


@dataclass(frozen=True)
class Observation:
    tick: int
    markets: dict[str, AssetObservation]
    cash: float


@dataclass(frozen=True)
class MarketEvent:
    time: float
    kind: Literal["reference_update", "dealer_cancel", "dealer_limit", "customer_order"]
    data: dict[str, Any]
    sequence: int = 0


@dataclass(frozen=True)
class MarketStep:
    start_time: int
    end_time: int
    events: tuple[MarketEvent, ...]
