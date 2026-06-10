"""
BTC taker — selectivity & conviction sweep (get more per trade).
================================================================
The latency-aware feasibility test showed momentum/OBI beat spread+latency but
the per-trade edge is sub-bps — far below realistic taker fees. This sweeps the
levers that increase edge PER TRADE:

  SELECTIVITY: raise the |signal| percentile threshold (p90 -> p99 -> p99.9).
               Bigger predicted move per trade, fewer trades.
  CONVICTION : require momentum AND OBI to agree in sign (confluence).
  HOLD       : extend to 30/60s (edge grew with hold in the feasibility test).

Reports per-trade edge in BPS and NET of a configurable round-trip taker fee,
plus trades/day. Goal: find the (signal, selectivity, hold) where net-of-fee
edge turns positive, and see how many trades survive.

Cost model: round trip crosses both ways (buy ask, sell bid) at t+LATENCY and
t+LATENCY+hold — spread + latency slippage emerge from real fills. Fees added
on top as bps (perp ~3.6 bps RT; spot ~15 bps RT).

Usage:
    python experiments/55_taker_feasibility/btc_taker_selectivity.py --days 43
"""
from __future__ import annotations
import argparse, glob, json, re, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/55_taker_feasibility/analysis")
TICK     = 0.01
LATENCY  = 0.10
EVAL_DT  = 0.25
MOM_WIN  = 1.0
HOLDS    = [10, 30, 60]
PCTLS    = [90.0, 99.0, 99.9]
PERP_FEE_BPS = 3.6     # round-trip taker fee, perp (≈1.8 bps/side)
SPOT_FEE_BPS = 15.0    # round-trip taker fee, spot (≈7.5 bps/side)


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
    return (ts, q["bid_price"].to_numpy(), q["ask_price"].to_numpy(),
            q["bid_size"].to_numpy(), q["ask_size"].to_numpy())


def px_at(ts, arr, t):
    idx = np.searchsorted(ts, t, side="right") - 1
    valid = idx >= 0
    out = arr[np.clip(idx, 0, len(arr) - 1)].astype(float)
    out[~valid] = np.nan
    return out


def roundtrip_ticks(ts, bid, ask, t_eval, dirn, hold):
    te = t_eval + LATENCY; tx = te + hold
    ea = px_at(ts, ask, te); eb = px_at(ts, bid, te)
    xa = px_at(ts, ask, tx); xb = px_at(ts, bid, tx)
    pnl = np.where(dirn > 0, xb - ea,
                   np.where(dirn < 0, eb - xa, np.nan))
    return pnl / TICK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=43)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dates = all_dates()[: args.days]
    print(f"BTC selectivity sweep on {len(dates)} days | latency={LATENCY*1000:.0f}ms")

    rows = []
    for d in dates:
        try:
            ts, bid, ask, bsz, asz = load_quotes(d)
            mid = (bid + ask) / 2.0
            g = np.arange(np.ceil(ts[0]) + MOM_WIN + 1,
                          np.floor(ts[-1]) - max(HOLDS) - 1, EVAL_DT)
            if len(g) < 100:
                print(f"  {d}: skip"); continue
            mid_now = px_at(ts, mid, g)
            mom = (mid_now - px_at(ts, mid, g - MOM_WIN)) / TICK
            bn = px_at(ts, bsz, g); an = px_at(ts, asz, g)
            den = bn + an
            obi = np.where(den > 0, (bn - an) / den, 0.0)
            mid_px = np.nanmean(mid_now)
            tick_to_bps = TICK / mid_px * 1e4

            amom = np.abs(mom); aobi = np.abs(obi)
            finite = np.isfinite(amom) & np.isfinite(aobi)
            # percentile thresholds per day
            mom_thr = {p: np.nanpercentile(amom[finite], p) for p in PCTLS}
            obi_thr = {p: np.nanpercentile(aobi[finite], p) for p in PCTLS}

            pnl_cache = {h: {} for h in HOLDS}
            for h in HOLDS:
                pnl_cache[h]["momentum"] = roundtrip_ticks(ts, bid, ask, g, np.sign(mom), h)
                pnl_cache[h]["obi"] = roundtrip_ticks(ts, bid, ask, g, np.sign(obi), h)
                # confluence: trade only when signs agree; direction = that sign
                agree = (np.sign(mom) == np.sign(obi)) & (np.sign(mom) != 0)
                cdir = np.where(agree, np.sign(mom), 0.0)
                pnl_cache[h]["conf"] = roundtrip_ticks(ts, bid, ask, g, cdir, h)

            day_secs = (g[-1] - g[0])
            for p in PCTLS:
                masks = {
                    "momentum": finite & (amom >= mom_thr[p]),
                    "obi":      finite & (aobi >= obi_thr[p]),
                    "conf":     finite & (amom >= mom_thr[p]) & (aobi >= obi_thr[p])
                                & (np.sign(mom) == np.sign(obi)),
                }
                for sig, m in masks.items():
                    for h in HOLDS:
                        p_arr = pnl_cache[h][sig][m]
                        p_arr = p_arr[np.isfinite(p_arr)]
                        if len(p_arr) == 0:
                            continue
                        # trades/day: count, but cap by non-overlap (hold spacing)
                        tn = len(p_arr)
                        rows.append({
                            "date": d, "signal": sig, "pctl": p, "hold": h,
                            "mean_ticks": float(p_arr.mean()),
                            "mean_bps": float(p_arr.mean() * tick_to_bps),
                            "win": float((p_arr > 0).mean() * 100),
                            "signals_per_day": int(tn),
                            # max independent trades if held serially (no overlap)
                            "max_indep_trades": float(day_secs / h),
                        })
            print(f"  {d}: {len(g):,} grid pts")
        except Exception as e:
            print(f"  {d}: ERROR {e}")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_DIR / "btc_taker_selectivity.parquet")

    print("\n" + "=" * 92)
    print("PER-TRADE EDGE vs SELECTIVITY  (mean across days; gross + net of fees, bps)")
    print(f"perp RT fee={PERP_FEE_BPS}bps, spot RT fee={SPOT_FEE_BPS}bps")
    print("=" * 92)
    hdr = (f"{'signal':>9} {'pctl':>6} {'hold':>5} | {'gross bps':>9} | "
           f"{'net perp':>9} | {'net spot':>9} | {'win%':>5} | {'signals/day':>11}")
    print(hdr); print("-" * len(hdr))
    for sig in ["momentum", "obi", "conf"]:
        for p in PCTLS:
            for h in HOLDS:
                s = df[(df.signal == sig) & (df.pctl == p) & (df.hold == h)]
                if s.empty:
                    continue
                g_bps = s.mean_bps.mean()
                print(f"{sig:>9} {p:>6} {h:>4}s | {g_bps:>+8.3f} | "
                      f"{g_bps-PERP_FEE_BPS:>+8.3f} | {g_bps-SPOT_FEE_BPS:>+8.3f} | "
                      f"{s.win.mean():>4.0f}% | {s.signals_per_day.mean():>11.0f}")
    df.to_csv(OUT_DIR / "btc_taker_selectivity.csv", index=False)
    print(f"\nSaved -> {OUT_DIR / 'btc_taker_selectivity.parquet'} (+ .csv)")
    print("NOTE: signals/day = top-pctl evals (overlapping). max independent trades")
    print("at hold h ~ 86400/h. Net-of-fee uses gross per-trade bps minus RT fee.")


if __name__ == "__main__":
    main()
