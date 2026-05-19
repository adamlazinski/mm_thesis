"""
Sensitivity analysis for the winning A-S strategy.

Holds all winner params fixed and varies one parameter at a time.
Loads OOS data once, then reuses it across all configs.

Run from master2/: python experiments/37_link_glft_control/sensitivity_sweep.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import date, timedelta

from hft_market_maker.data.loader import DataLoader
from hft_market_maker import (
    AvellanedaStoikov, Backtest, MarketState, OrderManager, DailyLossLimit,
)

OUT  = Path("experiments/37_link_glft_control/analysis")
DATA = Path("data/real")
SYM  = "LINK"

# ── Winner (baseline) params ────────────────────────────────────────────────
BASE = dict(
    gamma          = 1e-8,
    t_scaling      = 9702.0,
    order_size     = 5.0,
    min_spread_bps = 6.4381,
    max_inventory  = 38.0,
    daily_loss_limit = 25.011,
    tick_size      = 0.001,
    latency        = 0.1,
    quote_freq     = 0.5,
    vol_window     = 120,
    arrival_window = 60,
    ewma_alpha     = 0.9,
    tolerance_ticks = 0.5,
    kappa_force_interval = 60.0,
    short_gap      = 2.0,
    long_gap       = 30.0,
)

# ── Sweep grids (one dimension at a time) ───────────────────────────────────
SWEEPS = {
    "max_inventory":    [5, 10, 20, 30, 38, 50, 75, 100, 150, 200, 300],
    "min_spread_bps":   [3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.44, 7.0, 7.5, 8.5, 10.0],
    "daily_loss_limit": [5, 10, 15, 25, 40, 60, 100, 250, 9999],
}

# ── OOS date range ───────────────────────────────────────────────────────────
OOS_START = date(2025, 6, 28)
OOS_END   = date(2025, 7, 10)


# ── Helpers ──────────────────────────────────────────────────────────────────

def find_days(start, end):
    days, d = [], start
    while d <= end:
        t = DATA / f"trades_{SYM}_{d}.parquet"
        q = DATA / f"quotes_{SYM}_{d}.parquet"
        if t.exists() and q.exists():
            days.append((str(t), str(q), str(d)))
        d += timedelta(days=1)
    return days


def load_all(days):
    loader = DataLoader()
    loaded = []
    for tp, qp, ds in days:
        t, q = loader.load_coinapi(trades_path=tp, quotes_path=qp,
                                   timestamp_col="time_exchange")
        loaded.append((t, q, ds))
    return loaded


def run_config(loaded_days, cfg):
    """Run backtest for one parameter config, return per-day and aggregate metrics."""
    day_pnls, day_fills, day_spreads, day_markouts, day_advs = [], [], [], [], []
    day_intra_dds = []

    for trades, quotes, date_str in loaded_days:
        mid_est = (quotes[0].best_bid + quotes[0].best_ask) / 2
        tick    = cfg["tick_size"]

        base = AvellanedaStoikov(
            gamma        = cfg["gamma"],
            T            = cfg["t_scaling"],
            order_size   = cfg["order_size"],
            min_spread_bps = cfg["min_spread_bps"],
            max_inventory  = cfg["max_inventory"],
            tick_size    = tick,
        )
        strategy = DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"])

        ms = MarketState(
            vol_window     = int(cfg["vol_window"]),
            arrival_window = int(cfg["arrival_window"]),
            ewma_alpha     = cfg["ewma_alpha"],
        )
        om = OrderManager(maker_fee=0.0, latency=cfg["latency"])

        bt = Backtest(
            strategy             = strategy,
            market_state         = ms,
            order_manager        = om,
            requote_on_fill      = True,
            requote_interval     = cfg["quote_freq"],
            short_gap_threshold  = cfg["short_gap"],
            long_gap_threshold   = cfg["long_gap"],
            tolerance_ticks      = cfg["tolerance_ticks"],
            kappa_force_interval = cfg["kappa_force_interval"],
            tick_size            = cfg["tick_size"],
            verbose              = False,
        )
        result = bt.run(trades, quotes)
        m = result.metrics

        day_pnls.append(m.get("total_pnl", 0))
        day_fills.append(m.get("total_fills", 0))
        day_spreads.append(m.get("avg_spread_bps", 0))
        day_markouts.append(m.get("avg_markout_bps", 0))
        day_advs.append(m.get("pct_adverse_fills", 0))

        # Intraday drawdown from equity_curve
        eq = result.equity_curve.values if len(result.equity_curve) > 0 else np.array([0.0])
        peak = np.maximum.accumulate(eq)
        day_intra_dds.append(float((eq - peak).min()))

    pnls = np.array(day_pnls)
    return dict(
        mean_pnl       = float(pnls.mean()),
        total_pnl      = float(pnls.sum()),
        sharpe         = float(pnls.mean() / pnls.std() * np.sqrt(365)) if pnls.std() > 1e-9 else 0.0,
        win_rate       = float((pnls > 0).mean()),
        worst_day      = float(pnls.min()),
        mean_fills     = float(np.mean(day_fills)),
        avg_spread_bps = float(np.mean(day_spreads)),
        avg_markout    = float(np.mean(day_markouts)),
        avg_adv        = float(np.mean(day_advs)),
        worst_intra_dd = float(np.min(day_intra_dds)),
        mean_intra_dd  = float(np.mean(day_intra_dds)),
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading OOS data once...")
    days   = find_days(OOS_START, OOS_END)
    loaded = load_all(days)
    print(f"  {len(loaded)} days loaded.\n")

    all_results = []

    for param_name, values in SWEEPS.items():
        print(f"Sweeping {param_name}:  {values}")
        for val in values:
            cfg = {**BASE, param_name: val}
            t0  = time.time()
            res = run_config(loaded, cfg)
            elapsed = time.time() - t0
            row = {"sweep_param": param_name, "value": val, **res}
            all_results.append(row)
            marker = " ◄ winner" if abs(val - BASE.get(param_name, 0)) < 1e-6 else ""
            print(f"  {param_name}={val:<8}  pnl={res['mean_pnl']:>+8.2f}/d  "
                  f"Sharpe={res['sharpe']:>6.1f}  wins={res['win_rate']:.0%}  "
                  f"fills={res['mean_fills']:>6.0f}  "
                  f"intra_dd={res['worst_intra_dd']:>+7.2f}  ({elapsed:.1f}s){marker}")
        print()

    df = pd.DataFrame(all_results)
    csv_path = OUT / "sensitivity_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"Results saved to {csv_path}\n")

    # ── Plots ────────────────────────────────────────────────────────────────
    metrics_to_plot = [
        ("mean_pnl",       "Mean PnL / day ($)",     True),
        ("sharpe",         "Sharpe ratio (daily √365)", True),
        ("worst_day",      "Worst single day ($)",   False),
        ("worst_intra_dd", "Worst intraday M-t-M DD ($)", False),
        ("mean_fills",     "Mean fills / day",       True),
        ("avg_markout",    "Avg markout (bps)",      True),
    ]

    fig, axes = plt.subplots(len(SWEEPS), len(metrics_to_plot),
                             figsize=(22, 4 * len(SWEEPS)))
    fig.suptitle("Sensitivity Analysis — A-S Winner (γ≈0)   OOS Jun 28–Jul 10",
                 fontsize=14, fontweight="bold")

    param_labels = {
        "max_inventory":    "max_inventory (LINK)",
        "order_size":       "order_size (LINK)",
        "min_spread_bps":   "min_spread_bps",
        "daily_loss_limit": "daily_loss_limit ($)  [9999 = none]",
    }

    for row_i, param_name in enumerate(SWEEPS):
        sub = df[df["sweep_param"] == param_name].sort_values("value")
        winner_val = BASE.get(param_name)

        for col_i, (metric, ylabel, higher_better) in enumerate(metrics_to_plot):
            ax = axes[row_i, col_i]
            xs = sub["value"].values
            ys = sub[metric].values

            ax.plot(xs, ys, "o-", color="#1565C0", lw=2, ms=6)
            # Mark winner
            ax.axvline(winner_val, color="#E65100", ls="--", lw=1.5,
                       alpha=0.7, label=f"winner={winner_val}")
            ax.scatter([winner_val],
                       [sub.loc[sub["value"].sub(winner_val).abs().idxmin(), metric]],
                       color="#E65100", zorder=5, s=80)
            if row_i == 0:
                ax.set_title(ylabel, fontsize=9, fontweight="bold")
            if col_i == 0:
                ax.set_ylabel(param_labels[param_name], fontsize=8)
            ax.grid(alpha=0.25)
            ax.tick_params(labelsize=8)
            # Shade "better" region vs winner
            if row_i == 0 and col_i == 0:
                ax.legend(fontsize=7)

    plt.tight_layout()
    fig_path = OUT / "fig7_sensitivity.png"
    fig.savefig(fig_path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"Saved {fig_path}")

    # ── Quick summary table ──────────────────────────────────────────────────
    print("\n=== Best value for each parameter (by mean_pnl) ===")
    for param_name in SWEEPS:
        sub  = df[df["sweep_param"] == param_name]
        best = sub.loc[sub["mean_pnl"].idxmax()]
        base_pnl = sub.loc[sub["value"].sub(BASE[param_name]).abs().idxmin(), "mean_pnl"]
        delta = best["mean_pnl"] - base_pnl
        print(f"  {param_name:<22} best={best['value']:<8}  "
              f"pnl={best['mean_pnl']:>+8.2f}/d  "
              f"vs winner {base_pnl:>+8.2f}/d  (Δ={delta:>+7.2f})")


if __name__ == "__main__":
    main()
