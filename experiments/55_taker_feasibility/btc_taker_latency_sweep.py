"""
BTC taker — latency sweep (is latency the binding constraint?).
===============================================================
The selectivity sweep showed the per-trade edge caps at ~1 bps and does not
grow with signal strength — consistent with 100ms latency eating the move
before we fill. This sweeps LATENCY (10ms -> 500ms) for the OBI and confluence
signals to quantify how much edge latency destroys. If edge is large at 10ms
and ~1 bps at 100ms, latency is the binding constraint — the taker analog of
the queue-priority rent (only a co-located player captures it).

Fixed: top-decile signal, hold=10s, cost emerges from real ask/bid fills.

Usage:
    python experiments/55_taker_feasibility/btc_taker_latency_sweep.py --days 43
"""
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/55_taker_feasibility/analysis")
TICK     = 0.01
EVAL_DT  = 0.25
MOM_WIN  = 1.0
HOLD     = 10.0
LATENCIES = [0.01, 0.025, 0.05, 0.1, 0.2, 0.5]
PCTL     = 90.0
PERP_FEE_BPS = 3.6


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
    ts = q["time_exchange"].astype("int64").to_numpy() / 1e9
    return (ts, q["bid_price"].to_numpy(), q["ask_price"].to_numpy(),
            q["bid_size"].to_numpy(), q["ask_size"].to_numpy())


def px_at(ts, arr, t):
    idx = np.searchsorted(ts, t, side="right") - 1
    valid = idx >= 0
    out = arr[np.clip(idx, 0, len(arr) - 1)].astype(float)
    out[~valid] = np.nan
    return out


def rt(ts, bid, ask, te_grid, dirn, lat, hold):
    te = te_grid + lat; tx = te + hold
    ea = px_at(ts, ask, te); eb = px_at(ts, bid, te)
    xa = px_at(ts, ask, tx); xb = px_at(ts, bid, tx)
    return np.where(dirn > 0, xb - ea, np.where(dirn < 0, eb - xa, np.nan)) / TICK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=43)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dates = all_dates()[: args.days]
    print(f"BTC latency sweep on {len(dates)} days | hold={HOLD}s, top {PCTL}pctl")

    rows = []
    for d in dates:
        try:
            ts, bid, ask, bsz, asz = load_quotes(d)
            mid = (bid + ask) / 2.0
            g = np.arange(np.ceil(ts[0]) + MOM_WIN + 1,
                          np.floor(ts[-1]) - HOLD - max(LATENCIES) - 1, EVAL_DT)
            if len(g) < 100:
                continue
            mid_now = px_at(ts, mid, g)
            mom = (mid_now - px_at(ts, mid, g - MOM_WIN)) / TICK
            bn = px_at(ts, bsz, g); an = px_at(ts, asz, g)
            den = bn + an
            obi = np.where(den > 0, (bn - an) / den, 0.0)
            tick_to_bps = TICK / np.nanmean(mid_now) * 1e4

            amom = np.abs(mom); aobi = np.abs(obi)
            fin = np.isfinite(amom) & np.isfinite(aobi)
            obi_mask = fin & (aobi >= np.nanpercentile(aobi[fin], PCTL))
            conf_mask = (fin & (amom >= np.nanpercentile(amom[fin], PCTL))
                         & (aobi >= np.nanpercentile(aobi[fin], PCTL))
                         & (np.sign(mom) == np.sign(obi)))
            cdir = np.where(np.sign(mom) == np.sign(obi), np.sign(mom), 0.0)

            for lat in LATENCIES:
                po = rt(ts, bid, ask, g, np.sign(obi), lat, HOLD)[obi_mask]
                pc = rt(ts, bid, ask, g, cdir, lat, HOLD)[conf_mask]
                po = po[np.isfinite(po)]; pc = pc[np.isfinite(pc)]
                if len(po):
                    rows.append({"date": d, "signal": "obi", "lat_ms": lat*1000,
                                 "bps": float(po.mean()*tick_to_bps),
                                 "win": float((po > 0).mean()*100)})
                if len(pc):
                    rows.append({"date": d, "signal": "conf", "lat_ms": lat*1000,
                                 "bps": float(pc.mean()*tick_to_bps),
                                 "win": float((pc > 0).mean()*100)})
            print(f"  {d}: {len(g):,} grid pts")
        except Exception as e:
            print(f"  {d}: ERROR {e}")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_DIR / "btc_taker_latency_sweep.parquet")
    print("\n" + "=" * 64)
    print(f"EDGE vs LATENCY  (gross bps/trade, hold={HOLD}s, top {PCTL}pctl)")
    print(f"perp round-trip fee = {PERP_FEE_BPS} bps")
    print("=" * 64)
    print(f"{'signal':>8} {'latency':>9} | {'gross bps':>9} | {'net perp':>9} | {'win%':>5}")
    print("-" * 50)
    for sig in ["obi", "conf"]:
        for lat in LATENCIES:
            s = df[(df.signal == sig) & (df.lat_ms == lat*1000)]
            if s.empty:
                continue
            g_bps = s.bps.mean()
            print(f"{sig:>8} {lat*1000:>7.0f}ms | {g_bps:>+8.3f} | "
                  f"{g_bps-PERP_FEE_BPS:>+8.3f} | {s.win.mean():>4.0f}%")
    df.to_csv(OUT_DIR / "btc_taker_latency_sweep.csv", index=False)
    print(f"\nSaved -> {OUT_DIR / 'btc_taker_latency_sweep.parquet'} (+ .csv)")


if __name__ == "__main__":
    main()
