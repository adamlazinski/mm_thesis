"""
Taker feasibility check — LINK perp, OBI-conditional forward mid-move vs cost.
=============================================================================
The go/no-go gate for the maker->taker pivot, computed directly (no backtest,
no trade stream needed — orderbook mid + L1 sizes only).

Logic: a taker who reads OBI and crosses the spread in the predicted direction
profits only if the signal-conditional forward mid-move exceeds the round-trip
crossing cost. For a 1-tick-spread venue:
    enter by crossing (~0.5 tick from mid) + exit by crossing (~0.5 tick)
    => round-trip cost ~= 1 tick = $0.001 ~= 1.11 bps at $9.

We bucket observations by |OBI| decile and, for each forward horizon, measure
the SIGNED move in the OBI-predicted direction:
    signed_move = sign(OBI) * (mid(t+h) - mid(t))
reported in ticks and bps, with hit rate and net-of-1-tick edge. If the top
|OBI| decile's signed move clears ~1 tick within some horizon, the taker edge
is real on the perp (before fees).

Usage:
    python experiments/54_link_perp_micro/taker_feasibility_perp.py \
        --symbol LINK_PERP --days 30 --start 2026-04-01
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/54_link_perp_micro/analysis")
TICK     = 0.001
HORIZONS = [0.5, 1, 2, 5, 10, 30]   # seconds
ROUNDTRIP_TICKS = 1.0               # enter-cross + exit-cross on a 1-tick spread


def load_day(ob_path: str):
    """Return ts, mid, obi_l1 arrays for one day from orderbook snapshots."""
    ob = pq.read_table(ob_path).to_pandas()
    ts = ob["time_exchange"].astype("int64").to_numpy() / 1e9
    bids = ob["bids"].to_numpy()
    asks = ob["asks"].to_numpy()
    n = len(ob)
    bb = np.empty(n); ba = np.empty(n)
    bsz = np.empty(n); asz = np.empty(n)
    for i in range(n):
        b0 = bids[i][0]; a0 = asks[i][0]
        bb[i] = b0["price"]; bsz[i] = b0["size"]
        ba[i] = a0["price"]; asz[i] = a0["size"]
    mid = (bb + ba) / 2.0
    denom = bsz + asz
    obi = np.where(denom > 0, (bsz - asz) / denom, 0.0)
    return ts, mid, obi


def collect(symbol, days, start):
    obis = []
    moves = {h: [] for h in HORIZONS}   # signed move in TICKS
    d = date.fromisoformat(start)
    n_done = 0
    while n_done < days:
        ds = d.strftime("%Y-%m-%d")
        p = DATA_DIR / f"orderbooks_{symbol}_{ds}.parquet"
        d += timedelta(days=1)
        if not p.exists():
            continue
        ts, mid, obi = load_day(str(p))
        sgn = np.sign(obi)
        for h in HORIZONS:
            j = np.searchsorted(ts, ts + h)         # index of first ts >= t+h
            valid = j < len(mid)
            jj = np.clip(j, 0, len(mid) - 1)
            fwd = (mid[jj] - mid) / TICK            # forward move in ticks
            signed = sgn * fwd
            signed[~valid] = np.nan
            moves[h].append(signed)
        obis.append(obi)
        n_done += 1
        print(f"  {ds}: {len(ts):,} snapshots")
    obi_all = np.concatenate(obis)
    moves_all = {h: np.concatenate(moves[h]) for h in HORIZONS}
    return obi_all, moves_all


def report(symbol, obi, moves):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = len(obi)
    aobi = np.abs(obi)
    # Decile by |OBI|
    decile = pd.qcut(aobi, 10, labels=False, duplicates="drop")
    top = decile == decile.max()      # strongest-signal decile
    bot = decile == 0                 # weakest (near-balanced book)

    print("\n" + "=" * 78)
    print(f"TAKER FEASIBILITY — {symbol} | n={n:,} | round-trip cost = "
          f"{ROUNDTRIP_TICKS:.1f} tick (~{ROUNDTRIP_TICKS*TICK/9*1e4:.2f} bps @ $9)")
    print("=" * 78)
    print(f"|OBI| top decile threshold: {np.nanmin(aobi[top]):.3f}  "
          f"(n={top.sum():,})")

    results = {"symbol": symbol, "n": int(n),
               "roundtrip_ticks": ROUNDTRIP_TICKS, "by_horizon": []}

    hdr = (f"{'horizon':>8} | {'signed move (ticks)':>20} | {'hit>0':>7} | "
           f"{'hit>1t':>7} | {'NET-of-1t':>10}")
    print("\n--- TOP |OBI| DECILE (the tradeable signal) ---")
    print(hdr); print("-" * len(hdr))
    for h in HORIZONS:
        m = moves[h][top]
        m = m[~np.isnan(m)]
        mean_t = m.mean()
        hit0 = (m > 0).mean() * 100
        hit1 = (m > ROUNDTRIP_TICKS).mean() * 100
        net = mean_t - ROUNDTRIP_TICKS
        bps = mean_t * TICK / 9.0 * 1e4
        print(f"{h:>7.1f}s | {mean_t:>8.3f} ({bps:>+5.2f}bps) | {hit0:>6.1f}% | "
              f"{hit1:>6.1f}% | {net:>+9.3f}t")
        results["by_horizon"].append({
            "horizon_s": h, "mean_move_ticks": float(mean_t),
            "mean_move_bps": float(bps), "hit_gt0_pct": float(hit0),
            "hit_gt_cost_pct": float(hit1), "net_of_cost_ticks": float(net)})

    print("\n--- BOTTOM |OBI| DECILE (near-balanced book, control) ---")
    print(hdr); print("-" * len(hdr))
    for h in HORIZONS:
        m = moves[h][bot]; m = m[~np.isnan(m)]
        mean_t = m.mean(); hit0 = (m > 0).mean()*100
        hit1 = (m > ROUNDTRIP_TICKS).mean()*100; net = mean_t - ROUNDTRIP_TICKS
        bps = mean_t * TICK / 9.0 * 1e4
        print(f"{h:>7.1f}s | {mean_t:>8.3f} ({bps:>+5.2f}bps) | {hit0:>6.1f}% | "
              f"{hit1:>6.1f}% | {net:>+9.3f}t")

    # Verdict
    best = max(results["by_horizon"], key=lambda r: r["net_of_cost_ticks"])
    print("\n" + "=" * 78)
    if best["net_of_cost_ticks"] > 0:
        print(f"VERDICT: top-decile OBI clears cost at {best['horizon_s']}s "
              f"(net {best['net_of_cost_ticks']:+.3f} tick / "
              f"{best['mean_move_bps']:+.2f} bps gross move). Taker edge PLAUSIBLE.")
    else:
        print(f"VERDICT: top-decile OBI does NOT clear the 1-tick round-trip cost "
              f"at any horizon (best net {best['net_of_cost_ticks']:+.3f} tick "
              f"at {best['horizon_s']}s). Taker edge NOT supported pre-fee.")
    print("=" * 78)
    results["verdict_best"] = best

    with open(OUT_DIR / "taker_feasibility.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved -> {OUT_DIR / 'taker_feasibility.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="LINK_PERP")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default="2026-04-01")
    args = ap.parse_args()
    obi, moves = collect(args.symbol, args.days, args.start)
    report(args.symbol, obi, moves)


if __name__ == "__main__":
    main()
