from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from typing import TypeAlias


ZERO = Decimal("0")


def decimal(value: object) -> Decimal:
    """Parse configuration/CSV numerics without routing through binary floats."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def floor_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    return (price / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def ceil_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    return (price / tick).to_integral_value(rounding=ROUND_CEILING) * tick


class Side(str, Enum):
    BID = "bid"
    ASK = "ask"

    @property
    def position_sign(self) -> Decimal:
        return Decimal("1") if self is Side.BID else Decimal("-1")


class AggressorSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    LIVE = "live"
    CANCEL_PENDING = "cancel_pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class FillKind(str, Enum):
    MAKER = "maker"
    EXIT = "exit"


class TimerKind(str, Enum):
    DECISION = "decision"
    QUOTE_CUTOFF = "quote_cutoff"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class Instrument:
    contract_id: str
    tick_size: Decimal
    lot_size: Decimal = Decimal("1")
    mwh_per_lot: Decimal = Decimal("1")
    allow_negative_price: bool = True

    def __post_init__(self) -> None:
        for name in ("tick_size", "lot_size", "mwh_per_lot"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if not self.contract_id:
            raise ValueError("contract_id cannot be empty")
        numeric_values = (self.tick_size, self.lot_size, self.mwh_per_lot)
        if not all(value.is_finite() for value in numeric_values):
            raise ValueError("instrument numerics must be finite")
        if self.tick_size <= 0 or self.lot_size <= 0 or self.mwh_per_lot <= 0:
            raise ValueError("tick_size, lot_size and mwh_per_lot must be positive")


@dataclass(frozen=True, slots=True)
class BookQuote:
    timestamp: datetime
    contract_id: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    sequence: int = 0
    source_row: int = 0

    def __post_init__(self) -> None:
        for name in ("bid_price", "ask_price", "bid_size", "ask_size"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if not all(
            value.is_finite()
            for value in (self.bid_price, self.ask_price, self.bid_size, self.ask_size)
        ):
            raise ValueError("book numerics must be finite")
        if self.ask_price <= self.bid_price:
            raise ValueError("book must have ask_price > bid_price")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("book sizes cannot be negative")

    @property
    def mid(self) -> Decimal:
        return (self.bid_price + self.ask_price) / Decimal("2")


@dataclass(frozen=True, slots=True)
class Trade:
    timestamp: datetime
    contract_id: str
    price: Decimal
    size: Decimal
    aggressor_side: AggressorSide
    sequence: int = 0
    source_row: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", decimal(self.price))
        object.__setattr__(self, "size", decimal(self.size))
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if not self.price.is_finite() or not self.size.is_finite():
            raise ValueError("trade numerics must be finite")
        if self.size <= 0:
            raise ValueError("trade size must be positive")


MarketEvent: TypeAlias = BookQuote | Trade


@dataclass(frozen=True, slots=True)
class TimerEvent:
    timestamp: datetime
    kind: TimerKind


@dataclass(slots=True)
class Order:
    order_id: str
    contract_id: str
    side: Side
    price: Decimal
    quantity: Decimal
    submitted_at: datetime
    active_at: datetime
    reason: str = "market_make"
    remaining: Decimal = field(init=False)
    status: OrderStatus = OrderStatus.PENDING
    cancel_requested_at: datetime | None = None
    cancel_effective_at: datetime | None = None
    queue_ahead: Decimal | None = None
    activated_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        self.price = decimal(self.price)
        self.quantity = decimal(self.quantity)
        if not self.price.is_finite() or not self.quantity.is_finite():
            raise ValueError("order numerics must be finite")
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        self.remaining = self.quantity

    @property
    def is_open(self) -> bool:
        return self.status in {
            OrderStatus.PENDING,
            OrderStatus.LIVE,
            OrderStatus.PARTIAL,
            OrderStatus.CANCEL_PENDING,
        }


@dataclass(frozen=True, slots=True)
class Fill:
    timestamp: datetime
    order_id: str
    contract_id: str
    side: Side
    price: Decimal
    quantity: Decimal
    fee: Decimal
    kind: FillKind
    reason: str
    reference_mid: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", decimal(self.price))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "fee", decimal(self.fee))
        if self.reference_mid is not None:
            object.__setattr__(self, "reference_mid", decimal(self.reference_mid))
        values = (self.price, self.quantity, self.fee)
        if self.reference_mid is not None:
            values += (self.reference_mid,)
        if not all(value.is_finite() for value in values):
            raise ValueError("fill numerics must be finite")
        if self.quantity <= 0:
            raise ValueError("fill quantity must be positive")


@dataclass(frozen=True, slots=True)
class QuoteIntent:
    contract_id: str
    side: Side
    price: Decimal
    quantity: Decimal
    fair_value: Decimal
    reason: str = "market_make"

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", decimal(self.price))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "fair_value", decimal(self.fair_value))
        if not all(
            value.is_finite() for value in (self.price, self.quantity, self.fair_value)
        ):
            raise ValueError("quote intent numerics must be finite")
        if self.quantity <= 0:
            raise ValueError("quote intent quantity must be positive")


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    cash: Decimal
    equity_mid: Decimal | None
    equity_liquidation: Decimal | None
    position_a: Decimal
    position_b: Decimal
    common_mwh: Decimal
    spread_mwh: Decimal
    gross_mwh: Decimal
