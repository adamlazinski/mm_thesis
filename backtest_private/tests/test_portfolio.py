from datetime import datetime, timezone
from decimal import Decimal

from coupled_mm.domain import BookQuote, Fill, FillKind, Instrument, Side
from coupled_mm.portfolio import Portfolio


NOW = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def _instruments() -> dict[str, Instrument]:
    return {
        "A": Instrument("A", Decimal("0.5"), mwh_per_lot=Decimal("2")),
        "B": Instrument("B", Decimal("0.5"), mwh_per_lot=Decimal("2")),
    }


def _fill(contract: str, side: Side, price: str, fee: str = "0") -> Fill:
    return Fill(
        timestamp=NOW,
        order_id="test",
        contract_id=contract,
        side=side,
        price=Decimal(price),
        quantity=Decimal("1"),
        fee=Decimal(fee),
        kind=FillKind.MAKER,
        reason="test",
        reference_mid=Decimal(price),
    )


def _book(contract: str, bid: str, ask: str) -> BookQuote:
    return BookQuote(
        NOW,
        contract,
        Decimal(bid),
        Decimal(ask),
        Decimal("10"),
        Decimal("10"),
    )


def test_round_trip_cash_is_gross_realized_minus_fees() -> None:
    portfolio = Portfolio(_instruments())
    portfolio.apply_fill(_fill("A", Side.BID, "100", fee="1"))
    portfolio.apply_fill(_fill("A", Side.ASK, "103", fee="1"))

    assert portfolio.quantity("A") == 0
    assert portfolio.positions["A"].realized_gross == Decimal("6")
    assert portfolio.total_fees == Decimal("2")
    assert portfolio.cash == Decimal("4")


def test_common_and_spread_mark_decomposition_is_exact() -> None:
    portfolio = Portfolio(_instruments())
    portfolio.apply_fill(_fill("A", Side.BID, "100"))
    portfolio.apply_fill(_fill("B", Side.ASK, "100"))
    old = {"A": _book("A", "99.5", "100.5"), "B": _book("B", "99.5", "100.5")}
    new = {"A": _book("A", "102.5", "103.5"), "B": _book("B", "97.5", "98.5")}

    portfolio.record_mark_move(old, new, "A", "B")

    assert portfolio.common_mtm_pnl == 0
    assert portfolio.spread_mtm_pnl == Decimal("10")
    assert portfolio.equity_mid(new) == Decimal("10")

