"""
kappa_estimator.py
==================
AS fill-sensitivity kappa estimator — plug-in for MarketState.

Terminology clarification
--------------------------
MarketState.stats.kappa  = trade arrival rate (trades/sec) — unchanged
KappaEstimator.kappa_as  = AS fill-sensitivity parameter in lambda=A*exp(-kappa_as*delta)

These are different quantities that happen to share a name in the literature.
This module estimates kappa_as without touching the existing kappa field.

Usage
-----
# Initialise once
estimator = KappaEstimator(kappa_prior=1.5, window_seconds=300, min_fills=50)

# In your quote event loop — call whenever you post a quote
estimator.on_quote_posted(timestamp, half_spread=delta)

# In your fill event loop — call whenever one of YOUR limit orders gets filled
estimator.on_fill(timestamp, half_spread=delta)

# Read current estimate whenever needed (e.g. before computing optimal spread)
kappa_as, A_hat, se = estimator.kappa_as, estimator.A_hat, estimator.se
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque
import numpy as np
from scipy.optimize import minimize_scalar


# ---------------------------------------------------------------------------
# Internal observation record
# ---------------------------------------------------------------------------

@dataclass
class _TickObs:
    """One tick-level observation: how many fills arrived, at what spread."""
    timestamp: float
    delta: float      # half-spread posted that tick ($)
    count: int        # number of fills that arrived in this tick interval
    dt: float         # tick duration (seconds)


# ---------------------------------------------------------------------------
# Core estimator
# ---------------------------------------------------------------------------

class KappaEstimator:
    """
    Rolling Poisson MLE estimator for the AS fill-sensitivity parameter kappa_as.

    Model
    -----
    Fill arrivals on each side follow independent Poisson processes:
        lambda(delta) = A * exp(-kappa_as * delta)

    Both parameters are estimated jointly. A is concentrated out analytically
    at each kappa evaluation, so the optimisation is 1-dimensional.

    Identification note
    -------------------
    With quotes at a single fixed delta, only the product A*exp(-kappa*delta)
    is identified. kappa_as and A are separately identified only when delta
    varies across observations — which naturally occurs as your AS strategy
    skews quotes with inventory. If your spread barely varies, fix kappa_as
    to the offline calibrated value and only update A.

    Parameters
    ----------
    kappa_prior : float
        Initial estimate from offline calibration. Used as regularisation
        centre and returned when insufficient data is available.
    A_prior : float
        Initial estimate of baseline arrival intensity (fills/sec per side
        at delta=0). Used as starting point only, not regularised.
    window_seconds : float
        Rolling window length for estimation. Older observations are dropped.
    min_fills : int
        Minimum fill count before updating away from prior. Below this,
        kappa_prior is returned.
    lam_base : float
        Regularisation strength base. Actual lam = lam_base / sqrt(n_fills),
        i.e. regularisation weakens as data accumulates (Cao et al. 2409.02025).
    update_every : int
        Re-run MLE every this many new fills. Avoids recomputing every tick.
    delta_variation_threshold : float
        If std(delta) across window observations is below this fraction of
        mean(delta), warn that kappa and A may be confounded.
    """

    def __init__(
        self,
        kappa_prior: float = 1.5,
        A_prior: float = 2.0,
        window_seconds: float = 300.0,
        min_fills: int = 50,
        lam_base: float = 0.5,
        update_every: int = 10,
        delta_variation_threshold: float = 0.05,
    ):
        self.kappa_prior = kappa_prior
        self.A_prior = A_prior
        self.window_seconds = window_seconds
        self.min_fills = min_fills
        self.lam_base = lam_base
        self.update_every = update_every
        self.delta_variation_threshold = delta_variation_threshold

        # Current estimates — initialised to prior
        self.kappa_as: float = kappa_prior
        self.A_hat: float = A_prior
        self.se: float = np.inf
        self.n_fills: int = 0
        self.is_calibrated: bool = False   # True once min_fills reached
        self._confounded: bool = False     # True if delta doesn't vary enough

        # Rolling observation window
        self._obs: Deque[_TickObs] = deque()

        # State for building tick-level observations
        self._current_tick_start: Optional[float] = None
        self._current_delta: float = 0.0
        self._current_fill_count: int = 0

        # Fill counter for throttled updates
        self._fills_since_last_update: int = 0

    # ------------------------------------------------------------------
    # Public event interface
    # ------------------------------------------------------------------

    def on_quote_posted(self, timestamp: float, half_spread: float) -> None:
        """
        Call this whenever your strategy posts a new quote (i.e. on every
        BBO tick where you are active). Records the current delta so fills
        can be associated with the right spread.

        If the spread has changed from the previous tick, we close the
        previous tick observation and start a new one.
        """
        if self._current_tick_start is None:
            # First call — start first tick
            self._current_tick_start = timestamp
            self._current_delta = half_spread
            return

        spread_changed = abs(half_spread - self._current_delta) > 1e-8
        tick_too_long   = (timestamp - self._current_tick_start) > 1.0  # force close after 1s

        if spread_changed or tick_too_long:
            self._close_current_tick(timestamp)
            self._current_tick_start = timestamp
            self._current_delta = half_spread
            self._current_fill_count = 0

    def on_fill(self, timestamp: float, half_spread: float) -> None:
        """
        Call this whenever one of YOUR limit orders gets filled.
        half_spread should be the delta at which the fill occurred.
        """
        self._current_fill_count += 1
        self.n_fills += 1
        self._fills_since_last_update += 1

        # Throttled MLE update
        if self._fills_since_last_update >= self.update_every:
            self._close_current_tick(timestamp)
            self._current_tick_start = timestamp
            self._current_delta = half_spread
            self._current_fill_count = 0
            self._run_mle()
            self._fills_since_last_update = 0

    def force_update(self, timestamp: float) -> None:
        """
        Force an MLE update regardless of fill count.
        Call this periodically (e.g. every minute) to ensure estimates
        don't go stale in low-fill periods.
        """
        if self._current_tick_start is not None:
            self._close_current_tick(timestamp)
            self._current_tick_start = timestamp
            self._current_fill_count = 0
        self._run_mle()

    # ------------------------------------------------------------------
    # Internal: tick management
    # ------------------------------------------------------------------

    def _close_current_tick(self, timestamp: float) -> None:
        if self._current_tick_start is None:
            return
        dt = max(timestamp - self._current_tick_start, 1e-6)
        obs = _TickObs(
            timestamp=self._current_tick_start,
            delta=self._current_delta,
            count=self._current_fill_count,
            dt=dt,
        )
        self._obs.append(obs)

        # Prune observations outside window
        cutoff = timestamp - self.window_seconds
        while self._obs and self._obs[0].timestamp < cutoff:
            self._obs.popleft()

    # ------------------------------------------------------------------
    # Internal: MLE
    # ------------------------------------------------------------------

    def _run_mle(self) -> None:
        if not self._obs:
            return

        deltas = np.array([o.delta for o in self._obs])
        counts = np.array([o.count for o in self._obs], dtype=float)
        dts    = np.array([o.dt    for o in self._obs])

        n_fills_in_window = int(counts.sum())

        # Check identification: does delta vary enough?
        delta_cv = np.std(deltas) / (np.mean(deltas) + 1e-12)
        self._confounded = delta_cv < self.delta_variation_threshold

        # Not enough data — stay at prior
        if n_fills_in_window < self.min_fills:
            return

        # Adaptive regularisation: weaker as data accumulates
        lam = self.lam_base / np.sqrt(max(n_fills_in_window, 1))

        def neg_ll(log_kappa: float) -> float:
            k = np.exp(log_kappa)
            exp_terms = np.exp(-k * deltas)
            # Concentrate out A analytically: MLE is A = sum(counts) / sum(exp(-k*d)*dt)
            denom = np.sum(exp_terms * dts)
            if denom < 1e-12:
                return 1e10
            A = counts.sum() / denom
            lam_i = np.clip(A * exp_terms * dts, 1e-10, None)
            ll = np.sum(counts * np.log(lam_i) - lam_i)
            penalty = (lam / 2.0) * (k - self.kappa_prior) ** 2
            return -(ll - penalty)

        try:
            result = minimize_scalar(
                neg_ll,
                bounds=(np.log(0.01), np.log(100.0)),
                method="bounded",
            )
            if not result.success and result.fun > 1e9:
                return  # optimisation failed — keep previous estimate

            k_hat = np.exp(result.x)

            # Recover A at optimal kappa (same formula as inside neg_ll)
            exp_terms = np.exp(-k_hat * deltas)
            A_hat = np.clip(
                counts.sum() / np.sum(exp_terms * dts),
                1e-6, 1e6
            )

            # Standard error via finite-difference Hessian + delta method
            h = 1e-4
            hess = (
                neg_ll(result.x + h)
                - 2.0 * neg_ll(result.x)
                + neg_ll(result.x - h)
            ) / (h ** 2)
            se = k_hat / np.sqrt(max(hess, 1e-10))

            self.kappa_as = k_hat
            self.A_hat    = A_hat
            self.se       = se
            self.is_calibrated = True

        except Exception:
            pass  # keep previous estimate on numerical failure

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def is_confounded(self) -> bool:
        """
        True if delta has not varied enough to separately identify kappa and A.
        In this case kappa_as is estimated but may be unreliable — only
        A*exp(-kappa*delta) is well identified.
        """
        return self._confounded

    @property
    def window_fill_count(self) -> int:
        if not self._obs:
            return 0
        return int(sum(o.count for o in self._obs))

    def summary(self) -> dict:
        return {
            "kappa_as":       self.kappa_as,
            "A_hat":          self.A_hat,
            "se":             self.se,
            "is_calibrated":  self.is_calibrated,
            "is_confounded":  self.is_confounded,
            "n_fills_total":  self.n_fills,
            "n_fills_window": self.window_fill_count,
        }