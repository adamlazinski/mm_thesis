from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .domain import BookQuote, Fill, Instrument, Side, ZERO


@dataclass(slots=True)
class Position:
    quantity: Decimal = ZERO
    average_price: Decimal = ZERO
    realized_gross: Decimal = ZERO


class Portfolio:
    """Cash ledger plus average-cost diagnostics for both contracts."""

    def __init__(self, instruments: dict[str, Instrument]) -> None:
        self.instruments = instruments
        self.positions = {contract_id: Position() for contract_id in instruments}
        self.cash = ZERO
        self.total_fees = ZERO
        self.execution_edge = ZERO
        self.common_mtm_pnl = ZERO
        self.spread_mtm_pnl = ZERO
        self.turnover_mwh = ZERO
        self.turnover_notional = ZERO

    def quantity(self, contract_id: str) -> Decimal:
        return self.positions[contract_id].quantity

    def quantities(self) -> dict[str, Decimal]:
        return {key: value.quantity for key, value in self.positions.items()}

    def mwh_position(self, contract_id: str) -> Decimal:
        instrument = self.instruments[contract_id]
        return self.quantity(contract_id) * instrument.mwh_per_lot

    def apply_fill(self, fill: Fill) -> None:
        instrument = self.instruments[fill.contract_id]
        position = self.positions[fill.contract_id]
        signed_qty = fill.side.position_sign * fill.quantity
        old_qty = position.quantity
        new_qty = old_qty + signed_qty

        if old_qty == 0 or (old_qty > 0) == (signed_qty > 0):
            if new_qty == 0:
                position.average_price = ZERO
            else:
                position.average_price = (
                    position.average_price * old_qty + fill.price * signed_qty
                ) / new_qty
        else:
            closed_qty = min(abs(old_qty), abs(signed_qty))
            direction = Decimal("1") if old_qty > 0 else Decimal("-1")
            position.realized_gross += (
                closed_qty
                * instrument.mwh_per_lot
                * (fill.price - position.average_price)
                * direction
            )
            if new_qty == 0:
                position.average_price = ZERO
            elif (new_qty > 0) != (old_qty > 0):
                position.average_price = fill.price

        position.quantity = new_qty
        mwh = fill.quantity * instrument.mwh_per_lot
        notional = fill.price * mwh
        self.cash -= fill.side.position_sign * notional
        self.cash -= fill.fee
        self.total_fees += fill.fee
        self.turnover_mwh += mwh
        self.turnover_notional += abs(notional)

        if fill.reference_mid is not None:
            if fill.side is Side.BID:
                self.execution_edge += (fill.reference_mid - fill.price) * mwh
            else:
                self.execution_edge += (fill.price - fill.reference_mid) * mwh

    def record_mark_move(
        self,
        old_books: dict[str, BookQuote],
        new_books: dict[str, BookQuote],
        leg_a: str,
        leg_b: str,
    ) -> None:
        if not all(key in old_books and key in new_books for key in (leg_a, leg_b)):
            return
        old_a, old_b = old_books[leg_a].mid, old_books[leg_b].mid
        new_a, new_b = new_books[leg_a].mid, new_books[leg_b].mid
        old_level = (old_a + old_b) / Decimal("2")
        new_level = (new_a + new_b) / Decimal("2")
        old_spread = old_b - old_a
        new_spread = new_b - new_a
        x_a = self.mwh_position(leg_a)
        x_b = self.mwh_position(leg_b)
        common_exposure = x_a + x_b
        spread_exposure = (x_b - x_a) / Decimal("2")
        self.common_mtm_pnl += common_exposure * (new_level - old_level)
        self.spread_mtm_pnl += spread_exposure * (new_spread - old_spread)

    def exposures(self, leg_a: str, leg_b: str) -> tuple[Decimal, Decimal, Decimal]:
        x_a = self.mwh_position(leg_a)
        x_b = self.mwh_position(leg_b)
        common = x_a + x_b
        spread = x_b - x_a
        gross = abs(x_a) + abs(x_b)
        return common, spread, gross

    def equity_mid(self, books: dict[str, BookQuote]) -> Decimal | None:
        if not all(contract_id in books for contract_id in self.instruments):
            return None
        marked = self.cash
        for contract_id, instrument in self.instruments.items():
            marked += self.quantity(contract_id) * instrument.mwh_per_lot * books[contract_id].mid
        return marked

    def equity_liquidation(self, books: dict[str, BookQuote]) -> Decimal | None:
        if not all(contract_id in books for contract_id in self.instruments):
            return None
        marked = self.cash
        for contract_id, instrument in self.instruments.items():
            qty = self.quantity(contract_id)
            book = books[contract_id]
            price = book.bid_price if qty > 0 else book.ask_price if qty < 0 else book.mid
            marked += qty * instrument.mwh_per_lot * price
        return marked

