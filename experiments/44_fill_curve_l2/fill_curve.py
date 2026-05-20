"""
Experiment 44: Empirical Fill Probability Curve from L2 + Trades

Builds the fill probability curve P(fill | delta, T) from:
  - CoinAPI orderbook snapshots (queue depth at each level)
  - CoinAPI trade data (market order flow)

Key questions:
  1. Is the fill curve exponential (GLFT assumption) or step-function (LINK finding)?
  2. How does fill probability vary with OBI, time of day, volume regime?
  3. What are the implied A and kappa for the exponential model?
  4. What is the effective fill probability at inside-spread vs at-touch levels?

Price levels (delta = ticks from mid, bid side):
  delta=1..4  inside the natural spread  (queue_ahead=0, we are NBBO)
  delta=5     AT NATURAL BID             (queue_ahead = L2 depth at best bid)
  delta=6..15 outside the spread        (fill requires price to move through our level)

Run from master2/:
    python experiments/44_fill_curve_l2/fill_curve.py --days 5
    python experiments/44_fill_curve_l2/fill_curve.py --days 30 --plot
"""

import argparse
import glob
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# ── Configuration ─────────────────────────────────────────────────────────────
DATA_DIR    = Path("data/real")
OUT_DIR     = Path("experiments/44_fill_curve_l2/results")
ANALYSIS_DIR= Path("experiments/44_fill_curve_l2/analysis")

TICK        = 0.001          # LINK tick size
HALF_SPREAD = 5              # natural spread = 10 ticks → 5 per side
HOLD        = 0.5            # quote lifetime (seconds)
LATENCY     = 0.1            # activation latency (seconds)
SAMPLE_EVERY= 10             # use every Nth snapshot (speed vs accuracy)
MAX_DELTA   = 15             # sweep delta 1..MAX_DELTA ticks from mid
OBI_BINS    = 3              # quantile bins for OBI conditioning
HOUR_BINS   = [(0,8,'Asia'), (8,16,'Europe'), (16,24,'US')]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_day(date_str: str):
    """Load orderbook + trades for a single day."""
    ob_path = DATA_DIR / f"orderbooks_LINK_{date_str}.parquet"
    tr_path = DATA_DIR / f"trades_LINK_{date_str}.parquet"
    if not ob_path.exists() or not tr_path.exists():
        return None, None

    ob = pd.read_parquet(ob_path)
    tr = pd.read_parquet(tr_path)

    # Convert timestamps to float seconds
    ob["ts"] = pd.to_datetime(ob["time_exchange"]).astype("int64") / 1e9
    tr["ts"] = pd.to_datetime(tr["time_exchange"]).astype("int64") / 1e9

    # Parse best bid/ask and queue depth from L2
    ob["best_bid"]       = ob["bids"].apply(lambda x: list(x)[0]["price"])
    ob["best_ask"]       = ob["asks"].apply(lambda x: list(x)[0]["price"])
    ob["bid_depth"]      = ob["bids"].apply(lambda x: list(x)[0]["size"])
    ob["ask_depth"]      = ob["asks"].apply(lambda x: list(x)[0]["size"])
    ob["mid"]            = (ob["best_bid"] + ob["best_ask"]) / 2

    # Multi-level OBI
    def _depth(col, n):
        return ob[col].apply(lambda x: sum(l["size"] for l in list(x)[:n]))

    bid_d1 = _depth("bids", 1)
    ask_d1 = _depth("asks", 1)
    bid_d3 = _depth("bids", 3)
    ask_d3 = _depth("asks", 3)
    ob["obi_l1"] = (bid_d1 - ask_d1) / (bid_d1 + ask_d1 + 1e-9)
    ob["obi_l3"] = (bid_d3 - ask_d3) / (bid_d3 + ask_d3 + 1e-9)

    ob["hour"] = ((ob["ts"] % 86400) / 3600).astype(int)

    ob = ob.sort_values("ts").reset_index(drop=True)
    tr = tr.sort_values("ts").reset_index(drop=True)

    return ob, tr


def compute_fill_curve(ob: pd.DataFrame, tr: pd.DataFrame,
                       hold: float = HOLD, latency: float = LATENCY,
                       sample_every: int = SAMPLE_EVERY,
                       max_delta: int = MAX_DELTA) -> pd.DataFrame:
    """
    Compute empirical fill probability at each delta level.

    For each sampled snapshot at time t, for each delta (ticks from mid):
      - Determine bid_price = mid - delta * tick_size (rounded to tick)
      - Determine queue_ahead:
          delta < half_spread  → inside spread, queue_ahead = 0
          delta == half_spread → at touch, queue_ahead = L2 bid_depth
          delta > half_spread  → outside, queue_ahead = bid_depth + outside_levels
      - Find SELL trades in [t + latency, t + latency + hold]
      - Fill (bid) condition: cumulative SELL volume at price >= bid_price > queue_ahead
        For inside-spread: any SELL trade at or above best_bid fills us
        For at/outside:    cumulative SELL volume ≥ queue_ahead

    Returns DataFrame with columns:
        delta, fill_prob, n_obs, obi_l1, obi_l3, hour, bid_depth, ts
    """
    ts_ob  = ob["ts"].values
    ts_tr  = tr["ts"].values
    side   = tr["taker_side"].values       # 'SELL' or 'BUY'
    price  = tr["price"].values
    size   = tr["size"].values

    records = []
    n_snaps = len(ob)

    for i in range(0, n_snaps, sample_every):
        row = ob.iloc[i]
        t0       = row["ts"]
        mid      = row["mid"]
        bid_nat  = row["best_bid"]
        ask_nat  = row["best_ask"]
        bid_dep  = row["bid_depth"]
        obi_l1   = row["obi_l1"]
        obi_l3   = row["obi_l3"]
        hour     = row["hour"]

        t_start = t0 + latency
        t_end   = t0 + latency + hold

        # Slice trades in the window
        idx_lo = np.searchsorted(ts_tr, t_start, side="left")
        idx_hi = np.searchsorted(ts_tr, t_end,   side="right")
        w_side  = side[idx_lo:idx_hi]
        w_price = price[idx_lo:idx_hi]
        w_size  = size[idx_lo:idx_hi]

        sell_mask   = w_side == "SELL"
        sell_prices = w_price[sell_mask]
        sell_sizes  = w_size[sell_mask]

        # Pre-compute: cumulative SELL volume at each threshold
        # For queue-aware model we also need queue depths from L2
        bids_list = list(ob.iloc[i]["bids"])

        for delta in range(1, max_delta + 1):
            bid_price = round(mid - delta * TICK, 6)

            # ── Price-only fill (what the backtest uses) ──────────────────
            # A SELL trade at price T fills a BID at P if T <= P
            # Inside spread: bid_price > natural_bid, so SELL at natural_bid fills us
            # At touch: bid_price = natural_bid, SELL at natural_bid fills us (ignoring queue)
            # Outside: bid_price < natural_bid, only fills when natural bid moves there
            fill_price_only = bool(np.any(sell_prices <= bid_price + TICK / 2))

            # ── Queue-aware fill ──────────────────────────────────────────
            # Fill requires SELL volume to exceed all orders ahead of us in queue
            # queue_ahead = sum of L2 bid depths at prices strictly > bid_price
            if delta < HALF_SPREAD:
                # Inside spread: we are NBBO, no orders ahead
                queue_ahead = 0.0
            else:
                # At touch or outside: sum L2 depth at prices >= bid_price
                # (i.e., all orders that have priority over ours)
                queue_ahead = sum(
                    l["size"] for l in bids_list
                    if l["price"] >= bid_price - TICK / 2
                )

            cum_sell_vol = sell_sizes[sell_prices <= bid_price + TICK / 2].sum()
            fill_queue   = cum_sell_vol > queue_ahead

            records.append({
                "delta":          delta,
                "fill_price":     int(fill_price_only),
                "fill_queue":     int(fill_queue),
                "obi_l1":         obi_l1,
                "obi_l3":         obi_l3,
                "hour":           hour,
                "bid_depth":      bid_dep,
                "queue_ahead":    queue_ahead,
                "ts":             t0,
            })

    df = pd.DataFrame(records)
    curve = (df.groupby("delta")
               .agg(
                   fill_price=("fill_price", "mean"),
                   fill_queue=("fill_queue", "mean"),
                   n_obs=("fill_price", "count"),
                   obi_l1=("obi_l1", "mean"),
                   obi_l3=("obi_l3", "mean"),
                   bid_depth=("bid_depth", "mean"),
                   queue_ahead=("queue_ahead", "mean"),
               )
               .reset_index())
    return curve, df


def fit_exponential(deltas: np.ndarray, probs: np.ndarray):
    """Fit A * exp(-kappa * delta) to the empirical curve. Returns (A, kappa, r2)."""
    mask = probs > 0
    if mask.sum() < 3:
        return np.nan, np.nan, np.nan
    try:
        popt, _ = curve_fit(
            lambda x, A, k: A * np.exp(-k * x),
            deltas[mask], probs[mask],
            p0=[probs[mask].max(), 0.5],
            bounds=([0, 0], [10, 100]),
            maxfev=5000,
        )
        A, kappa = popt
        pred = A * np.exp(-kappa * deltas[mask])
        ss_res = np.sum((probs[mask] - pred) ** 2)
        ss_tot = np.sum((probs[mask] - probs[mask].mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return float(A), float(kappa), float(r2)
    except Exception:
        return np.nan, np.nan, np.nan


# ── Main analysis ─────────────────────────────────────────────────────────────

def run(dates: list, plot: bool = True):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    all_raw = []
    daily_curves = []

    for date_str in dates:
        ob, tr = load_day(date_str)
        if ob is None:
            print(f"  {date_str}: no data")
            continue
        print(f"  {date_str}: {len(ob):,} snapshots, {len(tr):,} trades", end=" ... ")
        curve, raw = compute_fill_curve(ob, tr)
        curve["date"] = date_str
        daily_curves.append(curve)
        raw["date"] = date_str
        all_raw.append(raw)
        A, kappa, r2 = fit_exponential(curve["delta"].values, curve["fill_price"].values)
        print(f"price-only A={A:.3f} κ={kappa:.3f} R²={r2:.3f}")

    if not daily_curves:
        print("No data found.")
        return

    # Aggregate across days
    raw_all = pd.concat(all_raw, ignore_index=True)
    agg = (raw_all.groupby("delta")
                  .agg(
                      fill_price=("fill_price", "mean"),
                      fill_queue=("fill_queue", "mean"),
                      n_obs=("fill_price", "count"),
                      queue_ahead=("queue_ahead", "mean"),
                  )
                  .reset_index())

    A_p, kappa_p, r2_p = fit_exponential(agg["delta"].values, agg["fill_price"].values)
    A_q, kappa_q, r2_q = fit_exponential(agg["delta"].values, agg["fill_queue"].values)

    print(f"\nAggregate ({len(dates)} days):")
    print(f"  Price-only:  A={A_p:.4f}  κ={kappa_p:.4f}  R²={r2_p:.4f}")
    print(f"  Queue-aware: A={A_q:.4f}  κ={kappa_q:.4f}  R²={r2_q:.4f}")
    print(f"\n  {'Delta':>5}  {'Region':>14}  {'Price-only':>10}  {'Queue-aware':>11}  {'AvgQueue':>9}")
    print("  " + "-"*58)
    for _, row in agg.iterrows():
        d = int(row["delta"])
        region = "inside spread" if d < HALF_SPREAD else ("AT TOUCH" if d == HALF_SPREAD else "outside")
        print(f"  {d:>5}  {region:>14}  {row['fill_price']:>10.4f}  {row['fill_queue']:>11.5f}  {row['queue_ahead']:>9.0f}")

    # Save aggregate CSV
    agg.to_csv(OUT_DIR / "fill_curve_aggregate.csv", index=False)

    # ── OBI conditioning ──────────────────────────────────────────────────────
    raw_all["obi_bin"] = pd.qcut(raw_all["obi_l1"], OBI_BINS,
                                  labels=["Low OBI\n(ask pressure)",
                                          "Neutral OBI",
                                          "High OBI\n(bid pressure)"])
    obi_curve = (raw_all.groupby(["delta", "obi_bin"])
                         .agg(fill_price=("fill_price", "mean"),
                              fill_queue=("fill_queue", "mean"))
                         .reset_index())

    # ── Time-of-day conditioning ──────────────────────────────────────────────
    def session(h):
        for lo, hi, name in HOUR_BINS:
            if lo <= h < hi:
                return name
        return "Asia"
    raw_all["session"] = raw_all["hour"].apply(session)
    session_curve = (raw_all.groupby(["delta", "session"])
                             .agg(fill_price=("fill_price", "mean"),
                                  fill_queue=("fill_queue", "mean"))
                             .reset_index())

    if not plot:
        return agg, obi_curve, session_curve

    # ── Figures ───────────────────────────────────────────────────────────────
    deltas   = agg["delta"].values
    p_price  = agg["fill_price"].values
    p_queue  = agg["fill_queue"].values
    exp_p    = A_p * np.exp(-kappa_p * deltas) if not np.isnan(A_p) else np.zeros_like(p_price)
    exp_q    = A_q * np.exp(-kappa_q * deltas) if not np.isnan(A_q) else np.zeros_like(p_queue)

    # fig1: both fill curves side by side
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(f"LINK/USDT Empirical Fill Probability — {len(dates)} days Apr 2026",
                 fontsize=13, fontweight="bold")

    # Left: price-only model (backtest model)
    ax = axes[0]
    colors = ["#1565C0" if d < HALF_SPREAD else ("#E65100" if d == HALF_SPREAD else "#757575")
              for d in deltas]
    ax.bar(deltas, p_price, color=colors, edgecolor="white", lw=0.5, zorder=3)
    ax.plot(deltas, exp_p, color="#B71C1C", lw=2, ls="--",
            label=f"Exp fit: A={A_p:.3f}, κ={kappa_p:.3f}, R²={r2_p:.3f}")
    ax.axvline(HALF_SPREAD - 0.5, color="#E65100", lw=1.5, ls=":", alpha=0.6)
    ax.set_xlabel("Ticks from mid (δ)")
    ax.set_ylabel("Fill probability  P(fill | δ, T=0.5s)")
    ax.set_title("Price-Only Fill Model\n[Backtest model: fill if trade price ≤ bid price]")
    ax.set_xticks(deltas)
    ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color="#1565C0", label="Inside spread"),
        Patch(color="#E65100", label="At natural bid"),
        Patch(color="#757575", label="Outside spread"),
    ] + ax.get_legend_handles_labels()[0], fontsize=8)

    # Right: queue-aware model (reality)
    ax2 = axes[1]
    ax2.bar(deltas, p_queue, color=colors, edgecolor="white", lw=0.5, zorder=3)
    ax2.plot(deltas, exp_q, color="#B71C1C", lw=2, ls="--",
             label=f"Exp fit: A={A_q:.4f}, κ={kappa_q:.3f}, R²={r2_q:.3f}")
    ax2.axvline(HALF_SPREAD - 0.5, color="#E65100", lw=1.5, ls=":", alpha=0.6)
    ax2.set_xlabel("Ticks from mid (δ)")
    ax2.set_ylabel("Fill probability  P(fill | δ, T=0.5s)")
    ax2.set_title("Queue-Aware Fill Model\n[Reality: fill requires clearing L2 queue ahead]")
    ax2.set_xticks(deltas)
    ax2.legend(fontsize=9); ax2.grid(alpha=0.25, axis="y")

    plt.tight_layout()
    fig.savefig(ANALYSIS_DIR / "fig1_fill_curve.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved fig1_fill_curve.png")

    # fig2: OBI conditioning (price-only model, inside-spread focus)
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Fill Probability Conditioned on OBI (L1)", fontsize=13)
    colors_obi = ["#E65100", "#757575", "#1565C0"]
    for ax_idx, col, title in [(0, "fill_price", "Price-Only Model"), (1, "fill_queue", "Queue-Aware Model")]:
        ax = axes[ax_idx]
        for (label, grp), c in zip(obi_curve.groupby("obi_bin"), colors_obi):
            ax.plot(grp["delta"], grp[col], "o-", color=c, lw=2, ms=6, label=str(label))
        ax.axvline(HALF_SPREAD - 0.5, color="k", lw=1, ls=":", alpha=0.5)
        ax.set_xlabel("Ticks from mid (δ)")
        ax.set_ylabel("Fill probability")
        ax.set_title(title)
        ax.set_xticks(agg["delta"].values)
        ax.legend(fontsize=9); ax.grid(alpha=0.25)
    plt.tight_layout()
    fig.savefig(ANALYSIS_DIR / "fig2_fill_curve_obi.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved fig2_fill_curve_obi.png")

    # fig3: time-of-day conditioning
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Fill Probability by Trading Session", fontsize=13)
    colors_session = {"Asia": "#9C27B0", "Europe": "#1565C0", "US": "#E65100"}
    for ax_idx, col, title in [(0, "fill_price", "Price-Only Model"), (1, "fill_queue", "Queue-Aware Model")]:
        ax = axes[ax_idx]
        for session_name, grp in session_curve.groupby("session"):
            c = colors_session.get(session_name, "#333")
            ax.plot(grp["delta"], grp[col], "o-", color=c, lw=2, ms=6, label=session_name)
        ax.axvline(HALF_SPREAD - 0.5, color="k", lw=1, ls=":", alpha=0.5)
        ax.set_xlabel("Ticks from mid (δ)")
        ax.set_ylabel("Fill probability")
        ax.set_title(f"{title}\n[Asia 00-08h / Europe 08-16h / US 16-24h UTC]")
        ax.set_xticks(agg["delta"].values)
        ax.legend(fontsize=9); ax.grid(alpha=0.25)
    plt.tight_layout()
    fig.savefig(ANALYSIS_DIR / "fig3_fill_curve_session.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved fig3_fill_curve_session.png")

    # fig4: daily variation
    if len(daily_curves) > 1:
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        fig.suptitle("Fill Curve — Day-by-Day Stability", fontsize=13)
        dc_all = pd.concat(daily_curves)
        for ax_idx, col, title in [(0, "fill_price", "Price-Only"), (1, "fill_queue", "Queue-Aware")]:
            ax = axes[ax_idx]
            for date_str, grp in dc_all.groupby("date"):
                ax.plot(grp["delta"], grp[col], alpha=0.4, lw=1.0, label=date_str[5:])
            ax.plot(agg["delta"], agg[col], "k-", lw=2.5, label="Aggregate", zorder=5)
            ax.axvline(HALF_SPREAD - 0.5, color="#E65100", lw=1.5, ls=":", alpha=0.7)
            ax.set_xlabel("Ticks from mid (δ)")
            ax.set_ylabel("Fill probability")
            ax.set_title(title)
            ax.set_xticks(agg["delta"].values)
            ax.legend(fontsize=7, ncol=4); ax.grid(alpha=0.25)
        plt.tight_layout()
        fig.savefig(ANALYSIS_DIR / "fig4_daily_stability.png", dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved fig4_daily_stability.png")

    # Save summary JSON
    summary = {
        "n_days": len(dates),
        "dates": dates,
        "price_only": {"A": A_p, "kappa": kappa_p, "r2": r2_p},
        "queue_aware": {"A": A_q, "kappa": kappa_q, "r2": r2_q},
        "fill_curve_price": {int(r["delta"]): float(r["fill_price"]) for _, r in agg.iterrows()},
        "fill_curve_queue": {int(r["delta"]): float(r["fill_queue"]) for _, r in agg.iterrows()},
        "natural_spread_ticks": HALF_SPREAD * 2,
        "inside_fill_price": float(agg[agg["delta"] < HALF_SPREAD]["fill_price"].mean()),
        "at_touch_fill_price": float(agg[agg["delta"] == HALF_SPREAD]["fill_price"].iloc[0]),
        "outside_fill_price": float(agg[agg["delta"] > HALF_SPREAD]["fill_price"].mean()),
        "inside_fill_queue": float(agg[agg["delta"] < HALF_SPREAD]["fill_queue"].mean()),
        "at_touch_fill_queue": float(agg[agg["delta"] == HALF_SPREAD]["fill_queue"].iloc[0]),
    }
    with open(OUT_DIR / "fill_curve_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved fill_curve_summary.json")
    return agg, obi_curve, session_curve


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=5,
                        help="Number of April 2026 days to use")
    parser.add_argument("--plot", action="store_true", default=True)
    parser.add_argument("--no-plot", dest="plot", action="store_false")
    args = parser.parse_args()

    # Find available April 2026 dates
    ob_files = sorted(glob.glob(str(DATA_DIR / "orderbooks_LINK_2026-04-*.parquet")))
    dates = [Path(f).stem.replace("orderbooks_LINK_", "") for f in ob_files[:args.days]]
    print(f"Running fill curve analysis on {len(dates)} days: {dates[0]} → {dates[-1]}")
    run(dates, plot=args.plot)
