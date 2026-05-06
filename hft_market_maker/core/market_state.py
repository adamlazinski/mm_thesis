"""
MarketState: maintains a rolling view of microstructure statistics needed
by the A-S model and its extensions.

Statistics tracked
------------------
  kappa_as      : AS fill-sensitivity — primary kappa, in lambda=A*exp(-kappa_as*delta)
  A_hat         : AS baseline fill intensity (fills/sec per side at delta=0)
  kappa_as_se   : standard error of kappa_as estimate
  trades_per_sec: background market order arrival rate (secondary, for regime info)
  lambda_buy / lambda_sell : directional arrival rates
  ofi           : order flow imbalance [-1, 1]
  sigma         : realised volatility (per second)
  mid_price     : latest mid
  momentum      : normalised momentum [-1, 1]
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional
import numpy as np

from .kappa_estimator import KappaEstimator


@dataclass
class MicrostructureStats:
    mid_price:     float = 0.0
    sigma:         float = 0.0
    kappa_as:      float = 1.5    # AS fill-sensitivity (1/$)  ← primary kappa
    A_hat:         float = 2.0    # AS baseline fill intensity
    kappa_as_se:   float = float('inf')
    trades_per_sec: float = 1.0   # background arrival rate (secondary)
    lambda_buy:    float = 0.5
    lambda_sell:   float = 0.5
    ofi:           float = 0.0
    spread:        float = 0.0
    momentum:      float = 0.0
    momentum_raw:  float = 0.0


class MarketState:
    """
    Event-driven market state estimator.

    Parameters
    ----------
    vol_window : int
        Number of mid-price ticks for volatility estimation.
    arrival_window : float
        Seconds of history for trades_per_sec estimation.
    ewma_alpha : float | None
        EWMA decay for volatility. None = simple rolling std.
    kappa_as_prior : float
        Offline-calibrated AS fill-sensitivity. Regularisation centre.
    A_prior : float
        Offline-calibrated baseline fill intensity.
    kappa_as_window : float
        Rolling window (seconds) for kappa_as MLE.
    kappa_as_min_fills : int
        Minimum fills before updating kappa_as from prior.
    """

    def __init__(
        self,
        vol_window: int = 100,
        arrival_window: float = 60.0,
        ewma_alpha: Optional[float] = 0.94,
        momentum_window: float = 5.0,
        momentum_clip: float = 3.0,
        kappa_as_prior: float = 1.5,
        A_prior: float = 2.0,
        kappa_as_window: float = 300.0,
        kappa_as_min_fills: int = 50,
        kappa_as_lam_base: float = 0.5,
        kappa_as_update_every: int = 10,
    ):
        self.vol_window     = vol_window
        self.arrival_window = arrival_window
        self.ewma_alpha     = ewma_alpha

        self._mid_prices: Deque[float] = deque(maxlen=vol_window)
        self._mid_times:  Deque[float] = deque(maxlen=vol_window)

        self._trade_times: Deque[float] = deque()
        self._buy_times:   Deque[float] = deque()
        self._sell_times:  Deque[float] = deque()

        self._ewma_var: float = 0.0
        self._ewma_initialised: bool = False

        self._best_bid: float = 0.0
        self._best_ask: float = 0.0

        self._ofi_buys: float = 0.0
        self._ofi_sells: float = 0.0
        self._ofi_window_trades: Deque[tuple] = deque()

        self.momentum_window = momentum_window
        self.momentum_clip   = momentum_clip

        self._kappa_estimator = KappaEstimator(
            kappa_prior=kappa_as_prior,
            A_prior=A_prior,
            window_seconds=kappa_as_window,
            min_fills=kappa_as_min_fills,
            lam_base=kappa_as_lam_base,
            update_every=kappa_as_update_every,
        )

        self.stats = MicrostructureStats(
            kappa_as=kappa_as_prior,
            A_hat=A_prior,
        )

    # ------------------------------------------------------------------
    # Public event interface
    # ------------------------------------------------------------------

    def on_quote(self, timestamp: float, best_bid: float, best_ask: float,
                 bid_size: float, ask_size: float,
                 mm_half_spread: Optional[float] = None) -> None:
        """
        Call on every BBO tick.

        mm_half_spread : your current quoted half-spread ($).
                         Pass this when you are actively quoting so the
                         estimator records the quote opportunity.
                         Pass None when you are flat / not quoting.
        """
        mid = (best_bid + best_ask) / 2.0
        self._best_bid = best_bid
        self._best_ask = best_ask

        self._update_volatility(timestamp, mid)

        self.stats.mid_price    = mid
        self.stats.spread       = best_ask - best_bid
        self.stats.sigma        = self._get_sigma()
        self.stats.momentum_raw, self.stats.momentum = self._get_momentum(timestamp, mid)

        if mm_half_spread is not None and mm_half_spread > 0:
            self._kappa_estimator.on_quote_posted(timestamp, mm_half_spread)

    def on_trade(self, timestamp: float, price: float, quantity: float,
                 side: str) -> None:
        """
        Background market order (taker hits BBO). Updates trades_per_sec and OFI.
        Does NOT update kappa_as — use on_mm_fill for that.
        """
        self._trade_times.append(timestamp)
        if side == "buy":
            self._buy_times.append(timestamp)
            self._ofi_buys += quantity
        else:
            self._sell_times.append(timestamp)
            self._ofi_sells += quantity

        self._ofi_window_trades.append((timestamp, side, quantity))

        cutoff = timestamp - self.arrival_window
        while self._trade_times and self._trade_times[0] < cutoff:
            self._trade_times.popleft()
        while self._buy_times and self._buy_times[0] < cutoff:
            self._buy_times.popleft()
        while self._sell_times and self._sell_times[0] < cutoff:
            self._sell_times.popleft()
        while self._ofi_window_trades and self._ofi_window_trades[0][0] < cutoff:
            _, old_side, old_qty = self._ofi_window_trades.popleft()
            if old_side == "buy":
                self._ofi_buys -= old_qty
            else:
                self._ofi_sells -= old_qty

        self.stats.trades_per_sec = self._get_trades_per_sec()
        self.stats.lambda_buy     = self._get_lambda("buy")
        self.stats.lambda_sell    = self._get_lambda("sell")
        self.stats.ofi            = self._get_ofi()

    def on_mm_fill(self, timestamp: float, half_spread: float) -> None:
        """
        Call when one of YOUR limit orders gets filled.
        half_spread = the delta ($) at which your order was resting.
        This is the primary input for kappa_as estimation.
        """
        self._kappa_estimator.on_fill(timestamp, half_spread)
        self._sync_kappa_as()

    def notify_quote_posted(self, timestamp: float, half_spread: float) -> None:
        """
        Call each time a new quote is actually submitted (not on hysteresis skips).
        half_spread is the dollar half-spread of the posted quote.
        """
        if half_spread > 0:
            self._kappa_estimator.on_quote_posted(timestamp, half_spread)

    def force_kappa_update(self, timestamp: float) -> None:
        """
        Force a kappa_as MLE update. Call on a timer (~60s) so estimates
        don't go stale during quiet periods with few fills.
        """
        self._kappa_estimator.force_update(timestamp)
        self._sync_kappa_as()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_kappa_as(self) -> None:
        self.stats.kappa_as    = self._kappa_estimator.kappa_as
        self.stats.A_hat       = self._kappa_estimator.A_hat
        self.stats.kappa_as_se = self._kappa_estimator.se

    def _update_volatility(self, timestamp: float, mid: float) -> None:
        if self._mid_prices:
            prev_mid  = self._mid_prices[-1]
            prev_time = self._mid_times[-1]
            dt = timestamp - prev_time
            if dt > 0 and prev_mid > 0:
                log_ret = np.log(mid / prev_mid)
                ret_sq  = (log_ret ** 2) / max(dt, 1e-6)
                if self.ewma_alpha is not None:
                    if not self._ewma_initialised:
                        self._ewma_var = ret_sq
                        self._ewma_initialised = True
                    else:
                        a = self.ewma_alpha
                        self._ewma_var = a * self._ewma_var + (1 - a) * ret_sq

        self._mid_prices.append(mid)
        self._mid_times.append(timestamp)

    def _get_sigma(self) -> float:
        if len(self._mid_prices) < 2:
            return 1e-4
        if self.ewma_alpha is not None and self._ewma_initialised:
            return float(np.sqrt(self._ewma_var))
        prices   = np.array(self._mid_prices)
        times    = np.array(self._mid_times)
        log_rets = np.diff(np.log(prices))
        dt       = np.where(np.diff(times) > 0, np.diff(times), 1e-6)
        return float(np.sqrt(max(np.mean(log_rets ** 2 / dt), 0)))

    def _get_trades_per_sec(self) -> float:
        n = len(self._trade_times)
        return n / self.arrival_window if n >= 2 else 1.0

    def _get_lambda(self, side: str) -> float:
        times = self._buy_times if side == "buy" else self._sell_times
        return len(times) / self.arrival_window

    def _get_ofi(self) -> float:
        total = self._ofi_buys + self._ofi_sells
        return (self._ofi_buys - self._ofi_sells) / total if total > 0 else 0.0

    def _get_momentum(self, timestamp: float, mid: float) -> tuple[float, float]:
        if len(self._mid_times) < 2:
            return 0.0, 0.0
        cutoff  = timestamp - self.momentum_window
        ref_mid = next((p for t, p in zip(self._mid_times, self._mid_prices)
                        if t >= cutoff), None)
        if ref_mid is None or ref_mid <= 0:
            return 0.0, 0.0
        momentum_raw  = np.log(mid / ref_mid)
        sigma         = self.stats.sigma
        expected_move = sigma * np.sqrt(self.momentum_window) if sigma > 0 else 1e-8
        momentum_norm = float(np.clip(
            momentum_raw / expected_move / self.momentum_clip, -1.0, 1.0
        ))
        return float(momentum_raw), momentum_norm

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return len(self._mid_prices) >= 10 and len(self._trade_times) >= 5

    @property
    def kappa_as_ready(self) -> bool:
        """True once kappa_as has been calibrated from real fill data."""
        return self._kappa_estimator.is_calibrated

    def kappa_as_summary(self) -> dict:
        return self._kappa_estimator.summary()