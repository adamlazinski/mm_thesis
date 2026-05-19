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

    def __init__(
        self,
        base,
        vol_threshold: float = 3.0,
        mom_threshold: float = 0.5,
        ofi_threshold: float = float("inf"),
    ):
        self.base = base
        self.vol_threshold = vol_threshold
        self.mom_threshold = mom_threshold
        self.ofi_threshold = ofi_threshold   # |OFI| ceiling; inf = disabled
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        self.in_bad_regime: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        sigma_dollar = stats.sigma * stats.mid_price
        self.in_bad_regime = (
            sigma_dollar > self.vol_threshold or
            abs(stats.momentum) > self.mom_threshold or
            abs(stats.ofi) > self.ofi_threshold
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


class OFIDirectedFilter:
    """
    One-sided quoting based on real-time order flow imbalance.

    Instead of suppressing all quotes during strong OFI (RegimeFilter),
    this wrapper participates on ONLY the side that is "safe" given the
    current flow direction:

      OFI > +ofi_threshold  (buy pressure):
          quote ASK only — sell to buyers at mid+δ
          suppress BID  — avoid catching the knife if the bid gets hit by informed sellers
      OFI < -ofi_threshold  (sell pressure):
          quote BID only — buy from sellers at mid-δ
          suppress ASK  — avoid selling cheap into informed selling
      |OFI| ≤ ofi_threshold  (balanced):
          quote both sides normally

    Parameters
    ----------
    base : any strategy with compute_quotes()
    ofi_threshold : float
        OFI magnitude above which one-sided quoting activates. [0, 1].
        0.0 = always one-sided (never two-sided).
        1.0 = effectively disabled (always two-sided).
        Typical range to search: [0.1, 0.6].
    mom_threshold : float
        Supplementary momentum gate — full suppression if |momentum| exceeds
        this (avoids quoting into strong sustained trends). inf = disabled.
    """

    def __init__(
        self,
        base,
        ofi_threshold: float = 0.3,
        mom_threshold: float = float("inf"),
    ):
        self.base = base
        self.ofi_threshold = ofi_threshold
        self.mom_threshold = mom_threshold
        self.max_inventory = getattr(base, "max_inventory", 1.0)

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        ofi = stats.ofi
        mom = stats.momentum

        # Full suppression if momentum is extreme (trend too strong to fade)
        if abs(mom) > self.mom_threshold:
            decision.should_quote_bid = False
            decision.should_quote_ask = False
            return decision

        if ofi > self.ofi_threshold:
            # Buy pressure: quote ask only (sell to buyers, avoid bid adverse selection)
            decision.should_quote_bid = False
            decision.should_quote_ask = True
        elif ofi < -self.ofi_threshold:
            # Sell pressure: quote bid only (buy from sellers, avoid ask adverse selection)
            decision.should_quote_bid = True
            decision.should_quote_ask = False
        else:
            # Balanced: quote both sides
            if not hasattr(decision, "should_quote_bid"):
                decision.should_quote_bid = True
                decision.should_quote_ask = True

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class KyleLambdaFilter:
    """
    Suppresses quoting when Kyle's lambda (price impact per unit signed volume)
    exceeds a threshold, indicating elevated informed trading activity.

    lambda is computed in MarketState via EWMA OLS over quote intervals.
    High lambda = each BTC of net flow moves price a lot = informed flow.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    lambda_threshold : float
        Kyle's lambda above which quoting is suppressed. Units: $/BTC.
        Typical intraday BTC range: 0.001–0.10 $/BTC.
    """

    def __init__(self, base, lambda_threshold: float = 0.01):
        self.base = base
        self.lambda_threshold = lambda_threshold
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        self.in_high_impact: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        lam = stats.kyle_lambda
        self.in_high_impact = lam != 0.0 and lam > self.lambda_threshold

        if self.in_high_impact:
            decision.should_quote_bid = False
            decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class DynamicSizeFilter:
    """
    Scales order sizes down when the market is in a high-toxicity state,
    without suppressing quoting entirely. Reduces adverse selection exposure
    while maintaining presence in the order book.

    Uses the trade-rate spike ratio (short/long window) as the toxicity proxy.
    size_multiplier = clip(1 / (1 + sensitivity * max(spike_ratio - 1, 0)), min_mult, 1)

    Parameters
    ----------
    base : any strategy with compute_quotes()
    sensitivity : float
        Controls how aggressively size is reduced on spikes. Default 0.5.
    min_mult : float
        Minimum size multiplier (floor). Default 0.2 (20% of normal size).
    """

    def __init__(self, base, sensitivity: float = 0.5, min_mult: float = 0.2):
        self.base = base
        self.sensitivity = sensitivity
        self.min_mult = min_mult
        self.max_inventory = getattr(base, "max_inventory", 1.0)

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        baseline = stats.trades_per_sec
        short_rate = stats.trades_per_sec_short
        spike_ratio = (short_rate / baseline) if baseline > 0.1 else 1.0
        excess = max(spike_ratio - 1.0, 0.0)
        mult = max(1.0 / (1.0 + self.sensitivity * excess), self.min_mult)

        decision.bid_size = decision.bid_size * mult
        decision.ask_size = decision.ask_size * mult

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class SpreadMultiplierFilter:
    """
    Widens the quoted spread by a toxicity-dependent multiplier instead of
    suppressing quoting entirely. More conservative than hard-stop filters —
    the strategy remains in the book but demands a larger premium in toxic regimes.

    spread_mult = 1 + alpha * toxicity_signal

    Toxicity signal options (toxicity_signal param):
      "vpin"   : stats.vpin (calibrated bucket size needed)
      "spike"  : short/long trade-rate ratio
      "lambda" : stats.kyle_lambda (normalised by lambda_scale)
      "ofi"    : |stats.ofi|

    Applies the multiplier to the optimal_spread, shifting bid/ask symmetrically
    around the reservation price.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    alpha : float
        Sensitivity to the toxicity signal. spread_mult = 1 + alpha * signal.
    signal : str
        Which signal to use. One of {"vpin", "spike", "lambda", "ofi"}.
    lambda_scale : float
        Scale for normalising kyle_lambda. Default 0.01 ($/BTC).
    max_mult : float
        Cap on the spread multiplier. Default 5.0.
    """

    def __init__(
        self,
        base,
        alpha: float = 2.0,
        signal: str = "spike",
        lambda_scale: float = 0.01,
        max_mult: float = 5.0,
    ):
        self.base = base
        self.alpha = alpha
        self.signal = signal
        self.lambda_scale = lambda_scale
        self.max_mult = max_mult
        self.max_inventory = getattr(base, "max_inventory", 1.0)

    def _get_toxicity(self, stats) -> float:
        if self.signal == "vpin":
            return max(stats.vpin - 0.5, 0.0) * 2.0  # map [0.5,1] → [0,1]
        elif self.signal == "spike":
            baseline = stats.trades_per_sec
            short = stats.trades_per_sec_short
            return max((short / baseline) - 1.0, 0.0) if baseline > 0.1 else 0.0
        elif self.signal == "lambda":
            return max(stats.kyle_lambda / self.lambda_scale, 0.0)
        elif self.signal == "ofi":
            return abs(stats.ofi)
        return 0.0

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        toxicity = self._get_toxicity(stats)
        mult = min(1.0 + self.alpha * toxicity, self.max_mult)

        # Re-centre bid/ask around reservation price with widened spread
        r = decision.reservation_price
        new_half = (decision.optimal_spread / 2.0) * mult
        from ..strategies.avellaneda_stoikov import QuoteDecision
        tick = getattr(getattr(self.base, "base", self.base), "tick_size", 0.01)

        import numpy as np
        decision.bid_price = np.floor((r - new_half) / tick) * tick
        decision.ask_price = np.ceil((r + new_half) / tick) * tick
        decision.optimal_spread = new_half * 2.0

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class TradeSpikeFilter:
    """
    Pauses quoting when the short-window trade arrival rate spikes above
    the long-window baseline by a multiplier — a sign of informed flow bursts.

    Uses stats.trades_per_sec_short (spike_window, default 5s) vs
    stats.trades_per_sec (arrival_window, default 60s).

    Parameters
    ----------
    base : any strategy with compute_quotes()
    spike_multiplier : float
        Suppress when short_rate > multiplier × long_rate. Default 3.0.
    spike_cooldown : float
        Seconds to remain suppressed after the spike clears. Default 5.0.
    min_baseline : float
        Minimum baseline trades/sec before spike detection is active.
        Prevents false positives at session open. Default 0.5.
    """

    def __init__(
        self,
        base,
        spike_multiplier: float = 3.0,
        spike_cooldown: float = 5.0,
        min_baseline: float = 0.5,
    ):
        self.base = base
        self.spike_multiplier = spike_multiplier
        self.spike_cooldown = spike_cooldown
        self.min_baseline = min_baseline
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        self._cooldown_until: float = 0.0
        self.in_spike: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        baseline = stats.trades_per_sec
        short_rate = stats.trades_per_sec_short

        is_spike = (
            baseline >= self.min_baseline and
            short_rate > self.spike_multiplier * baseline
        )

        if is_spike:
            self._cooldown_until = timestamp + self.spike_cooldown

        self.in_spike = timestamp < self._cooldown_until

        if self.in_spike:
            decision.should_quote_bid = False
            decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class DailyLossLimit:
    """
    Stops quoting for the rest of the calendar day (UTC) once cumulative
    daily P&L falls below -daily_limit.

    Receives total_pnl via the kwarg that Backtest passes to compute_quotes().
    Tracks day boundaries from the event timestamp.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    daily_limit : float
        Maximum allowed loss per day (positive number). Default 20.0.
    liquidate_ticks : float or None
        When set and the limit fires, quote aggressively on the inventory-
        reducing side (bid at mid+ticks when short, ask at mid-ticks when
        long) to unwind the position. None = old behaviour (halt only).
    """

    def __init__(self, base, daily_limit: float = 20.0,
                 liquidate_ticks: float = None):
        self.base = base
        self.daily_limit = daily_limit
        self.liquidate_ticks = liquidate_ticks
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        # Traverse filter chain to find tick_size on the innermost strategy
        _b = base
        while not hasattr(_b, "tick_size") and hasattr(_b, "base"):
            _b = _b.base
        self._tick_size: float = getattr(_b, "tick_size", 0.01)
        self._day_start_pnl: float = 0.0
        self._current_day: int = -1
        self.limit_hit: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        import datetime
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        total_pnl = kwargs.get("total_pnl", None)
        if total_pnl is None:
            return decision

        day = datetime.datetime.utcfromtimestamp(timestamp).toordinal()
        if day != self._current_day:
            self._current_day = day
            self._day_start_pnl = total_pnl
            self.limit_hit = False

        daily_pnl = total_pnl - self._day_start_pnl
        if daily_pnl < -self.daily_limit:
            self.limit_hit = True

        if self.limit_hit:
            if self.liquidate_ticks is not None and abs(inventory) > 1e-9:
                tick = self._tick_size
                mid = stats.mid_price if stats.mid_price > 0 else (
                    (decision.bid_price + decision.ask_price) / 2
                    if (decision.bid_price and decision.ask_price) else 0.0
                )
                size = abs(inventory)
                if inventory > 0:
                    # Long: sell aggressively — quote ask below mid to get filled
                    decision.should_quote_bid = False
                    decision.should_quote_ask = True
                    decision.ask_price = mid - self.liquidate_ticks * tick
                    decision.ask_size = size
                else:
                    # Short: buy aggressively — quote bid above mid to get filled
                    decision.should_quote_bid = True
                    decision.should_quote_ask = False
                    decision.bid_price = mid + self.liquidate_ticks * tick
                    decision.bid_size = size
            else:
                decision.should_quote_bid = False
                decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class HourFilter:
    """
    Suppresses quoting during specified UTC hours.

    Calibrated by computing per-hour PnL from a training period and blocking
    the hours with negative expected P&L. The filter is transparent to the
    underlying strategy — all other mechanics (spread, inventory skew, etc.)
    are unchanged.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    bad_hours : iterable of int
        UTC hours [0-23] during which quoting is suppressed.
    """

    def __init__(self, base, bad_hours=()):
        self.base = base
        self.bad_hours: frozenset = frozenset(bad_hours)
        self.max_inventory = getattr(base, "max_inventory", 1.0)

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        import datetime
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        hour = datetime.datetime.utcfromtimestamp(timestamp).hour
        if hour in self.bad_hours:
            decision.should_quote_bid = False
            decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class VPINFilter:
    """
    Pauses quoting when VPIN (Volume-Synchronized Probability of Informed Trading)
    exceeds a threshold, indicating elevated toxic flow.

    VPIN is computed in MarketState.on_trade() using actual taker_side and equal
    volume buckets. It ranges [0, 1]: near 0 = balanced flow, near 1 = one-sided
    (informed) flow. Typical toxic threshold in literature: 0.3–0.6.

    Parameters
    ----------
    base : any strategy with compute_quotes()
    vpin_threshold : float
        VPIN above which quoting is suppressed. Default 0.4.
    min_buckets : int
        Minimum completed buckets before VPIN signal is trusted.
        Below this count the estimator outputs 0.5 (neutral sentinel).
    """

    def __init__(
        self,
        base,
        vpin_threshold: float = 0.4,
        min_buckets: int = 10,
    ):
        self.base = base
        self.vpin_threshold = vpin_threshold
        self.min_buckets = min_buckets
        self.max_inventory = getattr(base, "max_inventory", 1.0)
        self.in_toxic_regime: bool = False

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        # stats.vpin == 0.5 is the uninitialised sentinel — don't suppress yet
        vpin = stats.vpin
        self.in_toxic_regime = vpin != 0.5 and vpin > self.vpin_threshold

        if self.in_toxic_regime:
            decision.should_quote_bid = False
            decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True


class OBIDirectedFilter:
    """
    Counter-OBI maker strategy (Albers et al. 2025, "The Market Maker's Dilemma").

    Posts maker orders on the side OPPOSITE to the current quote-size imbalance.
    The key distinction from OFIDirectedFilter:
      - OFI is trade-flow based (rolling window, lagged)
      - OBI = (bid_size - ask_size)/(bid_size + ask_size) is a top-of-book
        snapshot (instantaneous, leading signal for next tick direction)

    Strategy logic:
      OBI > +threshold  (large bid queue, buy pressure):
          quote ASK only — fills only during reversals when bid pressure fades
      OBI < -threshold  (large ask queue, sell pressure):
          quote BID only — fills only during reversals when ask pressure fades
      |OBI| < threshold (balanced):
          suppress both — no directional edge, risk of symmetric adverse selection

    The reversal-only fill selection produces near-zero adverse selection per
    Albers et al. 2025 Table 1 (−0.058 bps mean markout vs −0.775 bps natural).

    Parameters
    ----------
    base : any strategy with compute_quotes()
    obi_threshold : float
        OBI magnitude above which counter-quoting activates. [0, 1].
        Typical search range: [0.1, 0.7].
    mom_threshold : float
        Full suppression if |momentum| exceeds this. inf = disabled.
    """

    def __init__(
        self,
        base,
        obi_threshold: float = 0.3,
        mom_threshold: float = float("inf"),
    ):
        self.base = base
        self.obi_threshold = obi_threshold
        self.mom_threshold = mom_threshold
        self.max_inventory = getattr(base, "max_inventory", 1.0)

    def compute_quotes(self, stats, inventory: float, timestamp: float, **kwargs):
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        obi = stats.obi
        mom = stats.momentum

        if abs(mom) > self.mom_threshold:
            decision.should_quote_bid = False
            decision.should_quote_ask = False
            return decision

        if obi > self.obi_threshold:
            # Buy pressure: counter-trade by quoting ASK only (reversal fills)
            decision.should_quote_bid = False
            decision.should_quote_ask = True
        elif obi < -self.obi_threshold:
            # Sell pressure: counter-trade by quoting BID only (reversal fills)
            decision.should_quote_bid = True
            decision.should_quote_ask = False
        else:
            # No clear imbalance: suppress both (no edge per paper)
            decision.should_quote_bid = False
            decision.should_quote_ask = False

        return decision

    def should_quote(self, inventory: float):
        if hasattr(self.base, "should_quote"):
            return self.base.should_quote(inventory)
        return True, True
