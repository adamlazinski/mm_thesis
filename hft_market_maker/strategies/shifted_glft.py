"""
Shifted Exponential Fill Model & Modified GLFT
-----------------------------------------------
Extends the standard GLFT market making framework by replacing the
pure exponential fill intensity model with a two-component model:

    lambda(delta) = A_liq * exp(-kappa * delta) + A_mom

Where:
    A_liq  = liquidity-driven arrival rate (uninformed traders crossing spread)
    kappa  = price sensitivity of liquidity flow (decay rate)
    A_mom  = momentum-driven arrival rate (informed traders, invariant to spread)

The momentum floor A_mom represents irreducible adverse selection —
fills that arrive regardless of how wide you quote.

Modified GLFT Ergodic Solution
--------------------------------
With the shifted exponential intensity, the HJB equation becomes:

    max_delta { (A_liq * exp(-kappa*delta) + A_mom) * (delta - dw) }

Taking FOC with respect to delta and solving:

    A_liq * exp(-kappa*delta) * (1 - kappa*(delta - dw)) = A_mom * 0
    => only the liquidity component responds to spread choice
    => optimal delta satisfies:
       A_liq * exp(-kappa*delta*) * (1 - kappa*(delta* - dw)) = 0

    Which gives the same adverse selection term as standard GLFT:
       delta*_adv = (1/kappa) * ln(1 + kappa/gamma)

    But the inventory term gains a momentum correction because the
    value function curvature changes:

       alpha = gamma * sigma^2 / (2 * (A_liq + A_mom) * kappa)

    Note: A_liq + A_mom replaces A in the standard formula.
    The momentum floor increases the effective arrival rate, which
    tightens the inventory skew (you rebalance faster because more fills arrive).

    The total optimal half-spread:
       delta* = (1/kappa) * ln(1 + kappa/gamma)
              + (1/2) * sqrt(sigma^2 * gamma / (2*(A_liq+A_mom)*kappa)
                             * (1 + kappa/gamma)^(1+kappa/gamma))

    Reservation price (inventory skew):
       r = S - q * gamma * sigma^2 / (2 * (A_liq + A_mom) * kappa)

Key difference from standard GLFT:
    - A is replaced by (A_liq + A_mom) throughout
    - Wider quotes do NOT reduce momentum fills
    - A_mom / (A_liq + A_mom) = fraction of fills that are inevitably adverse
    - Market maker cannot escape momentum adverse selection by widening
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from dataclasses import dataclass
from typing import Optional

from hft_market_maker.core.market_state import MicrostructureStats
from hft_market_maker.strategies.glft import GLFTMarketMaker, QuoteDecision


# ============================================================
# Shifted exponential fit
# ============================================================

def shifted_exponential(delta, A_liq, kappa, A_floor):
    """Two-component fill intensity model."""
    return A_liq * np.exp(-kappa * delta) + A_floor


def fit_shifted_exponential(fp_df, min_delta=0.5):
    """
    Fit A_liq * exp(-kappa * delta) + A_floor to fill probability curve.

    Returns (A_liq, kappa, A_floor, se_A_liq, se_kappa, se_A_floor, r2)
    or all None on failure.

    Notes
    -----
    A_floor is bounded [0, min(fill_prob)] to prevent overfitting.
    Initial guess: A_floor = fill prob at largest delta (flat tail level).
    """
    df = fp_df[fp_df['delta'] >= min_delta].copy()
    if len(df) < 4:
        return None, None, None, None, None, None, None

    y = df['fill_prob'].values
    x = df['delta'].values

    # Informed initial guesses from data
    A_floor_guess = float(y[-3:].mean())       # tail level
    A_liq_guess   = float(y[0] - A_floor_guess)
    kappa_guess   = 2.0

    try:
        popt, pcov = curve_fit(
            shifted_exponential, x, y,
            p0=[A_liq_guess, kappa_guess, A_floor_guess],
            bounds=([0, 0.01, 0], [5, 200, float(y.min()) + 0.05]),
            maxfev=20000,
        )
        A_liq, kappa, A_floor = popt
        se = np.sqrt(np.diag(pcov))

        y_hat  = shifted_exponential(x, A_liq, kappa, A_floor)
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

        return A_liq, kappa, A_floor, se[0], se[1], se[2], r2
    except Exception:
        return None, None, None, None, None, None, None


def compare_fits(fp_df, min_delta=0.5):
    """
    Fit both pure exponential and shifted exponential.
    Return comparison dict with parameters, R2, and AIC for model selection.
    """
    from hft_market_maker.core.kappa_estimator import KappaEstimator
    from scipy.optimize import curve_fit

    df = fp_df[fp_df['delta'] >= min_delta].copy()
    x  = df['delta'].values
    y  = df['fill_prob'].values
    n  = len(y)

    results = {}

    # Pure exponential (2 params)
    try:
        popt_exp, _ = curve_fit(
            lambda d, A, k: A * np.exp(-k * d), x, y,
            p0=[y[0], 0.5], bounds=([0, 1e-4], [5, 200]), maxfev=10000
        )
        y_hat_exp = popt_exp[0] * np.exp(-popt_exp[1] * x)
        ss_res_exp = np.sum((y - y_hat_exp) ** 2)
        ss_tot     = np.sum((y - y.mean()) ** 2)
        r2_exp     = 1 - ss_res_exp / ss_tot if ss_tot > 1e-12 else 0.0
        # AIC = n*ln(RSS/n) + 2k
        aic_exp = n * np.log(ss_res_exp / n + 1e-12) + 2 * 2
        results['exponential'] = {
            'A': popt_exp[0], 'kappa': popt_exp[1],
            'A_floor': 0.0, 'r2': r2_exp, 'aic': aic_exp, 'n_params': 2
        }
    except Exception:
        results['exponential'] = None

    # Shifted exponential (3 params)
    A_liq, kappa, A_floor, *se, r2_shift = fit_shifted_exponential(fp_df, min_delta)
    if A_liq is not None:
        y_hat_sh = shifted_exponential(x, A_liq, kappa, A_floor)
        ss_res_sh = np.sum((y - y_hat_sh) ** 2)
        aic_shift = n * np.log(ss_res_sh / n + 1e-12) + 2 * 3
        results['shifted'] = {
            'A_liq': A_liq, 'kappa': kappa, 'A_floor': A_floor,
            'A_total': A_liq + A_floor,
            'mom_fraction': A_floor / (A_liq + A_floor),
            'r2': r2_shift, 'aic': aic_shift, 'n_params': 3
        }
    else:
        results['shifted'] = None

    # Model selection
    if results['exponential'] and results['shifted']:
        delta_aic = results['exponential']['aic'] - results['shifted']['aic']
        results['preferred'] = 'shifted' if delta_aic > 2 else 'exponential'
        results['delta_aic'] = delta_aic
    else:
        results['preferred'] = 'exponential'
        results['delta_aic'] = 0.0

    return results


# ============================================================
# Modified GLFT strategy using shifted exponential
# ============================================================

class ShiftedGLFTMarketMaker(GLFTMarketMaker):
    """
    GLFT market maker with two-component fill intensity:
        lambda(delta) = A_liq * exp(-kappa * delta) + A_mom

    The key modification: A_total = A_liq + A_mom replaces A in all formulas.
    The momentum floor A_mom:
      - Does NOT affect spread width (widening doesn't reduce momentum fills)
      - DOES affect inventory skew (more total arrivals = faster rebalancing)
      - Creates irreducible adverse selection = A_mom / A_total fraction of fills

    Parameters
    ----------
    A_liq : float
        Liquidity-driven baseline arrival rate.
    A_mom : float
        Momentum-driven arrival rate (floor). Fills regardless of spread.
    kappa : float
        Price sensitivity of liquidity flow only.
    All other params inherited from GLFTMarketMaker.
    """

    def __init__(self, A_liq: float = 0.5, A_mom: float = 0.1, **kwargs):
        # Pass A_liq as A to parent — we override the formulas below
        super().__init__(A=A_liq, **kwargs)
        self.A_liq = A_liq
        self.A_mom = A_mom

    @property
    def A_total(self) -> float:
        return self.A_liq + self.A_mom

    @property
    def mom_fraction(self) -> float:
        """Fraction of fills that are inevitably adverse (momentum-driven)."""
        return self.A_mom / self.A_total if self.A_total > 0 else 0.0

    def reservation_price(self, mid, inventory, sigma, A=None):
        """
        Modified reservation price using A_total.
        Momentum fills accelerate inventory rebalancing.
        """
        sigma_dollar = sigma * mid
        denom = 2.0 * self.A_total * self.kappa
        if denom < 1e-10:
            return mid
        skew = inventory * self.gamma * (sigma_dollar ** 2) / denom
        return mid - skew

    def optimal_half_spread(self, sigma, mid, A=None):
        """
        Modified spread using A_total in inventory term.
        Adverse selection term unchanged — only liquidity flow responds to spread.
        """
        gamma = self.gamma
        kappa = self.kappa
        sigma_dollar = sigma * mid

        # Adverse selection — same as standard GLFT, only liquidity component
        if gamma < 1e-10:
            adverse = 1.0 / kappa if kappa > 1e-10 else 0.0
        else:
            adverse = (1.0 / kappa) * np.log(1.0 + kappa / gamma)

        # Inventory risk — uses A_total (faster rebalancing = tighter inventory term)
        if self.A_total < 1e-10 or kappa < 1e-10:
            inv_term = 0.0
        else:
            ratio = kappa / gamma if gamma > 1e-10 else 1e6
            exponent = 1.0 + ratio
            base = 1.0 + ratio
            try:
                power = base ** min(exponent, 500.0)
            except (OverflowError, ValueError):
                power = np.exp(min(exponent * np.log(max(base, 1e-10)), 500.0))
            inner = (sigma_dollar ** 2) * gamma / (2.0 * self.A_total * kappa) * power
            inv_term = 0.5 * np.sqrt(max(inner, 0.0))

        half_spread = adverse + inv_term
        return half_spread, adverse, inv_term

    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kwargs):
        decision = super().compute_quotes(stats, inventory, timestamp, t_remaining, **kwargs)
        # Annotate with momentum fraction for logging
        decision.mom_fraction = self.mom_fraction
        return decision

    def describe(self, stats, inventory):
        mid    = stats.mid_price
        sigma  = stats.sigma
        r      = self.reservation_price(mid, inventory, sigma)
        hs, adv, inv_t = self.optimal_half_spread(sigma, mid)
        min_hs = self.min_spread_bps * mid / 20000.0
        hs_eff = max(hs, min_hs)

        return (
            f"ShiftedGLFT — mid={mid:.2f}  inv={inventory:.4f}\n"
            f"  A_liq={self.A_liq:.4f}  A_mom={self.A_mom:.4f}  "
            f"A_total={self.A_total:.4f}  kappa={self.kappa:.4f}  gamma={self.gamma:.4f}\n"
            f"  mom_fraction={self.mom_fraction:.3f}  "
            f"(={self.mom_fraction*100:.1f}% of fills inevitably adverse)\n"
            f"  reservation={r:.4f}  (skew={mid-r:+.4f})\n"
            f"  half_spread={hs_eff:.4f}  ({hs_eff*2/mid*10000:.4f} bps)\n"
            f"    adverse={adv:.6f}  inv={inv_t:.6f}\n"
            f"  bid={r-hs_eff:.4f}  ask={r+hs_eff:.4f}"
        )
