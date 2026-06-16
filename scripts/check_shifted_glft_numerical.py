"""
check_shifted_glft_numerical.py
=================================
Solve ShiftedGLFTNumerical at the realised sigma_$ distribution of a real
BTC/USDT day and report the resulting ergodic policy (delta_bid*, delta_ask*,
half-spread, reservation skew) -- compared against:

  - GLFTMarketMaker            (pure exponential, A=A_liq)
  - ShiftedGLFTMarketMaker      (A_total = A_liq + a closed-form hack)

at the same (gamma, kappa, sigma), and against the actual market spread
(always ~1 tick on BTC/USDT, per CLAUDE.md).

Run from master2/ root with .venv activated:
    python scripts/check_shifted_glft_numerical.py [DATE]
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from hft_market_maker import (
    ShiftedGLFTNumerical,
    ShiftedGLFTMarketMaker,
    GLFTMarketMaker,
    MicrostructureStats,
)

DATE = sys.argv[1] if len(sys.argv) > 1 else "2025-05-13"

TICK_SIZE = 0.01
GAMMA = 30.0
A_LIQ = 4.87
KAPPA_TICK = 2.39          # per-tick (calibrated)
A_FLOOR = 0.0871           # per-sec (calibrated)
KAPPA_DOLLAR = KAPPA_TICK / TICK_SIZE   # 239.0, for the closed-form models

ORDER_SIZE = 0.001
MAX_INVENTORY = 0.02
EWMA_ALPHA = 0.9           # matches config convention (smoothing factor)


def realised_sigma(date: str) -> tuple[np.ndarray, float]:
    df = pd.read_parquet(
        f"data/real/quotes_BTC_{date}.parquet",
        columns=["time_exchange", "bid_price", "ask_price"],
    )
    mid = (df["bid_price"] + df["ask_price"]).to_numpy() / 2.0
    t = df["time_exchange"].astype("int64").to_numpy() / 1e9  # ns -> sec

    log_ret = np.diff(np.log(mid))
    dt = np.diff(t)
    dt = np.where(dt > 0, dt, 1e-6)
    ret_sq = log_ret ** 2 / dt

    ewma_var = pd.Series(ret_sq).ewm(alpha=1.0 - EWMA_ALPHA, adjust=False).mean().to_numpy()
    sigma = np.sqrt(ewma_var)

    spread = (df["ask_price"] - df["bid_price"]).to_numpy()
    return sigma[200:], mid[1:][200:], spread  # drop EWMA warm-up


def main():
    sigma, mid, spread = realised_sigma(DATE)
    mid_repr = float(np.median(mid))

    print(f"=== {DATE}  (mid_repr=${mid_repr:,.2f}) ===")
    print(f"Market spread: median={np.median(spread):.4f}  mean={np.mean(spread):.4f}  "
          f"(1 tick = {TICK_SIZE})  -> {np.mean(spread == TICK_SIZE) * 100:.1f}% of ticks at exactly 1 tick")
    print()

    pcts = [10, 25, 50, 75, 90, 99]
    sigma_pcts = np.percentile(sigma, pcts)

    m_raw = ShiftedGLFTNumerical(min_spread_bps=0.0)               # pure PDE economics
    m_cfg = ShiftedGLFTNumerical(min_spread_bps=0.5)                # matches 08_shifted_glft floor

    glft = GLFTMarketMaker(
        gamma=GAMMA, kappa=KAPPA_DOLLAR, A=A_LIQ,
        order_size=ORDER_SIZE, max_inventory=MAX_INVENTORY,
        tick_size=TICK_SIZE, min_spread_bps=0.0, kappa_from_stats=False,
    )
    shifted = ShiftedGLFTMarketMaker(
        gamma=GAMMA, kappa=KAPPA_DOLLAR, A_liq=A_LIQ, A_mom=A_FLOOR,
        order_size=ORDER_SIZE, max_inventory=MAX_INVENTORY,
        tick_size=TICK_SIZE, min_spread_bps=0.0, kappa_from_stats=False,
    )

    header = (
        f"{'sigma pct':>9} {'sigma/sec':>10} {'sigma_$':>8} | "
        f"{'PDE hs (ticks)':>15} {'GLFT hs':>9} {'ShiftedGLFT hs':>15} | "
        f"{'PDE quoted spread':>18}"
    )
    print(header)
    print("-" * len(header))

    for pct, sig in zip(pcts, sigma_pcts):
        stats = MicrostructureStats(mid_price=mid_repr, sigma=float(sig), A_hat=A_LIQ)
        sigma_dollar = sig * mid_repr

        d_raw = m_raw.compute_quotes(stats, inventory=0.0, timestamp=0.0)
        d_cfg = m_cfg.compute_quotes(stats, inventory=0.0, timestamp=0.0)
        d_glft = glft.compute_quotes(stats, inventory=0.0, timestamp=0.0)
        d_shift = shifted.compute_quotes(stats, inventory=0.0, timestamp=0.0)

        print(
            f"{pct:>9} {sig:>10.3e} {sigma_dollar:>8.4f} | "
            f"{d_raw.half_spread / TICK_SIZE:>15.4f} "
            f"{d_glft.half_spread / TICK_SIZE:>9.4f} "
            f"{d_shift.half_spread / TICK_SIZE:>15.4f} | "
            f"{(d_cfg.ask_price - d_cfg.bid_price) / TICK_SIZE:>18.2f}"
        )

    # --- Inventory skew at the median sigma ---
    sig_med = float(sigma_pcts[2])
    stats = MicrostructureStats(mid_price=mid_repr, sigma=sig_med, A_hat=A_LIQ)
    q_max_lots = int(MAX_INVENTORY / ORDER_SIZE)

    print(f"\n=== Inventory skew at median sigma ({sig_med:.3e}/sec) ===")
    print(f"{'q (lots)':>9} {'PDE delta_bid':>14} {'PDE delta_ask':>14} {'PDE reservation skew':>22} | "
          f"{'GLFT skew':>10} {'ShiftedGLFT skew':>17}")
    for q_lots in (-q_max_lots, -1, 0, 1, q_max_lots):
        inv = q_lots * ORDER_SIZE
        d_raw = m_raw.compute_quotes(stats, inventory=inv, timestamp=0.0)
        d_glft = glft.compute_quotes(stats, inventory=inv, timestamp=0.0)
        d_shift = shifted.compute_quotes(stats, inventory=inv, timestamp=0.0)

        print(
            f"{q_lots:>9} "
            f"{d_raw.delta_bid / TICK_SIZE:>14.4f} "
            f"{d_raw.delta_ask / TICK_SIZE:>14.4f} "
            f"{(mid_repr - d_raw.reservation) / TICK_SIZE:>22.4f} | "
            f"{(mid_repr - d_glft.reservation) / TICK_SIZE:>10.4f} "
            f"{(mid_repr - d_shift.reservation) / TICK_SIZE:>17.4f}"
        )

    print(f"\nPDE q_max (incl. buffer) = {m_raw.q_max} lots; operative max_inventory = {q_max_lots} lots")


if __name__ == "__main__":
    main()
