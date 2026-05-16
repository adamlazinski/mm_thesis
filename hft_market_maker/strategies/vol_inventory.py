"""
Vol-Inventory Market Maker (Option 3)
--------------------------------------
Spread and reservation price driven directly by dollar volatility and inventory.
No exponential fill model, no kappa, no T-scaling.

Model
-----
The GLFT diagnostic shows that on BTC the ergodic optimal half-spread is
always ~sigma_dollar / sqrt(A) ≈ $0.45–2 (40–200 ticks), which lies firmly
in the momentum plateau (fill rate ~73%, adversely selected). Calibrating
kappa and A from the fill curve does not escape this regime.

This strategy strips the model down to its two essential degrees of freedom:

    reservation = mid - q * gamma_inv * sigma_dollar

    half_spread  = alpha * sigma_dollar * sqrt(exposure)

where:
    sigma_dollar = sigma × mid          [dollar vol, $/sqrt(s)]
    exposure     = quote_freq           [quote interval, s]
    q            = inventory / max_inv  [normalised to [-1, 1]]

Both parameters (alpha, gamma_inv) have direct economic meaning:
    alpha      — spread as a multiple of 1-sigma dollar move over one quote cycle
                 alpha=1 exactly compensates for one sigma adverse selection
    gamma_inv  — reservation skew as a multiple of alpha
                 gamma_inv=0.5 means max inventory skews reservation by 0.5 × half_spread

Compared to A-S
---------------
A-S:    spread = gamma * sigma^2 * T + (2/gamma) * ln(1 + gamma/kappa)
Here:   spread = 2 * alpha * sigma_dollar * sqrt(T)

The two are equivalent up to a change of variable, but:
  - Here sigma_dollar = sigma * mid makes the dollar-vol scaling explicit
  - alpha replaces the gamma/kappa term and is directly interpretable
  - No t_scaling parameter needed — exposure = quote_freq is the natural timescale
  - No kappa needed — fill probability is not modelled explicitly
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional

from ..core.market_state import MicrostructureStats


@dataclass
class QuoteDecision:
    bid_price:        float
    ask_price:        float
    bid_size:         float
    ask_size:         float
    reservation:      float
    half_spread:      float
    skew:             float
    sigma_dollar:     float
    should_quote_bid: bool = True
    should_quote_ask: bool = True


class VolInventoryMarketMaker:
    """
    Parameters
    ----------
    alpha : float
        Half-spread = alpha * sigma_dollar * sqrt(quote_freq).
        alpha=1 compensates for exactly one sigma adverse move per quote cycle.
        Typical search range: [0.05, 3.0].

    gamma_inv : float
        Inventory skew multiplier. Reservation shifts by:
            q * gamma_inv * alpha * sigma_dollar * sqrt(quote_freq) / max_inventory
        where q is signed inventory. gamma_inv=1 means max inventory produces a
        reservation shift equal to the full half-spread.
        Typical search range: [0.1, 10.0].

    quote_freq : float
        Quote interval in seconds. Exposure window for vol scaling.

    order_size : float
        Order size in base currency.

    min_spread_bps : float
        Minimum half-spread floor in basis points (overrides formula if tighter).

    max_inventory : float
        Hard inventory limit. Quoting suppressed on the side that would exceed it.

    tick_size : float
        Minimum price increment.
    """

    def __init__(
        self,
        alpha: float = 0.3,
        gamma_inv: float = 1.0,
        quote_freq: float = 0.5,
        order_size: float = 0.001,
        min_spread_bps: float = 0.0,
        max_inventory: float = 0.02,
        tick_size: float = 0.01,
    ):
        self.alpha = alpha
        self.gamma_inv = gamma_inv
        self.quote_freq = quote_freq
        self.order_size = order_size
        self.min_spread_bps = min_spread_bps
        self.max_inventory = max_inventory
        self.tick_size = tick_size

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        mid = stats.mid_price
        if mid <= 0 or stats.sigma <= 0:
            sigma_dollar = 0.0
        else:
            sigma_dollar = stats.sigma * mid

        # Vol-scaled half-spread
        vol_scale = sigma_dollar * np.sqrt(max(self.quote_freq, 1e-6))
        half_spread = self.alpha * vol_scale

        # Minimum floor
        min_half = self.min_spread_bps * mid / 20_000.0
        half_spread = max(half_spread, min_half, self.tick_size)

        # Inventory-adjusted reservation price
        q_norm = inventory / self.max_inventory   # normalised to [-1, 1], can exceed bounds
        skew = self.gamma_inv * half_spread * q_norm
        reservation = mid - skew

        # Raw quotes
        bid_raw = reservation - half_spread
        ask_raw = reservation + half_spread

        # Round to tick (conservative)
        bid_price = np.floor(bid_raw / self.tick_size) * self.tick_size
        ask_price = np.ceil(ask_raw / self.tick_size) * self.tick_size

        if ask_price - bid_price < self.tick_size:
            ask_price = bid_price + self.tick_size

        should_quote_bid = inventory < self.max_inventory
        should_quote_ask = inventory > -self.max_inventory

        return QuoteDecision(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=self.order_size,
            ask_size=self.order_size,
            reservation=reservation,
            half_spread=half_spread,
            skew=skew,
            sigma_dollar=sigma_dollar,
            should_quote_bid=should_quote_bid,
            should_quote_ask=should_quote_ask,
        )

    def should_quote(self, inventory: float):
        return inventory < self.max_inventory, inventory > -self.max_inventory

    def describe(self, stats: MicrostructureStats, inventory: float) -> str:
        mid = stats.mid_price
        sigma_dollar = stats.sigma * mid
        vol_scale = sigma_dollar * np.sqrt(self.quote_freq)
        half_spread = max(self.alpha * vol_scale, self.tick_size)
        q_norm = inventory / self.max_inventory
        skew = self.gamma_inv * half_spread * q_norm
        r = mid - skew
        return (
            f"VolInventory — mid={mid:.2f}  inv={inventory:.4f}\n"
            f"  sigma_dollar=${sigma_dollar:.4f}  vol_scale=${vol_scale:.4f}\n"
            f"  alpha={self.alpha:.4f}  gamma_inv={self.gamma_inv:.4f}\n"
            f"  half_spread=${half_spread:.4f}  ({half_spread/self.tick_size:.1f} ticks)\n"
            f"  reservation={r:.4f}  (skew={skew:+.4f})\n"
            f"  bid={r-half_spread:.4f}  ask={r+half_spread:.4f}\n"
            f"  spread={2*half_spread/mid*10000:.3f} bps"
        )
