"""
Aggressiveness Modelling Extension
------------------------------------

Extends A-S by making the risk aversion parameter `gamma` dynamic.
In the base A-S model, gamma is fixed — but in practice, a market maker
should be more aggressive (lower gamma → tighter spreads) when:
  - Volatility is low and predictable
  - Order flow is balanced (OFI ≈ 0)
  - We are close to flat inventory
  - Regime is ranging / mean-reverting

And more conservative (higher gamma → wider spreads) when:
  - Volatility is spiking
  - Order flow is strongly directional (informed flow)
  - Inventory is building
  - Trend is strong

This module implements several aggressiveness models:

1. RuleBasedAggressiveness  — hand-crafted signal combination
2. VolatilityScaledAS       — gamma scales with realised vol
3. OFIAdjustedAS            — asymmetric quotes based on order flow imbalance
4. InventoryUrgency         — accelerating inventory mean-reversion
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from typing import Optional

from ..core.market_state import MicrostructureStats
from .avellaneda_stoikov import AvellanedaStoikov, QuoteDecision


# ===========================================================================
# 1. Rule-Based Aggressiveness
# ===========================================================================

class RuleBasedAggressiveness(AvellanedaStoikov):
    """
    Dynamically adjusts gamma using a multi-signal scoring system.

    Each signal contributes to an aggressiveness score in [-1, 1]:
      +1 = be very aggressive (tight spreads)
      -1 = be very conservative (wide spreads)

    Final gamma = gamma_base * exp(-score * sensitivity)
    """

    def __init__(
        self,
        gamma_base: float = 0.1,
        gamma_min: float = 0.01,
        gamma_max: float = 1.0,
        sensitivity: float = 1.5,
        vol_lookback: int = 20,
        **kwargs,
    ):
        super().__init__(gamma=gamma_base, **kwargs)
        self.gamma_base = gamma_base
        self.gamma_min = gamma_min
        self.gamma_max = gamma_max
        self.sensitivity = sensitivity

        # Rolling vol history for relative vol signal
        self._vol_history: list[float] = []
        self.vol_lookback = vol_lookback

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        # Compute dynamic gamma
        score = self._aggressiveness_score(stats, inventory)
        dynamic_gamma = self.gamma_base * np.exp(-score * self.sensitivity)
        dynamic_gamma = np.clip(dynamic_gamma, self.gamma_min, self.gamma_max)

        # Temporarily override gamma
        old_gamma = self.gamma
        self.gamma = dynamic_gamma

        decision = super().compute_quotes(stats, inventory, timestamp, t_remaining)
        decision.gamma = dynamic_gamma  # record actual gamma used

        self.gamma = old_gamma

        # Track vol for next iteration
        self._vol_history.append(stats.sigma)
        if len(self._vol_history) > self.vol_lookback:
            self._vol_history.pop(0)

        return decision

    def _aggressiveness_score(self, stats: MicrostructureStats,
                               inventory: float) -> float:
        """
        Compute composite aggressiveness score in [-1, 1].
        Positive = be more aggressive (tighter spreads).
        """
        scores = []

        # Signal 1: Relative volatility
        # If current vol is below recent average → market is calm → be aggressive
        if len(self._vol_history) >= 5:
            avg_vol = np.mean(self._vol_history)
            if avg_vol > 0:
                rel_vol = stats.sigma / avg_vol
                # rel_vol < 1 → calm → positive score
                vol_score = np.clip(1.0 - rel_vol, -1.0, 1.0)
                scores.append(("vol", vol_score, 0.4))

        # Signal 2: Order flow imbalance
        # Balanced flow (OFI ≈ 0) → be aggressive; directional flow → be cautious
        ofi_score = 1.0 - 2.0 * abs(stats.ofi)  # 1 when balanced, -1 when extreme
        scores.append(("ofi", ofi_score, 0.3))

        # Signal 3: Inventory level
        # Flat inventory → be aggressive; large inventory → be conservative
        inv_ratio = abs(inventory) / max(self.max_inventory, 1e-6)
        inv_score = np.clip(1.0 - 2.0 * inv_ratio, -1.0, 1.0)
        scores.append(("inventory", inv_score, 0.3))

        # Weighted average
        total_weight = sum(w for _, _, w in scores)
        composite = sum(s * w for _, s, w in scores) / total_weight

        return float(np.clip(composite, -1.0, 1.0))


# ===========================================================================
# 2. Volatility-Scaled A-S
# ===========================================================================

class VolatilityScaledAS(AvellanedaStoikov):
    """
    Scales the effective gamma with a vol-of-vol measure.
    When volatility itself is volatile (uncertain regime), be more conservative.
    """

    def __init__(self, gamma_base: float = 0.1, vol_vol_window: int = 50, **kwargs):
        super().__init__(gamma=gamma_base, **kwargs)
        self.gamma_base = gamma_base
        self._vol_history: list[float] = []
        self.vol_vol_window = vol_vol_window

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        self._vol_history.append(stats.sigma)
        if len(self._vol_history) > self.vol_vol_window:
            self._vol_history.pop(0)

        if len(self._vol_history) >= 10:
            vol_of_vol = np.std(self._vol_history) / max(np.mean(self._vol_history), 1e-8)
            # Scale gamma proportionally to vol-of-vol uncertainty
            scale = 1.0 + 2.0 * vol_of_vol
        else:
            scale = 1.0

        self.gamma = self.gamma_base * scale
        return super().compute_quotes(stats, inventory, timestamp, t_remaining)


# ===========================================================================
# 3. OFI-Adjusted Asymmetric Quoting
# ===========================================================================

class OFIAsymmetricAS(AvellanedaStoikov):
    """
    Uses order flow imbalance to asymmetrically skew quotes.

    When buy pressure is high (OFI > 0):
      - Raise both bid and ask (lean to sell into the flow)
      - Widen the ask side (don't give away stock cheaply)

    When sell pressure is high (OFI < 0):
      - Lower both bid and ask
      - Widen the bid side

    This is an adverse selection defence: if order flow is informed,
    we protect ourselves by being less aggressive on the informed side.
    """

    def __init__(self, ofi_sensitivity: float = 0.5, **kwargs):
        super().__init__(**kwargs)
        self.ofi_sensitivity = ofi_sensitivity

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        t_remaining: Optional[float] = None,
        **kwargs,
    ) -> QuoteDecision:
        decision = super().compute_quotes(stats, inventory, timestamp, t_remaining)

        ofi = stats.ofi  # in [-1, 1]
        mid = stats.mid_price
        momentum = stats.momentum
         # Combine OFI and momentum into a single directional signal
    # Both point the same direction → strong signal
    # They disagree → weaker signal
        signal = 0.5 * ofi + 0.5 * momentum  # [-1, 1]

    # Shift both quotes in direction of signal
        skew = signal * self.ofi_sensitivity * mid * 1e-4  # in price units

    # Widen the side facing the signal (informed side)
        half_spread = decision.optimal_spread / 2.0
        extra = abs(signal) * half_spread * 0.5

        if signal > 0:
        # Buy pressure + upward momentum → lean ask up, protect from selling cheap
            decision.ask_price = decision.ask_price + skew + extra
            decision.bid_price = decision.bid_price + skew
        else:
        # Sell pressure + downward momentum → lean bid down, protect from buying expensive
            decision.bid_price = decision.bid_price + skew - extra
            decision.ask_price = decision.ask_price + skew

        decision.bid_price = self._round_price(decision.bid_price, "bid")
        decision.ask_price = self._round_price(decision.ask_price, "ask")

        return decision


# ===========================================================================
# 4. Inventory Urgency (accelerating mean reversion)
# ===========================================================================

class InventoryUrgencyAS(AvellanedaStoikov):
    """
    Standard A-S with an additional urgency layer:
    as inventory approaches the limit, we exponentially increase
    the inventory penalty to force faster mean reversion.

    This prevents the inventory from ever hitting the hard limit
    where we stop quoting entirely.
    """

    def __init__(self, urgency_factor: float = 3.0, **kwargs):
        super().__init__(**kwargs)
        self.urgency_factor = urgency_factor

    def reservation_price(self, mid: float, inventory: float,
                          sigma: float, t_remaining: float) -> float:
        # Normalised inventory [0, 1]
        inv_ratio = abs(inventory) / max(self.max_inventory, 1e-6)

        # Exponentially increase penalty as inventory grows
        urgency_multiplier = np.exp(self.urgency_factor * inv_ratio ** 2)
        effective_gamma = self.gamma * urgency_multiplier

        return mid - inventory * effective_gamma * (sigma ** 2) * t_remaining


# ===========================================================================
# 5. Combined strategy — everything together
# ===========================================================================

class FullAggressivenessAS(OFIAsymmetricAS, RuleBasedAggressiveness, InventoryUrgencyAS):
    """
    Combined strategy using Python MRO to stack all extensions.
    Order: OFI adjustment → Rule-based gamma → Inventory urgency → Base A-S

    This is the recommended production strategy before adding RL.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
