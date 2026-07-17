"""
metaorder_drift.py
==================
Exp 104 — Meta-order drift, reconstructed from wallet identity.

The classic institutional flow alpha: parent orders are split into child orders
executed over minutes, and *mid-execution* the remaining flow predictably
pushes price (Kyle lambda / Almgren-Chriss drift — among the best-documented
effects in microstructure). On anonymous CEX tape, meta-order reconstruction
requires broker data. On Hyperliquid every print carries the taker's wallet:
a streak of same-wallet, same-direction prints IS a meta-order, observable in
real time.

Detection (no lookahead): a wallet's K_MIN-th consecutive same-direction print
with inter-print gaps <= MAX_GAP_S and cumulative notional >= MIN_USD triggers
an entry signal at that print's timestamp. One entry per streak. The streak
ends at a direction flip or a gap > MAX_GAP_S.

Expression: taker, entry at the executable touch REACT_S after detection,
exits (a) fixed horizons, (b) streak-end + REACT_S (ride the execution),
both as full crossing round trips net of HL taker tiers.

Placebo: shuffle the wallet column (same trades, times, sizes, directions —
identity destroyed). Chance same-direction streaks under shuffling capture
pure tape momentum; the real detection must beat it, or "meta-orders" is just
"momentum" (which C31 priced).

Run: python experiments/104_metaorder_drift/metaorder_drift.py --date 2026-07-16 --asset HL_BTC
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

K_MIN = 5
MAX_GAP_S = 60.0
MIN_USD = 5_000.0
REACT_S = 0.5
HORIZONS = (30.0, 120.0, 600.0)
FEES_BPS = (4.5, 1.4)
N_PLACEBO = 50
QUOTE_TOL_S = 10.0


def load(asset, date):
    tr = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    tr["ts"] = tr["time_exchange"].astype("int64").to_numpy() / 1e9
    tr["d"] = np.where(tr["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    tr["usd"] = tr["price"] * tr["size"]
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return tr, q[keep].reset_index(drop=True)


def detect_streaks(tr, wallet_col):
    """Per-wallet same-direction runs -> (t_detect, dir, t_end, det_usd, tot_usd)."""
    events = []
    df = tr[[wallet_col, "ts", "d", "usd"]]
    for w, sub in df.groupby(wallet_col, sort=False):
        if len(sub) < K_MIN:
            continue
        ts = sub["ts"].to_numpy(); d = sub["d"].to_numpy(); usd = sub["usd"].to_numpy()
        run_start = 0
        fired = False
        for i in range(1, len(ts) + 1):
            broke = (i == len(ts) or d[i] != d[i - 1]
                     or ts[i] - ts[i - 1] > MAX_GAP_S)
            if broke:
                events_in_run = i - run_start
                if fired:
                    # close the last fired streak with its end time
                    events[-1]["t_end"] = ts[i - 1]
                    events[-1]["tot_usd"] = float(usd[run_start:i].sum())
                run_start = i
                fired = False
            elif not fired and (i - run_start + 1) >= K_MIN:
                cum = float(usd[run_start:i + 1].sum())
                if cum >= MIN_USD:
                    events.append({"t": ts[i], "dir": float(d[i]),
                                   "t_end": ts[i], "det_usd": cum,
                                   "tot_usd": cum, "wallet": str(w)})
                    fired = True
    events.sort(key=lambda e: e["t"])
    return events


def markouts(events, q, mid0):
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = q["bid_price"].to_numpy(); qa = q["ask_price"].to_numpy()
    qm = q["mid"].to_numpy()

    def row_at(t):
        i = np.searchsorted(qt, t, side="right") - 1
        if i < 0 or (t - qt[i]) > QUOTE_TOL_S:
            return None
        return qb[i], qa[i], qm[i]

    res = {"n_events": len(events)}
    per_h = {h: [] for h in HORIZONS}
    ride = []
    for e in events:
        r = row_at(e["t"] + REACT_S)
        if r is None:
            continue
        sgn = e["dir"]
        entry = r[1] if sgn > 0 else r[0]
        for h in HORIZONS:
            r2 = row_at(e["t"] + REACT_S + h)
            if r2 is None:
                continue
            exit_touch = r2[0] if sgn > 0 else r2[1]
            per_h[h].append(1e4 * sgn * (exit_touch - entry) / mid0)
        r3 = row_at(e["t_end"] + REACT_S)
        if r3 is not None and e["t_end"] > e["t"]:
            exit_touch = r3[0] if sgn > 0 else r3[1]
            ride.append(1e4 * sgn * (exit_touch - entry) / mid0)
    for h in HORIZONS:
        arr = np.array(per_h[h])
        if not len(arr):
            continue
        res[f"h{h:g}s"] = {"n": int(len(arr)), "gross_rt_bps": float(arr.mean()),
                           "p50": float(np.median(arr)),
                           "hit": float((arr > 0).mean()),
                           "net_rt_bps": {f"fee_{f}": round(float(arr.mean()) - 2 * f, 3)
                                          for f in FEES_BPS}}
    arr = np.array(ride)
    if len(arr):
        res["ride_to_end"] = {"n": int(len(arr)), "gross_rt_bps": float(arr.mean()),
                              "p50": float(np.median(arr)),
                              "hit": float((arr > 0).mean()),
                              "net_rt_bps": {f"fee_{f}": round(float(arr.mean()) - 2 * f, 3)
                                             for f in FEES_BPS}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", default="HL_BTC")
    args = ap.parse_args()

    tr, q = load(args.asset, args.date)
    mid0 = float(np.median(q["mid"]))
    ev = detect_streaks(tr, "taker_wallet")
    real = markouts(ev, q, mid0)
    dur = [e["t_end"] - e["t"] for e in ev if e["t_end"] > e["t"]]
    print(f"=== {args.asset} {args.date}  streaks={len(ev)}  "
          f"median ride={np.median(dur):.0f}s  "
          f"median det_usd=${np.median([e['det_usd'] for e in ev]):,.0f}" if ev
          else f"=== {args.asset} {args.date}  streaks=0")
    for k in [f"h{h:g}s" for h in HORIZONS] + ["ride_to_end"]:
        if k in real:
            r = real[k]
            print(f"  {k:12s} n={r['n']:4d} gross_rt={r['gross_rt_bps']:+7.2f} "
                  f"p50={r['p50']:+6.2f} hit={r['hit']:.2f} "
                  f"net@4.5={r['net_rt_bps']['fee_4.5']:+7.2f} "
                  f"net@1.4={r['net_rt_bps']['fee_1.4']:+7.2f}")

    # placebo: shuffle wallet labels — same tape, no identity
    rng = np.random.default_rng(0)
    key = "h120s"
    pl = []
    trp = tr.copy()
    for _ in range(N_PLACEBO):
        trp["w_shuf"] = rng.permutation(tr["taker_wallet"].to_numpy())
        evp = detect_streaks(trp, "w_shuf")
        r = markouts(evp, q, mid0)
        if key in r:
            pl.append((r["n_events"], r[key]["gross_rt_bps"]))
    if pl:
        n_pl = np.array([x[0] for x in pl]); v_pl = np.array([x[1] for x in pl])
        realv = real.get(key, {}).get("gross_rt_bps")
        pctile = float((v_pl < realv).mean() * 100) if realv is not None else None
        print(f"  placebo(shuffled wallets, @120s): events mean={n_pl.mean():.0f} "
              f"gross_rt mean={v_pl.mean():+.2f} p95={np.percentile(v_pl, 95):+.2f} "
              f"real@pctile={pctile}")
    out = {"asset": args.asset, "date": args.date, "n_streaks": len(ev),
           "real": real,
           "placebo_120s": {"mean": float(v_pl.mean()), "p95": float(np.percentile(v_pl, 95)),
                            "real_pctile": pctile} if pl else None}
    tag = f"{args.asset}_{args.date}"
    with open(OUT / f"metaorder_drift_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/metaorder_drift_{tag}.json")


if __name__ == "__main__":
    main()
