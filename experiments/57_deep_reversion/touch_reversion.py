"""
Touch-based deep-limit reversion — robustness check for conditional_reversion.py
================================================================================
The grid study (conditional_reversion.py) conditions on displacement SUSTAINED at
exactly t: disp = mid(t) - mid(t-DT). That censors wick fills — price touches the
level and reverts within the window — which would have filled a real resting limit
PROFITABLY but get filed in the shallow bin. Deep-bin adversity is therefore
overstated by construction (fill-time censoring; see defense_audit.md §3.5).

This study removes the censoring by simulating the actual limit-order event:

  At each placement time p (1s grid), a limit rests X ticks from mid(p) for DT=30s.
  FILL = first time tau in (p, p+DT] the 250ms-grid mid touches the level
         (running-extremum crossing — wicks count, at the limit price, as they
          would for a real resting order; no slippage for passive fills).
  PnL  = reversion from the FILL time at the FILL price:
         long  (bid X below): (mid(tau+HOLD) - level)/tick
         short (ask X above): (level - mid(tau+HOLD))/tick

State at FILL (what a guardrail could act on just before/at the fill):
  vol       : trailing-VOLWIN realized-vol tercile at tau
  ofi_state : OFI over [tau-DT, tau] vs the direction of the move that reached us
              (aligned+strong = informed continuation; opposed/weak = noise)

Caveats kept symmetric with the grid study: placements overlap (1s spacing,
30s windows) so n is inflated ~30x — conclusions rest on means/monotonicity,
not t-stats. Mid-touch (not trade-print) is used as the fill trigger, which is
mildly OPTIMISTIC for the strategy (a mid touch does not guarantee a print at
the level) — safe given the hypothesis under test is the strategy's viability.

Usage:
    python experiments/57_deep_reversion/touch_reversion.py --symbol LINK
    python experiments/57_deep_reversion/touch_reversion.py --symbol BTC
"""
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/57_deep_reversion/analysis")

GRID     = 0.25      # fill-detection resolution (s)
PLACE_DT = 1.0       # placement spacing (s)
DT       = 30.0      # limit lifetime (s)
HOLD     = 60.0      # reversion holding horizon after fill (s)
VOLWIN   = 120.0
OFI_THR  = 0.3
DEPTHS   = [10, 20, 50, 100, 200, 500]   # ticks from mid at placement

W  = int(DT / GRID)
HW = int(HOLD / GRID)


def dates_for(symbol):
    td = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / f"trades_{symbol}_*.parquet"))}
    qd = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / f"quotes_{symbol}_*.parquet"))}
    return sorted(td & qd)


def load_day(symbol, date):
    q = pd.read_parquet(DATA_DIR / f"quotes_{symbol}_{date}.parquet",
                        columns=["time_exchange", "ask_price", "bid_price"])
    qts = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qmid = (q["ask_price"].to_numpy() + q["bid_price"].to_numpy()) / 2.0
    t = pd.read_parquet(DATA_DIR / f"trades_{symbol}_{date}.parquet",
                        columns=["time_exchange", "size", "taker_side"])
    tts = t["time_exchange"].astype("int64").to_numpy() / 1e9
    tqty = t["size"].to_numpy()
    tside = t["taker_side"].astype(str).to_numpy()
    return qts, qmid, tts, tqty, tside


def day_events(symbol, date, tick):
    qts, qmid, tts, tqty, tside = load_day(symbol, date)
    if len(qts) < 100:
        return None, 0
    g = np.arange(np.ceil(qts[0]), np.floor(qts[-1]), GRID)
    if len(g) < W + HW + 200:
        return None, 0
    M = qmid[np.clip(np.searchsorted(qts, g, side="right") - 1, 0, len(qmid) - 1)]

    # trailing realized vol on the grid (tick-returns std)
    r = np.diff(M, prepend=M[0]) / tick
    vol = pd.Series(r).rolling(int(VOLWIN / GRID), min_periods=40).std().to_numpy()

    # OFI cumsums from trades (signed volume imbalance over a trailing DT window)
    low = np.char.lower(tside.astype(str))
    buy  = np.where(low == "buy",  tqty, 0.0)
    sell = np.where(low == "sell", tqty, 0.0)
    cb = np.concatenate([[0.0], np.cumsum(buy)])
    cs = np.concatenate([[0.0], np.cumsum(sell)])

    def ofi_at(times):
        hi = np.searchsorted(tts, times, side="right")
        lo = np.searchsorted(tts, times - DT, side="right")
        b = cb[hi] - cb[lo]; s = cs[hi] - cs[lo]
        return (b - s) / (b + s + 1e-9)

    step = int(PLACE_DT / GRID)
    p_idx = np.arange(0, len(g) - (W + HW + 1), step)
    sw = sliding_window_view(M, W)          # window starting at each grid index
    win = sw[p_idx + 1]                     # (n_placements, W) — (p, p+DT]

    frames = []
    for X in DEPTHS:
        for side in ("long", "short"):
            if side == "long":              # bid X ticks below mid(p)
                level = M[p_idx] - X * tick
                hitmat = win <= level[:, None] + 1e-12
            else:                           # ask X ticks above mid(p)
                level = M[p_idx] + X * tick
                hitmat = win >= level[:, None] - 1e-12
            filled = hitmat.any(axis=1)
            if not filled.any():
                continue
            first = hitmat[filled].argmax(axis=1)       # first touch in window
            tau = p_idx[filled] + 1 + first
            lev = level[filled]
            exit_m = M[tau + HW]
            pnl = ((exit_m - lev) if side == "long" else (lev - exit_m)) / tick

            tfill = g[tau]
            o = ofi_at(tfill)
            move_sign = -1.0 if side == "long" else 1.0  # move direction that reached us
            aligned = np.sign(o) == move_sign
            strong = np.abs(o) >= OFI_THR
            state = np.where(aligned & strong, "aligned_strong",
                     np.where(~aligned & strong, "opposed_strong", "weak"))
            frames.append(pd.DataFrame({
                "date": date, "depth": X, "side": side, "pnl": pnl,
                "ttf": (first + 1) * GRID, "vol": vol[tau], "ofi_state": state,
            }))
    if not frames:
        return None, len(p_idx)
    return pd.concat(frames, ignore_index=True), len(p_idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="LINK")
    ap.add_argument("--tick", type=float, default=None)
    ap.add_argument("--days", type=int, default=999)
    args = ap.parse_args()
    tick = args.tick if args.tick is not None else (0.01 if args.symbol.startswith("BTC") else 0.001)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dates = dates_for(args.symbol)[: args.days]
    print(f"Touch-based reversion — {args.symbol} (tick={tick}), {len(dates)} days, "
          f"DT={DT}s hold={HOLD}s, depths={DEPTHS}t")
    frames, n_place_total = [], 0
    for d in dates:
        try:
            e, n_p = day_events(args.symbol, d, tick)
            n_place_total += n_p
            if e is not None:
                frames.append(e)
                print(f"  {d}: {n_p:,} placements, {len(e):,} fills")
        except Exception as ex:
            print(f"  {d}: ERROR {ex}")
    df = pd.concat(frames, ignore_index=True)
    n_days = df["date"].nunique()
    df["volb"] = pd.qcut(df["vol"].fillna(df["vol"].median()), 3,
                         labels=["loV", "medV", "hiV"], duplicates="drop")

    def tab(group_cols, title):
        print(f"\n{'='*78}\n{title}\n{'='*78}")
        g = df.groupby(group_cols, observed=True)["pnl"]
        out = g.agg(mean="mean", p_profit=lambda x: (x > 0).mean()*100,
                    p5=lambda x: np.percentile(x, 5), n="count")
        out = out[out["n"] >= 50]
        if group_cols == ["depth"]:
            out["fills_per_day"] = out["n"] / n_days
            out["fill_rate_pct"] = out["n"] / 2 / max(n_place_total, 1) * 100
            out["mean_ttf_s"] = df.groupby(group_cols, observed=True)["ttf"].mean()
        with pd.option_context("display.float_format", lambda v: f"{v:.1f}"):
            print(out.to_string())
        return out

    print("\nReversion PnL in TICKS from the FILL price (wicks fill — no censoring).")
    t_depth = tab(["depth"], "Q1 — BY DEPTH (touch-based fills)")
    t_dv = tab(["depth", "volb"], "Q2a — DEPTH x VOL REGIME at fill")
    t_do = tab(["depth", "ofi_state"], "Q2b — DEPTH x OFI-ALIGNMENT at fill")

    res = {"symbol": args.symbol, "tick": tick, "DT": DT, "HOLD": HOLD,
           "grid": GRID, "depths": DEPTHS, "n_placements": int(n_place_total),
           "by_depth": json.loads(t_depth.reset_index().to_json(orient="records")),
           "by_depth_vol": json.loads(t_dv.reset_index().to_json(orient="records")),
           "by_depth_ofi": json.loads(t_do.reset_index().to_json(orient="records"))}
    with open(OUT_DIR / f"touch_reversion_{args.symbol}.json", "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nSaved -> {OUT_DIR / f'touch_reversion_{args.symbol}.json'}")


if __name__ == "__main__":
    main()
