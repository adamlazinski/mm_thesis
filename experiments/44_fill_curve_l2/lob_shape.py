"""
LOB Shape Analysis — LINK/USDT April 2026
==========================================
Analyses the shape and dynamics of the full 50-level limit order book.

Outputs
-------
fig1_lob_profile.png      — Average normalised depth at each tick level (bid + ask)
fig2_lob_ic_heatmap.png   — Spearman IC of per-level imbalance vs multi-horizon returns
fig3_intraday_depth.png   — L1 bid/ask depth by UTC hour (mean ± 1σ)
fig4_cumulative_depth.png — Cumulative volume fraction vs tick distance from mid
fig5_shape_stability.png  — Day-to-day variation in depth profile shape
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
DATA_DIR  = Path("data/real")
OUT_DIR   = Path("experiments/44_fill_curve_l2/analysis")
SYMBOL    = "LINK"
TICK      = 0.001          # $0.001 per tick
N_LEVELS  = 50             # levels per side in the snapshot
SAMPLE_S  = 5.0            # sample every 5 s for IC / profile analysis
HORIZONS  = [0.5, 1, 2, 5, 10, 30, 60, 120]   # seconds
IC_LEVELS = list(range(1, 21))                  # LOB levels to compute IC for


# ─────────────────────────────────────────────────────────────
# Data loading helpers
# ─────────────────────────────────────────────────────────────

def load_day(ob_path: str):
    """Return ob_df with ts, ob_ts, ob_mid arrays for one day."""
    ob = pq.read_table(ob_path).to_pandas()
    ob["ts"] = ob["time_exchange"].astype("int64") / 1e9
    # Pre-compute mid from the book itself (clean, no trade-price noise)
    bids0 = ob["bids"].apply(lambda x: list(x)[0]["price"] if len(list(x)) else np.nan)
    asks0 = ob["asks"].apply(lambda x: list(x)[0]["price"] if len(list(x)) else np.nan)
    ob["mid"] = (bids0 + asks0) / 2.0
    ob_ts  = ob["ts"].values
    ob_mid = ob["mid"].values
    return ob, ob_ts, ob_mid


def parse_levels(row):
    """Return (bid_sizes, ask_sizes) as arrays sorted best-first (50 levels)."""
    bids = list(row["bids"])
    asks = list(row["asks"])
    bs  = np.array([b["size"] for b in bids], dtype=np.float64)
    as_ = np.array([a["size"] for a in asks], dtype=np.float64)
    return bs, as_


def mid_at(ts: float, ob_ts: np.ndarray, ob_mid: np.ndarray) -> float:
    """Nearest (interpolated) mid from the book at time ts."""
    idx = np.searchsorted(ob_ts, ts, side="right") - 1
    if idx < 0:
        return np.nan
    if idx + 1 < len(ob_ts):
        # linear interpolation between adjacent snapshots
        t0, t1 = ob_ts[idx], ob_ts[idx + 1]
        m0, m1 = ob_mid[idx], ob_mid[idx + 1]
        w = (ts - t0) / (t1 - t0) if t1 > t0 else 0.0
        return float(m0 + w * (m1 - m0))
    return float(ob_mid[idx])


# ─────────────────────────────────────────────────────────────
# Per-snapshot feature extraction
# ─────────────────────────────────────────────────────────────

def extract_features(ob: pd.DataFrame, ob_ts: np.ndarray, ob_mid: np.ndarray,
                     sample_s: float = SAMPLE_S):
    """
    Sample every sample_s seconds. For each sample compute:
      - depth at each of N_LEVELS LOB levels (by level index, not tick offset)
      - OBI at each cumulative level depth
      - multi-horizon returns using book mid (clean, no trade-price noise)
    """
    ts_all = ob["ts"].values

    t_start = ts_all[0]
    t_end   = ts_all[-1]
    sample_times = np.arange(t_start, t_end, sample_s)
    snap_idx = np.searchsorted(ts_all, sample_times, side="left").clip(0, len(ts_all) - 1)

    max_lev = max(IC_LEVELS)
    records = []

    for si in snap_idx:
        row = ob.iloc[si]
        ts  = float(row["ts"])
        cur_mid = float(row["mid"])
        if np.isnan(cur_mid):
            continue

        bs, as_ = parse_levels(row)
        if len(bs) == 0 or len(as_) == 0:
            continue

        n_lev = min(len(bs), len(as_), N_LEVELS)

        # Depth by level index (not tick offset): level 0 = L1 (best), level 1 = L2, ...
        bid_depth_by_lev = np.zeros(N_LEVELS)
        ask_depth_by_lev = np.zeros(N_LEVELS)
        bid_depth_by_lev[:n_lev] = bs[:n_lev]
        ask_depth_by_lev[:n_lev] = as_[:n_lev]

        # OBI at each cumulative level
        n_avail = min(n_lev, max_lev)
        cum_bid = np.cumsum(bs[:n_avail])
        cum_ask = np.cumsum(as_[:n_avail])
        obi_by_level = np.full(max_lev, np.nan)
        for lev in range(1, n_avail + 1):
            b = cum_bid[lev - 1]
            a = cum_ask[lev - 1]
            denom = b + a
            obi_by_level[lev - 1] = (b - a) / denom if denom > 1e-9 else 0.0

        # Future returns using clean book mid
        rets = {}
        for h in HORIZONS:
            fm = mid_at(ts + h, ob_ts, ob_mid)
            rets[h] = (fm - cur_mid) / cur_mid if (not np.isnan(fm) and cur_mid > 0) else np.nan

        records.append({
            "ts":                ts,
            "mid":               cur_mid,
            "hour":              int((ts % 86400) // 3600),
            "bid_depth_touch":   bid_depth_by_lev[0],
            "ask_depth_touch":   ask_depth_by_lev[0],
            "bid_depth_by_lev":  bid_depth_by_lev,
            "ask_depth_by_lev":  ask_depth_by_lev,
            "obi_by_level":      obi_by_level,
            "rets":              rets,
        })

    return records


# ─────────────────────────────────────────────────────────────
# Aggregation helpers
# ─────────────────────────────────────────────────────────────

def agg_profile(all_records):
    """Mean depth profile normalised by L1 depth, bid and ask sides."""
    bid_stack = np.array([r["bid_depth_by_lev"] for r in all_records])
    ask_stack = np.array([r["ask_depth_by_lev"] for r in all_records])

    # Normalise each snapshot by its L1 depth (avoid all-zero rows)
    bid_l1 = bid_stack[:, 0].clip(1e-9)
    ask_l1 = ask_stack[:, 0].clip(1e-9)
    bid_norm = bid_stack / bid_l1[:, None]
    ask_norm = ask_stack / ask_l1[:, None]

    return (np.nanmean(bid_norm, axis=0),
            np.nanstd(bid_norm, axis=0),
            np.nanmean(ask_norm, axis=0),
            np.nanstd(ask_norm, axis=0))


def agg_cumulative(all_records):
    """Mean cumulative volume fraction vs LOB level."""
    bid_stack = np.array([r["bid_depth_by_lev"] for r in all_records])
    ask_stack = np.array([r["ask_depth_by_lev"] for r in all_records])
    bid_cum = np.cumsum(bid_stack, axis=1)
    ask_cum = np.cumsum(ask_stack, axis=1)
    bid_total = bid_cum[:, -1].clip(1e-9)
    ask_total = ask_cum[:, -1].clip(1e-9)
    bid_frac = bid_cum / bid_total[:, None]
    ask_frac = ask_cum / ask_total[:, None]
    return np.nanmean(bid_frac, axis=0), np.nanmean(ask_frac, axis=0)


def agg_ic(all_records):
    """Spearman IC of OBI at each level vs each return horizon."""
    obi_mat = np.array([r["obi_by_level"] for r in all_records])   # (N, max_lev)
    ic = np.full((len(IC_LEVELS), len(HORIZONS)), np.nan)

    for li, lev in enumerate(IC_LEVELS):
        obi_col = obi_mat[:, lev - 1]
        for hi, h in enumerate(HORIZONS):
            ret_col = np.array([r["rets"][h] for r in all_records])
            mask = np.isfinite(obi_col) & np.isfinite(ret_col)
            if mask.sum() > 50:
                ic[li, hi] = spearmanr(obi_col[mask], ret_col[mask]).statistic

    return ic


def agg_intraday(all_records):
    """Mean L1 bid/ask depth by UTC hour."""
    hours = np.array([r["hour"] for r in all_records])
    bid_l1 = np.array([r["bid_depth_touch"] for r in all_records])
    ask_l1 = np.array([r["ask_depth_touch"] for r in all_records])

    hour_bid_mean, hour_bid_std = np.zeros(24), np.zeros(24)
    hour_ask_mean, hour_ask_std = np.zeros(24), np.zeros(24)
    for h in range(24):
        mask = hours == h
        if mask.sum() > 0:
            hour_bid_mean[h] = bid_l1[mask].mean()
            hour_bid_std[h]  = bid_l1[mask].std()
            hour_ask_mean[h] = ask_l1[mask].mean()
            hour_ask_std[h]  = ask_l1[mask].std()
    return hour_bid_mean, hour_bid_std, hour_ask_mean, hour_ask_std


# ─────────────────────────────────────────────────────────────
# Plotting
# ─────────────────────────────────────────────────────────────

def plot_profile(bid_mean, bid_std, ask_mean, ask_std, out: Path):
    levels = np.arange(1, N_LEVELS + 1)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    for ax, mean, std, label, color in [
        (axes[0], bid_mean, bid_std, "Bid", "#1565C0"),
        (axes[0], ask_mean, ask_std, "Ask", "#C62828"),
    ]:
        ax.plot(levels, mean, color=color, label=label, lw=1.8)
        ax.fill_between(levels, mean - std, mean + std, color=color, alpha=0.15)

    axes[0].set_xlabel("LOB level (1 = best bid/ask)")
    axes[0].set_ylabel("Depth (normalised by L1)")
    axes[0].set_title("Average LOB depth profile (linear)")
    axes[0].legend()
    axes[0].set_xlim(1, N_LEVELS)
    axes[0].grid(alpha=0.3)

    # Log scale
    axes[1].semilogy(levels, np.maximum(bid_mean, 1e-6), color="#1565C0", label="Bid", lw=1.8)
    axes[1].semilogy(levels, np.maximum(ask_mean, 1e-6), color="#C62828", label="Ask", lw=1.8)
    axes[1].set_xlabel("LOB level (1 = best bid/ask)")
    axes[1].set_ylabel("Depth (log scale, normalised by L1)")
    axes[1].set_title("Average LOB depth profile (log scale)")
    axes[1].legend()
    axes[1].set_xlim(1, N_LEVELS)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out.name}")


def plot_ic_heatmap(ic: np.ndarray, out: Path):
    fig, ax = plt.subplots(figsize=(12, 7))
    vmax = np.nanmax(np.abs(ic))
    im = ax.imshow(ic, aspect="auto", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax, interpolation="nearest")
    ax.set_xticks(range(len(HORIZONS)))
    ax.set_xticklabels([f"{h}s" for h in HORIZONS])
    ax.set_yticks(range(len(IC_LEVELS)))
    ax.set_yticklabels([f"L{l}" for l in IC_LEVELS])
    ax.set_xlabel("Return horizon")
    ax.set_ylabel("OBI level (cumulative depth)")
    ax.set_title("Spearman IC: OBI by level vs future mid return")
    plt.colorbar(im, ax=ax, label="Spearman IC")
    for li in range(len(IC_LEVELS)):
        for hi in range(len(HORIZONS)):
            v = ic[li, hi]
            if not np.isnan(v):
                ax.text(hi, li, f"{v:.2f}", ha="center", va="center",
                        fontsize=6.5, color="white" if abs(v) > vmax * 0.6 else "black")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out.name}")


def plot_intraday(bmean, bstd, amean, astd, out: Path):
    hours = np.arange(24)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(hours, bmean / 1000, color="#1565C0", label="Bid L1 depth", lw=2)
    ax.fill_between(hours, (bmean - bstd) / 1000, (bmean + bstd) / 1000,
                    color="#1565C0", alpha=0.18)
    ax.plot(hours, amean / 1000, color="#C62828", label="Ask L1 depth", lw=2)
    ax.fill_between(hours, (amean - astd) / 1000, (amean + astd) / 1000,
                    color="#C62828", alpha=0.18)
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("Depth at touch (k LINK)")
    ax.set_title("Intraday depth at best bid/ask — LINK April 2026")
    ax.set_xticks(hours)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out.name}")


def plot_cumulative(bid_frac, ask_frac, out: Path):
    levels = np.arange(1, N_LEVELS + 1)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(levels, bid_frac, color="#1565C0", label="Bid", lw=2)
    ax.plot(levels, ask_frac, color="#C62828", label="Ask", lw=2, ls="--")
    for pct in [0.25, 0.5, 0.75, 0.9]:
        ax.axhline(pct, color="grey", lw=0.7, ls=":")
        ax.text(N_LEVELS, pct + 0.01, f"{int(pct*100)}%", va="bottom",
                ha="right", fontsize=8, color="grey")
    for side, frac, color in [("Bid", bid_frac, "#1565C0"), ("Ask", ask_frac, "#C62828")]:
        for pct in [0.5, 0.9]:
            idx = np.searchsorted(frac, pct)
            if idx < N_LEVELS:
                ax.axvline(idx + 1, color=color, lw=0.8, ls=":")
    ax.set_xlabel("LOB level (1 = best bid/ask)")
    ax.set_ylabel("Fraction of total book volume")
    ax.set_title("Cumulative depth distribution — how concentrated is the LINK book?")
    ax.legend()
    ax.set_xlim(1, N_LEVELS)
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out.name}")


def plot_shape_stability(daily_profiles: list, days: list, out: Path):
    """Plot bid depth profile for each day (normalised), showing day-to-day variation."""
    levels = np.arange(1, N_LEVELS + 1)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    cmap = plt.cm.viridis
    n = len(daily_profiles)

    for i, (bid_mean, _, ask_mean, _, day) in enumerate(
            zip(*zip(*daily_profiles), days)):
        color = cmap(i / max(n - 1, 1))
        axes[0].semilogy(levels, np.maximum(bid_mean, 1e-6), color=color, lw=0.8, alpha=0.7)
        axes[1].semilogy(levels, np.maximum(ask_mean, 1e-6), color=color, lw=0.8, alpha=0.7)

    for ax, side in zip(axes, ["Bid", "Ask"]):
        ax.set_xlabel("Tick distance from touch")
        ax.set_ylabel("Depth (log, normalised)")
        ax.set_title(f"{side} depth profile — daily variation")
        ax.set_xlim(0, N_LEVELS - 1)
        ax.grid(alpha=0.3)

    sm = plt.cm.ScalarMappable(cmap=cmap,
                                norm=plt.Normalize(vmin=0, vmax=n - 1))
    sm.set_array([])
    cb = fig.colorbar(sm, ax=axes[1], label="Day index (Apr 1 → Apr 30)")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"Saved {out.name}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--start", default="2026-04-01")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    start = date.fromisoformat(args.start)
    all_records = []
    daily_profiles = []
    days_used = []

    print(f"Running LOB shape analysis on {args.days} days")
    d = start
    n_done = 0
    while n_done < args.days:
        ds = d.strftime("%Y-%m-%d")
        ob_path = DATA_DIR / f"orderbooks_{SYMBOL}_{ds}.parquet"
        d += timedelta(days=1)
        if not ob_path.exists():
            continue

        ob, ob_ts, ob_mid = load_day(str(ob_path))
        recs = extract_features(ob, ob_ts, ob_mid)
        if not recs:
            continue
        all_records.extend(recs)

        # Per-day profile for stability plot
        bid_m, bid_s, ask_m, ask_s = agg_profile(recs)
        daily_profiles.append((bid_m, bid_s, ask_m, ask_s))
        days_used.append(ds)
        n_done += 1
        print(f"  {ds}: {len(ob):,} snapshots → {len(recs):,} samples")

    print(f"\nTotal samples: {len(all_records):,}")

    # ── Analysis 1: Average LOB profile ─────────────────────
    bid_m, bid_s, ask_m, ask_s = agg_profile(all_records)
    plot_profile(bid_m, bid_s, ask_m, ask_s,
                 OUT_DIR / "fig8_lob_profile.png")

    # Print key shape stats
    bid_norm_cum = np.cumsum(bid_m) / np.sum(bid_m)
    ask_norm_cum = np.cumsum(ask_m) / np.sum(ask_m)
    bid_50 = np.searchsorted(bid_norm_cum, 0.5) + 1
    ask_50 = np.searchsorted(ask_norm_cum, 0.5) + 1
    bid_90 = np.searchsorted(bid_norm_cum, 0.9) + 1
    ask_90 = np.searchsorted(ask_norm_cum, 0.9) + 1
    print(f"\nDepth concentration (by LOB level):")
    print(f"  50% of bid book within L{bid_50} | ask within L{ask_50}")
    print(f"  90% of bid book within L{bid_90} | ask within L{ask_90}")
    print(f"  L2/L1 depth ratio  bid={bid_m[1]:.2f}x  ask={ask_m[1]:.2f}x")
    print(f"  L5/L1 depth ratio  bid={bid_m[4]:.2f}x  ask={ask_m[4]:.2f}x")
    print(f"  L10/L1 depth ratio bid={bid_m[9]:.2f}x  ask={ask_m[9]:.2f}x")

    # ── Analysis 2: IC heatmap ───────────────────────────────
    ic = agg_ic(all_records)
    plot_ic_heatmap(ic, OUT_DIR / "fig9_lob_ic_heatmap.png")

    print(f"\nIC by level at 0.5s horizon:")
    for li, lev in enumerate(IC_LEVELS):
        print(f"  L{lev:>2}: {ic[li, 0]:+.4f}")

    # ── Analysis 3: Intraday depth ───────────────────────────
    bmean, bstd, amean, astd = agg_intraday(all_records)
    plot_intraday(bmean, bstd, amean, astd,
                  OUT_DIR / "fig10_intraday_depth.png")
    peak_h = int(np.argmax(bmean))
    thin_h = int(np.argmin(bmean[bmean > 0]))
    print(f"\nIntraday depth: peak hour UTC={peak_h:02d}  "
          f"({bmean[peak_h]/1000:.1f}k LINK)  "
          f"thinnest UTC={thin_h:02d} ({bmean[thin_h]/1000:.1f}k LINK)")

    # ── Analysis 4: Cumulative depth ─────────────────────────
    bid_frac, ask_frac = agg_cumulative(all_records)
    plot_cumulative(bid_frac, ask_frac,
                    OUT_DIR / "fig11_cumulative_depth.png")

    # ── Analysis 5: Daily shape stability ───────────────────
    if len(daily_profiles) > 1:
        plot_shape_stability(daily_profiles, days_used,
                             OUT_DIR / "fig12_shape_stability.png")


if __name__ == "__main__":
    main()
