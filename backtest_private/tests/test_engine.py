from datetime import datetime, time, timezone
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
    Fill,
    FillKind,
    Instrument,
    OrderStatus,
    Side,
    Trade,
)
from coupled_mm.engine import BacktestEngine


D = Decimal
DAY = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _at(hour: int, minute: int, second: int, microsecond: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second, microsecond=microsecond)


def _config(
    *,
    max_quote_age_ms: int = 1_000,
    quote_interval_ms: int = 100,
) -> BacktestConfig:
    return BacktestConfig(
        pair=PairConfig("A", "B", "-5"),
        instruments={
            "A": Instrument("A", D("0.5")),
            "B": Instrument("B", D("0.5")),
        },
        session=SessionConfig(
            timezone="UTC",
            quote_start=time(11, 0),
            signal_start=time(11, 0),
            exit_time=time(11, 45),
            cancel_before_exit_ms=500,
            max_quote_age_ms=max_quote_age_ms,
        ),
        strategy=StrategyConfig(
            order_quantity="1",
            half_width_a="0.5",
            half_width_b="0.5",
            quote_interval_ms=quote_interval_ms,
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
            new_order_latency_ms=0,
            cancel_latency_ms=250,
            fill_model="trade_queue",
            queue_fraction="0",
            maker_fee_per_mwh="0",
            taker_fee_per_mwh="0",
            maker_fee_rate="0",
            taker_fee_rate="0",
            exit_slippage_ticks=0,
        ),
    )


def _quote(timestamp: datetime, contract_id: str) -> BookQuote:
    return BookQuote(timestamp, contract_id, D("99"), D("101"), D("10"), D("10"))


def _seed_position(
    engine: BacktestEngine,
    contract_id: str,
    side: Side,
    quantity: str,
) -> None:
    engine.portfolio.apply_fill(
        Fill(
            timestamp=_at(11, 44, 0),
            order_id=f"SEED-{contract_id}",
            contract_id=contract_id,
            side=side,
            price=D("100"),
            quantity=D(quantity),
            fee=D("0"),
            kind=FillKind.MAKER,
            reason="test_seed",
            reference_mid=D("100"),
        )
    )


def test_scheduled_exit_liquidates_long_at_bid_short_at_ask_and_closes_pnl_identity() -> None:
    engine = BacktestEngine(_config())
    _seed_position(engine, "A", Side.BID, "2")
    _seed_position(engine, "B", Side.ASK, "3")
    final_book_time = _at(11, 44, 59, 900_000)

    result = engine.run(
        [_quote(final_book_time, "A"), _quote(final_book_time, "B")]
    )

    exits = {fill.contract_id: fill for fill in result.fills if fill.kind is FillKind.EXIT}
    assert exits["A"].side is Side.ASK
    assert exits["A"].price == D("99")
    assert exits["A"].quantity == D("2")
    assert exits["B"].side is Side.BID
    assert exits["B"].price == D("101")
    assert exits["B"].quantity == D("3")
    assert result.sessions[0].exit_timestamp == _at(11, 45, 0).isoformat()
    assert result.sessions[0].status == "complete"
    assert result.summary["end_positions"] == {"A": D("0"), "B": D("0")}

    # Buy 2 A at 100, sell at 99: -2. Sell 3 B at 100, buy at 101: -3.
    assert result.summary["cash"] == D("-5")
    assert result.summary["net_pnl"] == D("-5")
    assert result.summary["pnl_identity_error"] == D("0")


def test_engine_never_submits_a_new_passive_quote_at_or_after_cutoff() -> None:
    engine = BacktestEngine(_config())
    before_cutoff = _at(11, 44, 59, 400_000)
    cutoff = _at(11, 44, 59, 500_000)
    after_cutoff = _at(11, 44, 59, 800_000)

    result = engine.run(
        [
            _quote(before_cutoff, "A"),
            _quote(before_cutoff, "B"),
            _quote(cutoff, "A"),
            _quote(cutoff, "B"),
            _quote(after_cutoff, "A"),
            _quote(after_cutoff, "B"),
        ]
    )

    assert len(result.orders) == 4
    assert all(order.submitted_at < cutoff for order in result.orders)
    assert all(order.status is OrderStatus.CANCELLED for order in result.orders)
    assert result.sessions[0].status == "complete"


def test_stale_book_with_inventory_marks_session_as_incomplete_exit() -> None:
    engine = BacktestEngine(_config(max_quote_age_ms=1_000))
    _seed_position(engine, "A", Side.BID, "1")
    stale_time = _at(11, 44, 50)

    result = engine.run([_quote(stale_time, "A"), _quote(stale_time, "B")])

    assert result.sessions[0].status == "incomplete_exit"
    assert "stale book" in result.sessions[0].message
    assert not [fill for fill in result.fills if fill.kind is FillKind.EXIT]
    assert result.summary["end_positions"]["A"] == D("1")
    assert result.summary["status"] == "incomplete"


def test_stale_quote_timer_cancels_orders_before_a_late_trade_can_fill() -> None:
    engine = BacktestEngine(_config(max_quote_age_ms=1_000))
    start = _at(11, 0, 0)
    late_trade = Trade(
        _at(11, 0, 10),
        "A",
        D("99.5"),
        D("10"),
        AggressorSide.SELL,
    )
    final = _at(11, 44, 59, 900_000)

    result = engine.run(
        [
            _quote(start, "A"),
            _quote(start, "B"),
            late_trade,
            _quote(final, "A"),
            _quote(final, "B"),
        ]
    )

    assert not [fill for fill in result.fills if fill.kind is FillKind.MAKER]
    assert result.sessions[0].status == "complete"


def test_decision_timer_reprices_relation_without_new_market_event() -> None:
    engine = BacktestEngine(
        _config(max_quote_age_ms=3_600_000, quote_interval_ms=15 * 60 * 1_000)
    )
    start = _at(11, 0, 0)
    final = _at(11, 44, 59, 900_000)

    result = engine.run(
        [
            _quote(start, "A"),
            _quote(start, "B"),
            _quote(final, "A"),
            _quote(final, "B"),
        ]
    )

    assert any(order.submitted_at == _at(11, 30, 0) for order in result.orders)
    assert result.sessions[0].status == "complete"


def test_previous_days_other_leg_is_not_used_for_new_session_quotes() -> None:
    config = _config(max_quote_age_ms=100_000_000, quote_interval_ms=60_000)
    engine = BacktestEngine(config)
    day_two = DAY.replace(day=16)
    events = [
        _quote(_at(11, 44, 59, 900_000), "A"),
        _quote(_at(11, 44, 59, 900_000), "B"),
        _quote(day_two.replace(hour=11, minute=0, second=0), "A"),
        _quote(day_two.replace(hour=11, minute=0, second=1), "B"),
        _quote(day_two.replace(hour=11, minute=44, second=59, microsecond=900_000), "A"),
        _quote(day_two.replace(hour=11, minute=44, second=59, microsecond=900_000), "B"),
    ]

    result = engine.run(events)
    day_two_orders = [
        order
        for order in result.orders
        if order.submitted_at.date() == day_two.date()
    ]

    assert day_two_orders
    assert min(order.submitted_at for order in day_two_orders) == day_two.replace(
        hour=11, minute=0, second=1
    )


def test_exit_never_invents_more_size_than_visible_l1_depth() -> None:
    engine = BacktestEngine(_config())
    _seed_position(engine, "A", Side.BID, "11")
    final = _at(11, 44, 59, 900_000)

    result = engine.run([_quote(final, "A"), _quote(final, "B")])

    assert result.sessions[0].status == "incomplete_exit"
    assert "insufficient L1 exit depth" in result.sessions[0].message
    assert result.summary["net_pnl"] is None
    assert result.summary["marked_liquidation_pnl"] is None
    assert not [fill for fill in result.fills if fill.kind is FillKind.EXIT]
