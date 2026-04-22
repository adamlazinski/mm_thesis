"""
Volatility Measures & Guardrails
----------------------------------

Four volatility estimators running in parallel:

1. RealisedVol      — rolling window of squared log returns (reactive)
2. EWMAVol          — exponentially weighted (smooth, already in MarketState)
3. ParkinsonVol     — range-based using bid/ask spread as a proxy for high/low
4. GarmanKlassVol   — OHLC-style estimator using open/close/high/low within window
5. VolOfVol         — std of recent vol estimates (is vol itself stable?)

These are combined into a VolatilityComposite which:
  - Tracks a rolling history of each estimator
  - Computes percentile rank of current vol vs recent history
  - Outputs a VolState object consumed by the guardrail

The VolGuardrail then translates VolState into:
  - bid_size_multiplier   [0, 1]
  - ask_size_multiplier   [0, 1]
  - spread_multiplier     [1, ∞)
  - should_quote_bid      bool
  - should_quote_ask      bool

The guardrail is inventory-aware: if you're long and vol spikes,
bid size is cut harder than ask size (you don't want to get longer).

References:
  Parkinson (1980) "The Extreme Value Method for Estimating the Variance of the Rate of Return"
  Garman & Klass (1980) "On the Estimation of Security Price Volatilities from Historical Data"
"""

from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import Optional, Tuple
import numpy as np


# ============================================================
# Output types
# ============================================================

@dataclass
class VolEstimates:
    """Current values from all four estimators."""
    realised: float = 0.0
    ewma: float = 0.0
    parkinson: float = 0.0
    garman_klass: float = 0.0
    vol_of_vol: float = 0.0
    composite: float = 0.0       # weighted average of all four
    composite_percentile: float = 0.0   # [0, 1] — where composite sits in recent history


@dataclass
class GuardrailState:
    """
    Sizing and quoting decisions from the guardrail.
    All multipliers are in [0, 1] for sizes, [1, inf) for spreads.
    """
    bid_size_multiplier: float = 1.0
    ask_size_multiplier: float = 1.0
    spread_multiplier: float = 1.0
    should_quote_bid: bool = True
    should_quote_ask: bool = True

    # Diagnostics
    vol_percentile: float = 0.0
    trigger_reason: str = "none"

    @property
    def is_active(self) -> bool:
        """True if any guardrail is currently reducing activity."""
        return (self.bid_size_multiplier < 1.0 or
                self.ask_size_multiplier < 1.0 or
                self.spread_multiplier > 1.0 or
                not self.should_quote_bid or
                not self.should_quote_ask)


# ============================================================
# Individual estimators
# ============================================================

class RealisedVol:
    """
    Rolling window realised volatility.
    Computed as sqrt(mean of squared log returns / dt) — variance per second.

    More reactive than EWMA: responds fully to recent observations
    with no decay weighting.
    """

    def __init__(self, window: int = 100):
        self.window = window
        self._prices: deque[float] = deque(maxlen=window + 1)
        self._times: deque[float] = deque(maxlen=window + 1)

    def update(self, mid: float, timestamp: float) -> Optional[float]:
        self._prices.append(mid)
        self._times.append(timestamp)

        if len(self._prices) < 3:
            return None

        prices = np.array(self._prices)
        times = np.array(self._times)
        log_rets = np.diff(np.log(prices))
        dt = np.diff(times)
        dt = np.where(dt > 1e-6, dt, 1e-6)

        # Variance per second, then annualise to per-second sigma
        var_per_sec = np.mean(log_rets ** 2 / dt)
        return float(np.sqrt(max(var_per_sec, 0)))


class ParkinsonVol:
    """
    Parkinson (1980) range-based volatility estimator.

    Original formula uses daily high/low. Here we adapt it for
    tick data using bid/ask as a proxy:
        high ≈ ask_price
        low  ≈ bid_price

    Over a rolling window of N quote snapshots:
        sigma² = (1 / (4N·ln2)) · sum(ln(ask/bid)²)

    Parkinson vol is ~5× more efficient than close-to-close vol
    because it uses intraday range information. It's also good at
    detecting sudden spread expansions during vol spikes.

    Limitation: underestimates vol in the presence of jumps.
    """

    PARKINSON_CONSTANT = 1.0 / (4.0 * np.log(2))

    def __init__(self, window: int = 100):
        self.window = window
        self._log_hl_sq: deque[float] = deque(maxlen=window)

    def update(self, best_bid: float, best_ask: float) -> Optional[float]:
        if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
            return None

        log_hl_sq = (np.log(best_ask / best_bid)) ** 2
        self._log_hl_sq.append(log_hl_sq)

        if len(self._log_hl_sq) < 5:
            return None

        var = self.PARKINSON_CONSTANT * np.mean(self._log_hl_sq)
        return float(np.sqrt(max(var, 0)))


class GarmanKlassVol:
    """
    Garman-Klass (1980) OHLC volatility estimator.

    Original formula: sigma² = 0.5·ln(H/L)² - (2ln2-1)·ln(C/O)²

    We adapt for tick data by maintaining a rolling window and treating
    each window as a "bar":
        O = first mid price in window
        C = last mid price in window
        H = max mid price in window
        L = min mid price in window

    GK is the most statistically efficient of the four estimators
    (~7.4× more efficient than close-to-close). However it assumes
    continuous trading and no overnight gaps — fine for 24/7 crypto.
    """

    GK_CONSTANT = 2 * np.log(2) - 1  # ≈ 0.3863

    def __init__(self, window: int = 100):
        self.window = window
        self._mids: deque[float] = deque(maxlen=window)

    def update(self, mid: float) -> Optional[float]:
        self._mids.append(mid)

        if len(self._mids) < 5:
            return None

        prices = np.array(self._mids)
        O = prices[0]
        C = prices[-1]
        H = prices.max()
        L = prices.min()

        if O <= 0 or C <= 0 or H <= 0 or L <= 0 or L >= H:
            return None

        hl_term = 0.5 * (np.log(H / L)) ** 2
        co_term = self.GK_CONSTANT * (np.log(C / O)) ** 2
        var = hl_term - co_term

        # GK can occasionally be negative in very quiet windows
        return float(np.sqrt(max(var, 0)))


class VolOfVol:
    """
    Volatility of volatility — the standard deviation of recent vol estimates.

    High vol-of-vol means the market is in an uncertain/transitioning regime.
    Even if current vol is moderate, if it's been jumping around a lot,
    that uncertainty itself is a risk signal.

    Normalised as: vol_of_vol / mean_vol  (coefficient of variation)
    So it's scale-independent and comparable across assets.
    """

    def __init__(self, window: int = 50):
        self.window = window
        self._vol_history: deque[float] = deque(maxlen=window)

    def update(self, composite_vol: float) -> Optional[float]:
        if composite_vol > 0:
            self._vol_history.append(composite_vol)

        if len(self._vol_history) < 10:
            return None

        vols = np.array(self._vol_history)
        mean_vol = np.mean(vols)
        if mean_vol < 1e-10:
            return None

        # Coefficient of variation: std/mean
        return float(np.std(vols) / mean_vol)


# ============================================================
# Composite vol + percentile tracker
# ============================================================

class VolatilityComposite:
    """
    Runs all four estimators in parallel and combines them into a
    single composite signal with percentile ranking.

    Composite = weighted average of available estimators:
        realised:     0.25
        parkinson:    0.25
        garman_klass: 0.30   (highest weight — most efficient)
        ewma:         0.20

    Vol-of-vol is tracked separately and used as a multiplier on
    the composite, not averaged in — it modulates the signal rather
    than contributing to the level.

    Percentile is computed over a rolling history of `percentile_window`
    composite observations. This self-calibrates to your asset:
    a 2% daily vol might be 95th percentile for BTC on a quiet day
    and 20th percentile during a crisis.

    Parameters
    ----------
    realised_window : int
        Lookback for realised vol (number of ticks).
    parkinson_window : int
        Lookback for Parkinson vol.
    gk_window : int
        Lookback for Garman-Klass vol.
    vol_of_vol_window : int
        History length for vol-of-vol.
    percentile_window : int
        History of composite vol observations for percentile computation.
    ewma_alpha : float
        EWMA decay factor.
    """

    def __init__(
        self,
        realised_window: int = 100,
        parkinson_window: int = 100,
        gk_window: int = 100,
        vol_of_vol_window: int = 50,
        percentile_window: int = 500,
        ewma_alpha: float = 0.94,
    ):
        self.realised = RealisedVol(window=realised_window)
        self.parkinson = ParkinsonVol(window=parkinson_window)
        self.garman_klass = GarmanKlassVol(window=gk_window)
        self.vol_of_vol = VolOfVol(window=vol_of_vol_window)

        self.ewma_alpha = ewma_alpha
        self._ewma_var: float = 0.0
        self._ewma_ready: bool = False
        self._prev_mid: Optional[float] = None
        self._prev_time: Optional[float] = None

        # Rolling history for percentile computation
        self._composite_history: deque[float] = deque(maxlen=percentile_window)

        # Weights for composite (must sum to 1.0)
        self._weights = {
            "realised": 0.25,
            "parkinson": 0.25,
            "garman_klass": 0.30,
            "ewma": 0.20,
        }

        # Last estimates — public for inspection
        self.estimates = VolEstimates()

    def on_quote(
        self,
        timestamp: float,
        mid: float,
        best_bid: float,
        best_ask: float,
    ) -> VolEstimates:
        """
        Update all estimators on a new quote event.
        Returns the latest VolEstimates.
        """
        # 1. Realised vol
        rv = self.realised.update(mid, timestamp)

        # 2. Parkinson
        pk = self.parkinson.update(best_bid, best_ask)

        # 3. Garman-Klass
        gk = self.garman_klass.update(mid)

        # 4. EWMA
        ewma = self._update_ewma(mid, timestamp)

        # 5. Composite — only use estimators that have enough data
        composite = self._compute_composite(rv, pk, gk, ewma)

        # 6. Vol-of-vol (fed by composite)
        vov = self.vol_of_vol.update(composite) if composite > 0 else None

        # 7. Percentile
        if composite > 0:
            self._composite_history.append(composite)
        pct = self._compute_percentile(composite)

        self.estimates = VolEstimates(
            realised=rv or 0.0,
            ewma=ewma or 0.0,
            parkinson=pk or 0.0,
            garman_klass=gk or 0.0,
            vol_of_vol=vov or 0.0,
            composite=composite,
            composite_percentile=pct,
        )

        return self.estimates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_ewma(self, mid: float, timestamp: float) -> Optional[float]:
        if self._prev_mid is not None and self._prev_time is not None:
            dt = timestamp - self._prev_time
            if dt > 1e-6 and self._prev_mid > 0:
                log_ret = np.log(mid / self._prev_mid)
                ret_sq = (log_ret ** 2) / dt
                if not self._ewma_ready:
                    self._ewma_var = ret_sq
                    self._ewma_ready = True
                else:
                    a = self.ewma_alpha
                    self._ewma_var = a * self._ewma_var + (1 - a) * ret_sq

        self._prev_mid = mid
        self._prev_time = timestamp

        if self._ewma_ready:
            return float(np.sqrt(max(self._ewma_var, 0)))
        return None

    def _compute_composite(
        self,
        rv: Optional[float],
        pk: Optional[float],
        gk: Optional[float],
        ewma: Optional[float],
    ) -> float:
        estimates = {
            "realised": rv,
            "parkinson": pk,
            "garman_klass": gk,
            "ewma": ewma,
        }

        # Only use estimators that have returned a value
        available = {k: v for k, v in estimates.items() if v is not None and v > 0}
        if not available:
            return 0.0

        # Re-normalise weights for available estimators
        total_weight = sum(self._weights[k] for k in available)
        if total_weight == 0:
            return 0.0

        composite = sum(
            v * self._weights[k] / total_weight
            for k, v in available.items()
        )
        return float(composite)

    def _compute_percentile(self, current_vol: float) -> float:
        """
        Where does current_vol sit in the recent history?
        Returns a value in [0, 1].
        0.95 means current vol is higher than 95% of recent observations.
        """
        if len(self._composite_history) < 20 or current_vol <= 0:
            return 0.5  # not enough history — assume median

        history = np.array(self._composite_history)
        # Fraction of historical observations below current vol
        return float(np.mean(history <= current_vol))

    @property
    def is_ready(self) -> bool:
        return len(self._composite_history) >= 20


# ============================================================
# The Guardrail
# ============================================================

class VolGuardrail:
    """
    Translates volatility percentile into sizing and quoting decisions.

    Behaviour
    ---------
    The guardrail has two zones defined by percentile thresholds:

    Zone 1 — Soft scaling  [soft_threshold, hard_threshold)
        Size scales linearly from 1.0 down to min_size_multiplier.
        Spread scales linearly from 1.0 up to max_spread_multiplier.
        Inventory-aware: the side that would increase a large inventory
        gets an additional size cut on top.

    Zone 2 — Hard floor    [hard_threshold, 1.0]
        Size is floored at min_size_multiplier on both sides.
        Spread is floored at max_spread_multiplier.
        If inventory is also large AND we're in this zone, the
        inventory-increasing side is stopped entirely.

    The vol-of-vol signal adds an additional multiplier:
        If vol_of_vol > vov_threshold, sizes are further reduced
        by vov_penalty (independent of the percentile zone).

    Parameters
    ----------
    soft_threshold : float
        Percentile above which soft scaling begins. Default 0.60.
    hard_threshold : float
        Percentile above which the hard floor applies. Default 0.90.
    min_size_multiplier : float
        Minimum size as fraction of nominal. Default 0.20 (20%).
    max_spread_multiplier : float
        Maximum spread multiplier at hard threshold. Default 3.0.
    inventory_bias_threshold : float
        Absolute inventory (as fraction of max) above which the
        inventory-increasing side gets extra cut. Default 0.5.
    inventory_bias_cut : float
        Additional size reduction on the inventory-increasing side.
        Default 0.5 (halved again on top of vol scaling).
    vov_threshold : float
        Vol-of-vol (coefficient of variation) above which extra
        penalty applies. Default 0.3.
    vov_penalty : float
        Size multiplier applied when vol-of-vol is elevated. Default 0.7.
    """

    def __init__(
        self,
        soft_threshold: float = 0.60,
        hard_threshold: float = 0.90,
        min_size_multiplier: float = 0.20,
        max_spread_multiplier: float = 3.0,
        inventory_bias_threshold: float = 0.50,
        inventory_bias_cut: float = 0.50,
        vov_threshold: float = 0.30,
        vov_penalty: float = 0.70,
    ):
        self.soft_threshold = soft_threshold
        self.hard_threshold = hard_threshold
        self.min_size_multiplier = min_size_multiplier
        self.max_spread_multiplier = max_spread_multiplier
        self.inventory_bias_threshold = inventory_bias_threshold
        self.inventory_bias_cut = inventory_bias_cut
        self.vov_threshold = vov_threshold
        self.vov_penalty = vov_penalty

    def evaluate(
        self,
        vol_estimates: VolEstimates,
        inventory: float,
        max_inventory: float,
    ) -> GuardrailState:
        """
        Compute guardrail state from current vol and inventory.

        Parameters
        ----------
        vol_estimates : VolEstimates
            Output from VolatilityComposite.on_quote()
        inventory : float
            Current position in base asset (signed).
        max_inventory : float
            Hard inventory limit from the strategy.
        """
        pct = vol_estimates.composite_percentile
        vov = vol_estimates.vol_of_vol
        inv_ratio = abs(inventory) / max(max_inventory, 1e-6)  # [0, 1]

        # ------------------------------------------------------------------
        # Step 1: Base size multiplier from vol percentile
        # ------------------------------------------------------------------
        base_mult = self._vol_size_multiplier(pct)
        spread_mult = self._vol_spread_multiplier(pct)
        trigger = "none"

        if pct >= self.hard_threshold:
            trigger = f"hard_vol (p={pct:.2f})"
        elif pct >= self.soft_threshold:
            trigger = f"soft_vol (p={pct:.2f})"

        # ------------------------------------------------------------------
        # Step 2: Vol-of-vol penalty (applied on top)
        # ------------------------------------------------------------------
        if vov > self.vov_threshold:
            base_mult *= self.vov_penalty
            trigger += f"+vov({vov:.2f})"

        # ------------------------------------------------------------------
        # Step 3: Inventory-aware asymmetric cut
        # Both sides start at base_mult; the side that increases
        # a large inventory gets cut further.
        # ------------------------------------------------------------------
        bid_mult = base_mult
        ask_mult = base_mult

        if inv_ratio > self.inventory_bias_threshold and pct >= self.soft_threshold:
            if inventory > 0:
                # Long and vol is elevated → cut bids harder (don't get longer)
                bid_mult *= self.inventory_bias_cut
                trigger += f"+long_bias(inv={inventory:.3f})"
            elif inventory < 0:
                # Short and vol is elevated → cut asks harder (don't get shorter)
                ask_mult *= self.inventory_bias_cut
                trigger += f"+short_bias(inv={inventory:.3f})"

        # ------------------------------------------------------------------
        # Step 4: Hard stop on inventory-increasing side in extreme vol
        # ------------------------------------------------------------------
        should_quote_bid = True
        should_quote_ask = True

        if pct >= self.hard_threshold and inv_ratio > 0.8:
            if inventory > 0:
                should_quote_bid = False
                trigger += "+bid_stopped"
            elif inventory < 0:
                should_quote_ask = False
                trigger += "+ask_stopped"

        # ------------------------------------------------------------------
        # Clamp all multipliers
        # ------------------------------------------------------------------
        bid_mult = float(np.clip(bid_mult, self.min_size_multiplier, 1.0))
        ask_mult = float(np.clip(ask_mult, self.min_size_multiplier, 1.0))
        spread_mult = float(np.clip(spread_mult, 1.0, self.max_spread_multiplier))

        return GuardrailState(
            bid_size_multiplier=bid_mult,
            ask_size_multiplier=ask_mult,
            spread_multiplier=spread_mult,
            should_quote_bid=should_quote_bid,
            should_quote_ask=should_quote_ask,
            vol_percentile=pct,
            trigger_reason=trigger if trigger != "none" else "none",
        )

    # ------------------------------------------------------------------
    # Scaling curves
    # ------------------------------------------------------------------

    def _vol_size_multiplier(self, percentile: float) -> float:
        """
        Linear interpolation from 1.0 at soft_threshold down to
        min_size_multiplier at hard_threshold. Flat outside those bounds.

              1.0 ──────────┐
                             ╲
        min_size ─────────────╲──────  (flat at floor beyond hard_threshold)
                  0   soft   hard   1
        """
        if percentile < self.soft_threshold:
            return 1.0
        if percentile >= self.hard_threshold:
            return self.min_size_multiplier

        # Linear interpolation in the scaling zone
        t = (percentile - self.soft_threshold) / (self.hard_threshold - self.soft_threshold)
        return 1.0 - t * (1.0 - self.min_size_multiplier)

    def _vol_spread_multiplier(self, percentile: float) -> float:
        """
        Spread widens as vol rises. Linear from 1.0 at soft_threshold
        to max_spread_multiplier at hard_threshold.
        """
        if percentile < self.soft_threshold:
            return 1.0
        if percentile >= self.hard_threshold:
            return self.max_spread_multiplier

        t = (percentile - self.soft_threshold) / (self.hard_threshold - self.soft_threshold)
        return 1.0 + t * (self.max_spread_multiplier - 1.0)


# ============================================================
# Combined wrapper: composite vol + guardrail in one object
# ============================================================

class VolRiskManager:
    """
    Drop-in risk manager that combines VolatilityComposite and VolGuardrail.

    Usage in the backtest loop:
        vol_rm = VolRiskManager()

        # On every quote event:
        guardrail = vol_rm.on_quote(timestamp, mid, best_bid, best_ask,
                                     inventory, max_inventory)

        # Apply to strategy decision:
        decision.bid_size *= guardrail.bid_size_multiplier
        decision.ask_size *= guardrail.ask_size_multiplier
        if not guardrail.should_quote_bid: skip bid
        if not guardrail.should_quote_ask: skip ask

    Parameters
    ----------
    All parameters passed through to VolatilityComposite and VolGuardrail.
    See their docstrings for details.
    """

    def __init__(
        self,
        # VolatilityComposite params
        realised_window: int = 100,
        parkinson_window: int = 100,
        gk_window: int = 100,
        vol_of_vol_window: int = 50,
        percentile_window: int = 500,
        ewma_alpha: float = 0.94,
        # VolGuardrail params
        soft_threshold: float = 0.60,
        hard_threshold: float = 0.90,
        min_size_multiplier: float = 0.20,
        max_spread_multiplier: float = 3.0,
        inventory_bias_threshold: float = 0.50,
        inventory_bias_cut: float = 0.50,
        vov_threshold: float = 0.30,
        vov_penalty: float = 0.70,
    ):
        self.composite = VolatilityComposite(
            realised_window=realised_window,
            parkinson_window=parkinson_window,
            gk_window=gk_window,
            vol_of_vol_window=vol_of_vol_window,
            percentile_window=percentile_window,
            ewma_alpha=ewma_alpha,
        )
        self.guardrail = VolGuardrail(
            soft_threshold=soft_threshold,
            hard_threshold=hard_threshold,
            min_size_multiplier=min_size_multiplier,
            max_spread_multiplier=max_spread_multiplier,
            inventory_bias_threshold=inventory_bias_threshold,
            inventory_bias_cut=inventory_bias_cut,
            vov_threshold=vov_threshold,
            vov_penalty=vov_penalty,
        )

        # Public state
        self.estimates = VolEstimates()
        self.guardrail_state = GuardrailState()

    def on_quote(
        self,
        timestamp: float,
        mid: float,
        best_bid: float,
        best_ask: float,
        inventory: float,
        max_inventory: float,
    ) -> GuardrailState:
        """
        Call on every quote event. Returns the current guardrail state.
        """
        self.estimates = self.composite.on_quote(timestamp, mid, best_bid, best_ask)
        self.guardrail_state = self.guardrail.evaluate(
            self.estimates, inventory, max_inventory
        )
        return self.guardrail_state

    @property
    def is_ready(self) -> bool:
        return self.composite.is_ready

    def summary(self) -> str:
        e = self.estimates
        g = self.guardrail_state
        return (
            f"Vol: realised={e.realised:.6f} ewma={e.ewma:.6f} "
            f"park={e.parkinson:.6f} gk={e.garman_klass:.6f} "
            f"composite={e.composite:.6f} pct={e.composite_percentile:.2f} "
            f"vov={e.vol_of_vol:.3f} | "
            f"Guard: bid={g.bid_size_multiplier:.2f} ask={g.ask_size_multiplier:.2f} "
            f"spread={g.spread_multiplier:.2f} "
            f"quote_bid={g.should_quote_bid} quote_ask={g.should_quote_ask} "
            f"reason={g.trigger_reason}"
        )
