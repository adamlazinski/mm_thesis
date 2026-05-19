"""
Experiment 38: OFI-directed and momentum-filter overlays on the A-S winner.

Tests whether selective one-sided quoting based on real-time OFI/momentum
improves the A-S winner (γ≈0, max_inv=38, min_spread=6.44, limit=$25).

Two filter types:
  A. OFIDirectedFilter  — one-sided quoting when |OFI| > threshold
     (quotes only the side aligned with mean-reversion; two-sided when neutral)
  B. MomentumFilter     — full suppression when |momentum| > threshold
     (pauses quoting entirely during strong trends)

Runs on full 30-day period (IS: Jun 11–27, OOS: Jun 28–Jul 10).

Run from master2/: python experiments/38_link_ofi_overlay/ofi_sweep.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import time
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
    OFIDirectedFilter, RegimeFilter,
)

OUT  = Path("experiments/38_link_ofi_overlay/analysis")
DATA = Path("data/real")
SYM  = "LINK"

# A-S winner params — identical to sensitivity sweep baseline
BASE = dict(
    gamma            = 1e-8,
    t_scaling        = 9702.0,
    order_size       = 5.0,
    min_spread_bps   = 6.4381,
    max_inventory    = 38.0,
    daily_loss_limit = 25.011,
    tick_size        = 0.001,
    latency          = 0.1,
    quote_freq       = 0.5,
    vol_window       = 120,
    arrival_window   = 60,
    ewma_alpha       = 0.9,
    tolerance_ticks  = 0.5,
    kappa_force_interval = 60.0,
    short_gap        = 2.0,
    long_gap         = 30.0,
)

IS_START  = date(2025, 6, 11)
IS_END    = date(2025, 6, 27)
OOS_START = date(2025, 6, 28)
OOS_END   = date(2025, 7, 10)

# OFI threshold: 1.0 = effectively disabled (OFI ≤ 1.0 always → always two-sided = baseline)
OFI_THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0]
# Momentum threshold: 1.0 = never triggers (baseline)
MOM_THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]


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


def build_strategy(cfg, filter_type=None, threshold=None):
    base = AvellanedaStoikov(
        gamma          = cfg["gamma"],
        T              = cfg["t_scaling"],
        order_size     = cfg["order_size"],
        min_spread_bps = cfg["min_spread_bps"],
        max_inventory  = cfg["max_inventory"],
        tick_size      = cfg["tick_size"],
    )
    if filter_type == "ofi":
        base = OFIDirectedFilter(base, ofi_threshold=threshold,
                                 mom_threshold=float("inf"))
    elif filter_type == "mom":
        base = RegimeFilter(base, vol_threshold=float("inf"),
                            mom_threshold=threshold, ofi_threshold=float("inf"))
    return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"])


def run_config(loaded_days, cfg, filter_type=None, threshold=None):
    day_pnls, day_fills, day_intra_dds = [], [], []

    for trades, quotes, date_str in loaded_days:
        strategy = build_strategy(cfg, filter_type, threshold)

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

        eq = result.equity_curve.values if len(result.equity_curve) > 0 else np.array([0.0])
        peak = np.maximum.accumulate(eq)
        day_intra_dds.append(float((eq - peak).min()))

    pnls = np.array(day_pnls)
    return dict(
        mean_pnl      = float(pnls.mean()),
        sharpe        = float(pnls.mean() / pnls.std() * np.sqrt(365)) if pnls.std() > 1e-9 else 0.0,
        win_rate      = float((pnls > 0).mean()),
        worst_day     = float(pnls.min()),
        mean_fills    = float(np.mean(day_fills)),
        worst_intra_dd = float(np.min(day_intra_dds)),
        day_pnls      = day_pnls,
    )


def print_row(label, val, res, marker=""):
    print(f"  {label}={val:<6}  pnl={res['mean_pnl']:>+8.2f}/d  "
          f"Sharpe={res['sharpe']:>6.1f}  wins={res['win_rate']:.0%}  "
          f"fills={res['mean_fills']:>6.0f}  "
          f"worst_dd={res['worst_intra_dd']:>+7.2f}{marker}")


def main():
    print("Loading IS + OOS data once...")
    is_days  = find_days(IS_START,  IS_END)
    oos_days = find_days(OOS_START, OOS_END)
    all_days = is_days + oos_days
    loaded_is  = load_all(is_days)
    loaded_oos = load_all(oos_days)
    loaded_all = loaded_is + loaded_oos
    print(f"  IS: {len(loaded_is)} days, OOS: {len(loaded_oos)} days, "
          f"total: {len(loaded_all)} days\n")

    rows = []

    # ── Baseline (no filter) ─────────────────────────────────────────────────
    print("Baseline (no filter):")
    t0 = time.time()
    r_is  = run_config(loaded_is,  BASE)
    r_oos = run_config(loaded_oos, BASE)
    r_all = run_config(loaded_all, BASE)
    print(f"  IS  ({len(loaded_is):2d}d): pnl={r_is['mean_pnl']:>+8.2f}/d  "
          f"Sharpe={r_is['sharpe']:>6.1f}  wins={r_is['win_rate']:.0%}  "
          f"fills={r_is['mean_fills']:>6.0f}  worst_dd={r_is['worst_intra_dd']:>+7.2f}")
    print(f"  OOS ({len(loaded_oos):2d}d): pnl={r_oos['mean_pnl']:>+8.2f}/d  "
          f"Sharpe={r_oos['sharpe']:>6.1f}  wins={r_oos['win_rate']:.0%}  "
          f"fills={r_oos['mean_fills']:>6.0f}  worst_dd={r_oos['worst_intra_dd']:>+7.2f}")
    print(f"  ALL ({len(loaded_all):2d}d): pnl={r_all['mean_pnl']:>+8.2f}/d  "
          f"Sharpe={r_all['sharpe']:>6.1f}  wins={r_all['win_rate']:.0%}  "
          f"fills={r_all['mean_fills']:>6.0f}  worst_dd={r_all['worst_intra_dd']:>+7.2f}"
          f"  ({time.time()-t0:.0f}s)\n")
    for period, r, loaded in [("IS", r_is, loaded_is), ("OOS", r_oos, loaded_oos),
                               ("ALL", r_all, loaded_all)]:
        rows.append({"filter": "baseline", "threshold": None, "period": period,
                     "n_days": len(loaded), **{k: v for k, v in r.items() if k != "day_pnls"}})

    # ── OFI-Directed sweep ───────────────────────────────────────────────────
    print(f"OFI-Directed filter sweep (OFI thresholds, OOS {len(loaded_oos)}d):")
    for thr in OFI_THRESHOLDS:
        t0 = time.time()
        r_is  = run_config(loaded_is,  BASE, "ofi", thr)
        r_oos = run_config(loaded_oos, BASE, "ofi", thr)
        r_all = run_config(loaded_all, BASE, "ofi", thr)
        marker = " ◄ baseline equiv" if thr == 1.0 else ""
        print(f"  ofi_thr={thr:.2f}  "
              f"IS pnl={r_is['mean_pnl']:>+8.2f}  Sharpe={r_is['sharpe']:>6.1f}  wins={r_is['win_rate']:.0%}  fills={r_is['mean_fills']:>6.0f}  |  "
              f"OOS pnl={r_oos['mean_pnl']:>+8.2f}  Sharpe={r_oos['sharpe']:>6.1f}  wins={r_oos['win_rate']:.0%}  fills={r_oos['mean_fills']:>6.0f}"
              f"  ({time.time()-t0:.0f}s){marker}")
        for period, r, loaded in [("IS", r_is, loaded_is), ("OOS", r_oos, loaded_oos),
                                   ("ALL", r_all, loaded_all)]:
            rows.append({"filter": "ofi_directed", "threshold": thr, "period": period,
                         "n_days": len(loaded), **{k: v for k, v in r.items() if k != "day_pnls"}})
    print()

    # ── Momentum-Filter sweep ────────────────────────────────────────────────
    print(f"Momentum suppression sweep (full halt when |mom| > threshold):")
    for thr in MOM_THRESHOLDS:
        t0 = time.time()
        r_is  = run_config(loaded_is,  BASE, "mom", thr)
        r_oos = run_config(loaded_oos, BASE, "mom", thr)
        r_all = run_config(loaded_all, BASE, "mom", thr)
        marker = " ◄ baseline equiv" if thr == 1.0 else ""
        print(f"  mom_thr={thr:.1f}   "
              f"IS pnl={r_is['mean_pnl']:>+8.2f}  Sharpe={r_is['sharpe']:>6.1f}  wins={r_is['win_rate']:.0%}  fills={r_is['mean_fills']:>6.0f}  |  "
              f"OOS pnl={r_oos['mean_pnl']:>+8.2f}  Sharpe={r_oos['sharpe']:>6.1f}  wins={r_oos['win_rate']:.0%}  fills={r_oos['mean_fills']:>6.0f}"
              f"  ({time.time()-t0:.0f}s){marker}")
        for period, r, loaded in [("IS", r_is, loaded_is), ("OOS", r_oos, loaded_oos),
                                   ("ALL", r_all, loaded_all)]:
            rows.append({"filter": "mom_suppress", "threshold": thr, "period": period,
                         "n_days": len(loaded), **{k: v for k, v in r.items() if k != "day_pnls"}})
    print()

    # ── Save CSV ─────────────────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    csv_path = OUT / "ofi_sweep_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"Results saved to {csv_path}\n")

    # ── Plots ─────────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 4, figsize=(20, 9))
    fig.suptitle(
        "Experiment 38: OFI-Directed & Momentum-Filter Overlays — A-S Winner\n"
        "LINK/USDT Jun 11–Jul 10 2025 (17 IS + 13 OOS days)",
        fontsize=12, fontweight="bold"
    )

    metrics = [
        ("mean_pnl",       "Mean PnL / day ($)"),
        ("sharpe",         "Sharpe (daily √365)"),
        ("win_rate",       "Win rate"),
        ("mean_fills",     "Mean fills / day"),
    ]

    # Compute IS-optimal thresholds for annotation
    is_opt = {}
    for filter_name in ["ofi_directed", "mom_suppress"]:
        sub_is = df[(df["filter"] == filter_name) & (df["period"] == "IS")]
        is_opt[filter_name] = sub_is.loc[sub_is["sharpe"].idxmax(), "threshold"]

    for row_i, (filter_name, label, thresholds, color) in enumerate([
        ("ofi_directed", "OFI-Directed (ofi_threshold)", OFI_THRESHOLDS, "#1565C0"),
        ("mom_suppress",  "Momentum Suppress (mom_threshold)", MOM_THRESHOLDS, "#E65100"),
    ]):
        for col_i, (metric, ylabel) in enumerate(metrics):
            ax = axes[row_i, col_i]

            for period, ls, alpha in [("IS", "--", 0.7), ("OOS", "-", 1.0)]:
                sub = df[(df["filter"] == filter_name) & (df["period"] == period)].sort_values("threshold")
                base_val = df[(df["filter"] == "baseline") & (df["period"] == period)][metric].values[0]

                xs = sub["threshold"].values
                ys = sub[metric].values
                ax.plot(xs, ys, linestyle=ls, color=color, lw=2, marker="o", ms=5,
                        label=period, alpha=alpha)
                ax.axhline(base_val, color="gray", ls=":", lw=1.2, alpha=0.7,
                           label="baseline" if period == "OOS" else None)

            # Mark IS-optimal threshold
            ax.axvline(is_opt[filter_name], color="#B71C1C", ls="--", lw=1.5,
                       alpha=0.8, label=f"IS-opt={is_opt[filter_name]}")

            if row_i == 0:
                ax.set_title(ylabel, fontsize=9, fontweight="bold")
            if col_i == 0:
                ax.set_ylabel(label, fontsize=8)
            ax.grid(alpha=0.25)
            ax.tick_params(labelsize=8)
            if col_i == 0:
                ax.legend(fontsize=7, loc="best")

    plt.tight_layout()
    fig_path = OUT / "fig8_ofi_overlay.png"
    fig.savefig(fig_path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"Saved {fig_path}")

    # ── Summary: IS-optimal → OOS evaluation ────────────────────────────────
    base_is  = df[(df["filter"] == "baseline") & (df["period"] == "IS")].iloc[0]
    base_oos = df[(df["filter"] == "baseline") & (df["period"] == "OOS")].iloc[0]

    print("\n" + "="*70)
    print("IS-OPTIMAL THRESHOLD → OOS EVALUATION")
    print("="*70)

    for filter_name, label in [("ofi_directed", "OFI-Directed"), ("mom_suppress", "Momentum Suppress")]:
        # Find IS-optimal threshold (by IS Sharpe)
        sub_is  = df[(df["filter"] == filter_name) & (df["period"] == "IS")]
        sub_oos = df[(df["filter"] == filter_name) & (df["period"] == "OOS")]
        best_is_idx = sub_is["sharpe"].idxmax()
        best_is_thr = sub_is.loc[best_is_idx, "threshold"]
        best_is_row = sub_is.loc[best_is_idx]

        # OOS performance at IS-optimal threshold
        oos_row = sub_oos[sub_oos["threshold"] == best_is_thr].iloc[0]
        # Best possible OOS threshold (for reference — would be data-snooping)
        best_oos_row = sub_oos.loc[sub_oos["sharpe"].idxmax()]

        print(f"\n  {label}:")
        print(f"    IS-optimal threshold   = {best_is_thr}")
        print(f"    IS performance         pnl={best_is_row['mean_pnl']:>+8.2f}/d  "
              f"Sharpe={best_is_row['sharpe']:.1f}  wins={best_is_row['win_rate']:.0%}  "
              f"fills={best_is_row['mean_fills']:.0f}")
        print(f"    IS baseline            pnl={base_is['mean_pnl']:>+8.2f}/d  "
              f"Sharpe={base_is['sharpe']:.1f}  wins={base_is['win_rate']:.0%}  "
              f"fills={base_is['mean_fills']:.0f}")
        print(f"    IS Δ Sharpe:  {best_is_row['sharpe'] - base_is['sharpe']:>+.1f}")
        print(f"    ── applied OOS ──")
        print(f"    OOS at IS-opt thr      pnl={oos_row['mean_pnl']:>+8.2f}/d  "
              f"Sharpe={oos_row['sharpe']:.1f}  wins={oos_row['win_rate']:.0%}  "
              f"fills={oos_row['mean_fills']:.0f}")
        print(f"    OOS baseline           pnl={base_oos['mean_pnl']:>+8.2f}/d  "
              f"Sharpe={base_oos['sharpe']:.1f}  wins={base_oos['win_rate']:.0%}  "
              f"fills={base_oos['mean_fills']:.0f}")
        print(f"    OOS Δ Sharpe: {oos_row['sharpe'] - base_oos['sharpe']:>+.1f}  "
              f"OOS Δ PnL: {oos_row['mean_pnl'] - base_oos['mean_pnl']:>+.2f}/d")
        print(f"    (Best possible OOS thr = {best_oos_row['threshold']}  "
              f"Sharpe={best_oos_row['sharpe']:.1f}  ← snooping ref only)")
    print()


if __name__ == "__main__":
    main()
