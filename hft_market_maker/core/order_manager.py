"""
Order management: tracks our open limit orders, simulates fills,
and maintains inventory / P&L accounting.

Performance
-----------
Maintains a separate _active dict (at most 2 orders for a basic MM).
process_trade and cancel_all only iterate over this small set.
Dead orders are pruned immediately into _archive for logging only.

Latency model
-------------
Both placement and cancels have configurable latency:
  - submit_order: order only matchable after timestamp + latency
  - cancel_order / cancel_all: cancel only takes effect after timestamp + latency

During the cancel latency window the order is still in _active and can
still fill — this models the real race between your cancel and an
incoming trade at the exchange.

Fill model
----------
  - Resting bid fills when a sell trade arrives at price <= bid
  - Resting ask fills when a buy trade arrives at price >= ask
  - Partial fills supported via queue_model='partial'
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List
import uuid


@dataclass
class Order:
    order_id: str
    side: str            # 'bid' or 'ask'
    price: float
    quantity: float
    timestamp: float     # when submitted
    filled: float = 0.0
    status: str = "open"        # open | partially_filled | filled | cancelled
    active_from: float = 0.0    # matchable only after this timestamp
    cancel_from: float = 0.0    # cancel effective only after this timestamp

    @property
    def remaining(self) -> float:
        return self.quantity - self.filled

    def is_live(self, timestamp: float) -> bool:
        """True if this order can be matched at the given timestamp."""
        if self.status == "filled":
            return False
        if self.status == "cancelled" and timestamp >= self.cancel_from:
            return False
        if timestamp < self.active_from:
            return False
        return True


@dataclass
class Fill:
    order_id: str
    side: str
    price: float
    quantity: float
    timestamp: float
    fee: float = 0.0


class OrderManager:
    """
    Parameters
    ----------
    maker_fee : float
        Fraction of trade value. Negative = rebate. Binance+BNB: 0.00075.
    queue_model : str
        'none'    — fill immediately when price touched
        'partial' — only capture fraction proportional to trade size
    queue_depth_estimate : float
        Fraction of visible volume ahead of us. Used when queue_model='partial'.
    latency : float
        Seconds applied to both placement and cancel. Default 0.0.
        Typical retail co-location: 0.10–0.20.
    """

    def __init__(
        self,
        maker_fee: float = 0.001,
        queue_model: str = "partial",
        queue_depth_estimate: float = 0.3,
        latency: float = 0.0,
    ):
        self.maker_fee = maker_fee
        self.queue_model = queue_model
        self.queue_depth_estimate = queue_depth_estimate
        self.latency = latency

        # _active: only live/pending-cancel orders — ≤2 for a basic MM
        # This is the ONLY dict iterated in the hot path
        self._active: Dict[str, Order] = {}

        # _archive: filled/expired orders for logging only, never matched
        self._archive: Dict[str, Order] = {}

        self.fills: List[Fill] = []

        # P&L — total_pnl = cash + inventory * last_mid
        # cash is debited on buys and credited on sells so it already
        # encodes cost basis — no separate avg_entry_price needed
        self.inventory: float = 0.0
        self.cash: float = 0.0
        self.total_fees: float = 0.0
        self._last_mid: float = 0.0

    # ------------------------------------------------------------------
    # Order lifecycle
    # ------------------------------------------------------------------

    def submit_order(self, side: str, price: float, quantity: float,
                     timestamp: float) -> str:
        order_id = str(uuid.uuid4())[:8]
        self._active[order_id] = Order(
            order_id=order_id,
            side=side,
            price=price,
            quantity=quantity,
            timestamp=timestamp,
            active_from=timestamp + self.latency,
        )
        return order_id

    def cancel_order(self, order_id: str, timestamp: float = 0.0) -> bool:
        order = self._active.get(order_id)
        if order is None or order.status not in ("open", "partially_filled"):
            return False
        order.status = "cancelled"
        order.cancel_from = timestamp + self.latency
        # Keep in _active until cancel_from so it can still fill during window
        return True

    def cancel_all(self, timestamp: float = 0.0) -> int:
        cancelled = 0
        for order in self._active.values():
            if order.status in ("open", "partially_filled"):
                order.status = "cancelled"
                order.cancel_from = timestamp + self.latency
                cancelled += 1
        # Prune orders whose cancel is already effective
        self._prune_expired(timestamp)
        return cancelled

    def get_active_orders(self) -> List[Order]:
        return list(self._active.values())

    # ------------------------------------------------------------------
    # Fill simulation — hot path, called on every trade event
    # ------------------------------------------------------------------

    def process_trade(self, timestamp: float, trade_price: float,
                      trade_qty: float, trade_side: str) -> List[Fill]:
        if not self._active:
            return []

        new_fills: List[Fill] = []
        to_archive: List[str] = []

        for order_id, order in self._active.items():

            if not order.is_live(timestamp):
                # Prune expired cancels lazily
                if order.status == "cancelled" and timestamp >= order.cancel_from:
                    to_archive.append(order_id)
                continue

            # Price match
            if order.side == "bid":
                hit = trade_price <= order.price #drop trade_side==sell
            else:
                hit = trade_price >= order.price

            if not hit:
                continue

            # Fill quantity
            if self.queue_model == "none":
                fill_qty = order.remaining
            else:
                fill_qty = min(order.remaining,
                               trade_qty * (1.0 - self.queue_depth_estimate))

            if fill_qty <= 1e-12:
                continue

            fee = fill_qty * order.price * self.maker_fee

            # Update P&L atomically
            # total_pnl = cash + inventory * mid is always correct:
            # cash debited at cost on buy, credited at price on sell
            if order.side == "bid":
                self.inventory += fill_qty
                self.cash -= fill_qty * order.price + fee
            else:
                self.inventory -= fill_qty
                self.cash += fill_qty * order.price - fee

            if abs(self.inventory) < 1e-10:
                self.inventory = 0.0

            self.total_fees += fee

            fill = Fill(order_id=order_id, side=order.side,
                        price=order.price, quantity=fill_qty,
                        timestamp=timestamp, fee=fee)
            self.fills.append(fill)
            new_fills.append(fill)

            order.filled += fill_qty
            if order.filled >= order.quantity - 1e-10:
                order.status = "filled"
                to_archive.append(order_id)
            else:
                order.status = "partially_filled"

        # Prune dead orders from _active — keeps the dict at ≤2 entries
        for oid in to_archive:
            if oid in self._active:
                self._archive[oid] = self._active.pop(oid)

        return new_fills

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_expired(self, timestamp: float) -> None:
        to_archive = [
            oid for oid, o in self._active.items()
            if o.status == "cancelled" and timestamp >= o.cancel_from
        ]
        for oid in to_archive:
            self._archive[oid] = self._active.pop(oid)

    # ------------------------------------------------------------------
    # P&L
    # ------------------------------------------------------------------

    def update_mid(self, mid: float) -> None:
        self._last_mid = mid

    @property
    def unrealized_pnl(self) -> float:
        return self.inventory * self._last_mid

    @property
    def total_pnl(self) -> float:
        return self.cash + self.unrealized_pnl

    @property
    def n_active(self) -> int:
        return len(self._active)

    @property
    def stats(self) -> dict:
        return {
            "inventory":       self.inventory,
            "cash":            self.cash,
            "unrealized_pnl":  self.unrealized_pnl,
            "total_pnl":       self.total_pnl,
            "total_fees":      self.total_fees,
            "total_fills":     len(self.fills),
            "n_active_orders": self.n_active,
        }

    # Backward-compat shim — avoid in hot paths
    @property
    def orders(self) -> Dict[str, Order]:
        return {**self._active, **self._archive}