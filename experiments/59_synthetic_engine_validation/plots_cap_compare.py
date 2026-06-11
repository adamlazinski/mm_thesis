"""
Inventory cap comparison for the synthetic MM (exp 59).
=======================================================
The FixedSpreadMM has no inventory skew (gamma -> 0); its only inventory control
is the hard cap (stop quoting a side at ±MAX_INV). This script compares the capped
(±50) run against an effectively UNCAPPED one (±1e12) on the same seed/data, to
show what the cap is doing: nothing to P&L in the no-adverse-selection world
(constant), but limiting the short-gamma tail in the volatile worlds.

Run:
    python experiments/59_synthetic_engine_validation/plots_cap_compare.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader

_spec = importlib.util.spec_from_file_location(
    "synval", Path(__file__).resolve().parent / "synthetic_validation.py")
sv = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(sv)

FIGS = Path("experiments/59_synthetic_engine_validation/figs")
TICK = sv.TICK
UNCAP = 1e12
REGIMES = [
    ("constant",         "Constant value — no adverse selection"),
    ("ou",               "Ornstein–Uhlenbeck — mean-reverting"),
    ("brownian",         "Brownian (mild σ=0.01)"),
    ("brownian_highvol", "Brownian (high σ=0.20)"),
]
plt.rcParams.update({"figure.dpi": 130, "savefig.dpi": 150, "font.size": 10,
    "axes.grid": True, "grid.alpha": 0.25, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 11, "axes.titleweight": "bold"})


def run(regime, max_inv, seed=0):
    tp, qp, *_ = sv.generate(regime, seed, fill_model="bbo")
    trades, quotes = DataLoader().load_coinapi(tp, qp)
    om = OrderManager(maker_fee=0.0, latency=0.0, queue_model="none")
    ms = MarketState(120, 60, 0.9)
    bt = Backtest(sv.FixedSpreadMM(sv.MM_HALF_TICKS, TICK, sv.ORDER_SIZE, max_inv),
                  market_state=ms, order_manager=om, requote_on_fill=True,
                  requote_interval=0.1, tolerance_ticks=0.5, tick_size=TICK, verbose=False)
    res = bt.run(trades, quotes)
    q_ts = np.array([q.timestamp for q in quotes])
    q_mid = np.array([(q.best_bid + q.best_ask) / 2.0 for q in quotes])
    return res, q_ts, q_mid


def hrs(idx, t0):
    if isinstance(idx, pd.DatetimeIndex):
        return (idx.astype("int64").to_numpy() / 1e9 - t0) / 3600.0
    return (np.asarray(idx, float) - t0) / 3600.0


def ds(x, y, n=2500):
    if len(x) <= n: return x, y
    s = len(x) // n; return x[::s], y[::s]


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    CAP_C, UNCAP_C = "#1f77b4", "#d62728"
    rows = []
    for regime, title in REGIMES:
        rc, qts, qmid = run(regime, sv.MAX_INV)
        ru, _, _ = run(regime, UNCAP)
        t0 = qts[0]
        pnl_c = float(rc.metrics.get("total_pnl", 0)); pnl_u = float(ru.metrics.get("total_pnl", 0))
        inv_u_max = float(np.max(np.abs(ru.inventory_curve.to_numpy())))
        f_c = int(rc.metrics.get("total_fills", 0)); f_u = int(ru.metrics.get("total_fills", 0))
        rows.append((regime, pnl_c, pnl_u, inv_u_max, f_c, f_u))

        fig, ax = plt.subplots(3, 1, figsize=(11, 8.4), sharex=True,
                               gridspec_kw={"height_ratios": [0.8, 1.1, 1.1], "hspace": 0.13})
        dx, dy = ds(hrs(qts, t0), qmid); ax[0].plot(dx, dy, color="#444", lw=1.0)
        ax[0].set_ylabel("Mid ($)"); ax[0].set_title(f"{title}  —  inventory cap ±50 vs uncapped", loc="left")

        for res, c, lab in [(rc, CAP_C, "capped ±50"), (ru, UNCAP_C, "uncapped")]:
            dx, dy = ds(hrs(res.inventory_curve.index, t0), res.inventory_curve.to_numpy())
            ax[1].plot(dx, dy, color=c, lw=0.9, label=lab)
        ax[1].axhline(0, color="#888", lw=0.8)
        ax[1].axhline(sv.MAX_INV, color=CAP_C, lw=0.8, ls="--", alpha=0.6)
        ax[1].axhline(-sv.MAX_INV, color=CAP_C, lw=0.8, ls="--", alpha=0.6)
        ax[1].set_ylabel("Inventory (units)"); ax[1].legend(loc="upper left", fontsize=9, ncol=2)

        for res, c, lab, pnl in [(rc, CAP_C, "capped ±50", pnl_c), (ru, UNCAP_C, "uncapped", pnl_u)]:
            dx, dy = ds(hrs(res.equity_curve.index, t0), res.equity_curve.to_numpy())
            ax[2].plot(dx, dy, color=c, lw=1.3, label=f"{lab}: ${pnl:,.0f}")
        ax[2].axhline(0, color="#888", lw=0.8)
        ax[2].set_ylabel("Cumulative P&L ($)"); ax[2].set_xlabel("Time (hours)")
        ax[2].legend(loc="best", fontsize=9)
        for a in ax: a.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.2f}"))
        fig.align_ylabels(ax)
        out = FIGS / f"capcompare_{regime}.png"; fig.savefig(out, bbox_inches="tight"); plt.close(fig)
        print(f"  {regime:18s} capped ${pnl_c:>9.2f} ({f_c:,} fills) | uncapped ${pnl_u:>9.2f} "
              f"({f_u:,} fills, |inv|max {inv_u_max:,.0f}) -> {out}")

    print(f"\n{'regime':18s} {'capped P&L':>12} {'uncapped P&L':>13} {'uncap |inv|max':>14}")
    for regime, pc, pu, im, fc, fu in rows:
        print(f"{regime:18s} {pc:>12.2f} {pu:>13.2f} {im:>14,.0f}")


if __name__ == "__main__":
    main()
