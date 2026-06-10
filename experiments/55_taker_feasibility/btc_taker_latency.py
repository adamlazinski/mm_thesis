"""
BTC spot taker feasibility — tick-resolution, latency-aware round trips.
========================================================================
Honest taker economics using the full HF data + 100ms latency:

  signal at t (from data <= t)  ->  send order at t
  ENTRY fills at t+LATENCY at the ACTUAL ask (long) / bid (short)   [cross]
  EXIT  crosses back at t+LATENCY+HOLD at the ACTUAL bid (long) / ask (short)
  pnl_ticks = (exit_fill - entry_fill)/TICK   (signed by signal direction)

The spread cost and the latency slippage both EMERGE from real bid/ask fills —
no hardcoded cost. On a 1-tick book with no move, a round trip costs exactly
1 tick (buy ask, sell bid); if price runs during the 100ms latency, the entry
is already worse = latency adverse selection, the thing we want to measure.

Signals (all computed from data available at t):
  MOMENTUM   dir = sign(mid(t) - mid(t-W));  top |trailing| decile = strong mom.
  OBI        dir = sign(bid_size - ask_size) at t; top |OBI| decile.
  OVERSHOOT  at each large trade (size>=p95) in high vol: dir = -sign(taker_side).

Eval on a fine grid (default 250ms) to honor sub-second structure; fills use the
RAW quote stream at the exact latency-adjusted times.

Usage:
    python experiments/55_taker_feasibility/btc_taker_latency.py --days 43
"""
from __future__ import annotations
import argparse, glob, json, re, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/55_taker_feasibility/analysis")
TICK     = 0.01
LATENCY  = 0.10                 # seconds — order send -> fill
EVAL_DT  = 0.25                 # signal evaluation grid (s)
MOM_WIN  = 1.0                  # trailing momentum window (s)
HOLDS    = [0.5, 1, 2, 5, 10]   # post-latency hold (s)
VOL_WIN  = 60.0
SWEEP_PCTL = 0.95


def all_dates():
    td = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / "trades_BTC_*.parquet"))}
    qd = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / "quotes_BTC_*.parquet"))}
    return sorted(td & qd)


def load_quotes(date):
    q = pd.read_parquet(DATA_DIR / f"quotes_BTC_{date}.parquet",
                        columns=["time_exchange", "ask_price", "bid_price",
                                 "ask_size", "bid_size"])
    ts  = q["time_exchange"].astype("int64").to_numpy() / 1e9
    ask = q["ask_price"].to_numpy(); bid = q["bid_price"].to_numpy()
    asz = q["ask_size"].to_numpy();  bsz = q["bid_size"].to_numpy()
    return ts, bid, ask, bsz, asz


def px_at(ts, arr, t):
    """Value of arr at the last quote with timestamp <= t (vectorized over t)."""
    idx = np.searchsorted(ts, t, side="right") - 1
    valid = idx >= 0
    idx = np.clip(idx, 0, len(arr) - 1)
    out = arr[idx].astype(float)
    out[~valid] = np.nan
    return out


def roundtrip_ticks(ts, bid, ask, t_eval, dirn, hold):
    """
    Latency-aware taker round trip, signed by dirn (+1 long, -1 short).
    Entry at t_eval+LATENCY (cross), exit at t_eval+LATENCY+hold (cross back).
    Returns pnl in ticks (NaN where prices unavailable / dir==0).
    """
    te = t_eval + LATENCY
    tx = te + hold
    entry_ask = px_at(ts, ask, te)   # buy fills at ask
    entry_bid = px_at(ts, bid, te)   # sell fills at bid
    exit_ask  = px_at(ts, ask, tx)
    exit_bid  = px_at(ts, bid, tx)
    pnl = np.where(
        dirn > 0, (exit_bid - entry_ask),          # long: buy ask, sell bid
        np.where(dirn < 0, (entry_bid - exit_ask),  # short: sell bid, buy ask
                 np.nan))
    return pnl / TICK


def eval_grid(ts):
    return np.arange(np.ceil(ts[0]) + MOM_WIN + 1, np.floor(ts[-1]) - max(HOLDS) - 1,
                     EVAL_DT)


def regime_of(date):
    if date.startswith("2025-05"):
        return "May2025"
    if date.startswith("2025-06") or date.startswith("2025-07"):
        return "JunJul2025"
    return "Apr2026"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=43)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    dates = all_dates()[: args.days]
    print(f"BTC latency-aware taker on {len(dates)} days "
          f"({dates[0]} -> {dates[-1]}) | latency={LATENCY*1000:.0f}ms")

    # Per-DAY top-decile mean round-trip PnL (ticks) for each signal+hold.
    # Treating each day as one observation blunts the overlapping-positions
    # inflation and exposes regime dependence.
    # rows: list of {date, regime, signal, hold, mean_ticks, win, n}
    rows = []

    def day_topdecile(sig, pnl_by_hold, dirn, label, date):
        asig = np.abs(sig); fin = np.isfinite(asig)
        thr = np.nanquantile(asig[fin], 0.9)
        mask = fin & (asig >= thr)
        for h in HOLDS:
            p = pnl_by_hold[h][mask]; p = p[np.isfinite(p)]
            if len(p) == 0:
                continue
            rows.append({"date": date, "regime": regime_of(date), "signal": label,
                         "hold": h, "mean_ticks": float(p.mean()),
                         "win": float((p > 0).mean() * 100), "n": int(len(p))})

    for d in dates:
        try:
            ts, bid, ask, bsz, asz = load_quotes(d)
            mid = (bid + ask) / 2.0
            g = eval_grid(ts)
            if len(g) < 100:
                print(f"  {d}: too few grid pts, skip"); continue

            mid_now  = px_at(ts, mid, g)
            mid_prev = px_at(ts, mid, g - MOM_WIN)
            mom_sig  = (mid_now - mid_prev) / TICK
            bsz_now  = px_at(ts, bsz, g); asz_now = px_at(ts, asz, g)
            den = bsz_now + asz_now
            obi_sig = np.where(den > 0, (bsz_now - asz_now) / den, 0.0)

            rand_dir = rng.choice([-1.0, 1.0], size=len(g))   # control direction

            mom_pnl, obi_pnl, rnd_pnl = {}, {}, {}
            for h in HOLDS:
                mom_pnl[h] = roundtrip_ticks(ts, bid, ask, g, np.sign(mom_sig), h)
                obi_pnl[h] = roundtrip_ticks(ts, bid, ask, g, np.sign(obi_sig), h)
                rnd_pnl[h] = roundtrip_ticks(ts, bid, ask, g, rand_dir, h)

            day_topdecile(mom_sig, mom_pnl, None, "momentum", d)
            day_topdecile(obi_sig, obi_pnl, None, "obi", d)
            # control: random direction at the top-|momentum| points
            day_topdecile(mom_sig, rnd_pnl, None, "random_ctrl", d)

            # overshoot: large trades in high vol, fade
            t = pd.read_parquet(DATA_DIR / f"trades_BTC_{d}.parquet",
                                columns=["time_exchange", "size", "taker_side"])
            tts = t["time_exchange"].astype("int64").to_numpy() / 1e9
            tsz = t["size"].to_numpy()
            tside = t["taker_side"].astype(str).to_numpy()
            thr = np.quantile(tsz, SWEEP_PCTL)
            r = np.diff(mid_now, prepend=mid_now[0])
            gvol = pd.Series(r).rolling(int(VOL_WIN / EVAL_DT), min_periods=10).std().to_numpy()
            volhi = np.nanmedian(gvol)
            big = tts[tsz >= thr]; big_side = tside[tsz >= thr]
            vi = np.clip(np.searchsorted(g, big) - 1, 0, len(gvol) - 1)
            keep = gvol[vi] >= volhi
            big = big[keep]; big_side = big_side[keep]
            fade = np.where(np.char.lower(big_side.astype(str)) == "buy", -1.0, 1.0)
            for h in HOLDS:
                p = roundtrip_ticks(ts, bid, ask, big, fade, h)
                p = p[np.isfinite(p)]
                if len(p):
                    rows.append({"date": d, "regime": regime_of(d),
                                 "signal": "overshoot_fade", "hold": h,
                                 "mean_ticks": float(p.mean()),
                                 "win": float((p > 0).mean() * 100), "n": int(len(p))})

            print(f"  {d}: {len(g):,} grid pts, {len(big):,} hi-vol sweeps")
        except Exception as e:
            print(f"  {d}: ERROR {e}")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_DIR / "btc_taker_perday.parquet")

    def show(scope_df, title):
        print(f"\n{'='*78}\n{title}\n{'='*78}")
        print(f"  {'signal':>14} | {'hold':>5} | {'mean/day(ticks)':>15} | "
              f"{'std/day':>8} | {'days>0':>7} | {'win%':>6}")
        for signame in ["momentum", "obi", "random_ctrl", "overshoot_fade"]:
            for h in HOLDS:
                sub = scope_df[(scope_df.signal == signame) & (scope_df.hold == h)]
                if sub.empty:
                    continue
                m = sub.mean_ticks.mean(); s = sub.mean_ticks.std()
                dpos = (sub.mean_ticks > 0).mean() * 100; win = sub.win.mean()
                print(f"  {signame:>14} | {h:>4}s | {m:>15.2f} | {s:>8.2f} | "
                      f"{dpos:>6.0f}% | {win:>5.1f}%")

    print("\n### Per-day top-decile mean round-trip PnL (ticks), averaged across days")
    show(df, "OVERALL (all regimes)")
    for reg in ["May2025", "JunJul2025", "Apr2026"]:
        sub = df[df.regime == reg]
        if not sub.empty:
            show(sub, f"REGIME: {reg}  ({sub.date.nunique()} days)")

    print("\nNOTE: 'random_ctrl' = random direction at the SAME top-|momentum| points.")
    print("If a real-signal mean >> random_ctrl, the edge is direction prediction,")
    print("not selection/timing. Per-day means blunt the overlapping-position inflation.")
    df.to_csv(OUT_DIR / "btc_taker_perday.csv", index=False)
    print(f"Saved -> {OUT_DIR / 'btc_taker_perday.parquet'} (+ .csv)")


if __name__ == "__main__":
    main()
