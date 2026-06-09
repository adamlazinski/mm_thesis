"""
Regime-conditional markout for the HONEST (outside-spread) passive-MM regime.
==============================================================================
Tests the one open question from the queue-priority verdict (contribution 30):
is there ANY regime in which honest (outside-natural-spread) passive fills have
POSITIVE 1s markout? If even the honest fills are adverse in every regime, the
thin-queue / regime-timing escape is closed and the negative MM result is final.

Input : experiments/53_link_spread_sweep/results_17p8_full/{date}_fills.parquet
        (the outside-spread 8t config, run with save_full=true)
Method: for each fill, compute 1s markout and tag it with
          - UTC hour
          - trailing-120s realized-vol tercile (low/med/high)
          - post-sweep flag: a large trade (>= p95 size) within the prior 5s
          - time-since-last-large-trade bucket
        then aggregate mean markout / %positive / count per regime cell.
Output: console tables + summary.json. Flags any positive cell with n >= 30.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hft_market_maker.data.loader import DataLoader  # noqa: E402

EXP   = Path(__file__).parent
FILLS = EXP / "results_17p8_full"
DATA  = ROOT / "data" / "real"
OUT   = EXP / "analysis"
OUT.mkdir(exist_ok=True)

MARKOUT_H   = 1.0     # seconds
VOL_WINDOW  = 120.0   # trailing seconds for realized vol
SWEEP_LOOKBACK = 5.0  # seconds — post-sweep window
MIN_N       = 30      # min fills for a regime cell to be trusted

loader = DataLoader()


def day_files(date_str):
    f = FILLS / f"{date_str}_fills.parquet"
    tr = DATA / f"trades_LINK_{date_str}.parquet"
    qu = DATA / f"quotes_LINK_{date_str}.parquet"
    return f, tr, qu


def collect():
    rows = []
    fill_files = sorted(FILLS.glob("*_fills.parquet"))
    if not fill_files:
        print(f"No fills found in {FILLS}. Run config_spread_17p8_full.json first.")
        sys.exit(1)

    for ff in fill_files:
        date_str = ff.name.replace("_fills.parquet", "")
        _, tr_p, qu_p = day_files(date_str)
        if not (tr_p.exists() and qu_p.exists()):
            print(f"  {date_str}: missing trade/quote data, skipping")
            continue

        fills = pd.read_parquet(ff)
        if fills.empty:
            continue

        trades, quotes = loader.load_coinapi(trades_path=str(tr_p),
                                             quotes_path=str(qu_p),
                                             timestamp_col="time_exchange")
        q_ts  = np.array([q.timestamp for q in quotes])
        q_mid = np.array([q.mid for q in quotes])
        t_ts  = np.array([t.timestamp for t in trades])
        t_sz  = np.array([t.quantity for t in trades])

        # Trailing realized-vol series on a 1s grid (log-return std over VOL_WINDOW)
        if len(q_ts) < 10:
            continue
        g0, g1 = q_ts[0], q_ts[-1]
        grid = np.arange(g0, g1, 1.0)
        gmid = np.interp(grid, q_ts, q_mid)
        logret = np.diff(np.log(gmid), prepend=np.log(gmid[0]))
        w = int(VOL_WINDOW)
        # rolling std via pandas
        sig = pd.Series(logret).rolling(w, min_periods=20).std().to_numpy()

        for _, fl in fills.iterrows():
            ft = float(fl["timestamp"])
            side = fl["side"]
            price = float(fl["price"])

            # 1s markout
            j = np.searchsorted(q_ts, ft + MARKOUT_H)
            if j >= len(q_mid):
                continue
            mid_fut = q_mid[j]
            sign = 1.0 if side == "bid" else -1.0
            mk = sign * (mid_fut / price - 1.0) * 1e4

            hour = datetime.fromtimestamp(ft, tz=timezone.utc).hour

            gi = min(max(int(ft - g0), 0), len(sig) - 1)
            vol = sig[gi]

            # post-sweep: largest trade in the prior SWEEP_LOOKBACK seconds
            k  = np.searchsorted(t_ts, ft)
            lo = np.searchsorted(t_ts, ft - SWEEP_LOOKBACK)
            window_sz = t_sz[lo:k]
            prior_max_sz = float(window_sz.max()) if window_sz.size else 0.0
            t_since = (ft - t_ts[k - 1]) if k > 0 else np.inf

            rows.append({
                "date": date_str, "ts": ft, "side": side, "markout": mk,
                "hour": hour, "vol": vol,
                "prior_max_sz": prior_max_sz,
                "t_since_trade": t_since,
            })
        print(f"  {date_str}: {len(fills)} fills processed")

    return pd.DataFrame(rows)


def report(df):
    # Global thresholds
    p95_sz = df["prior_max_sz"].quantile(0.95)
    df["post_sweep"] = df["prior_max_sz"] >= p95_sz
    df["vol_bucket"] = pd.qcut(df["vol"].fillna(df["vol"].median()),
                               3, labels=["low", "med", "high"], duplicates="drop")

    def agg(g):
        return pd.Series({
            "mean_markout_bps": g["markout"].mean(),
            "pct_positive": (g["markout"] > 0).mean() * 100,
            "n": len(g),
        })

    print("\n" + "=" * 70)
    print(f"OVERALL: mean markout = {df['markout'].mean():.3f} bps | "
          f"%positive = {(df['markout']>0).mean()*100:.1f}% | n = {len(df)}")
    print("=" * 70)

    results = {"overall": {
        "mean_markout_bps": float(df["markout"].mean()),
        "pct_positive": float((df["markout"] > 0).mean() * 100),
        "n": int(len(df)),
        "p95_sweep_size_LINK": float(p95_sz),
    }}

    print("\n--- BY UTC HOUR ---")
    by_hr = df.groupby("hour").apply(agg)
    print(by_hr.to_string(float_format=lambda x: f"{x:.3f}"))
    results["by_hour"] = by_hr.reset_index().to_dict("records")

    print("\n--- BY VOL TERCILE ---")
    by_vol = df.groupby("vol_bucket", observed=True).apply(agg)
    print(by_vol.to_string(float_format=lambda x: f"{x:.3f}"))
    results["by_vol"] = by_vol.reset_index().to_dict("records")

    print("\n--- BY POST-SWEEP (large trade >= p95 in prior 5s) ---")
    by_sw = df.groupby("post_sweep").apply(agg)
    print(by_sw.to_string(float_format=lambda x: f"{x:.3f}"))
    results["by_sweep"] = by_sw.reset_index().to_dict("records")

    print("\n--- VOL x POST-SWEEP CROSS ---")
    by_x = df.groupby(["vol_bucket", "post_sweep"], observed=True).apply(agg)
    print(by_x.to_string(float_format=lambda x: f"{x:.3f}"))
    results["by_vol_sweep"] = by_x.reset_index().to_dict("records")

    # The verdict: any positive cell with n >= MIN_N?
    print("\n" + "=" * 70)
    print(f"POSITIVE-MARKOUT REGIME CELLS (n >= {MIN_N}):")
    positives = []
    for label, table in [("hour", by_hr), ("vol", by_vol),
                         ("sweep", by_sw), ("vol×sweep", by_x)]:
        for idx, r in table.iterrows():
            if r["mean_markout_bps"] > 0 and r["n"] >= MIN_N:
                positives.append((label, idx, r["mean_markout_bps"], int(r["n"])))
    if positives:
        for lab, idx, mk, n in positives:
            print(f"  [{lab}] {idx}: +{mk:.3f} bps (n={n})")
    else:
        print("  NONE. Every regime cell with sufficient n has NEGATIVE markout.")
        print("  => thin-queue / regime-timing escape is CLOSED. MM negative is final.")
    print("=" * 70)
    results["positive_cells"] = [
        {"dim": l, "bucket": str(i), "markout": float(m), "n": n}
        for l, i, m, n in positives
    ]

    with open(OUT / "honest_markout_by_regime.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved -> {OUT / 'honest_markout_by_regime.json'}")


if __name__ == "__main__":
    df = collect()
    if df.empty:
        print("No fills collected.")
        sys.exit(1)
    report(df)
