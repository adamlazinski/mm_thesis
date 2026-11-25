from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from coupled_mm.config import (
    BacktestConfig,
    ExecutionConfig,
    PairConfig,
    RiskConfig,
    SessionConfig,
    StrategyConfig,
)
from coupled_mm.domain import (
    AggressorSide,
    BookQuote,
    Instrument,
    OrderStatus,
    QuoteIntent,
    Side,
    Trade,
)
from coupled_mm.execution import OrderManager


D = Decimal
NOW = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def _config(
    *,
    fill_model: str = "trade_queue",
    queue_fraction: str = "1",
    new_order_latency_ms: int = 0,
    cancel_latency_ms: int = 0,
) -> BacktestConfig:
    return BacktestConfig(
        pair=PairConfig("A", "B", "-5"),
        instruments={
            "A": Instrument("A", D("0.5")),
            "B": Instrument("B", D("0.5")),
        },
        session=SessionConfig(
            timezone="UTC",
            quote_start=time(9, 0),
            signal_start=time(9, 0),
            exit_time=time(11, 45),
            cancel_before_exit_ms=max(cancel_latency_ms, 1),
            max_quote_age_ms=5_000,
        ),
        strategy=StrategyConfig(
            order_quantity="1",
            half_width_a="0.5",
            half_width_b="0.5",
            quote_interval_ms=1_000,
            target_weight_start=0,
            target_weight_end=1,
            convergence_gamma=1,
            confidence_a="1",
            confidence_b="1",
            inventory_skew_common="0",
            inventory_skew_spread="0",
            refresh_ticks=1,
        ),
        risk=RiskConfig("100", "100", "100", "100"),
        execution=ExecutionConfig(
            new_order_latency_ms=new_order_latency_ms,
            cancel_latency_ms=cancel_latency_ms,
            fill_model=fill_model,
            queue_fraction=queue_fraction,
            maker_fee_per_mwh="0",
            taker_fee_per_mwh="0",
            maker_fee_rate="0",
            taker_fee_rate="0",
            exit_slippage_ticks=0,
        ),
    )


def _book(
    timestamp: datetime = NOW,
    *,
    bid: str = "99",
    ask: str = "101",
    bid_size: str = "10",
    ask_size: str = "10",
) -> BookQuote:
    return BookQuote(
        timestamp,
        "A",
        D(bid),
        D(ask),
        D(bid_size),
        D(ask_size),
    )


def _intent(side: Side, price: str, quantity: str = "1") -> QuoteIntent:
    return QuoteIntent("A", side, D(price), D(quantity), D("100"))


def test_post_only_marketable_order_is_rejected_on_activation() -> None:
    manager = OrderManager(_config())
    books = {"A": _book()}
    order = manager.submit(_intent(Side.BID, "101"), NOW)

    manager.advance_through(NOW, books)

    assert order.status is OrderStatus.REJECTED
    assert manager.n_post_only_rejects == 1
    assert manager.fills == []


def test_new_order_tied_with_trade_cannot_fill_from_that_trade() -> None:
    manager = OrderManager(_config(queue_fraction="0"))
    books = {"A": _book()}
    order = manager.submit(_intent(Side.BID, "99"), NOW)
    trade = Trade(NOW, "A", D("99"), D("1"), AggressorSide.SELL)

    manager.advance_before(NOW, books)
    eligible = manager.eligible_order_ids(NOW)
    fills = manager.match_trade(trade, eligible, books)
    manager.advance_through(NOW, books)

    assert eligible == set()
    assert fills == []
    assert order.status is OrderStatus.LIVE


def test_cancel_tied_with_trade_can_still_fill() -> None:
    manager = OrderManager(_config(queue_fraction="0", cancel_latency_ms=0))
    books = {"A": _book()}
    order = manager.submit(_intent(Side.BID, "99"), NOW)
    manager.advance_through(NOW, books)
    trade_time = NOW + timedelta(seconds=1)
    manager.request_cancel(order, trade_time)

    eligible = manager.eligible_order_ids(trade_time)
    fills = manager.match_trade(
        Trade(trade_time, "A", D("99"), D("1"), AggressorSide.SELL),
        eligible,
        books,
    )

    assert order.order_id in eligible
    assert len(fills) == 1
    assert fills[0].quantity == D("1")
    assert order.status is OrderStatus.FILLED


def test_exact_price_trade_consumes_queue_but_trade_through_fills_remaining() -> None:
    manager = OrderManager(_config(queue_fraction="1"))
    books = {"A": _book(bid_size="10")}
    order = manager.submit(_intent(Side.BID, "99", quantity="2"), NOW)
    manager.advance_through(NOW, books)

    first_time = NOW + timedelta(seconds=1)
    first = manager.match_trade(
        Trade(first_time, "A", D("99"), D("6"), AggressorSide.SELL),
        manager.eligible_order_ids(first_time),
        books,
    )
    assert first == []
    assert order.queue_ahead == D("4")
    assert order.remaining == D("2")

    second_time = NOW + timedelta(seconds=2)
    second = manager.match_trade(
        Trade(second_time, "A", D("99"), D("5"), AggressorSide.SELL),
        manager.eligible_order_ids(second_time),
        books,
    )
    assert len(second) == 1
    assert second[0].quantity == D("1")
    assert order.remaining == D("1")
    assert order.status is OrderStatus.PARTIAL

    through_time = NOW + timedelta(seconds=3)
    through = manager.match_trade(
        Trade(through_time, "A", D("98.5"), D("0.1"), AggressorSide.SELL),
        manager.eligible_order_ids(through_time),
        books,
    )
    assert len(through) == 1
    assert through[0].quantity == D("1")
    assert order.remaining == 0
    assert order.status is OrderStatus.FILLED


def test_quote_through_requires_strict_cross_and_does_not_fill_on_touch() -> None:
    manager = OrderManager(_config(fill_model="quote_through"))
    initial = _book()
    order = manager.submit(_intent(Side.BID, "99"), NOW)
    manager.advance_through(NOW, {"A": initial})

    touch_time = NOW + timedelta(seconds=1)
    touch = _book(touch_time, bid="98.5", ask="99")
    touch_fills = manager.match_quote_through(
        touch,
        manager.eligible_order_ids(touch_time),
    )

    assert touch_fills == []
    assert order.status is OrderStatus.LIVE

    through_time = NOW + timedelta(seconds=2)
    through = _book(through_time, bid="98", ask="98.5")
    through_fills = manager.match_quote_through(
        through,
        manager.eligible_order_ids(through_time),
    )

    assert len(through_fills) == 1
    assert through_fills[0].quantity == D("1")
    assert order.status is OrderStatus.FILLED

