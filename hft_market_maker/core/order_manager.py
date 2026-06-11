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

Marketable-on-arrival (taker conversion)
----------------------------------------
With latency, an order can become active into a market that has already moved
THROUGH its limit (e.g. bid 99 arrives when the market is 98). Such an order is
marketable: in reality it crosses and executes as a TAKER at the opposing touch
(the ask for a bid), not as a maker at its stale limit. check_activation() detects
this once, at the instant the order first becomes active, and fills it at the
opposing touch with taker_fee. An order that was genuinely resting (not marketable
on arrival) and is only crossed LATER by the market remains a maker at its limit —
it is the resting liquidity that incoming takers hit at its price.
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
    queue_ahead: float = 0.0    # L2 depth ahead of us at submission (for 'l2' model)
    vol_since_submit: float = 0.0  # cumulative volume at our price since submission
    sigma_at_post: float = 0.0  # market sigma when posted (for risk-based requote gate)
    activation_checked: bool = False  # marketable-on-arrival check done once at activation

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
    is_taker: bool = False   # True if filled by crossing on arrival (marketable order)


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
        taker_fee: float = 0.0,
    ):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.queue_model = queue_model
        self.queue_depth_estimate = queue_depth_estimate
        self.queue_fraction = 1.0  # set externally by backtest for 'l2' mode
        self.latency = latency
        # Prevailing touch (quote events) and last trade price; used to price
        # marketable-on-arrival fills at the closest available reference.
        self._best_bid: float = 0.0
        self._best_ask: float = 0.0
        self._last_quote_ts: float = -1.0
        self._last_trade: float = 0.0
        self._last_trade_ts: float = -1.0

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
                     timestamp: float, queue_ahead: float = 0.0,
                     sigma_at_post: float = 0.0) -> str:
        order_id = str(uuid.uuid4())[:8]
        self._active[order_id] = Order(
            order_id=order_id,
            side=side,
            price=price,
            quantity=quantity,
            timestamp=timestamp,
            active_from=timestamp + self.latency,
            queue_ahead=queue_ahead,
            sigma_at_post=sigma_at_post,
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
    # Marketable-on-arrival (taker) — checked once when an order activates
    # ------------------------------------------------------------------

    def update_book(self, best_bid: float, best_ask: float,
                    timestamp: float) -> None:
        """Record the prevailing touch and its timestamp (on quote events). The
        activation check is run separately by the event loop, BEFORE each event's
        own update, so a marketable-on-arrival order is priced off the market state
        as of its arrival (no look-ahead onto post-arrival prints)."""
        self._best_bid = best_bid
        self._best_ask = best_ask
        self._last_quote_ts = timestamp

    def check_activation(self, timestamp: float) -> List[Fill]:
        """Taker-fill orders that are marketable at the instant they first become
        active. The reference is the FRESHEST side-appropriate market signal with
        timestamp <= the order's arrival (active_from): for a buy the ask or the last
        trade; for a sell the bid or the last trade. If that reference crosses the
        limit the order is a taker filled there; else it rests as a maker. One-shot
        per order via the activation_checked flag."""
        if not self._active:
            return []
        new_fills: List[Fill] = []
        to_archive: List[str] = []
        for order_id, order in self._active.items():
            if order.activation_checked:
                continue
            if timestamp < order.active_from:
                continue                      # not active yet — check later
            if order.status not in ("open", "partially_filled"):
                order.activation_checked = True
                continue
            ta = order.active_from
            # MARKETABILITY is defined by crossing the OPPOSING QUOTE as of arrival
            # (bid >= ask, or ask <= bid). A trade at/through our limit alone does NOT
            # make us a taker — that is a normal maker fill (handled in process_trade).
            quote_fresh = self._last_quote_ts >= 0 and self._last_quote_ts <= ta
            if order.side == "bid":
                marketable = quote_fresh and self._best_ask > 0 and \
                    order.price >= self._best_ask - 1e-12
            else:
                marketable = quote_fresh and self._best_bid > 0 and \
                    order.price <= self._best_bid + 1e-12
            if not marketable:
                order.activation_checked = True       # rests as a maker from here on
                continue
            # FILL PRICE: freshest of {opposing touch, last trade} known at-or-before
            # arrival (the user's "closest trade or ask"), capped at our limit so we
            # never fill worse than the price we were willing to pay.
            touch = self._best_ask if order.side == "bid" else self._best_bid
            cands = [(self._last_quote_ts, touch)]
            if self._last_trade > 0 and self._last_trade_ts <= ta:
                cands.append((self._last_trade_ts, self._last_trade))
            ref = max(cands, key=lambda c: c[0])[1]   # freshest signal as of arrival
            fill_price = min(ref, order.price) if order.side == "bid" \
                else max(ref, order.price)
            fill_qty = order.remaining
            fee = fill_qty * fill_price * self.taker_fee
            if order.side == "bid":
                self.inventory += fill_qty
                self.cash -= fill_qty * fill_price + fee
            else:
                self.inventory -= fill_qty
                self.cash += fill_qty * fill_price - fee
            if abs(self.inventory) < 1e-10:
                self.inventory = 0.0
            self.total_fees += fee

            fill = Fill(order_id=order_id, side=order.side, price=fill_price,
                        quantity=fill_qty, timestamp=timestamp, fee=fee, is_taker=True)
            self.fills.append(fill)
            new_fills.append(fill)
            order.filled += fill_qty
            order.status = "filled"
            to_archive.append(order_id)

        for oid in to_archive:
            if oid in self._active:
                self._archive[oid] = self._active.pop(oid)
        return new_fills

    # ------------------------------------------------------------------
    # Fill simulation — hot path, called on every trade event
    # ------------------------------------------------------------------

    def process_trade(self, timestamp: float, trade_price: float,
                      trade_qty: float, trade_side: str) -> List[Fill]:
        # Record this trade as a reference for future marketable-on-arrival pricing.
        # (The activation check itself runs in the event loop BEFORE this update, so
        # it sees only at-or-before-arrival references — no look-ahead.)
        self._last_trade = trade_price
        self._last_trade_ts = timestamp
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
            elif self.queue_model == "l2":
                # Queue-clearing model: accumulate volume at our price level.
                # We only fill after cumulative volume exceeds queue_ahead.
                vol_before = order.vol_since_submit
                order.vol_since_submit += trade_qty
                vol_after = order.vol_since_submit
                if vol_after <= order.queue_ahead:
                    continue  # queue not yet cleared
                # Volume of this trade that reaches us after clearing the queue
                vol_to_us = vol_after - max(order.queue_ahead, vol_before)
                fill_qty = min(order.remaining, vol_to_us)
            else:  # 'partial'
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