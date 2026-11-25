from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Iterable, Mapping

from .config import PairConfig, RiskConfig
from .domain import Instrument, Order, QuoteIntent, Side, decimal


ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Exposures:
    """Pair exposure expressed in MWh, not in lots."""

    leg_a_mwh: Decimal
    leg_b_mwh: Decimal
    common_mwh: Decimal
    spread_mwh: Decimal
    gross_mwh: Decimal


@dataclass(frozen=True, slots=True)
class _PotentialFill:
    contract_id: str
    delta_lots: Decimal


def _validate_pair_instruments(
    pair: PairConfig,
    instruments: Mapping[str, Instrument],
) -> None:
    required = {pair.leg_a, pair.leg_b}
    if set(instruments) != required:
        raise ValueError(f"instruments must contain exactly {sorted(required)}")


def calculate_exposures(
    positions: Mapping[str, object],
    pair: PairConfig,
    instruments: Mapping[str, Instrument],
) -> Exposures:
    """Convert signed positions in lots into leg/common/spread/gross MWh."""

    _validate_pair_instruments(pair, instruments)
    unknown = set(positions) - {pair.leg_a, pair.leg_b}
    if unknown:
        raise ValueError(f"positions contain unknown contracts: {sorted(unknown)}")

    lots_a = decimal(positions.get(pair.leg_a, ZERO))
    lots_b = decimal(positions.get(pair.leg_b, ZERO))
    leg_a = lots_a * instruments[pair.leg_a].mwh_per_lot
    leg_b = lots_b * instruments[pair.leg_b].mwh_per_lot
    return Exposures(
        leg_a_mwh=leg_a,
        leg_b_mwh=leg_b,
        common_mwh=leg_a + leg_b,
        spread_mwh=leg_b - leg_a,
        gross_mwh=abs(leg_a) + abs(leg_b),
    )


def within_limits(exposures: Exposures, limits: RiskConfig) -> bool:
    return (
        abs(exposures.leg_a_mwh) <= limits.max_leg_mwh
        and abs(exposures.leg_b_mwh) <= limits.max_leg_mwh
        and abs(exposures.common_mwh) <= limits.max_common_mwh
        and abs(exposures.spread_mwh) <= limits.max_spread_mwh
        and exposures.gross_mwh <= limits.max_gross_mwh
    )


def _potential_fill_from_order(order: Order) -> _PotentialFill | None:
    if not order.is_open:
        return None
    if order.remaining <= ZERO:
        raise ValueError(f"open order {order.order_id!r} must have positive remaining quantity")
    return _PotentialFill(order.contract_id, order.side.position_sign * order.remaining)


def _potential_fill_from_candidate(candidate: QuoteIntent | Order) -> _PotentialFill:
    if isinstance(candidate, Order):
        if not candidate.is_open:
            raise ValueError("candidate order must be open")
        quantity = candidate.remaining
    else:
        quantity = decimal(candidate.quantity)
    if quantity <= ZERO:
        raise ValueError("candidate quantity must be positive")
    return _PotentialFill(candidate.contract_id, candidate.side.position_sign * quantity)


def allow_order(
    positions: Mapping[str, object],
    open_orders: Iterable[Order],
    candidate: QuoteIntent | Order,
    pair: PairConfig,
    instruments: Mapping[str, Instrument],
    limits: RiskConfig,
    *,
    max_scenario_orders: int = 5,
) -> bool:
    """Check every full/no-fill scenario for live, pending and candidate orders.

    Partial fills cannot produce a larger value of any configured convex exposure
    than one of the vertices enumerated here. A cancel-pending order remains at risk
    until it is actually cancelled, so ``Order.is_open`` intentionally includes it.
    The function fails closed when there are too many simultaneous order outcomes.
    """

    _validate_pair_instruments(pair, instruments)
    if max_scenario_orders <= 0:
        raise ValueError("max_scenario_orders must be positive")

    candidate_fill = _potential_fill_from_candidate(candidate)
    valid_contracts = {pair.leg_a, pair.leg_b}
    if candidate_fill.contract_id not in valid_contracts:
        raise ValueError(f"unknown candidate contract {candidate_fill.contract_id!r}")

    fills: list[_PotentialFill] = []
    candidate_id = candidate.order_id if isinstance(candidate, Order) else None
    seen_order_ids: set[str] = set()
    for order in open_orders:
        if order.order_id in seen_order_ids:
            raise ValueError(f"duplicate open order id {order.order_id!r}")
        seen_order_ids.add(order.order_id)
        if candidate_id is not None and order.order_id == candidate_id:
            raise ValueError("candidate order is already present in open_orders")
        fill = _potential_fill_from_order(order)
        if fill is None:
            continue
        if fill.contract_id not in valid_contracts:
            raise ValueError(f"open order contains unknown contract {fill.contract_id!r}")
        fills.append(fill)

    fills.append(candidate_fill)
    if len(fills) > max_scenario_orders:
        return False

    base_positions = {
        pair.leg_a: decimal(positions.get(pair.leg_a, ZERO)),
        pair.leg_b: decimal(positions.get(pair.leg_b, ZERO)),
    }
    unknown_positions = set(positions) - valid_contracts
    if unknown_positions:
        raise ValueError(f"positions contain unknown contracts: {sorted(unknown_positions)}")

    for outcomes in product((False, True), repeat=len(fills)):
        scenario = dict(base_positions)
        for filled, potential in zip(outcomes, fills, strict=True):
            if filled:
                scenario[potential.contract_id] += potential.delta_lots
        if not within_limits(calculate_exposures(scenario, pair, instruments), limits):
            return False
    return True


class RiskManager:
    """Configured facade used by the event-driven engine."""

    def __init__(
        self,
        pair: PairConfig,
        instruments: Mapping[str, Instrument],
        limits: RiskConfig,
        *,
        max_scenario_orders: int = 5,
    ) -> None:
        _validate_pair_instruments(pair, instruments)
        if max_scenario_orders <= 0:
            raise ValueError("max_scenario_orders must be positive")
        self.pair = pair
        self.instruments = dict(instruments)
        self.limits = limits
        self.max_scenario_orders = max_scenario_orders

    def exposures(self, positions: Mapping[str, object]) -> Exposures:
        return calculate_exposures(positions, self.pair, self.instruments)

    def allow_order(
        self,
        positions: Mapping[str, object],
        open_orders: Iterable[Order],
        candidate: QuoteIntent | Order,
    ) -> bool:
        return allow_order(
            positions,
            open_orders,
            candidate,
            self.pair,
            self.instruments,
            self.limits,
            max_scenario_orders=self.max_scenario_orders,
        )
