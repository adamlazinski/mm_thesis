"""
ForecastAS — A-S market maker with an XGBoost mid-price direction overlay.

At each quoting step the model outputs p_up ∈ [0,1].
The reservation price is shifted by:

    r += alpha * (2 * p_up - 1) * tick_size

so both bid and ask shift together in the predicted direction without
widening or narrowing the spread.  If `gate_threshold > 0`, the adverse
side is additionally suppressed when the signal is very strong:
    signal >  gate_threshold  → suppress ask  (don't sell before an up move)
    signal < -gate_threshold  → suppress bid  (don't buy before a down move)

Features must match ml/train_forecast.py FEATURE_NAMES exactly.
"""

from __future__ import annotations
from collections import deque
from typing import Optional

import numpy as np
import joblib

from .avellaneda_stoikov import AvellanedaStoikov, QuoteDecision
from ..core.market_state import MicrostructureStats

FEATURE_NAMES = [
    "ofi", "momentum", "obi", "sigma_norm", "spike_ratio",
    "lambda_imbalance", "mid_ret_lag1", "spread_norm",
]


class ForecastAS:
    """
    A-S market maker with a short-horizon ML direction signal.

    Parameters
    ----------
    base : AvellanedaStoikov
        The underlying A-S strategy that computes the baseline quotes.
    model_path : str
        Path to a joblib-serialised XGBoost classifier (trained with
        ml/train_forecast.py).
    alpha : float
        Reservation price shift in ticks per unit signal.  A value of 2.0
        means a fully bullish signal (p_up=1) shifts r by +2 ticks.
    gate_threshold : float
        If |signal| > gate_threshold the adverse-side quote is suppressed.
        0.0 = disabled (both sides always quoted).
    """

    def __init__(
        self,
        base: AvellanedaStoikov,
        model_path: str,
        alpha: float = 2.0,
        gate_threshold: float = 0.0,
    ):
        self.base           = base
        self.model          = joblib.load(model_path)
        self.alpha          = alpha
        self.gate_threshold = gate_threshold

        self._sigma_history: deque = deque(maxlen=120)
        self._last_mid: float = 0.0
        self._last_signal: float = 0.0  # diagnostic

    # ------------------------------------------------------------------
    # Interface compatibility shims
    # ------------------------------------------------------------------

    @property
    def tick_size(self) -> float:
        return self.base.tick_size

    @property
    def max_inventory(self) -> float:
        return self.base.max_inventory

    def should_quote(self, inventory: float):
        return self.base.should_quote(inventory)

    # ------------------------------------------------------------------
    # Feature extraction (matches train_forecast.py computation)
    # ------------------------------------------------------------------

    def _extract_features(self, stats: MicrostructureStats) -> np.ndarray:
        self._sigma_history.append(stats.sigma)

        sigma_mean = float(np.mean(self._sigma_history)) if len(self._sigma_history) >= 5 else stats.sigma
        sigma_norm = np.clip(stats.sigma / (sigma_mean + 1e-10) / 4.0, 0.0, 1.0)

        spike_ratio = np.clip(
            stats.trades_per_sec_short / (stats.trades_per_sec + 1e-6) / 5.0, 0.0, 1.0
        )

        lam_sum = stats.lambda_buy + stats.lambda_sell + 1e-6
        lambda_imbalance = (stats.lambda_buy - stats.lambda_sell) / lam_sum

        # Lagged mid return: current mid vs previous mid, normalised by σ√dt
        if self._last_mid > 0 and stats.mid_price > 0:
            log_ret = np.log(stats.mid_price / self._last_mid)
            exp_move = stats.sigma * np.sqrt(0.5) + 1e-9
            mid_ret_lag1 = float(np.clip(log_ret / exp_move / 3.0, -1.0, 1.0))
        else:
            mid_ret_lag1 = 0.0
        self._last_mid = stats.mid_price

        spread_norm = stats.spread / (self.base.tick_size + 1e-9)

        return np.array([
            stats.ofi,
            stats.momentum,
            stats.obi,
            sigma_norm,
            spike_ratio,
            lambda_imbalance,
            mid_ret_lag1,
            spread_norm,
        ], dtype=np.float32)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        **kwargs,
    ) -> QuoteDecision:
        decision = self.base.compute_quotes(stats, inventory, timestamp, **kwargs)

        features = self._extract_features(stats).reshape(1, -1)
        proba = self.model.predict_proba(features)[0]  # [p_down, p_flat, p_up]
        # 3-class model: signal = p_up - p_down ∈ [-1, 1], zero when flat
        signal = float(proba[2] - proba[0]) if len(proba) == 3 else float(2.0 * proba[1] - 1.0)
        self._last_signal = signal

        shift = self.alpha * signal * self.base.tick_size
        decision.bid_price        += shift
        decision.ask_price        += shift
        decision.reservation_price += shift

        # Re-round to tick after shift
        decision.bid_price = self.base._round_price(decision.bid_price, "bid")
        decision.ask_price = self.base._round_price(decision.ask_price, "ask")

        # Ensure valid spread after rounding
        if decision.ask_price <= decision.bid_price:
            decision.ask_price = decision.bid_price + self.base.tick_size

        # Gate adverse side on strong signals
        bid_ok, ask_ok = self.base.should_quote(inventory)
        if self.gate_threshold > 0.0:
            if signal > self.gate_threshold:
                ask_ok = False   # strong up signal → don't sell cheap before the move
            elif signal < -self.gate_threshold:
                bid_ok = False   # strong down signal → don't buy before the drop

        decision.should_quote_bid = bid_ok
        decision.should_quote_ask = ask_ok

        return decision
