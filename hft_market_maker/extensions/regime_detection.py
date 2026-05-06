"""
Regime Recognition
------------------

Detects market regimes from tick data and adjusts strategy parameters accordingly.

Regimes implemented:
  1. Trending       — strong directional price movement
  2. Ranging        — mean-reverting, good for market making
  3. High Volatility — volatile but not trending (noisy)
  4. Low Liquidity  — wide spreads, sparse trades

Detection methods:
  - Hurst exponent (trending vs mean-reverting)
  - Volatility z-score (high vol vs normal)
  - Trade arrival rate (liquidity)
  - Directional trade imbalance (trend confirmation)
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from collections import deque
from typing import Optional
import numpy as np


class Regime(Enum):
    RANGING = auto()          # Mean-reverting — ideal for market making
    TRENDING_UP = auto()      # Strong upward trend — lean short
    TRENDING_DOWN = auto()    # Strong downward trend — lean long
    HIGH_VOLATILITY = auto()  # Volatile / uncertain — widen spreads
    LOW_LIQUIDITY = auto()    # Thin market — be selective


@dataclass
class RegimeState:
    regime: Regime
    confidence: float         # [0, 1]
    hurst: float              # Hurst exponent estimate
    vol_zscore: float         # Vol z-score vs recent history
    trend_strength: float     # Signed trend [-1, 1]
    liquidity_score: float    # [0, 1], higher = more liquid

    # Strategy parameter adjustments
    gamma_multiplier: float = 1.0
    spread_multiplier: float = 1.0
    size_multiplier: float = 1.0


class RegimeDetector:
    """
    Event-driven regime detector.

    Parameters
    ----------
    hurst_window : int
        Number of mid-price observations for Hurst estimation.
    vol_window : int
        Lookback for vol z-score computation.
    trend_window : int
        Trades to use for directional imbalance.
    update_interval : float
        Minimum seconds between regime updates (avoid thrashing).
    """

    def __init__(
        self,
        hurst_window: int = 200,
        vol_window: int = 100,
        trend_window: int = 50,
        update_interval: float = 30.0,
        liquidity_window: float = 60.0,
    ):
        self.hurst_window = hurst_window
        self.vol_window = vol_window
        self.trend_window = trend_window
        self.update_interval = update_interval
        self.liquidity_window = liquidity_window

        self._mid_prices: deque[float] = deque(maxlen=hurst_window)
        self._mid_times: deque[float] = deque(maxlen=hurst_window)
        self._vol_history: deque[float] = deque(maxlen=vol_window)
        self._trade_sides: deque[str] = deque(maxlen=trend_window)
        self._trade_times: deque[float] = deque()

        self._last_update: float = 0.0
        self.current_regime: RegimeState = RegimeState(
            regime=Regime.RANGING,
            confidence=0.5,
            hurst=0.5,
            vol_zscore=0.0,
            trend_strength=0.0,
            liquidity_score=1.0,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_quote(self, timestamp: float, mid: float, sigma: float) -> None:
        self._mid_prices.append(mid)
        self._mid_times.append(timestamp)
        self._vol_history.append(sigma)

        if timestamp - self._last_update >= self.update_interval:
            self._update_regime(timestamp)
            self._last_update = timestamp

    def on_trade(self, timestamp: float, side: str) -> None:
        self._trade_sides.append(side)
        self._trade_times.append(timestamp)

        # Prune old trades
        cutoff = timestamp - self.liquidity_window
        while self._trade_times and self._trade_times[0] < cutoff:
            self._trade_times.popleft()

    # ------------------------------------------------------------------
    # Regime computation
    # ------------------------------------------------------------------

    def _update_regime(self, timestamp: float) -> None:
        if len(self._mid_prices) < 30:
            return

        hurst = self._estimate_hurst()
        vol_zscore = self._vol_zscore()
        trend_strength = self._trend_strength()
        liquidity = self._liquidity_score(timestamp)

        regime, confidence = self._classify(hurst, vol_zscore, trend_strength, liquidity)
        adjustments = self._get_adjustments(regime, vol_zscore, trend_strength)

        self.current_regime = RegimeState(
            regime=regime,
            confidence=confidence,
            hurst=hurst,
            vol_zscore=vol_zscore,
            trend_strength=trend_strength,
            liquidity_score=liquidity,
            **adjustments,
        )

    def _estimate_hurst(self) -> float:
        """
        Estimate Hurst exponent using the R/S (rescaled range) method.
        H < 0.5 → mean-reverting (ideal for MM)
        H ≈ 0.5 → random walk
        H > 0.5 → trending (dangerous for MM)
        """
        prices = np.array(self._mid_prices)
        if len(prices) < 20:
            return 0.5

        log_prices = np.log(prices)
        returns = np.diff(log_prices)

        # R/S analysis with multiple lags
        lags = [8, 16, 32, min(64, len(returns) // 2)]
        lags = [l for l in lags if l < len(returns)]

        if len(lags) < 2:
            return 0.5

        rs_values = []
        for lag in lags:
            rs = self._rs_statistic(returns[:lag])
            rs_values.append(rs)

        # Hurst from log-log regression
        log_lags = np.log(lags)
        log_rs = np.log(np.array(rs_values) + 1e-10)
        try:
            hurst = np.polyfit(log_lags, log_rs, 1)[0]
            return float(np.clip(hurst, 0.0, 1.0))
        except Exception:
            return 0.5

    def _rs_statistic(self, returns: np.ndarray) -> float:
        if len(returns) < 2:
            return 1.0
        mean_ret = np.mean(returns)
        deviations = np.cumsum(returns - mean_ret)
        R = np.max(deviations) - np.min(deviations)
        S = np.std(returns)
        if S < 1e-10:
            return 1.0
        return R / S

    def _vol_zscore(self) -> float:
        vols = np.array(self._vol_history)
        if len(vols) < 10:
            return 0.0
        mean_vol = np.mean(vols[:-1])
        std_vol = np.std(vols[:-1]) + 1e-10
        return (vols[-1] - mean_vol) / std_vol

    def _trend_strength(self) -> float:
        """Signed trend: +1 = strong up, -1 = strong down."""
        sides = list(self._trade_sides)
        if len(sides) < 5:
            return 0.0
        n_buy = sides.count("buy")
        n_sell = sides.count("sell")
        total = n_buy + n_sell
        if total == 0:
            return 0.0
        return (n_buy - n_sell) / total  # in [-1, 1]

    def _liquidity_score(self, timestamp: float) -> float:
        """Normalised trade arrival rate. Higher = more liquid."""
        recent = sum(1 for t in self._trade_times if timestamp - t <= self.liquidity_window)
        # Normalise: assume 10 trades/minute = normal
        normal_rate = 10.0 * self.liquidity_window / 60.0
        return min(recent / normal_rate, 1.0)

    def _classify(
        self,
        hurst: float,
        vol_zscore: float,
        trend_strength: float,
        liquidity: float,
    ) -> tuple[Regime, float]:
        # Low liquidity overrides everything
        if liquidity < 0.2:
            return Regime.LOW_LIQUIDITY, 0.8

        # High volatility
        if vol_zscore > 2.5:
            return Regime.HIGH_VOLATILITY, min(1.0, vol_zscore / 4.0)

        # Trending up or down
        if hurst > 0.6 and abs(trend_strength) > 0.3:
            if trend_strength > 0:
                return Regime.TRENDING_UP, min(1.0, (hurst - 0.5) * 4)
            else:
                return Regime.TRENDING_DOWN, min(1.0, (hurst - 0.5) * 4)

        # Mean-reverting / ranging
        if hurst < 0.5:
            return Regime.RANGING, min(1.0, (0.5 - hurst) * 4)

        # Default
        return Regime.RANGING, 0.4

    def _get_adjustments(
        self,
        regime: Regime,
        vol_zscore: float,
        trend_strength: float,
    ) -> dict:
        """
        Returns strategy parameter multipliers for the detected regime.
        """
        if regime == Regime.RANGING:
            return {"gamma_multiplier": 0.7, "spread_multiplier": 0.8, "size_multiplier": 1.2}

        elif regime == Regime.TRENDING_UP:
            # Lean short: tighter asks, wider bids
            return {"gamma_multiplier": 1.5, "spread_multiplier": 1.3, "size_multiplier": 0.7}

        elif regime == Regime.TRENDING_DOWN:
            return {"gamma_multiplier": 1.5, "spread_multiplier": 1.3, "size_multiplier": 0.7}

        elif regime == Regime.HIGH_VOLATILITY:
            vol_scale = 1.0 + vol_zscore * 0.3
            return {
                "gamma_multiplier": vol_scale,
                "spread_multiplier": vol_scale,
                "size_multiplier": max(0.3, 1.0 / vol_scale),
            }

        elif regime == Regime.LOW_LIQUIDITY:
            return {"gamma_multiplier": 2.0, "spread_multiplier": 2.0, "size_multiplier": 0.5}

        return {"gamma_multiplier": 1.0, "spread_multiplier": 1.0, "size_multiplier": 1.0}


# ===========================================================================
# Regime-Aware Strategy Wrapper
# ===========================================================================

class RegimeAwareAS:
    """
    Wraps any A-S strategy variant with regime detection.
    Adjusts gamma, spread, and size based on detected regime.
    """

    def __init__(self, base_strategy, regime_detector: Optional[RegimeDetector] = None):
        self.strategy = base_strategy
        self.detector = regime_detector or RegimeDetector()

    def on_quote(self, timestamp: float, mid: float, sigma: float) -> None:
        self.detector.on_quote(timestamp, mid, sigma)

    def on_trade(self, timestamp: float, side: str) -> None:
        self.detector.on_trade(timestamp, side)

    def compute_quotes(self, stats, inventory: float, timestamp: float):
        decision = self.strategy.compute_quotes(stats, inventory, timestamp)
        regime = self.detector.current_regime

        # Apply regime multipliers
        original_gamma = self.strategy.gamma
        original_min_spread = self.strategy.min_spread

        # Scale parameters
        self.strategy.gamma *= regime.gamma_multiplier
        self.strategy.min_spread *= regime.spread_multiplier
        decision = self.strategy.compute_quotes(stats, inventory, timestamp)
        decision.bid_size *= regime.size_multiplier
        decision.ask_size *= regime.size_multiplier

        # Restore
        self.strategy.gamma = original_gamma
        self.strategy.min_spread = original_min_spread

        return decision, regime


class RegimeFilter:
    """
    Lightweight wrapper that suppresses quoting during high-volatility or
    high-momentum regimes. Works with any strategy (A-S, GLFT, ShiftedGLFT).

    The GLFT/ShiftedGLFT Poisson fill model holds during calm, liquidity-driven
    windows (R²>0.8 in the kappa analysis). This filter pauses quoting when:
      - sigma_dollar = stats.sigma × mid > vol_threshold  (price vol too high)
      - |stats.momentum| > mom_threshold                  (directional drift)

    In bad regimes, sets should_quote_bid = should_quote_ask = False on the
    decision so the backtest cancels any live orders and skips submission.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    vol_threshold : float
        Dollar volatility ceiling (sigma × mid). Default 3.0 $/√s, chosen
        from thesis finding that good GLFT fit windows have σ_$ < 3.
    mom_threshold : float
        Normalised momentum ceiling [0,1]. Default 0.5 (= 0.5/3 sigma moves
        over the 5s window, beyond which momentum adverse selection dominates).
    """

    def __init__(self, base, vol_threshold: float = 3.0, mom_threshold: float = 0.5):
        self.base = base
        self.vol_threshold = vol_threshold
        self.mom_threshold = mom_threshold
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        # track regime state for metrics
        self.in_bad_regime: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        sigma_dollar = stats.sigma * stats.mid_price
        self.in_bad_regime = (
            sigma_dollar > self.vol_threshold or
            abs(stats.momentum) > self.mom_threshold
        )

        if self.in_bad_regime:
            decision.should_quote_bid = False
            decision.should_quote_ask = False
        else:
            if not hasattr(decision, "should_quote_bid"):
                decision.should_quote_bid = True
                decision.should_quote_ask = True

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True
