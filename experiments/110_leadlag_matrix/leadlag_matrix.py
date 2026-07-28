"""
leadlag_matrix.py
=================
Exp 110 — The systematic lead-lag matrix: who leads whom, across every captured
venue and asset, at what horizon and with what strength.

Consolidates the project's scattered lead-lag findings (C36 spot-perp symmetry,
C56 perp leads spot 40-100ms, exp 99's CEX->HL dislocation) into one exhibit,
and checks for any pair we never tested.

Method: resample each series' mid to a common GRID_MS grid (last value, ffill
within a small tolerance), take log returns, and cross-correlate over
+-MAX_LAG_MS. corr(r_A(t), r_B(t+lag)) > 0 at lag L>0 means A leads B by L.
Report per ordered pair: peak lag, peak correlation, and the contemporaneous
correlation for scale. Same-asset cross-venue pairs are the informative ones;
cross-asset pairs (BTC vs ETH) measure the market factor's propagation.

Multiple-testing caveat: with N series there are N(N-1)/2 pairs; a peak at a
nonzero lag with |rho| barely above the contemporaneous value is not evidence.
We report the full matrix and flag only pairs where the peak is both nonzero-lag
AND materially above the zero-lag correlation.

Run: python experiments/110_leadlag_matrix/leadlag_matrix.py --dates 2026-07-15,2026-07-16
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

GRID_MS = 100
MAX_LAG_MS = 10000
SERIES = ["BTC", "BTC_PERP", "CB_BTC", "HL_BTC",
          "LINK", "LINK_PERP", "CB_LINK", "HL_LINK",
          "HL_ETH", "HL_SOL", "HL_HYPE"]


def load_grid(asset, dates, grid_ms, clock="exchange"):
    """clock: 'exchange' = venue's own stamp; 'recv' = our local receive time
    (a single common clock, but includes per-venue network latency)."""
    tcol = "time_exchange" if clock == "exchange" else "time_coinapi"
    frames = []
    for d in dates:
        p = PROC / f"quotes_{asset}_{d}.parquet"
        if not p.exists():
            continue
        q = pd.read_parquet(p, columns=[tcol, "bid_price", "ask_price"])
        q = q.sort_values(tcol).set_index(tcol)
        mid = (q["bid_price"] + q["ask_price"]) / 2.0
        frames.append(mid.resample(f"{grid_ms}ms").last())
    if not frames:
        return None
    s = pd.concat(frames).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.ffill(limit=int(5000 / grid_ms))       # ffill up to 5s of staleness


def xcorr(ra, rb, max_lag):
    """corr(ra[t], rb[t+lag]) for lag in [-max_lag, max_lag]; >0 => A leads B."""
    out = {}
    a = ra - ra.mean(); b = rb - rb.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom == 0:
        return out
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            v = float((a[:len(a) - lag] * b[lag:]).sum() / denom)
        else:
            v = float((a[-lag:] * b[:len(b) + lag]).sum() / denom)
        out[lag] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    ap.add_argument("--grid-ms", type=int, default=GRID_MS)
    ap.add_argument("--max-lag-ms", type=int, default=MAX_LAG_MS)
    ap.add_argument("--clock", choices=["exchange", "recv"], default="exchange")
    ap.add_argument("--only", action="append",
                    help="restrict to these series (repeatable)")
    args = ap.parse_args()
    dates = args.dates.split(",")
    max_lag = int(args.max_lag_ms / args.grid_ms)

    series = {}
    for a in (args.only or SERIES):
        s = load_grid(a, dates, args.grid_ms, args.clock)
        if s is not None and len(s) > 5000:
            series[a] = s
    print(f"loaded {len(series)} series at {args.grid_ms}ms: {list(series)}")

    df = pd.DataFrame(series).dropna()
    print(f"aligned grid rows: {len(df):,}  "
          f"({len(df)*args.grid_ms/3.6e6:.1f}h of common overlap)")
    rets = np.log(df).diff().dropna()

    results = {}
    flagged = []
    for a, b in itertools.combinations(rets.columns, 2):
        xc = xcorr(rets[a].to_numpy(), rets[b].to_numpy(), max_lag)
        if not xc:
            continue
        peak_lag = max(xc, key=lambda k: abs(xc[k]))
        peak = xc[peak_lag]
        zero = xc.get(0, 0.0)
        lead = a if peak_lag > 0 else (b if peak_lag < 0 else "contemporaneous")
        rec = {"peak_lag_ms": peak_lag * args.grid_ms, "peak_corr": round(peak, 4),
               "zero_lag_corr": round(zero, 4), "leader": lead,
               "peak_over_zero": round(peak - abs(zero), 4)}
        results[f"{a}|{b}"] = rec
        if peak_lag != 0 and (peak - abs(zero)) > 0.005:
            flagged.append((f"{a}->{b}" if peak_lag > 0 else f"{b}->{a}",
                            abs(peak_lag) * args.grid_ms, peak, zero))

    print(f"\n{'pair':28s} {'peak lag':>9s} {'peak rho':>9s} {'zero rho':>9s}  leader")
    for k, r in sorted(results.items(), key=lambda kv: -abs(kv[1]["peak_corr"]))[:22]:
        print(f"{k:28s} {r['peak_lag_ms']:>8d}ms {r['peak_corr']:>9.4f} "
              f"{r['zero_lag_corr']:>9.4f}  {r['leader']}")

    print(f"\nFLAGGED (nonzero-lag peak materially above contemporaneous):")
    if flagged:
        for name, lag, peak, zero in sorted(flagged, key=lambda x: -(x[2] - abs(x[3]))):
            print(f"  {name:26s} lead={lag:5.0f}ms  peak={peak:.4f} vs zero={zero:.4f}")
    else:
        print("  none — all peaks are contemporaneous at this grid")

    with open(OUT / f"leadlag_{args.grid_ms}ms_{args.clock}.json", "w") as fh:
        json.dump({"grid_ms": args.grid_ms, "clock": args.clock, "dates": dates,
                   "n_rows": len(df), "results": results,
                   "flagged": [{"pair": f, "lead_ms": l, "peak": p, "zero": z}
                               for f, l, p, z in flagged]}, fh, indent=2)
    print(f"\nSaved -> {OUT}/leadlag_{args.grid_ms}ms_{args.clock}.json")


if __name__ == "__main__":
    main()
