from datetime import datetime, timezone
from decimal import Decimal

import pytest

from coupled_mm.config import PairConfig, RiskConfig
from coupled_mm.domain import Instrument, Order, OrderStatus, QuoteIntent, Side
from coupled_mm.risk import RiskManager, allow_order, calculate_exposures


NOW = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)


def _pair() -> PairConfig:
    return PairConfig("A", "B", "-5")


def _instruments() -> dict[str, Instrument]:
    return {
        "A": Instrument("A", Decimal("0.1"), mwh_per_lot=Decimal("2")),
        "B": Instrument("B", Decimal("0.1"), mwh_per_lot=Decimal("1")),
    }


def _limits(**overrides: object) -> RiskConfig:
    values: dict[str, object] = {
        "max_leg_mwh": "10",
        "max_common_mwh": "10",
        "max_spread_mwh": "10",
        "max_gross_mwh": "12",
    }
    values.update(overrides)
    return RiskConfig(**values)


def _intent(contract_id: str, side: Side, quantity: str = "1") -> QuoteIntent:
    return QuoteIntent(
        contract_id=contract_id,
        side=side,
        price=Decimal("100"),
        quantity=Decimal(quantity),
        fair_value=Decimal("100"),
    )


def _order(
    order_id: str,
    contract_id: str,
    side: Side,
    quantity: str = "1",
    status: OrderStatus = OrderStatus.LIVE,
) -> Order:
    order = Order(
        order_id=order_id,
        contract_id=contract_id,
        side=side,
        price=Decimal("100"),
        quantity=Decimal(quantity),
        submitted_at=NOW,
        active_at=NOW,
    )
    order.status = status
    return order


def test_exposures_are_converted_from_lots_to_mwh() -> None:
    exposures = calculate_exposures(
        {"A": Decimal("2"), "B": Decimal("-3")}, _pair(), _instruments()
    )

    assert exposures.leg_a_mwh == Decimal("4")
    assert exposures.leg_b_mwh == Decimal("-3")
    assert exposures.common_mwh == Decimal("1")
    assert exposures.spread_mwh == Decimal("-7")
    assert exposures.gross_mwh == Decimal("7")


def test_candidate_is_allowed_when_every_fill_scenario_is_within_limits() -> None:
    manager = RiskManager(_pair(), _instruments(), _limits())
    existing = [_order("one", "B", Side.ASK, "2")]

    assert manager.allow_order({"A": "0", "B": "0"}, existing, _intent("A", Side.BID))


def test_allow_order_accounts_for_existing_pending_and_live_orders() -> None:
    instruments = _instruments()
    pair = _pair()
    limits = _limits(max_common_mwh="3")
    pending = _order("pending", "A", Side.BID, "1", OrderStatus.PENDING)

    # Pending A contributes +2 MWh and the candidate B bid contributes +2 MWh.
    assert not allow_order(
        {"A": "0", "B": "0"},
        [pending],
        _intent("B", Side.BID, "2"),
        pair,
        instruments,
        limits,
    )


def test_cancel_pending_order_remains_at_risk_but_cancelled_order_does_not() -> None:
    manager = RiskManager(
        _pair(), _instruments(), _limits(max_common_mwh="2", max_leg_mwh="4")
    )
    cancelling = _order("old", "A", Side.BID, "1", OrderStatus.CANCEL_PENDING)
    candidate = _intent("B", Side.BID, "1")

    assert not manager.allow_order({}, [cancelling], candidate)
    cancelling.status = OrderStatus.CANCELLED
    assert manager.allow_order({}, [cancelling], candidate)


@pytest.mark.parametrize(
    ("limits", "candidate"),
    [
        (_limits(max_leg_mwh="1"), _intent("A", Side.BID, "1")),
        (_limits(max_common_mwh="1"), _intent("A", Side.BID, "1")),
        (_limits(max_spread_mwh="1"), _intent("A", Side.BID, "1")),
        (_limits(max_gross_mwh="1"), _intent("A", Side.BID, "1")),
    ],
)
def test_each_limit_can_reject_an_order(limits: RiskConfig, candidate: QuoteIntent) -> None:
    assert not allow_order({}, [], candidate, _pair(), _instruments(), limits)


def test_opposite_orders_are_checked_independently_not_only_as_net_position() -> None:
    manager = RiskManager(
        _pair(), _instruments(), _limits(max_leg_mwh="2", max_gross_mwh="3")
    )
    existing_ask = _order("ask", "A", Side.ASK, "1")
    candidate_bid = _intent("A", Side.BID, "2")

    # Net fill of both orders would be safe, but the bid can fill on its own (+4 MWh).
    assert not manager.allow_order({}, [existing_ask], candidate_bid)


def test_partial_remaining_quantity_not_original_quantity_drives_risk() -> None:
    manager = RiskManager(
        _pair(), _instruments(), _limits(max_leg_mwh="3", max_common_mwh="3")
    )
    partial = _order("partial", "A", Side.BID, "2", OrderStatus.PARTIAL)
    partial.remaining = Decimal("0.5")

    assert manager.allow_order({}, [partial], _intent("B", Side.BID, "1"))


def test_more_than_configured_scenario_orders_fails_closed() -> None:
    manager = RiskManager(_pair(), _instruments(), _limits(), max_scenario_orders=5)
    orders = [
        _order("a1", "A", Side.BID),
        _order("a2", "A", Side.ASK),
        _order("b1", "B", Side.BID),
        _order("b2", "B", Side.ASK),
        _order("b3", "B", Side.ASK),
    ]

    assert not manager.allow_order({}, orders, _intent("A", Side.BID))


def test_unknown_position_contract_is_not_silently_ignored() -> None:
    with pytest.raises(ValueError, match="unknown contracts"):
        calculate_exposures({"OTHER": "1"}, _pair(), _instruments())
