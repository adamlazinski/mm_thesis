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
        self.gamma = gamma*1000
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
        r = s - q * gamma * sigma_rel^2 * (T - t) * s

        sigma is normalised (relative), so the skew term is in relative units.
        Multiply by mid to convert back to dollar terms.
        """
        t_remaining=3600
        skew_rel = inventory * self.gamma * (sigma ** 2) * t_remaining
        return mid - skew_rel * mid

    def optimal_spread(self, sigma: float, kappa: float,
                       t_remaining: float) -> float:
        """
        delta* = gamma * sigma^2 * (T-t) + (2/gamma) * ln(1 + gamma/kappa_scaled)

        kappa in the original A-S paper is dimensionless (expected arrivals over
        the horizon). We receive kappa in trades/sec so scale by t_remaining
        to make it dimensionless before applying the formula.

        First term:  inventory risk — grows with vol and horizon
        Second term: adverse selection — shrinks with arrival rate
        """
        #t_remaining=
        inventory_term = self.gamma * (sigma ** 2) * 3600
        #kappa=1
        # Scale kappa to dimensionless expected arrivals over remaining horizon
        kappa_scaled = max(kappa * t_remaining, 1e-6)
        adverse_selection_term = (2.0 / self.gamma) * np.log(1.0 + self.gamma / kappa_scaled)
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
        # sigma is already in log-return/sqrt(sec) units (dimensionless fraction)
        # kappa is in trades/sec — scaled to dimensionless inside optimal_spread
        sigma = stats.sigma
        kappa = max(stats.kappa_as, self.kappa_as_min)
        # 1. Reservation price (inventory-adjusted mid)
        r = self.reservation_price(mid, inventory, sigma, t_remaining)

        # 2. Optimal half-spread (dimensionless fraction of mid)
        delta = self.optimal_spread(sigma, kappa, t_remaining)
        delta = delta * mid  # convert fraction -> dollar spread

        # Apply minimum spread floor
        min_spread_abs = mid * self.min_spread
        delta = max(delta, min_spread_abs / 2.0)  # delta is half-spread here

        # 3. Quote prices: symmetric around reservation price
        raw_bid = r - delta
        raw_ask = r + delta

        # 4. Round to tick size
        bid_price = self._round_price(raw_bid, "bid")
        ask_price = self._round_price(raw_ask, "ask")

        # 5. Inventory skew for sizing (optional — size down the side we want to reduce)
        bid_size, ask_size = self._compute_sizes(inventory)

        return QuoteDecision(
            bid_price=bid_price,
            ask_price=ask_price,
            reservation_price=r,
            optimal_spread=delta * 2,  # full spread
            bid_size=bid_size,
            ask_size=ask_size,
            gamma=self.gamma,
            sigma=sigma,
            kappa=kappa,
            inventory_skew=inventory / self.max_inventory,
        )

    def _compute_sizes(self, inventory: float) -> tuple[float, float]:
        """
        Reduce size on the side that would increase a large inventory.
        """
        inv_ratio = abs(inventory) / self.max_inventory
        scale = max(0.1, 1.0 - inv_ratio)
        scale = 1 #switch it off for fuck sake
        if inventory > 0:
            # Long — reduce bid size, keep ask size
            return self.order_size * scale, self.order_size
        elif inventory < 0:
            # Short — keep bid size, reduce ask size
            return self.order_size, self.order_size * scale
        else:
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