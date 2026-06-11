"""
Readable plots for the synthetic market-making validation (exp 59).
===================================================================
For each regime, runs the FixedSpreadMM through the real engine and renders a
3-panel figure sharing the time axis:
    (1) underlying mid price
    (2) inventory (with ±cap guides)
    (3) cumulative P&L
Plus a 2×2 cumulative-P&L overview across regimes.

Run:
    python experiments/59_synthetic_engine_validation/plots.py
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader

_spec = importlib.util.spec_from_file_location(
    "synval", Path(__file__).resolve().parent / "synthetic_validation.py")
sv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sv)

FIGS = Path("experiments/59_synthetic_engine_validation/figs")
TICK, MAX_INV = sv.TICK, sv.MAX_INV

REGIMES = [
    ("constant",         "Constant value  —  no adverse selection",        "#1f77b4"),
    ("ou",               "Ornstein–Uhlenbeck  —  mean-reverting",          "#2ca02c"),
    ("brownian",         "Brownian (mild σ=0.01)  —  spread > vol cost",   "#9467bd"),
    ("brownian_highvol", "Brownian (high σ=0.20)  —  short-gamma blowup",  "#d62728"),
]

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 150, "font.size": 10,
    "axes.grid": True, "grid.alpha": 0.25, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 11, "axes.titleweight": "bold",
})


def run(regime, seed=0):
    tp, qp, *_ = sv.generate(regime, seed, fill_model="bbo")
    trades, quotes = DataLoader().load_coinapi(tp, qp)
    om = OrderManager(maker_fee=0.0, latency=0.0, queue_model="none")
    ms = MarketState(vol_window=120, arrival_window=60, ewma_alpha=0.9)
    bt = Backtest(sv.FixedSpreadMM(sv.MM_HALF_TICKS, TICK, sv.ORDER_SIZE, MAX_INV),
                  market_state=ms, order_manager=om, requote_on_fill=True,
                  requote_interval=0.1, tolerance_ticks=0.5, tick_size=TICK, verbose=False)
    res = bt.run(trades, quotes)
    q_ts = np.array([q.timestamp for q in quotes])
    q_mid = np.array([(q.best_bid + q.best_ask) / 2.0 for q in quotes])
    return res, q_ts, q_mid


def _hours(idx, t0):
    """Convert a datetime index (or float seconds) to elapsed hours from t0."""
    if isinstance(idx, pd.DatetimeIndex):
        return (idx.astype("int64").to_numpy() / 1e9 - t0) / 3600.0
    return (np.asarray(idx, float) - t0) / 3600.0


def _downsample(x, y, n=2500):
    if len(x) <= n:
        return x, y
    step = len(x) // n
    return x[::step], y[::step]


def regime_figure(regime, title, color, res, q_ts, q_mid):
    t0 = q_ts[0]
    xh = (q_ts - t0) / 3600.0
    eq = res.equity_curve; inv = res.inventory_curve
    et = _hours(eq.index, t0); iv_t = _hours(inv.index, t0)
    m = res.metrics
    final_pnl = float(m.get("total_pnl", eq.iloc[-1] if len(eq) else 0))
    fills = int(m.get("total_fills", 0))

    fig, ax = plt.subplots(3, 1, figsize=(11, 8.2), sharex=True,
                           gridspec_kw={"height_ratios": [1, 1, 1.1], "hspace": 0.12})

    # 1) underlying mid
    dx, dy = _downsample(xh, q_mid)
    ax[0].plot(dx, dy, color="#444", lw=1.0)
    ax[0].set_ylabel("Mid price ($)")
    ax[0].set_title(title, loc="left")

    # 2) inventory
    dx, dy = _downsample(iv_t, inv.to_numpy())
    ax[1].plot(dx, dy, color=color, lw=0.9)
    ax[1].fill_between(dx, 0, dy, color=color, alpha=0.15)
    ax[1].axhline(0, color="#888", lw=0.8)
    ax[1].axhline(MAX_INV, color="#bbb", lw=0.8, ls="--")
    ax[1].axhline(-MAX_INV, color="#bbb", lw=0.8, ls="--")
    ax[1].set_ylabel("Inventory (units)")

    # 3) cumulative PnL
    dx, dy = _downsample(et, eq.to_numpy())
    pos = final_pnl >= 0
    pcol = "#2ca02c" if pos else "#d62728"
    ax[2].plot(dx, dy, color=pcol, lw=1.3)
    ax[2].fill_between(dx, 0, dy, color=pcol, alpha=0.15)
    ax[2].axhline(0, color="#888", lw=0.8)
    ax[2].set_ylabel("Cumulative P&L ($)")
    ax[2].set_xlabel("Time (hours)")
    ax[2].annotate(f"final P&L  ${final_pnl:,.2f}\n{fills:,} fills",
                   xy=(0.985, 0.06 if pos else 0.92), xycoords="axes fraction",
                   ha="right", va="bottom" if pos else "top", fontsize=10, fontweight="bold",
                   color=pcol, bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=pcol, alpha=0.9))
    for a in ax:
        a.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.2f}"))

    fig.align_ylabels(ax)
    out = FIGS / f"synthetic_{regime}.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out, final_pnl, fills


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    runs = {}
    paths = []
    for regime, title, color in REGIMES:
        res, q_ts, q_mid = run(regime)
        runs[regime] = (res, q_ts, q_mid, title, color)
        p, pnl, fills = regime_figure(regime, title, color, res, q_ts, q_mid)
        paths.append(p)
        print(f"  {regime:18s} final P&L ${pnl:>9.2f}  ({fills:,} fills)  -> {p}")

    # Overview: cumulative P&L, 2x2
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    for axx, (regime, title, color) in zip(axes.ravel(), REGIMES):
        res, q_ts, _, _, _ = runs[regime]
        t0 = q_ts[0]; eq = res.equity_curve
        et = _hours(eq.index, t0)
        dx, dy = _downsample(et, eq.to_numpy())
        pcol = "#2ca02c" if float(res.metrics.get("total_pnl", 0)) >= 0 else "#d62728"
        axx.plot(dx, dy, color=pcol, lw=1.3)
        axx.fill_between(dx, 0, dy, color=pcol, alpha=0.15)
        axx.axhline(0, color="#888", lw=0.8)
        axx.set_title(title, loc="left", fontsize=10)
        axx.set_ylabel("Cum. P&L ($)"); axx.set_xlabel("Time (hours)")
        axx.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    fig.suptitle("Synthetic market making — cumulative P&L by regime (fixed 2-tick MM)",
                 fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    ov = FIGS / "synthetic_overview_pnl.png"
    fig.savefig(ov, bbox_inches="tight"); plt.close(fig)
    paths.append(ov)
    print(f"  overview -> {ov}")
    return paths


if __name__ == "__main__":
    main()
