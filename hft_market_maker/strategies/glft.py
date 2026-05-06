"""
Guéant-Lehalle-Fernández-Tapia (GLFT) Market Making Strategy
-------------------------------------------------------------
Implements the ergodic (infinite horizon) solution from:

    Guéant, O., Lehalle, C-A., & Fernandez-Tapia, J. (2013).
    "Dealing with the Inventory Risk: A solution to the market making problem."
    Mathematics and Financial Economics, 7(4), 477-507.

The model assumes:
    - Mid price follows arithmetic Brownian motion: dS = σ dW
    - Market orders arrive as Poisson processes with intensity:
        λ(δ) = A × exp(-κ × δ)
      where δ is the distance from mid (half-spread), A is the baseline
      arrival rate and κ is the price sensitivity of order flow
    - The market maker maximises expected utility of wealth with
      risk aversion γ over an infinite horizon (ergodic control)

Ergodic closed-form solution
-----------------------------
The optimal reservation price (indifference price):

    r = S - q × γ × σ² / (2 × A × κ)            ... (1)

where q is current inventory.

The optimal symmetric half-spread around r:

    δ* = (1/κ) × ln(1 + κ/γ)                     ... (2a)  [adverse selection term]
       + (1/2) × θ                                 ... (2b)  [inventory risk term]

where:
    θ = sqrt(σ²γ / (2Aκ) × (1 + κ/γ)^(1 + κ/γ))

This gives:
    bid = r - δ*
    ask = r + δ*

Key differences from Avellaneda-Stoikov
----------------------------------------
1. No finite horizon T — the ergodic solution removes the time-remaining
   dependence entirely. Quotes are stationary and do not widen as T→0.

2. A and κ are separate parameters:
   - A  = baseline fill rate at zero spread (fills/sec)
   - κ  = price sensitivity of order flow (how fast fill rate decays with spread)
   In A-S these are conflated into a single kappa parameter.

3. Inventory skew formula (1) is derived from the full HJB solution rather
   than approximated, and scales as 1/(A×κ) rather than σ²×T.

4. The spread formula (2) has two interpretable components:
   - (1/κ) × ln(1 + κ/γ): adverse selection compensation — depends only on
     the fill probability structure and risk aversion
   - θ/2: inventory risk compensation — depends on volatility, arrival rate,
     and risk aversion

Calibration
-----------
A  — estimate from trade data: average trades/sec at zero spread. In practice
     use total kappa from MarketState as a proxy for A since all trades in a
     liquid market arrive near mid. A ≈ kappa.

κ  — price sensitivity of order flow. Must be estimated from fill probability
     curve: fit λ(δ) = A × exp(-κ × δ) to empirical fill rates at different
     spread distances. See ml/estimate_kappa_ml.py. Typical values for BTC: 1-10
     in vol-normalised units, or 100-1000 in raw price units.

     IMPORTANT: κ must be in the same units as δ. If δ is in dollars, κ is in
     1/dollars. If δ is in bps, κ is in 1/bps. This implementation uses
     raw dollar spreads throughout.

γ  — risk aversion. Same interpretation as A-S gamma. On BTC with σ ~2.9e-5/sec,
     meaningful inventory skew requires γ in the range 10-100.

σ  — per-second volatility, taken from MarketState.stats.sigma (same as A-S).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional

from ..core.market_state import MicrostructureStats


@dataclass
class QuoteDecision:
    bid_price:      float
    ask_price:      float
    bid_size:       float
    ask_size:       float
    reservation:    float   # indifference price r
    half_spread:    float   # δ* — optimal half-spread
    adverse_term:   float   # (1/κ) × ln(1 + κ/γ)
    inventory_term: float   # θ/2
    skew:           float   # inventory skew applied to reservation price
    should_quote_bid: bool = True
    should_quote_ask: bool = True


class GLFTMarketMaker:
    """
    Ergodic GLFT market making strategy.

    Parameters
    ----------
    gamma : float
        Risk aversion coefficient γ. Controls inventory skew magnitude.
        On BTC with per-second sigma, use values in range 10-100 for
        meaningful skew. Same interpretation as A-S gamma.

    A : float
        Baseline order arrival rate (fills/sec at zero spread).
        If None, uses MarketState kappa as a proxy (reasonable approximation).
        Typical BTC value: ~44 trades/sec.

    kappa : float
        Price sensitivity of order flow κ (1/dollar units).
        Controls how quickly fill probability decays with spread.
        Must be estimated from fill probability curve — see ml/estimate_kappa_ml.py.
        Typical BTC range in raw dollar units: 0.01-1.0.
        In vol-normalised units: 1-10.

    order_size : float
        Order size in base currency (BTC). Default 0.001.

    min_spread_bps : float
        Minimum half-spread floor in basis points. Overrides formula output
        if formula produces tighter spread.

    max_inventory : float
        Hard inventory limit in BTC. Quoting is suspended on the side that
        would increase inventory beyond this level.

    tick_size : float
        Minimum price increment. Quotes are rounded to tick.

    kappa_from_stats : bool
        If True, use MarketState.stats.A_hat (KappaEstimator baseline intensity)
        as A and keep self.kappa fixed as the price sensitivity parameter.
        If False, both A and kappa are fixed at construction time.
    """

    def __init__(
        self,
        gamma: float = 0.1,
        A: Optional[float] = None,
        kappa: float = 1.5,
        order_size: float = 0.001,
        min_spread_bps: float = 0.1,
        max_inventory: float = 0.1,
        tick_size: float = 0.01,
        kappa_from_stats: bool = True,
    ):
        self.gamma = gamma
        self._A_fixed = A
        self.kappa = kappa
        self.order_size = order_size
        self.min_spread_bps = min_spread_bps
        self.max_inventory = max_inventory
        self.tick_size = tick_size
        self.kappa_from_stats = kappa_from_stats

    # ------------------------------------------------------------------
    # Core formula
    # ------------------------------------------------------------------

    def reservation_price(
        self,
        mid: float,
        inventory: float,
        sigma: float,
        A: float,
    ) -> float:
        """
        Equation (1): indifference price.

            r = S - q × γ × σ_$² / (2 × A × κ)

        where σ_$ = σ × S is volatility in dollar/sqrt(sec) units,
        consistent with the paper's arithmetic Brownian motion assumption
        dS = σ_$ dW (price in dollars, not log-price).

        Parameters
        ----------
        mid : float
            Current mid price S.
        inventory : float
            Current inventory q in BTC. Positive = long, negative = short.
        sigma : float
            Per-second log-return volatility from MarketState.
            Converted internally to dollar volatility: σ_$ = σ × mid.
        A : float
            Baseline arrival rate (trades/sec).
        """
        sigma_dollar = sigma * mid   # convert to dollar vol units
        denom = 2.0 * A * self.kappa
        if denom < 1e-10:
            return mid
        skew = inventory * self.gamma * (sigma_dollar ** 2) / denom
        return mid - skew

    def optimal_half_spread(
        self,
        sigma: float,
        mid: float,
        A: float,
    ) -> tuple[float, float, float]:
        """
        Equation (2): optimal symmetric half-spread δ* in dollars.

            adverse_term   = (1/κ) × ln(1 + κ/γ)
            inventory_term = (1/2) × sqrt(σ_$²γ / (2Aκ) × (1 + κ/γ)^(1+κ/γ))
            δ* = adverse_term + inventory_term

        σ_$ = σ × mid converts log-return vol to dollar vol per the paper.

        Returns
        -------
        half_spread : float
            Total optimal half-spread δ* in dollars.
        adverse_term : float
            Adverse selection component in dollars.
        inventory_term : float
            Inventory risk component in dollars.
        """
        gamma = self.gamma
        kappa = self.kappa
        sigma_dollar = sigma * mid   # dollar vol

        # Adverse selection term: (1/κ) × ln(1 + κ/γ)
        # Units: 1/κ is in dollars (κ in 1/dollar), result in dollars
        if gamma < 1e-10:
            adverse = 1.0 / kappa if kappa > 1e-10 else 0.0
        else:
            adverse = (1.0 / kappa) * np.log(1.0 + kappa / gamma)

        # Inventory risk term: (1/2) × sqrt(σ_$²γ / (2Aκ) × (1 + κ/γ)^(1+κ/γ))
        if A < 1e-10 or kappa < 1e-10:
            inv_term = 0.0
        else:
            ratio = kappa / gamma if gamma > 1e-10 else 1e6
            exponent = 1.0 + ratio
            base = 1.0 + ratio
            try:
                power = base ** min(exponent, 500.0)
            except (OverflowError, ValueError):
                power = np.exp(min(exponent * np.log(max(base, 1e-10)), 500.0))

            inner = (sigma_dollar ** 2) * gamma / (2.0 * A * kappa) * power
            inv_term = 0.5 * np.sqrt(max(inner, 0.0))

        half_spread = adverse + inv_term
        return half_spread, adverse, inv_term

    # ------------------------------------------------------------------
    # Main interface — matches AvellanedaStoikov.compute_quotes signature
    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,  # ignored — ergodic model
        **kwargs,
    ) -> QuoteDecision:
        """
        Compute optimal bid and ask prices.

        Parameters
        ----------
        stats : MicrostructureStats
            Current market state from MarketState.
        inventory : float
            Current inventory in BTC.
        timestamp : float
            Current Unix timestamp (unused in ergodic model, kept for interface compatibility).
        t_remaining : float, optional
            Ignored — the ergodic model has no finite horizon.
        """
        mid = stats.mid_price
        sigma = stats.sigma

        # Arrival rate A — use fixed value or dynamic from market state
        A = self._A_fixed if self._A_fixed is not None else max(stats.A_hat, 1e-6)

        # --- Reservation price ---
        r = self.reservation_price(mid, inventory, sigma, A)
        skew = mid - r  # positive when long (shifted down)

        # --- Optimal half-spread ---
        half_spread, adverse_term, inv_term = self.optimal_half_spread(sigma, mid, A)

        # Apply min spread floor (in price units)
        min_half_spread = self.min_spread_bps * mid / 20000.0  # bps → half-spread in dollars
        half_spread = max(half_spread, min_half_spread)

        # --- Raw quotes ---
        bid_raw = r - half_spread
        ask_raw = r + half_spread

        # --- Round to tick ---
        bid_price = self._round_price(bid_raw, "bid")
        ask_price = self._round_price(ask_raw, "ask")

        # Ensure minimum spread after rounding
        if ask_price - bid_price < self.tick_size:
            ask_price = bid_price + self.tick_size

        # --- Inventory limits ---
        should_quote_bid = inventory < self.max_inventory
        should_quote_ask = inventory > -self.max_inventory

        return QuoteDecision(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=self.order_size,
            ask_size=self.order_size,
            reservation=r,
            half_spread=half_spread,
            adverse_term=adverse_term,
            inventory_term=inv_term,
            skew=skew,
            should_quote_bid=should_quote_bid,
            should_quote_ask=should_quote_ask,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _round_price(self, price: float, side: str) -> float:
        """Round to nearest tick, conservative direction."""
        if self.tick_size <= 0:
            return price
        if side == "bid":
            return np.floor(price / self.tick_size) * self.tick_size
        else:
            return np.ceil(price / self.tick_size) * self.tick_size

    def describe(self, stats: MicrostructureStats, inventory: float) -> str:
        """Human-readable summary of current quote decision."""
        A = self._A_fixed if self._A_fixed is not None else max(stats.A_hat, 1e-6)
        mid = stats.mid_price
        sigma = stats.sigma

        r = self.reservation_price(mid, inventory, stats.sigma, A)
        hs, adv, inv = self.optimal_half_spread(sigma, mid, A)
        min_hs = self.min_spread_bps * mid / 20000.0
        hs_eff = max(hs, min_hs)

        lines = [
            f"GLFT Ergodic — mid={mid:.2f}  inv={inventory:.4f}",
            f"  sigma={sigma:.6f}  A={A:.2f}  kappa={self.kappa:.4f}  gamma={self.gamma:.4f}",
            f"  reservation = {r:.4f}  (skew={mid-r:+.4f})",
            f"  half_spread = {hs_eff:.4f}",
            f"    adverse_term  = {adv:.6f}  [{adv/hs_eff*100:.1f}%]" if hs_eff > 0 else "",
            f"    inventory_term= {inv:.6f}  [{inv/hs_eff*100:.1f}%]" if hs_eff > 0 else "",
            f"  bid={r-hs_eff:.4f}  ask={r+hs_eff:.4f}",
            f"  spread = {(r+hs_eff - (r-hs_eff)) / mid * 10000:.4f} bps",
        ]
        return "\n".join(l for l in lines if l)