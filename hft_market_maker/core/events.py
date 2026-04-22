"""
Event system for the HFT market making simulator.
All market activity is modelled as a stream of typed events sorted by timestamp.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import numpy as np


class EventType(Enum):
    TRADE = auto()       # A trade occurred on the exchange
    QUOTE = auto()       # Order book top-of-book update
    ORDER_FILL = auto()  # One of our orders got filled
    ORDER_CANCEL = auto()
    TIMER = auto()       # Periodic recalculation trigger


@dataclass(order=True)
class Event:
    """
    Base event. Sorted by timestamp so we can use a heap / sorted list.
    """
    timestamp: float          # Unix epoch in seconds (use microseconds if available)
    event_type: EventType = field(compare=False)
    data: dict = field(default_factory=dict, compare=False)


@dataclass
class TradeEvent:
    """
    Represents a single trade on the exchange (aggressor hitting the book).
    """
    timestamp: float
    price: float
    quantity: float
    side: str              # 'buy' or 'sell' (aggressor side)
    trade_id: Optional[str] = None

    def to_event(self) -> Event:
        return Event(
            timestamp=self.timestamp,
            event_type=EventType.TRADE,
            data={"trade": self}
        )


@dataclass
class QuoteEvent:
    """
    Top-of-book snapshot from the exchange.
    """
    timestamp: float
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    def to_event(self) -> Event:
        return Event(
            timestamp=self.timestamp,
            event_type=EventType.QUOTE,
            data={"quote": self}
        )


@dataclass
class FillEvent:
    """
    One of our resting limit orders was filled.
    """
    timestamp: float
    order_id: str
    side: str          # 'bid' or 'ask'
    price: float
    quantity: float
    fee: float = 0.0

    def to_event(self) -> Event:
        return Event(
            timestamp=self.timestamp,
            event_type=EventType.ORDER_FILL,
            data={"fill": self}
        )
