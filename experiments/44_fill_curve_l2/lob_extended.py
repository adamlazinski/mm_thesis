"""
LOB Shape — Extended Analysis
==============================
Supplements lob_shape.py with three additional analyses:

1. OBI autocorrelation  (fig13)
   Measures how long OBI persists at each lag.  Explains why the IC heatmap
   peaks at 30s instead of 0.5s: sustained imbalance, not momentary signal.

2. Trade size vs L1 queue depth  (fig14)
   Plots the trade size CDF against the L1 queue depth CDF.
   This is the quantitative explanation for the step-function fill curve:
   most individual trades are smaller than the queue, so they cannot clear
   the queue ahead of an at-touch passive order.

3. L1 queue depth distribution  (fig15)
   Distribution (PDF + CDF) of the instantaneous L1 bid and ask depth.
   Shows how thin the touch can get and how that drives the variance in
   fill probability.

Run from master2/:
    python experiments/44_fill_curve_l2/lob_extended.py
"""

from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

DATA_DIR  = Path("data/real")
OUT_DIR   = Path("experiments/44_fill_curve_l2/analysis")
SYMBOL    = "LINK"
TICK      = 0.001
SAMPLE_S  = 5.0       # OBI sampled every 5s (same as lob_shape.py)
MAX_LAG_S = 300.0     # ACF up to 5 minutes
ACF_LAGS  = [0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180, 300]  # seconds


# ─────────────────────────────────────────────────────────────
# Loading helpers
# ─────────────────────────────────────────────────────────────

def load_ob(date_str: str):
    path = DATA_DIR / f"orderbooks_{SYMBOL}_{date_str}.parquet"
    if not path.exists():
        return None
    ob = pq.read_table(path).to_pandas()
    ob["ts"] = ob["time_exchange"].astype("int64") / 1e9

    def _depth(col, n):
        return ob[col].apply(lambda x: sum(l["size"] for l in list(x)[:n]))

    b1 = _depth("bids", 1);  a1 = _depth("asks", 1)
    ob["obi_l1"]        = (b1 - a1) / (b1 + a1 + 1e-9)
    ob["bid_depth_l1"]  = b1
    ob["ask_depth_l1"]  = a1
    return ob.sort_values("ts").reset_index(drop=True)


def load_trades(date_str: str):
    path = DATA_DIR / f"trades_{SYMBOL}_{date_str}.parquet"
    if not path.exists():
        return None
    tr = pq.read_table(path).to_pandas()
    tr["ts"] = tr["time_exchange"].astype("int64") / 1e9
    return tr.sort_values("ts").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Analysis 1: OBI autocorrelation
# ─────────────────────────────────────────────────────────────

def compute_obi_acf(ob: pd.DataFrame, lags_s=ACF_LAGS, sample_s=SAMPLE_S):
    """
    Compute Spearman autocorrelation of OBI L1 at various time lags.
    Returns dict {lag_s: acf_value}.
    """
    ts  = ob["ts"].values
    obi = ob["obi_l1"].values

    # Sample OBI uniformly every sample_s seconds
    t_start = ts[0]
    t_end   = ts[-1]
    t_grid  = np.arange(t_start, t_end, sample_s)

    obi_series = []
    for t in t_grid:
        idx = np.searchsorted(ts, t, side="right") - 1
        if 0 <= idx < len(obi):
            obi_series.append(float(obi[idx]))
        else:
            obi_series.append(np.nan)

    obi_arr = np.array(obi_series)

    acf = {}
    for lag_s in lags_s:
        lag_steps = int(round(lag_s / sample_s))
        if lag_steps <= 0 or lag_steps >= len(obi_arr) - 10:
            acf[lag_s] = np.nan
            continue
        x = obi_arr[:-lag_steps]
        y = obi_arr[lag_steps:]
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 30:
            acf[lag_s] = np.nan
            continue
        acf[lag_s] = spearmanr(x[mask], y[mask]).statistic

    return acf


# ─────────────────────────────────────────────────────────────
# Analysis 2: Trade size vs L1 queue depth
# ─────────────────────────────────────────────────────────────

def compute_trade_vs_queue(ob: pd.DataFrame, tr: pd.DataFrame):
    """
    For each trade, find the contemporaneous L1 bid/ask queue depth.
    Returns (trade_sizes, queue_depths) arrays.
    """
    ts_ob  = ob["ts"].values
    ts_tr  = tr["ts"].values
    sizes  = tr["size"].values
    sides  = tr["taker_side"].values

    queue_at_trade = []
    trade_sizes    = []

    for i in range(len(tr)):
        snap = np.searchsorted(ts_ob, ts_tr[i], side="right") - 1
        if snap < 0:
            continue
        side = sides[i]
        # Taker SELL hits the bid side; Taker BUY hits the ask side
        if side == "SELL":
            q = float(ob["bid_depth_l1"].iloc[snap])
        else:
            q = float(ob["ask_depth_l1"].iloc[snap])
        queue_at_trade.append(q)
        trade_sizes.append(float(sizes[i]))

    return np.array(trade_sizes), np.array(queue_at_trade)


# ─────────────────────────────────────────────────────────────
# Plotting
# ─────────────────────────────────────────────────────────────

def plot_obi_acf(all_acf: list[dict], ic_at_horizon: dict, out: Path):
    """
    Two-panel figure:
      Left:  OBI ACF vs lag (mean ± std across days)
      Right: ACF vs IC at matching horizons (shows the link between persistence and predictability)
    """
    lag_grid = ACF_LAGS
    acf_mat  = np.array([[d.get(l, np.nan) for l in lag_grid] for d in all_acf])
    acf_mean = np.nanmean(acf_mat, axis=0)
    acf_std  = np.nanstd(acf_mat, axis=0)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("OBI L1 Autocorrelation — LINK/USDT April 2026 (30 days)",
                 fontsize=13, fontweight="bold")

    # Left: ACF decay curve
    ax = axes[0]
    ax.semilogx(lag_grid, acf_mean, "o-", color="#1565C0", lw=2.5, ms=7,
                label="Mean ACF (Spearman)")
    ax.fill_between(lag_grid,
                    acf_mean - acf_std, acf_mean + acf_std,
                    color="#1565C0", alpha=0.18, label="±1σ across days")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("Lag (seconds, log scale)")
    ax.set_ylabel("Spearman autocorrelation")
    ax.set_title("OBI Persistence: How Long Does Imbalance Last?")
    ax.set_xticks(lag_grid)
    ax.set_xticklabels([f"{l:.0f}s" for l in lag_grid], fontsize=7, rotation=30)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)

    # Right: ACF vs IC at matching horizons
    ax2 = axes[1]
    # Only plot lags that have a matching IC horizon
    shared = sorted(set(lag_grid) & set(ic_at_horizon.keys()))
    acf_shared = [acf_mean[lag_grid.index(l)] for l in shared]
    ic_shared  = [ic_at_horizon[l]             for l in shared]
    ax2.scatter(acf_shared, ic_shared, s=80, color="#E65100", zorder=5)
    for acf_v, ic_v, lag in zip(acf_shared, ic_shared, shared):
        ax2.annotate(f"{lag:.0f}s",
                     (acf_v, ic_v),
                     textcoords="offset points", xytext=(6, 3), fontsize=8)
    # Correlation line
    mask = [not (np.isnan(a) or np.isnan(b)) for a, b in zip(acf_shared, ic_shared)]
    if sum(mask) >= 3:
        xs = np.array(acf_shared)[mask]
        ys = np.array(ic_shared)[mask]
        m, b = np.polyfit(xs, ys, 1)
        xr = np.linspace(min(xs), max(xs), 50)
        ax2.plot(xr, m * xr + b, color="#B71C1C", lw=1.5, ls="--",
                 label=f"OLS (slope={m:.2f})")
    ax2.set_xlabel("OBI autocorrelation at lag t")
    ax2.set_ylabel("IC of OBI vs return at horizon t")
    ax2.set_title("ACF vs IC: Does Persistence Explain Predictability?")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.25)

    plt.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out.name}")
    return acf_mean, acf_std


def plot_trade_vs_queue(trade_sizes: np.ndarray, queue_depths: np.ndarray,
                        out: Path):
    """
    Three panels:
      Left:   CDF of trade size vs CDF of L1 queue depth
      Middle: P(trade size > queue) — the direct fill probability proxy
      Right:  Trade size / queue depth ratio distribution
    """
    # Clip extreme outliers for display
    ts_clip  = np.clip(trade_sizes,  0, np.percentile(trade_sizes,  99))
    qd_clip  = np.clip(queue_depths, 0, np.percentile(queue_depths, 99))

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(
        "Trade Size vs L1 Queue Depth — Root Cause of Step-Function Fill Curve\n"
        "LINK/USDT April 2026 (30 days)",
        fontsize=12, fontweight="bold")

    # ── Left: CDFs ────────────────────────────────────────────
    ax = axes[0]
    x_max = max(np.percentile(ts_clip, 99), np.percentile(qd_clip, 99))
    x_grid = np.linspace(0, x_max, 1000)
    cdf_trade = np.array([np.mean(trade_sizes <= x) for x in x_grid])
    cdf_queue = np.array([np.mean(queue_depths <= x) for x in x_grid])

    ax.plot(x_grid, cdf_trade, color="#E65100", lw=2.5, label="Trade size (LINK)")
    ax.plot(x_grid, cdf_queue, color="#1565C0", lw=2.5, label="L1 queue depth (LINK)")
    ax.axhline(0.5,  color="k", lw=0.7, ls=":")
    ax.axhline(0.9,  color="k", lw=0.7, ls=":")

    # Annotate medians
    med_t = np.median(trade_sizes)
    med_q = np.median(queue_depths)
    ax.axvline(med_t, color="#E65100", lw=1, ls="--", alpha=0.7)
    ax.axvline(med_q, color="#1565C0", lw=1, ls="--", alpha=0.7)
    ax.text(med_t, 0.05, f"Median\ntrade\n{med_t:.0f} LINK",
            color="#E65100", fontsize=8, ha="left", va="bottom")
    ax.text(med_q, 0.15, f"Median\nqueue\n{med_q:.0f} LINK",
            color="#1565C0", fontsize=8, ha="right", va="bottom")

    ax.set_xlabel("Size (LINK)")
    ax.set_ylabel("CDF")
    ax.set_title("CDF of Trade Size vs L1 Queue Depth\n"
                 "[Queue is much larger than typical trade]")
    ax.legend(fontsize=9)
    ax.set_xlim(0, x_max)
    ax.grid(alpha=0.25)

    # ── Middle: P(single trade clears queue) ─────────────────
    ax2 = axes[1]
    # For each trade, does it exceed the queue?
    clears = (trade_sizes >= queue_depths).astype(float)
    pct_clears = clears.mean() * 100

    bins = np.logspace(np.log10(max(trade_sizes.min(), 0.01)),
                       np.log10(trade_sizes.max()), 40)
    bin_centres = 0.5 * (bins[:-1] + bins[1:])
    clears_by_size = []
    counts_by_size = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (trade_sizes >= lo) & (trade_sizes < hi)
        if mask.sum() > 0:
            clears_by_size.append(clears[mask].mean() * 100)
            counts_by_size.append(mask.sum())
        else:
            clears_by_size.append(np.nan)
            counts_by_size.append(0)

    valid = ~np.isnan(clears_by_size)
    ax2.plot(bin_centres[valid], np.array(clears_by_size)[valid],
             "-o", color="#2E7D32", lw=2, ms=4)
    ax2.axhline(pct_clears, color="#B71C1C", lw=1.5, ls="--",
                label=f"Overall: {pct_clears:.1f}% of trades clear queue")
    ax2.set_xscale("log")
    ax2.set_xlabel("Trade size (LINK, log scale)")
    ax2.set_ylabel("% trades that clear the L1 queue")
    ax2.set_title(f"P(trade clears queue) by trade size\n"
                  f"[Overall: {pct_clears:.1f}% of trades — rest fill only inside-spread]")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.25)

    # ── Right: ratio distribution ─────────────────────────────
    ax3 = axes[2]
    ratio = trade_sizes / (queue_depths + 1e-9)
    pct_gt1 = (ratio >= 1.0).mean() * 100

    log_ratio = np.log10(np.clip(ratio, 1e-4, 1e4))
    ax3.hist(log_ratio, bins=60, color="#9C27B0", alpha=0.75, edgecolor="white")
    ax3.axvline(0, color="#B71C1C", lw=2, ls="--",
                label=f"Ratio=1 (trade = queue)\n{pct_gt1:.1f}% of trades ≥ queue")
    ax3.set_xlabel("log₁₀(trade size / L1 queue depth)")
    ax3.set_ylabel("Count")
    ax3.set_title("Distribution of Trade/Queue Ratio\n"
                  "[Left of 0 = trade smaller than queue]")
    ax3.legend(fontsize=9)
    ax3.grid(alpha=0.25)

    plt.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out.name}")
    return pct_clears, med_t, med_q


def plot_l1_depth_distribution(bid_depths: np.ndarray, ask_depths: np.ndarray,
                                out: Path):
    """
    Two panels:
      Left:  PDF of L1 bid and ask depth (log-x scale)
      Right: CDF + percentile table
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("L1 Queue Depth Distribution — LINK/USDT April 2026",
                 fontsize=13, fontweight="bold")

    bins = np.logspace(np.log10(max(bid_depths.min(), 0.1)),
                       np.log10(bid_depths.max()), 60)

    ax = axes[0]
    ax.hist(bid_depths, bins=bins, alpha=0.6, color="#1565C0", label="Bid L1",
            density=True, edgecolor="white")
    ax.hist(ask_depths, bins=bins, alpha=0.6, color="#C62828", label="Ask L1",
            density=True, edgecolor="white")
    ax.set_xscale("log")
    ax.set_xlabel("L1 queue depth (LINK, log scale)")
    ax.set_ylabel("Density")
    ax.set_title("L1 Queue Depth PDF\n[Shows how thin the touch can get]")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)

    for depths, color, label in [
        (bid_depths, "#1565C0", "Bid"),
        (ask_depths, "#C62828", "Ask"),
    ]:
        p1  = np.percentile(depths, 1)
        p5  = np.percentile(depths, 5)
        p10 = np.percentile(depths, 10)
        p50 = np.percentile(depths, 50)
        p90 = np.percentile(depths, 90)
        ax.axvline(p5,  color=color, lw=1.2, ls=":", alpha=0.8)
        ax.axvline(p50, color=color, lw=1.8, ls="--", alpha=0.9)
        print(f"  {label} L1 depth: p1={p1:.0f}  p5={p5:.0f}  p10={p10:.0f}  "
              f"p50={p50:.0f}  p90={p90:.0f}  LINK")

    ax2 = axes[1]
    x_max = np.percentile(bid_depths, 99)
    x_grid = np.linspace(0, x_max, 500)
    ax2.plot(x_grid, [np.mean(bid_depths <= x) for x in x_grid],
             color="#1565C0", lw=2.5, label="Bid L1 CDF")
    ax2.plot(x_grid, [np.mean(ask_depths <= x) for x in x_grid],
             color="#C62828", lw=2.5, ls="--", label="Ask L1 CDF")

    for pct in [0.1, 0.25, 0.5]:
        ax2.axhline(pct, color="k", lw=0.6, ls=":")
        ax2.text(x_max * 0.97, pct + 0.01, f"{int(pct*100)}%",
                 ha="right", va="bottom", fontsize=8, color="grey")

    ax2.set_xlabel("L1 queue depth (LINK)")
    ax2.set_ylabel("CDF")
    ax2.set_title("L1 Queue Depth CDF\n[10th percentile = 'thin touch' threshold]")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.25)

    plt.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out.name}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(exist_ok=True)

    ob_files = sorted(glob.glob(str(DATA_DIR / f"orderbooks_{SYMBOL}_2026-04-*.parquet")))
    dates    = [Path(f).stem.replace(f"orderbooks_{SYMBOL}_", "") for f in ob_files]
    print(f"Extended LOB analysis on {len(dates)} days: {dates[0]} → {dates[-1]}")

    # IC at each horizon from fig9 (lob_shape.py output — L1 row)
    ic_l1 = {0.5: 0.20, 1: 0.22, 2: 0.26, 5: 0.32,
              10: 0.37, 30: 0.39, 60: 0.35, 120: 0.29}

    all_acf        = []
    all_trade_sz   = []
    all_queue_dep  = []
    all_bid_depth  = []
    all_ask_depth  = []

    for ds in dates:
        ob = load_ob(ds)
        tr = load_trades(ds)
        if ob is None or tr is None:
            continue
        print(f"  {ds}: {len(ob):,} snapshots  {len(tr):,} trades", end=" ... ")

        acf = compute_obi_acf(ob)
        all_acf.append(acf)

        ts, qd = compute_trade_vs_queue(ob, tr)
        all_trade_sz.append(ts)
        all_queue_dep.append(qd)

        all_bid_depth.append(ob["bid_depth_l1"].values)
        all_ask_depth.append(ob["ask_depth_l1"].values)

        print(f"acf@30s={acf.get(30, np.nan):.3f}")

    all_trade_sz  = np.concatenate(all_trade_sz)
    all_queue_dep = np.concatenate(all_queue_dep)
    all_bid_depth = np.concatenate(all_bid_depth)
    all_ask_depth = np.concatenate(all_ask_depth)

    print(f"\nTotal trades: {len(all_trade_sz):,}")
    print(f"Total OB snapshots: {len(all_bid_depth):,}")

    # ── Fig 13: OBI autocorrelation ───────────────────────────
    print("\nPlotting fig13_obi_acf.png ...")
    acf_mean, acf_std = plot_obi_acf(all_acf, ic_l1,
                                      OUT_DIR / "fig13_obi_acf.png")

    print("\nOBI ACF summary:")
    for lag, am, sd in zip(ACF_LAGS, acf_mean, acf_std):
        print(f"  lag={lag:>5.0f}s  ACF={am:.4f} ± {sd:.4f}")

    # ── Fig 14: Trade size vs queue ───────────────────────────
    print("\nPlotting fig14_trade_vs_queue.png ...")
    pct_clears, med_t, med_q = plot_trade_vs_queue(
        all_trade_sz, all_queue_dep,
        OUT_DIR / "fig14_trade_vs_queue.png")

    print(f"\nTrade size vs queue:")
    print(f"  Median trade size : {med_t:.1f} LINK")
    print(f"  Median queue depth: {med_q:.1f} LINK")
    print(f"  Queue / trade ratio: {med_q/med_t:.1f}×")
    print(f"  % trades that clear L1 queue: {pct_clears:.1f}%")

    # ── Fig 15: L1 depth distribution ────────────────────────
    print("\nPlotting fig15_l1_depth_dist.png ...")
    plot_l1_depth_distribution(all_bid_depth, all_ask_depth,
                                OUT_DIR / "fig15_l1_depth_dist.png")

    print("\nDone.")


if __name__ == "__main__":
    main()
