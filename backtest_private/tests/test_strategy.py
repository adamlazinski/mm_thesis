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
from coupled_mm.domain import BookQuote, Instrument, Side
from coupled_mm.strategy import CoupledMarketMaker


D = Decimal
EXIT = datetime(2026, 1, 15, 11, 45, tzinfo=timezone.utc)


def _config(
    *,
    k_common: str = "0",
    k_spread: str = "0",
) -> BacktestConfig:
    return BacktestConfig(
        pair=PairConfig("A", "B", "-5"),
        instruments={
            "A": Instrument("A", D("0.5")),
            "B": Instrument("B", D("0.5")),
        },
        session=SessionConfig(
            timezone="UTC",
            quote_start=time(10, 0),
            signal_start=time(10, 45),
            exit_time=time(11, 45),
            cancel_before_exit_ms=250,
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
            inventory_skew_common=k_common,
            inventory_skew_spread=k_spread,
            refresh_ticks=1,
        ),
        risk=RiskConfig("100", "100", "100", "100"),
        execution=ExecutionConfig(0, 0, "trade_queue", "1", "0", "0", "0", "0", 0),
    )


def _books(*, wide: bool = False) -> dict[str, BookQuote]:
    bid, ask = (D("50"), D("150")) if wide else (D("99"), D("101"))
    return {
        "A": BookQuote(EXIT, "A", bid, ask, D("10"), D("10")),
        "B": BookQuote(EXIT, "B", bid, ask, D("10"), D("10")),
    }


def _by_leg_and_side(intents: list) -> dict[tuple[str, Side], object]:
    return {(intent.contract_id, intent.side): intent for intent in intents}


def test_terminal_relation_tick_grid_and_post_only_are_enforced_together() -> None:
    config = _config()
    books = _books()
    intents = CoupledMarketMaker(config).quote(
        EXIT,
        books,
        {"A": D("0"), "B": D("0")},
    )
    quoted = _by_leg_and_side(intents)

    assert {intent.fair_value for intent in intents if intent.contract_id == "A"} == {
        D("102.5")
    }
    assert {intent.fair_value for intent in intents if intent.contract_id == "B"} == {
        D("97.5")
    }
    assert D("97.5") - D("102.5") == config.pair.target_spread_b_minus_a

    for intent in intents:
        instrument = config.instruments[intent.contract_id]
        book = books[intent.contract_id]
        assert intent.price % instrument.tick_size == 0
        if intent.side is Side.BID:
            assert intent.price < book.ask_price
        else:
            assert intent.price > book.bid_price

    assert quoted[("A", Side.BID)].price == D("100.5")
    assert quoted[("B", Side.ASK)].price == D("99.5")


def test_inventory_on_leg_a_cross_skews_quotes_on_leg_b() -> None:
    config = _config(k_common="2", k_spread="0.5")
    strategy = CoupledMarketMaker(config)
    books = _books(wide=True)
    flat = _by_leg_and_side(
        strategy.quote(EXIT, books, {"A": D("0"), "B": D("0")})
    )
    long_a = _by_leg_and_side(
        strategy.quote(EXIT, books, {"A": D("1"), "B": D("0")})
    )

    # cross = k_common - k_spread = 1.5, so long A lowers both B quotes by 1.5.
    assert long_a[("B", Side.BID)].price == flat[("B", Side.BID)].price - D("1.5")
    assert long_a[("B", Side.ASK)].price == flat[("B", Side.ASK)].price - D("1.5")
