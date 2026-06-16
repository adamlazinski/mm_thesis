"""
Avellaneda-Stoikov Optimal Market Making Strategy
--------------------------------------------------

Based on: Avellaneda & Stoikov (2008) "High-frequency trading in a limit order book"

The model gives closed-form solutions for:
  1. Reservation price r(s,q,t) — the inventory-adjusted fair value
  2. Optimal spread delta*(s,q,t) — the total bid-ask spread to quote

Key parameters:
  gamma  : risk aversion (controls how aggressively inventory is reduced)
  T      : trading horizon in seconds (rolling window)
  sigma  : price volatility (estimated from market state)
  kappa  : order arrival intensity (estimated from market state)

We implement the model in its original continuous-time form, with
a rolling horizon so it can run 24/7 on crypto.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from typing import Optional

from ..core.market_state import MicrostructureStats


@dataclass
class QuoteDecision:
    """Output of the strategy: what prices to quote."""
    bid_price: float
    ask_price: float
    reservation_price: float
    optimal_spread: float
    bid_size: float
    ask_size: float
    # Diagnostics
    gamma: float = 0.0
    sigma: float = 0.0
    kappa: float = 0.0
    inventory_skew: float = 0.0


class AvellanedaStoikov:
    """
    Pure Avellaneda-Stoikov market maker.

    Parameters
    ----------
    gamma : float
        Risk aversion parameter. Higher = more aggressive inventory management,
        tighter spreads when flat, wider when inventory builds.
        Typical range: 0.01 – 1.0
    T : float
        Trading horizon in seconds. For 24/7 crypto, use a rolling window
        (e.g. 3600 for 1 hour). Time-to-horizon = T always (stationary approx).
    order_size : float
        Default quantity to quote on each side.
    min_spread : float
        Minimum spread as a fraction of mid price (floor to cover fees).
    max_inventory : float
        Maximum absolute inventory before we stop quoting one side.
    tick_size : float
        Minimum price increment for rounding quotes.
    """

    def __init__(
        self,
        gamma: float = 0.1,
        T: float = 3600,
        order_size: float = 0.01,
        min_spread_bps: float = 5.0,
        max_inventory: float = 1.0,
        tick_size: float = 0.01,
        kappa_as_min: float = 1.5,
    ):
        self.gamma = gamma
        self.kappa_as_min = kappa_as_min
        self.T = T
        self.order_size = order_size
        self.min_spread = min_spread_bps / 10_000  # convert bps to fraction
        self.max_inventory = max_inventory
        self.tick_size = tick_size

    # ------------------------------------------------------------------
    # Core A-S equations
    # ------------------------------------------------------------------

    def reservation_price(self, mid: float, inventory: float,
                          sigma: float, t_remaining: float) -> float:
        """
        r = s - q * gamma * sigma_price^2 * (T - t)

        MarketState supplies relative log-return volatility. The A-S arithmetic
        Brownian-motion formula requires price volatility, so convert with
        sigma_price = sigma * mid before applying the equation.
        """
        sigma_price = sigma * mid
        skew = inventory * self.gamma * (sigma_price ** 2) * t_remaining
        return mid - skew

    def optimal_spread(self, sigma_price: float, kappa: float,
                       t_remaining: float) -> float:
        """
        Full optimal spread:

            spread* = gamma * sigma_price^2 * (T-t)
                    + (2/gamma) * ln(1 + gamma/kappa)

        gamma and kappa both have inverse-price units. kappa is the distance
        sensitivity in lambda(delta) = A * exp(-kappa * delta); it is not an
        arrival rate and must not be multiplied by the horizon.
        """
        kappa = max(kappa, 1e-12)
        inventory_term = self.gamma * (sigma_price ** 2) * t_remaining
        if self.gamma <= 1e-12:
            adverse_selection_term = 2.0 / kappa
        else:
            adverse_selection_term = (
                2.0 / self.gamma
            ) * np.log1p(self.gamma / kappa)
        spread = inventory_term + adverse_selection_term
        return max(spread, 0.0)

    # ------------------------------------------------------------------
    # Quote generation
    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        """
        Main entry point. Returns bid/ask prices and sizes.

        t_remaining defaults to T (stationary / rolling horizon assumption).
        This is the right approach for 24/7 crypto trading.
        """
        if t_remaining is None:
            t_remaining = self.T
        mid = stats.mid_price
        # sigma is relative log-return volatility per sqrt(second).
        # kappa_as is inverse price in lambda(delta)=A*exp(-kappa_as*delta).
        sigma = stats.sigma
        kappa = max(stats.kappa_as, self.kappa_as_min)
        # 1. Reservation price (inventory-adjusted mid)
        r = self.reservation_price(mid, inventory, sigma, t_remaining)

        # 2. Compute the full spread in price units, then split it around r.
        full_spread = self.optimal_spread(sigma * mid, kappa, t_remaining)
        half_spread = full_spread / 2.0

        # min_spread is a full quote-to-quote spread floor.
        min_full_spread = mid * self.min_spread
        half_spread = max(half_spread, min_full_spread / 2.0)

        # 3. Quote prices: symmetric around reservation price
        raw_bid = r - half_spread
        raw_ask = r + half_spread

        # 4. Round to tick size
        bid_price = self._round_price(raw_bid, "bid")
        ask_price = self._round_price(raw_ask, "ask")

        # 5. Inventory skew for sizing (optional — size down the side we want to reduce)
        bid_size, ask_size = self._compute_sizes(inventory)

        return QuoteDecision(
            bid_price=bid_price,
            ask_price=ask_price,
            reservation_price=r,
            optimal_spread=half_spread * 2,
            bid_size=bid_size,
            ask_size=ask_size,
            gamma=self.gamma,
            sigma=sigma,
            kappa=kappa,
            inventory_skew=inventory / self.max_inventory,
        )

    def _compute_sizes(self, inventory: float) -> tuple[float, float]:
        # Both sides always quote at order_size. Inventory management is handled
        # by the reservation-price skew and the hard should_quote() cutoff at
        # max_inventory, not by tapering size with inventory.
        return self.order_size, self.order_size

    def _round_price(self, price: float, side: str) -> float:
        if self.tick_size <= 0:
            return price
        if side == "bid":
            return np.floor(price / self.tick_size) * self.tick_size
        else:
            return np.ceil(price / self.tick_size) * self.tick_size

    def should_quote(self, inventory: float) -> tuple[bool, bool]:
        """
        Returns (quote_bid, quote_ask).
        Stop quoting a side when inventory limit is breached.
        """
        quote_bid = inventory < self.max_inventory
        quote_ask = inventory > -self.max_inventory
        return quote_bid, quote_ask