from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .config import BacktestConfig
from .domain import (
    BookQuote,
    EquityPoint,
    Fill,
    FillKind,
    MarketEvent,
    Order,
    Side,
    TimerEvent,
    TimerKind,
    Trade,
    ZERO,
)
from .execution import OrderManager
from .portfolio import Portfolio
from .risk import RiskManager
from .strategy import CoupledMarketMaker


@dataclass(frozen=True, slots=True)
class SessionResult:
    local_date: str
    exit_timestamp: str
    status: str
    actual_spread_b_minus_a: Decimal | None
    target_spread_b_minus_a: Decimal
    forecast_error: Decimal | None
    message: str = ""


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class BacktestResult:
    summary: dict[str, object]
    fills: list[Fill]
    orders: list[Order]
    equity_curve: list[EquityPoint]
    sessions: list[SessionResult]

    def write(self, output_dir: str | Path) -> None:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        with (destination / "summary.json").open("w", encoding="utf-8") as handle:
            json.dump(_jsonable(self.summary), handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        with (destination / "fills.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "order_id",
                    "contract_id",
                    "side",
                    "price",
                    "quantity",
                    "fee",
                    "kind",
                    "reason",
                    "reference_mid",
                ],
            )
            writer.writeheader()
            for fill in self.fills:
                writer.writerow(
                    {
                        "timestamp": fill.timestamp.isoformat(),
                        "order_id": fill.order_id,
                        "contract_id": fill.contract_id,
                        "side": fill.side.value,
                        "price": str(fill.price),
                        "quantity": str(fill.quantity),
                        "fee": str(fill.fee),
                        "kind": fill.kind.value,
                        "reason": fill.reason,
                        "reference_mid": "" if fill.reference_mid is None else str(fill.reference_mid),
                    }
                )

        with (destination / "orders.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "order_id",
                    "contract_id",
                    "side",
                    "price",
                    "quantity",
                    "remaining",
                    "submitted_at",
                    "active_at",
                    "status",
                    "cancel_requested_at",
                    "cancel_effective_at",
                    "queue_ahead",
                    "reason",
                ],
            )
            writer.writeheader()
            for order in self.orders:
                writer.writerow(
                    {
                        "order_id": order.order_id,
                        "contract_id": order.contract_id,
                        "side": order.side.value,
                        "price": str(order.price),
                        "quantity": str(order.quantity),
                        "remaining": str(order.remaining),
                        "submitted_at": order.submitted_at.isoformat(),
                        "active_at": order.active_at.isoformat(),
                        "status": order.status.value,
                        "cancel_requested_at": (
                            "" if order.cancel_requested_at is None else order.cancel_requested_at.isoformat()
                        ),
                        "cancel_effective_at": (
                            "" if order.cancel_effective_at is None else order.cancel_effective_at.isoformat()
                        ),
                        "queue_ahead": "" if order.queue_ahead is None else str(order.queue_ahead),
                        "reason": order.reason,
                    }
                )

        with (destination / "equity.csv").open("w", newline="", encoding="utf-8") as handle:
            fieldnames = list(asdict(self.equity_curve[0])) if self.equity_curve else ["timestamp"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for point in self.equity_curve:
                row = asdict(point)
                row["timestamp"] = point.timestamp.isoformat()
                for key, value in row.items():
                    if isinstance(value, Decimal):
                        row[key] = str(value)
                writer.writerow(row)

        with (destination / "sessions.json").open("w", encoding="utf-8") as handle:
            json.dump(_jsonable([asdict(session) for session in self.sessions]), handle, indent=2)
            handle.write("\n")


class BacktestEngine:
    """Causal, timestamp-batched replay for a two-contract market maker."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.portfolio = Portfolio(config.instruments)
        self.order_manager = OrderManager(config)
        self.risk = RiskManager(config.pair, config.instruments, config.risk)
        self.strategy = CoupledMarketMaker(config)
        self.books: dict[str, BookQuote] = {}
        self.equity_curve: list[EquityPoint] = []
        self.sessions: list[SessionResult] = []
        self._last_quote_decision: dict[date, datetime] = {}
        self._exited_dates: set[date] = set()

    def _session_times(self, local_date: date) -> tuple[datetime, datetime]:
        zone = self.config.session.zone
        exit_timestamp = datetime.combine(local_date, self.config.session.exit_time, tzinfo=zone)
        cutoff = exit_timestamp - timedelta(
            milliseconds=self.config.session.cancel_before_exit_ms
        )
        return cutoff, exit_timestamp

    def _timers(self, events: Iterable[MarketEvent]) -> list[TimerEvent]:
        dates = {
            event.timestamp.astimezone(self.config.session.zone).date()
            for event in events
        }
        timers: list[TimerEvent] = []
        for local_date in sorted(dates):
            cutoff, exit_timestamp = self._session_times(local_date)
            timers.append(TimerEvent(cutoff, TimerKind.QUOTE_CUTOFF))
            timers.append(TimerEvent(exit_timestamp, TimerKind.EXIT))
        return timers

    def _books_fresh(self, timestamp: datetime) -> bool:
        for contract_id in self.config.instruments:
            book = self.books.get(contract_id)
            if book is None:
                return False
            age_ms = Decimal(str((timestamp - book.timestamp).total_seconds())) * Decimal("1000")
            if age_ms < 0 or age_ms > self.config.session.max_quote_age_ms:
                return False
        return True

    def _can_quote(self, timestamp: datetime) -> bool:
        local = timestamp.astimezone(self.config.session.zone)
        if local.date() in self._exited_dates:
            return False
        cutoff, _ = self._session_times(local.date())
        quote_start = datetime.combine(
            local.date(), self.config.session.quote_start, tzinfo=self.config.session.zone
        )
        return quote_start <= timestamp < cutoff

    def _record_fills(self, fills: Iterable[Fill]) -> int:
        count_fills = 0
        for fill in fills:
            self.portfolio.apply_fill(fill)
            count_fills += 1
        return count_fills

    def _taker_fee(self, contract_id: str, price: Decimal, quantity: Decimal) -> Decimal:
        instrument = self.config.instruments[contract_id]
        mwh = quantity * instrument.mwh_per_lot
        return (
            mwh * self.config.execution.taker_fee_per_mwh
            + abs(price * mwh) * self.config.execution.taker_fee_rate
        )

    def _exit_session(self, timestamp: datetime) -> None:
        local_date = timestamp.astimezone(self.config.session.zone).date()
        if local_date in self._exited_dates:
            return
        self.order_manager.cancel_all(timestamp)
        self.order_manager.advance_through(timestamp, self.books)

        pair = self.config.pair
        actual_spread: Decimal | None = None
        forecast_error: Decimal | None = None
        books_fresh = self._books_fresh(timestamp)
        if books_fresh:
            actual_spread = self.books[pair.leg_b].mid - self.books[pair.leg_a].mid
            forecast_error = actual_spread - pair.target_spread_b_minus_a

        problems: list[str] = []
        if not books_fresh:
            problems.append("missing or stale book at scheduled exit")
        if self.order_manager.open_orders():
            problems.append("passive orders still open at exit")
        has_inventory = any(self.portfolio.quantity(key) != 0 for key in self.config.instruments)
        if has_inventory and not books_fresh:
            problems.append("cannot liquidate inventory")

        if not problems:
            for contract_id, instrument in self.config.instruments.items():
                position = self.portfolio.quantity(contract_id)
                if position == 0:
                    continue
                book = self.books[contract_id]
                slip = instrument.tick_size * self.config.execution.exit_slippage_ticks
                if position > 0:
                    side = Side.ASK
                    price = book.bid_price - slip
                else:
                    side = Side.BID
                    price = book.ask_price + slip
                quantity = abs(position)
                fill = Fill(
                    timestamp=timestamp,
                    order_id=f"EXIT-{local_date.isoformat()}-{contract_id}",
                    contract_id=contract_id,
                    side=side,
                    price=price,
                    quantity=quantity,
                    fee=self._taker_fee(contract_id, price, quantity),
                    kind=FillKind.EXIT,
                    reason="scheduled_exit",
                    reference_mid=book.mid,
                )
                self.order_manager.fills.append(fill)
                self.portfolio.apply_fill(fill)

        status = "complete" if not problems else "incomplete_exit"
        self.sessions.append(
            SessionResult(
                local_date=local_date.isoformat(),
                exit_timestamp=timestamp.isoformat(),
                status=status,
                actual_spread_b_minus_a=actual_spread,
                target_spread_b_minus_a=pair.target_spread_b_minus_a,
                forecast_error=forecast_error,
                message="; ".join(problems),
            )
        )
        self._exited_dates.add(local_date)

    def _record_equity(self, timestamp: datetime) -> None:
        pair = self.config.pair
        exposures = self.risk.exposures(self.portfolio.quantities())
        self.equity_curve.append(
            EquityPoint(
                timestamp=timestamp,
                cash=self.portfolio.cash,
                equity_mid=self.portfolio.equity_mid(self.books),
                equity_liquidation=self.portfolio.equity_liquidation(self.books),
                position_a=self.portfolio.quantity(pair.leg_a),
                position_b=self.portfolio.quantity(pair.leg_b),
                common_mwh=exposures.common_mwh,
                spread_mwh=exposures.spread_mwh,
                gross_mwh=exposures.gross_mwh,
            )
        )

    def _summary(self) -> dict[str, object]:
        pair = self.config.pair
        liquidation_values = [
            point.equity_liquidation
            for point in self.equity_curve
            if point.equity_liquidation is not None
        ]
        peak: Decimal | None = None
        max_drawdown = ZERO
        for value in liquidation_values:
            peak = value if peak is None else max(peak, value)
            max_drawdown = max(max_drawdown, peak - value)
        max_common = max((abs(point.common_mwh) for point in self.equity_curve), default=ZERO)
        max_spread = max((abs(point.spread_mwh) for point in self.equity_curve), default=ZERO)
        max_gross = max((point.gross_mwh for point in self.equity_curve), default=ZERO)
        max_leg_a = max((abs(point.position_a) for point in self.equity_curve), default=ZERO)
        max_leg_b = max((abs(point.position_b) for point in self.equity_curve), default=ZERO)
        seconds_with_common_exposure = ZERO
        for left, right in zip(self.equity_curve, self.equity_curve[1:]):
            if left.common_mwh != 0:
                seconds_with_common_exposure += Decimal(
                    str((right.timestamp - left.timestamp).total_seconds())
                )

        final_liquidation = (
            self.portfolio.equity_liquidation(self.books)
            if self.books
            else None
        )
        net_pnl = self.portfolio.cash if all(
            position.quantity == 0 for position in self.portfolio.positions.values()
        ) else final_liquidation
        decomposition = (
            self.portfolio.execution_edge
            + self.portfolio.common_mtm_pnl
            + self.portfolio.spread_mtm_pnl
            - self.portfolio.total_fees
        )
        identity_error = None if net_pnl is None else net_pnl - decomposition
        maker_fills = [fill for fill in self.order_manager.fills if fill.kind is FillKind.MAKER]
        exit_fills = [fill for fill in self.order_manager.fills if fill.kind is FillKind.EXIT]
        maker_fees = sum((fill.fee for fill in maker_fills), ZERO)
        exit_fees = sum((fill.fee for fill in exit_fills), ZERO)
        forced_exit_edge = sum(
            (
                (
                    (fill.reference_mid - fill.price)
                    if fill.side is Side.BID
                    else (fill.price - fill.reference_mid)
                )
                * fill.quantity
                * self.config.instruments[fill.contract_id].mwh_per_lot
                for fill in exit_fills
                if fill.reference_mid is not None
            ),
            ZERO,
        )
        return {
            "status": (
                "complete"
                if self.sessions and all(session.status == "complete" for session in self.sessions)
                else "incomplete"
            ),
            "net_pnl": net_pnl,
            "cash": self.portfolio.cash,
            "fees": self.portfolio.total_fees,
            "maker_fees": maker_fees,
            "exit_fees": exit_fees,
            "execution_edge": self.portfolio.execution_edge,
            "forced_exit_edge": forced_exit_edge,
            "common_mtm_pnl": self.portfolio.common_mtm_pnl,
            "spread_mtm_pnl": self.portfolio.spread_mtm_pnl,
            "pnl_identity_error": identity_error,
            "realized_gross": sum(
                (position.realized_gross for position in self.portfolio.positions.values()), ZERO
            ),
            "turnover_mwh": self.portfolio.turnover_mwh,
            "turnover_notional": self.portfolio.turnover_notional,
            "total_fills": len(self.order_manager.fills),
            "maker_fills": len(maker_fills),
            "exit_fills": len(exit_fills),
            "orders_submitted": len(self.order_manager.orders),
            "post_only_rejects": self.order_manager.n_post_only_rejects,
            "risk_rejects": self.order_manager.n_risk_rejects,
            "max_drawdown_liquidation": max_drawdown,
            "max_abs_common_mwh": max_common,
            "max_abs_spread_mwh": max_spread,
            "max_gross_mwh": max_gross,
            "seconds_with_common_exposure": seconds_with_common_exposure,
            "max_abs_position_lots": {pair.leg_a: max_leg_a, pair.leg_b: max_leg_b},
            "end_positions": self.portfolio.quantities(),
            "fill_model": self.config.execution.fill_model,
            "target_spread_b_minus_a": pair.target_spread_b_minus_a,
            "sessions": [asdict(session) for session in self.sessions],
        }

    def run(self, events: Iterable[MarketEvent]) -> BacktestResult:
        market_events = list(events)
        if not market_events:
            raise ValueError("cannot run an empty event stream")
        allowed = set(self.config.instruments)
        unknown = {event.contract_id for event in market_events} - allowed
        if unknown:
            raise ValueError(f"event stream contains unknown contracts: {sorted(unknown)}")

        grouped: dict[datetime, list[MarketEvent | TimerEvent]] = defaultdict(list)
        for event in market_events:
            grouped[event.timestamp].append(event)
        for timer in self._timers(market_events):
            grouped[timer.timestamp].append(timer)

        for timestamp in sorted(grouped):
            batch = grouped[timestamp]
            trades = sorted(
                (event for event in batch if isinstance(event, Trade)),
                key=lambda event: (event.sequence, event.contract_id, event.source_row),
            )
            quotes = [event for event in batch if isinstance(event, BookQuote)]
            timers = sorted(
                (event for event in batch if isinstance(event, TimerEvent)),
                key=lambda event: 0 if event.kind is TimerKind.QUOTE_CUTOFF else 1,
            )

            self.order_manager.advance_before(timestamp, self.books)
            eligible_ids = self.order_manager.eligible_order_ids(timestamp)
            fills_in_batch = 0

            # Trade prints are matched against orders that existed before this timestamp.
            for trade in trades:
                fills_in_batch += self._record_fills(
                    self.order_manager.match_trade(trade, eligible_ids, self.books)
                )

            # The timestamp is atomic across legs: use the final quote per contract,
            # then call the strategy once. This makes CSV row ordering irrelevant.
            final_quotes: dict[str, BookQuote] = {}
            for quote in quotes:
                previous = final_quotes.get(quote.contract_id)
                if previous is None or (quote.sequence, quote.source_row) > (
                    previous.sequence,
                    previous.source_row,
                ):
                    final_quotes[quote.contract_id] = quote
            if final_quotes:
                old_books = dict(self.books)
                new_books = dict(self.books)
                new_books.update(final_quotes)
                self.portfolio.record_mark_move(
                    old_books,
                    new_books,
                    self.config.pair.leg_a,
                    self.config.pair.leg_b,
                )
                self.books = new_books
                for quote in final_quotes.values():
                    fills_in_batch += self._record_fills(
                        self.order_manager.match_quote_through(quote, eligible_ids)
                    )

            # An activation tied with this market batch becomes live only afterwards;
            # a cancellation tied with it can still have filled above.
            self.order_manager.advance_through(timestamp, self.books)

            for timer in timers:
                if timer.kind is TimerKind.QUOTE_CUTOFF:
                    self.order_manager.cancel_all(timestamp)
                    self.order_manager.advance_through(timestamp, self.books)
                else:
                    self._exit_session(timestamp)

            if self._can_quote(timestamp):
                if not self._books_fresh(timestamp):
                    self.order_manager.reconcile([], timestamp, lambda _intent, _orders: False)
                else:
                    local_date = timestamp.astimezone(self.config.session.zone).date()
                    last_decision = self._last_quote_decision.get(local_date)
                    elapsed_ms = (
                        None
                        if last_decision is None
                        else (timestamp - last_decision).total_seconds() * 1000
                    )
                    due = (
                        last_decision is None
                        or fills_in_batch > 0
                        or elapsed_ms >= self.config.strategy.quote_interval_ms
                    )
                    if due:
                        intents = self.strategy.quote(
                            timestamp,
                            self.books,
                            self.portfolio.quantities(),
                        )
                        self.order_manager.reconcile(
                            intents,
                            timestamp,
                            lambda intent, orders: self.risk.allow_order(
                                self.portfolio.quantities(), orders, intent
                            ),
                        )
                        self._last_quote_decision[local_date] = timestamp
            elif timers or quotes or trades:
                # Before quote_start this is a no-op; after cutoff it keeps the
                # invariant that no passive order survives accidentally.
                local = timestamp.astimezone(self.config.session.zone)
                cutoff, _ = self._session_times(local.date())
                if timestamp >= cutoff:
                    self.order_manager.reconcile([], timestamp, lambda _i, _o: False)

            self._record_equity(timestamp)

        result = BacktestResult(
            summary=self._summary(),
            fills=list(self.order_manager.fills),
            orders=list(self.order_manager.orders.values()),
            equity_curve=list(self.equity_curve),
            sessions=list(self.sessions),
        )
        return result
