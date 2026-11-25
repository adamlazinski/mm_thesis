from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Callable, Iterable

from .config import BacktestConfig
from .domain import (
    AggressorSide,
    BookQuote,
    Fill,
    FillKind,
    Order,
    OrderStatus,
    QuoteIntent,
    Side,
    Trade,
    ZERO,
)


RiskCheck = Callable[[QuoteIntent, Iterable[Order]], bool]


class OrderManager:
    """Deterministic post-only lifecycle with placement/cancel latency and L1 queue."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self._ids = count(1)
        self.n_post_only_rejects = 0
        self.n_risk_rejects = 0

    def open_orders(self) -> list[Order]:
        return [order for order in self.orders.values() if order.is_open]

    def submit(self, intent: QuoteIntent, now: datetime) -> Order:
        latency = timedelta(milliseconds=self.config.execution.new_order_latency_ms)
        order = Order(
            order_id=f"MM-{next(self._ids):08d}",
            contract_id=intent.contract_id,
            side=intent.side,
            price=intent.price,
            quantity=intent.quantity,
            submitted_at=now,
            active_at=now + latency,
            reason=intent.reason,
        )
        self.orders[order.order_id] = order
        return order

    def request_cancel(self, order: Order, now: datetime) -> None:
        if not order.is_open or order.cancel_effective_at is not None:
            return
        order.cancel_requested_at = now
        order.cancel_effective_at = now + timedelta(
            milliseconds=self.config.execution.cancel_latency_ms
        )
        if order.status in {OrderStatus.LIVE, OrderStatus.PARTIAL}:
            order.status = OrderStatus.CANCEL_PENDING

    def cancel_all(self, now: datetime) -> None:
        for order in self.open_orders():
            self.request_cancel(order, now)

    def _cancel(self, order: Order, timestamp: datetime) -> None:
        if not order.is_open:
            return
        order.status = OrderStatus.CANCELLED
        order.closed_at = timestamp

    def _activate(self, order: Order, timestamp: datetime, books: dict[str, BookQuote]) -> None:
        if order.status is not OrderStatus.PENDING:
            return
        book = books.get(order.contract_id)
        if book is None:
            order.status = OrderStatus.REJECTED
            order.closed_at = timestamp
            self.n_post_only_rejects += 1
            return
        marketable = (
            order.side is Side.BID and order.price >= book.ask_price
        ) or (
            order.side is Side.ASK and order.price <= book.bid_price
        )
        if marketable:
            order.status = OrderStatus.REJECTED
            order.closed_at = timestamp
            self.n_post_only_rejects += 1
            return
        qf = self.config.execution.queue_fraction
        if order.side is Side.BID:
            if order.price == book.bid_price:
                order.queue_ahead = book.bid_size * qf
            elif order.price > book.bid_price:
                order.queue_ahead = ZERO
            else:
                order.queue_ahead = None
        else:
            if order.price == book.ask_price:
                order.queue_ahead = book.ask_size * qf
            elif order.price < book.ask_price:
                order.queue_ahead = ZERO
            else:
                order.queue_ahead = None
        order.status = OrderStatus.LIVE
        order.activated_at = timestamp

    def _advance(self, timestamp: datetime, books: dict[str, BookQuote], inclusive: bool) -> None:
        before = (lambda value: value <= timestamp) if inclusive else (lambda value: value < timestamp)
        for order in self.open_orders():
            if order.cancel_effective_at is not None and before(order.cancel_effective_at):
                self._cancel(order, order.cancel_effective_at)
                continue
            if order.status is OrderStatus.PENDING and before(order.active_at):
                self._activate(order, order.active_at, books)

    def advance_before(self, timestamp: datetime, books: dict[str, BookQuote]) -> None:
        self._advance(timestamp, books, inclusive=False)

    def advance_through(self, timestamp: datetime, books: dict[str, BookQuote]) -> None:
        self._advance(timestamp, books, inclusive=True)

    def eligible_order_ids(self, timestamp: datetime) -> set[str]:
        eligible: set[str] = set()
        for order in self.open_orders():
            live_status = order.status in {
                OrderStatus.LIVE,
                OrderStatus.PARTIAL,
                OrderStatus.CANCEL_PENDING,
            }
            cancel_has_not_won = (
                order.cancel_effective_at is None or order.cancel_effective_at >= timestamp
            )
            if live_status and order.active_at < timestamp and cancel_has_not_won:
                eligible.add(order.order_id)
        return eligible

    def _fee(self, order: Order, quantity: Decimal, maker: bool) -> Decimal:
        instrument = self.config.instruments[order.contract_id]
        mwh = quantity * instrument.mwh_per_lot
        notional = abs(order.price * mwh)
        if maker:
            return (
                mwh * self.config.execution.maker_fee_per_mwh
                + notional * self.config.execution.maker_fee_rate
            )
        return (
            mwh * self.config.execution.taker_fee_per_mwh
            + notional * self.config.execution.taker_fee_rate
        )

    def _maker_fill(
        self,
        order: Order,
        timestamp: datetime,
        quantity: Decimal,
        reference_mid: Decimal | None,
    ) -> Fill:
        quantity = min(quantity, order.remaining)
        fill = Fill(
            timestamp=timestamp,
            order_id=order.order_id,
            contract_id=order.contract_id,
            side=order.side,
            price=order.price,
            quantity=quantity,
            fee=self._fee(order, quantity, maker=True),
            kind=FillKind.MAKER,
            reason=order.reason,
            reference_mid=reference_mid,
        )
        order.remaining -= quantity
        if order.remaining == 0:
            order.status = OrderStatus.FILLED
            order.closed_at = timestamp
        elif order.cancel_effective_at is not None:
            order.status = OrderStatus.CANCEL_PENDING
        else:
            order.status = OrderStatus.PARTIAL
        self.fills.append(fill)
        return fill

    def match_trade(
        self,
        trade: Trade,
        eligible_ids: set[str],
        books: dict[str, BookQuote],
    ) -> list[Fill]:
        if self.config.execution.fill_model != "trade_queue":
            return []
        desired_side = Side.BID if trade.aggressor_side is AggressorSide.SELL else Side.ASK
        candidates = [
            order
            for order in self.open_orders()
            if order.order_id in eligible_ids
            and order.contract_id == trade.contract_id
            and order.side is desired_side
            and (
                trade.price <= order.price
                if desired_side is Side.BID
                else trade.price >= order.price
            )
        ]
        candidates.sort(
            key=lambda order: (
                -order.price if desired_side is Side.BID else order.price,
                order.active_at,
                order.order_id,
            )
        )
        available = trade.size
        fills: list[Fill] = []
        reference_mid = books.get(trade.contract_id).mid if trade.contract_id in books else None
        for order in candidates:
            traded_through = (
                trade.price < order.price if order.side is Side.BID else trade.price > order.price
            )
            if traded_through:
                quantity = order.remaining
            else:
                if order.queue_ahead is None:
                    continue
                consumed = min(available, order.queue_ahead)
                order.queue_ahead -= consumed
                available -= consumed
                if order.queue_ahead > 0 or available <= 0:
                    continue
                quantity = min(order.remaining, available)
                available -= quantity
            if quantity > 0:
                fills.append(self._maker_fill(order, trade.timestamp, quantity, reference_mid))
            if available <= 0 and not traded_through:
                break
        return fills

    def match_quote_through(
        self,
        quote: BookQuote,
        eligible_ids: set[str],
    ) -> list[Fill]:
        if self.config.execution.fill_model != "quote_through":
            return []
        fills: list[Fill] = []
        for order in list(self.open_orders()):
            if order.order_id not in eligible_ids or order.contract_id != quote.contract_id:
                continue
            crossed_through = (
                order.side is Side.BID and quote.ask_price < order.price
            ) or (
                order.side is Side.ASK and quote.bid_price > order.price
            )
            if crossed_through:
                fills.append(
                    self._maker_fill(order, quote.timestamp, order.remaining, quote.mid)
                )
        return fills

    def reconcile(
        self,
        intents: list[QuoteIntent],
        now: datetime,
        risk_check: RiskCheck,
    ) -> None:
        desired = {(intent.contract_id, intent.side): intent for intent in intents}
        keys = [
            (contract_id, side)
            for contract_id in self.config.instruments
            for side in (Side.BID, Side.ASK)
        ]
        for key in keys:
            intent = desired.get(key)
            existing = [
                order
                for order in self.open_orders()
                if (order.contract_id, order.side) == key
            ]
            if intent is None:
                for order in existing:
                    self.request_cancel(order, now)
                continue

            instrument = self.config.instruments[intent.contract_id]
            threshold = instrument.tick_size * self.config.strategy.refresh_ticks
            reusable = next(
                (
                    order
                    for order in existing
                    if order.cancel_effective_at is None
                    and abs(order.price - intent.price) < threshold
                    and order.quantity == intent.quantity
                ),
                None,
            )
            if reusable is not None:
                continue
            for order in existing:
                self.request_cancel(order, now)
            if existing:
                # No overlapping replacement during the cancel/fill race.
                continue
            if risk_check(intent, self.open_orders()):
                self.submit(intent, now)
            else:
                self.n_risk_rejects += 1

