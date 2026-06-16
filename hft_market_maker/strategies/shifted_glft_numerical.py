"""
shifted_glft_numerical.py
==========================
Numerically-solved HJB market maker for a general (non-exponential) fill
intensity

    lambda(delta) = A_liq * exp(-kappa * delta) + max(a - b * delta, 0)

This is the academically-grounded replacement for the `A_total = A_liq +
A_mom` closed-form substitution used in `shifted_glft.py`. That shortcut is
only exact when lambda itself is a pure exponential; for the two-component
intensity it changes lambda'(delta), which feeds directly into the optimal
quote distances and is therefore NOT a valid substitution into GLFT's
closed-form formulas. `shifted_glft.py` is left untouched (deferred
contribution) -- this module is a separate strategy.

Derivation
----------
With the standard CARA ansatz

    u(t, x, s, q) = -exp(-gamma * (x + q*s)) * exp(-gamma * h_q(t))

the HJB PDE reduces -- for ANY intensity function lambda(delta), not just
the exponential one -- to a coupled ODE system in (t, q):

    h_q'(t) = (1/2) * sigma_$^2 * gamma * q^2
              - (1/gamma) * [ g*(h_{q+1}(t) - h_q(t)) + g*(h_{q-1}(t) - h_q(t)) ]

    g*(dh) = sup_{delta >= 0} g(delta; dh),
    g(delta; dh) = lambda(delta) * (1 - exp(-gamma * (delta + dh)))

with terminal condition h_q(T) = 0 for all q. This terminal condition has
no executable-liquidation penalty, matching the project's mark-to-market-
only P&L convention (total_pnl = cash + inventory * last_mid).

The optimal quote distances at inventory q are

    delta_bid*(q) = argmax_{delta>=0} g(delta; h_{q+1}(t) - h_q(t))
    delta_ask*(q) = argmax_{delta>=0} g(delta; h_{q-1}(t) - h_q(t))

found via Newton's method on the first-order condition

    F(delta)  = lambda'(delta)  * (1 - z) + gamma * lambda(delta) * z = 0
    F'(delta) = lambda''(delta) * (1 - z) + 2*gamma*lambda'(delta)*z
                - gamma^2 * lambda(delta) * z
    z = exp(-gamma * (delta + dh))

In the pure-exponential limit (a = b = 0), this FOC has the closed form

    delta* = (1/gamma) * ln(1 + gamma/kappa) - dh

which, at dh = 0, matches GLFTMarketMaker.optimal_half_spread's adverse-
selection term `log1p(gamma/kappa)/gamma` exactly. This identity is used as
a Newton warm start (see _solve_foc) and as the correctness check in
tests/test_shifted_glft_numerical.py.

Numerical scheme
----------------
The terminal-value problem is integrated by stepping tau = T - t forward
from tau = 0 (H(0) = h(T) = 0) using explicit Euler:

    H_q(tau + dt) = H_q(tau) - dt * h_q'(t)|_{h = H(tau)}

over a finite inventory grid q in {-q_max, ..., q_max} (q_max = ceil(
max_inventory / order_size) + q_buffer) with reflecting (Neumann) boundary
conditions h_{q_max+1} := h_{q_max}, h_{-q_max-1} := h_{-q_max}.

As tau -> infinity, h_q(tau) grows at a q-independent linear rate (the
ergodic growth rate of the certainty-equivalent), so the *differences*
Delta h_q = h_{q+1} - h_q converge to a stationary value. The tau = horizon
slice is therefore taken as the ergodic/stationary policy, exactly as
GLFTMarketMaker.optimal_half_spread is the ergodic (infinite-horizon)
policy for the exponential case.

Units
-----
delta, dh and h_q are all in DOLLARS (consistent with gamma and sigma_$ =
sigma * mid, and with GLFTMarketMaker's "raw price units" convention where
kappa ~ 100-1000). A_liq and a are fill-intensity AMPLITUDES in fills/sec
and do not depend on the delta unit. kappa and b are accepted in PER-TICK
units -- the natural output of scripts/calibrate_fill_intensity.py -- and
converted internally to per-dollar units by dividing by tick_size.

Calibrated defaults (survival-based hazard MLE, BTC/USDT, 4 days -- see
analysis/fill_intensity_calibration.json):

    A_liq=4.87/sec, kappa=2.39/tick, a=0.0871/sec, b=8.71e-5/tick

The fitted b is ~0 on all four days studied (implied cutoff a/b -> inf
within the tested 0.5-100 tick range): the data alone does not distinguish
a finite toxic-flow cutoff from an infinite one. b=0 is nonetheless NOT
used as the default, for a well-posedness reason that goes beyond "the
price can't move infinitely":

With b=0, g(delta;dh) -> a as delta -> infinity (approached, never
attained). For the calibrated (A_liq, kappa, a, gamma) this is harmless --
the near-touch local max of g (~0.22) exceeds a (~0.087), so the global
sup is attained at a finite near-touch delta* regardless. But if a were
ever larger relative to A_liq/kappa/gamma (a different instrument/regime,
or a dynamically-shrunk A_liq under kappa_from_stats), g could become
monotonically increasing toward a with NO finite maximizer -- the FOC
would have no root and Newton would run off toward _delta_max, an
arbitrary numerical wall rather than a true optimum.

A finite cutoff fixes this unconditionally: lambda(delta) -> 0 implies
g(delta;dh) -> 0 as delta -> infinity, so g is continuous and zero at both
ends of [0, infinity) with g>0 in between, guaranteeing a finite global
maximizer for ANY (A_liq, kappa, a, gamma). b = a/1000 (cutoff = 1000
ticks = $10 =~ 1bps on $100k BTC, 10x past the calibrated range) is a tail
regularizer only: at delta=1000 ticks, exp(-kappa*delta) =~ exp(-2390) =~
0, so it cannot perturb the near-touch optimum (delta* =~ 0.5 ticks) --
see test_cutoff_is_a_noop_near_the_touch in
tests/test_shifted_glft_numerical.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..core.market_state import MicrostructureStats


@dataclass
class QuoteDecision:
    bid_price:        float
    ask_price:        float
    bid_size:         float
    ask_size:         float
    reservation:      float   # implied centre of the (generally asymmetric) quotes
    half_spread:      float   # (delta_bid + delta_ask) / 2, after the min-spread floor
    delta_bid:        float   # delta_bid*(q) — distance of the bid from mid, pre-floor
    delta_ask:        float   # delta_ask*(q) — distance of the ask from mid, pre-floor
    should_quote_bid: bool = True
    should_quote_ask: bool = True


class ShiftedGLFTNumerical:
    """
    Numerically-solved ergodic market maker for the two-component fill
    intensity lambda(delta) = A_liq*exp(-kappa*delta) + max(a-b*delta, 0).

    Parameters
    ----------
    gamma : float
        Risk aversion, in 1/dollar units (consistent with sigma_$ = sigma*mid).
    A_liq, a : float
        Fill-intensity amplitudes in fills/sec (unit-independent of delta scale).
    kappa, b : float
        Accepted in PER-TICK units (matching calibrate_fill_intensity.py output)
        and converted internally to per-dollar via tick_size.
    order_size : float
        Order size in base currency.
    min_spread_bps : float
        Minimum half-spread floor in basis points (same convention as glft.py).
    max_inventory : float
        Hard inventory limit in base currency.
    tick_size : float
        Minimum price increment; also used to convert kappa, b to dollar units.
    q_buffer : int
        Extra inventory levels (beyond max_inventory/order_size) carried in the
        PDE grid so the reflecting boundary doesn't distort the policy near
        the operative inventory limit.
    horizon, n_steps : float, int
        Integration horizon (in tau = T-t) and number of explicit-Euler steps.
        The t=0 (tau=horizon) slice is taken as the ergodic policy.
    newton_iters : int
        Newton iterations for the FOC solve, warm-started from the pure-
        exponential closed form.
    sigma_bucket_rel : float
        Relative bucket width for caching PDE solutions across sigma_$ (and,
        if kappa_from_stats, A_liq) values that recur during a backtest.
    kappa_from_stats : bool
        If True, A_liq is taken from stats.A_hat each call (kappa, a, b stay
        fixed). Adds an extra cache dimension. If False (default), A_liq is
        the fixed constructor value.
    """

    def __init__(
        self,
        gamma: float = 30.0,
        A_liq: float = 4.87,
        kappa: float = 2.39,
        a: float = 0.0871,
        b: float = 0.0871 / 1000.0,
        order_size: float = 0.001,
        min_spread_bps: float = 0.1,
        max_inventory: float = 0.02,
        tick_size: float = 0.01,
        q_buffer: int = 5,
        horizon: float = 60.0,
        n_steps: int = 600,
        newton_iters: int = 12,
        sigma_bucket_rel: float = 0.05,
        kappa_from_stats: bool = False,
    ):
        self.gamma = gamma
        self.A_liq = A_liq
        self.a = a
        # kappa, b calibrated per-tick -> convert to per-dollar for the FOC/ODE.
        self.kappa = kappa / tick_size
        self.b = b / tick_size
        self.order_size = order_size
        self.min_spread_bps = min_spread_bps
        self.max_inventory = max_inventory
        self.tick_size = tick_size
        self.q_buffer = q_buffer
        self.horizon = horizon
        self.n_steps = n_steps
        self.dt = horizon / n_steps
        self.newton_iters = newton_iters
        self.sigma_bucket_rel = sigma_bucket_rel
        self.kappa_from_stats = kappa_from_stats

        self.q_max = int(np.ceil(max_inventory / order_size)) + q_buffer
        self.q_grid = np.arange(-self.q_max, self.q_max + 1)

        # Bounds for the FOC's delta search (dollars). _delta_max MUST reach
        # the cutoff a/b: g*(dh) = sup_delta lambda(delta)*(1-e^{-gamma(delta+dh)})
        # is bounded in [0, A_liq+a] for ANY dh because lambda(cutoff)=0 makes
        # g(cutoff;dh)=0 regardless of dh. If _delta_max < cutoff, that zero is
        # unreachable: for dh whose true argmax lies in (_delta_max, cutoff),
        # Newton is clipped to _delta_max where lambda>0 still, and
        # g(_delta_max;dh) blows up as |dh|->infinity instead of -> 0.
        self._delta_min = 1e-8
        self._delta_max = max(50.0 / self.kappa, 100.0 * tick_size,
                               self.a / self.b if self.b > 0 else 0.0)

        self._policy_cache: dict = {}

    # ------------------------------------------------------------------
    # Fill intensity lambda(delta) = A_liq*exp(-kappa*delta) + max(a-b*delta, 0)
    # ------------------------------------------------------------------

    def intensity(self, delta: np.ndarray, A_liq: Optional[float] = None) -> np.ndarray:
        """lambda(delta), in fills/sec, with delta in dollars."""
        lam, _, _ = self._intensity_and_derivs(delta, self._A(A_liq))
        return lam

    def _A(self, A_liq: Optional[float]) -> float:
        return self.A_liq if A_liq is None else A_liq

    def _intensity_and_derivs(self, delta, A_liq: float):
        delta = np.asarray(delta, dtype=float)
        exp_term = A_liq * np.exp(-self.kappa * delta)

        lam = exp_term + np.clip(self.a - self.b * delta, 0.0, None)
        lam_p = -self.kappa * exp_term
        lam_pp = self.kappa ** 2 * exp_term

        if self.b > 0:
            cutoff = self.a / self.b
            below_cutoff = delta < cutoff
            lam_p = np.where(below_cutoff, lam_p - self.b, lam_p)

        return lam, lam_p, lam_pp

    # ------------------------------------------------------------------
    # g(delta; dh) = lambda(delta) * (1 - exp(-gamma*(delta+dh))), and its
    # supremum over delta >= 0 via Newton's method on the FOC.
    # ------------------------------------------------------------------

    def _g_star(self, delta, dh, A_liq: float):
        lam, _, _ = self._intensity_and_derivs(delta, A_liq)
        z = np.exp(np.clip(-self.gamma * (delta + dh), -700.0, 700.0))
        return lam * (1.0 - z)

    def _solve_foc(self, dh: np.ndarray, A_liq: float) -> np.ndarray:
        """
        Vectorized Newton solve for delta*(dh) = argmax_{delta>=0} g(delta; dh).

        Warm-started from the pure-exponential closed form, which is exact
        when a = b = 0 and -- for the calibrated defaults, where a is small
        relative to A_liq -- a good starting point even when a > 0 (the
        floor term shifts F(delta) by a small +gamma*a*z, perturbing the
        root only slightly from the pure-exponential solution).
        """
        gamma = self.gamma
        dh = np.asarray(dh, dtype=float)

        delta = (1.0 / gamma) * np.log1p(gamma / self.kappa) - dh
        delta = np.clip(delta, self._delta_min, self._delta_max)

        for _ in range(self.newton_iters):
            lam, lam_p, lam_pp = self._intensity_and_derivs(delta, A_liq)
            z = np.exp(np.clip(-gamma * (delta + dh), -700.0, 700.0))

            F = lam_p * (1.0 - z) + gamma * lam * z
            Fp = lam_pp * (1.0 - z) + 2.0 * gamma * lam_p * z - gamma ** 2 * lam * z

            with np.errstate(divide="ignore", invalid="ignore"):
                step = np.where(np.abs(Fp) > 1e-12, F / Fp, 0.0)
            # Damp to a relative step so Newton can't jump out of the basin
            # containing the warm-start root.
            max_step = np.maximum(0.5 * delta, self._delta_min)
            step = np.clip(step, -max_step, max_step)

            delta = np.clip(delta - step, self._delta_min, self._delta_max)

        return delta

    # ------------------------------------------------------------------
    # PDE solve: backward (in tau = T-t) integration of h_q'(t), returning
    # the ergodic (tau=horizon) optimal quote-distance arrays over q_grid.
    # ------------------------------------------------------------------

    def _solve(self, sigma_dollar: float, A_liq: float):
        gamma = self.gamma
        q_vals = self.q_grid.astype(float) * self.order_size
        n = len(self.q_grid)
        H = np.zeros(n)

        for _ in range(self.n_steps):
            dh_b, dh_a = self._neighbor_diffs(H)

            delta_b = self._solve_foc(dh_b, A_liq)
            delta_a = self._solve_foc(dh_a, A_liq)

            rhs = (
                0.5 * sigma_dollar ** 2 * gamma * q_vals ** 2
                - (self._g_star(delta_b, dh_b, A_liq) + self._g_star(delta_a, dh_a, A_liq)) / gamma
            )

            H = H - self.dt * rhs

        dh_b, dh_a = self._neighbor_diffs(H)
        delta_bid = self._solve_foc(dh_b, A_liq)
        delta_ask = self._solve_foc(dh_a, A_liq)
        return delta_bid, delta_ask

    def _neighbor_diffs(self, H: np.ndarray):
        """Delta h^b_q = h_{q+1}-h_q, Delta h^a_q = h_{q-1}-h_q, reflecting boundaries."""
        n = len(H)
        H_up = np.empty(n)
        H_up[:-1] = H[1:]
        H_up[-1] = H[-1]
        H_down = np.empty(n)
        H_down[1:] = H[:-1]
        H_down[0] = H[0]
        return H_up - H, H_down - H

    # ------------------------------------------------------------------
    # Caching: PDE solutions depend only on sigma_$ (and, if
    # kappa_from_stats, A_liq), both of which recur many times across a
    # backtest, so bucket them on a log-relative grid.
    # ------------------------------------------------------------------

    def _bucket(self, value: float) -> int:
        value = max(value, 1e-12)
        return int(round(np.log(value) / np.log(1.0 + self.sigma_bucket_rel)))

    def _policy(self, sigma_dollar: float, A_liq: float):
        sigma_bucket = self._bucket(sigma_dollar)
        if self.kappa_from_stats:
            A_bucket = self._bucket(A_liq)
            key = (sigma_bucket, A_bucket)
        else:
            key = sigma_bucket

        if key not in self._policy_cache:
            rel = self.sigma_bucket_rel
            sigma_repr = (1.0 + rel) ** sigma_bucket
            A_repr = (1.0 + rel) ** A_bucket if self.kappa_from_stats else A_liq
            self._policy_cache[key] = self._solve(sigma_repr, A_repr)

        return self._policy_cache[key]

    # ------------------------------------------------------------------
    # Main interface — matches AvellanedaStoikov/GLFT compute_quotes signature
    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,  # ignored — ergodic model
        **kwargs,
    ) -> QuoteDecision:
        mid = stats.mid_price
        sigma_dollar = stats.sigma * mid

        A_liq = max(stats.A_hat, 1e-6) if self.kappa_from_stats else self.A_liq

        delta_bid_arr, delta_ask_arr = self._policy(sigma_dollar, A_liq)

        q_idx = int(np.clip(round(inventory / self.order_size), -self.q_max, self.q_max))
        arr_idx = q_idx + self.q_max

        delta_bid = float(delta_bid_arr[arr_idx])
        delta_ask = float(delta_ask_arr[arr_idx])

        reservation = mid + 0.5 * (delta_ask - delta_bid)
        half_spread = 0.5 * (delta_bid + delta_ask)

        min_half_spread = self.min_spread_bps * mid / 20000.0  # bps -> half-spread in dollars
        half_spread = max(half_spread, min_half_spread)

        bid_raw = reservation - half_spread
        ask_raw = reservation + half_spread

        bid_price = self._round_price(bid_raw, "bid")
        ask_price = self._round_price(ask_raw, "ask")
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
            delta_bid=delta_bid,
            delta_ask=delta_ask,
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
        mid = stats.mid_price
        sigma_dollar = stats.sigma * mid
        A_liq = max(stats.A_hat, 1e-6) if self.kappa_from_stats else self.A_liq

        delta_bid_arr, delta_ask_arr = self._policy(sigma_dollar, A_liq)
        q_idx = int(np.clip(round(inventory / self.order_size), -self.q_max, self.q_max))
        arr_idx = q_idx + self.q_max
        delta_bid = delta_bid_arr[arr_idx]
        delta_ask = delta_ask_arr[arr_idx]

        decision = self.compute_quotes(stats, inventory, timestamp=0.0)

        lines = [
            f"ShiftedGLFTNumerical — mid={mid:.2f}  inv={inventory:.4f}",
            f"  sigma_$={sigma_dollar:.6f}  A_liq={A_liq:.4f}  kappa={self.kappa:.2f}/$  "
            f"a={self.a:.4f}  b={self.b:.4f}/$  gamma={self.gamma:.4f}",
            f"  delta_bid*={delta_bid:.6f}  delta_ask*={delta_ask:.6f}",
            f"  reservation = {decision.reservation:.4f}",
            f"  half_spread = {decision.half_spread:.4f}",
            f"  bid={decision.bid_price:.4f}  ask={decision.ask_price:.4f}",
            f"  spread = {(decision.ask_price - decision.bid_price) / mid * 10000:.4f} bps",
        ]
        return "\n".join(lines)
