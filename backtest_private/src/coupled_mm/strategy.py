from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .config import BacktestConfig
from .domain import BookQuote, QuoteIntent, Side, ceil_to_tick, floor_to_tick
from .relation import fair_values_from_config


class CoupledMarketMaker:
    """Quotes two legs around fair values constrained by a terminal spread belief."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def quote(
        self,
        timestamp: datetime,
        books: dict[str, BookQuote],
        positions: dict[str, Decimal],
    ) -> list[QuoteIntent]:
        pair = self.config.pair
        if pair.leg_a not in books or pair.leg_b not in books:
            return []
        coupled = fair_values_from_config(
            books[pair.leg_a].mid,
            books[pair.leg_b].mid,
            timestamp,
            pair,
            self.config.session,
            self.config.strategy,
        )
        fair_a, fair_b = coupled.leg_a, coupled.leg_b
        instrument_a = self.config.instruments[pair.leg_a]
        instrument_b = self.config.instruments[pair.leg_b]
        x_a = positions[pair.leg_a] * instrument_a.mwh_per_lot
        x_b = positions[pair.leg_b] * instrument_b.mwh_per_lot

        k_common = self.config.strategy.inventory_skew_common
        k_spread = self.config.strategy.inventory_skew_spread
        diagonal = k_common + k_spread
        cross = k_common - k_spread
        reservation_a = fair_a - diagonal * x_a - cross * x_b
        reservation_b = fair_b - cross * x_a - diagonal * x_b

        intents: list[QuoteIntent] = []
        for contract_id, fair, reservation, half_width in (
            (pair.leg_a, fair_a, reservation_a, self.config.strategy.half_width_a),
            (pair.leg_b, fair_b, reservation_b, self.config.strategy.half_width_b),
        ):
            instrument = self.config.instruments[contract_id]
            book = books[contract_id]
            bid = floor_to_tick(reservation - half_width, instrument.tick_size)
            ask = ceil_to_tick(reservation + half_width, instrument.tick_size)

            # Post-only clamp. An order may improve the touch, but never cross it.
            bid = min(bid, book.ask_price - instrument.tick_size)
            ask = max(ask, book.bid_price + instrument.tick_size)
            if not instrument.allow_negative_price:
                bid = max(bid, Decimal("0"))
                ask = max(ask, instrument.tick_size)

            quantity = self.config.strategy.order_quantity
            intents.append(QuoteIntent(contract_id, Side.BID, bid, quantity, fair))
            intents.append(QuoteIntent(contract_id, Side.ASK, ask, quantity, fair))
        return intents
