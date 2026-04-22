from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional
import numpy as np


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

class AvellanedaStoikov2:
    """
    Minimal, debuggable Avellaneda-Stoikov-style quoting model.

    Assumptions:
    - stats.sigma is relative volatility per sqrt(second)
    - stats.kappa is a recent trade-arrival proxy in trades/sec
    - gamma is dimensionless and should be externally tuned
    """

    def __init__(
        self,
        gamma: float = 0.005,
        order_size: float = 0.001,
        min_spread_bps: float = 3.0,
        max_inventory: float = 0.01,
        tick_size: float = 0.01,
        inventory_horizon_s: float = 300.0,
        kappa_scale: float = 9000,
        kappa_min: float = 1000,
        kappa_max: float = 100000,
        debug: bool = True,
        debug_every: int = 400,
    ):
        self.gamma = gamma
        self.order_size = order_size
        self.min_spread = min_spread_bps / 10_000.0   # convert bps -> fraction
        self.max_inventory = max_inventory
        self.tick_size = tick_size
        self.inventory_horizon_s = inventory_horizon_s

        # Practical conversion from raw trades/sec -> liquidity proxy for A-S
        self.kappa_scale = kappa_scale
        self.kappa_min = kappa_min
        self.kappa_max = kappa_max

        self.debug = debug
        self.debug_every = debug_every
        self._debug_counter = 0

    def reservation_price(
        self,
        mid: float,
        inventory: float,
        sigma: float,
        t_remaining: float,
    ) -> float:
        """
        Reservation price:
            r = s - q * gamma * sigma^2 * T * s

        where:
        - s is mid price
        - q is inventory
        - gamma is risk aversion
        - sigma is relative vol per sqrt(second)
        - T is inventory horizon in seconds
        """
        sigma = max(float(sigma), 0.0)
        t_remaining = max(float(t_remaining), 0.0)

        skew_frac = inventory * self.gamma * (sigma ** 2) * t_remaining
        r = mid * (1.0 - skew_frac)
        return r

    def _effective_kappa(self, raw_kappa: float) -> float:
        """
        Turn raw trades/sec into a practical liquidity proxy.

        This is NOT a theoretically pure A-S calibration of k,
        but a pragmatic minimal fix so the spread formula behaves sensibly.
        """
        kappa = float(raw_kappa) * self.kappa_scale
        kappa = float(np.clip(kappa, self.kappa_min, self.kappa_max))
        return kappa

    def optimal_spread(
        self,
        sigma: float,
        kappa: float,
        t_remaining: float,
    ) -> Tuple[float, float, float]:
        """
        Returns:
            full_spread_frac,
            inventory_term,
            liquidity_term

        Formula:
            full_spread = gamma * sigma^2 * T + (2/gamma) * ln(1 + gamma/kappa)

        This is a FRACTION of price, not an absolute price spread.
        """
        gamma = max(float(self.gamma), 1e-12)
        sigma = max(float(sigma), 0.0)
        kappa = max(float(kappa), 1e-12)
        t_remaining = max(float(t_remaining), 0.0)

        inventory_term = gamma * (sigma ** 2) * t_remaining
        liquidity_term = (2.0 / gamma) * np.log(1.0 + gamma / kappa)

        full_spread_frac = inventory_term + liquidity_term

        # Apply practical floor in fractional terms
        full_spread_frac = max(full_spread_frac, self.min_spread)

        return full_spread_frac, inventory_term, liquidity_term

    def _compute_sizes(self, inventory: float) -> Tuple[float, float]:
        """
        Basic inventory-aware sizing:
        - if long, reduce bid size
        - if short, reduce ask size
        """
        if self.max_inventory <= 0:
            return self.order_size, self.order_size

        inv_ratio = min(abs(inventory) / self.max_inventory, 1.0)
        scale = max(0.2, 1.0 - inv_ratio)

        if inventory > 0:
            bid_size = self.order_size * scale
            ask_size = self.order_size
        elif inventory < 0:
            bid_size = self.order_size
            ask_size = self.order_size * scale
        else:
            bid_size = self.order_size
            ask_size = self.order_size

        return bid_size, ask_size

    def _round_bid(self, price: float) -> float:
        return np.floor(price / self.tick_size) * self.tick_size

    def _round_ask(self, price: float) -> float:
        return np.ceil(price / self.tick_size) * self.tick_size

    def should_quote(self, inventory: float) -> Tuple[bool, bool]:
        """
        Returns:
            should_quote_bid, should_quote_ask
        """
        should_quote_bid = inventory < self.max_inventory
        should_quote_ask = inventory > -self.max_inventory
        return should_quote_bid, should_quote_ask

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        mid = float(stats.mid_price)
        if mid <= 0:
            raise ValueError("mid_price must be positive")

        sigma = max(float(stats.sigma), 1e-8)
        raw_kappa = max(float(stats.kappa), 0.0)

        # Use provided horizon, otherwise default
        T = self.inventory_horizon_s if t_remaining is None else float(t_remaining)
        T = max(T, 0.0)

        # Practical liquidity proxy
        kappa = self._effective_kappa(raw_kappa)

        # Reservation price
        r = self.reservation_price(
            mid=mid,
            inventory=inventory,
            sigma=sigma,
            t_remaining=T,
        )

        # IMPORTANT:
        # optimal_spread returns FULL spread fraction
        full_spread_frac, inventory_term, liquidity_term = self.optimal_spread(
            sigma=sigma,
            kappa=kappa,
            t_remaining=T,
        )

        # Convert FULL spread fraction -> HALF spread in absolute price units
        half_spread_abs = 0.5 * full_spread_frac * mid

        raw_bid = r - half_spread_abs
        raw_ask = r + half_spread_abs

        bid_price = self._round_bid(raw_bid)
        ask_price = self._round_ask(raw_ask)

        # Prevent crossing after rounding
        if ask_price <= bid_price:
            ask_price = bid_price + self.tick_size

        bid_size, ask_size = self._compute_sizes(inventory)
        should_quote_bid, should_quote_ask = self.should_quote(inventory)

        # Optional debug output
        self._debug_counter += 1
        if self.debug and (self._debug_counter % self.debug_every == 0):
            spread_bps = 1e4 * (ask_price - bid_price) / mid
            inventory_term_bps = 1e4 * inventory_term
            liquidity_term_bps = 1e4 * liquidity_term
            skew_frac = inventory * self.gamma * (sigma ** 2) * T
            skew_bps = 1e4 * skew_frac

            print(
                f"[AS DEBUG #{self._debug_counter}] "
                f"ts={timestamp:.3f} "
                f"mid={mid:.2f} "
                f"sigma={sigma:.8f} "
                f"raw_kappa={raw_kappa:.6f} "
                f"kappa={kappa:.6f} "
                f"T={T:.1f} "
                f"inv={inventory:.6f} "
                f"r={r:.2f} "
                f"bid={bid_price:.2f} "
                f"ask={ask_price:.2f} "
                f"spread_bps={spread_bps:.3f} "
                f"inv_term_bps={inventory_term_bps:.6f} "
                f"liq_term_bps={liquidity_term_bps:.6f} "
                f"skew_bps={skew_bps:.6f}"
            )

        return QuoteDecision(
            bid_price=bid_price if should_quote_bid else np.nan,
            ask_price=ask_price if should_quote_ask else np.nan,
            bid_size=bid_size if should_quote_bid else 0.0,
            ask_size=ask_size if should_quote_ask else 0.0,
            reservation_price=r,
            optimal_spread=(ask_price - bid_price),
            gamma=self.gamma,
            sigma=sigma,
            kappa=kappa,
            inventory_skew=inventory,
        )