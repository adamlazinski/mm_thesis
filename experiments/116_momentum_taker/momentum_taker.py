"""
momentum_taker.py
=================
Exp 116 — Pure momentum taker: see a strong move, enter at market, exit seconds
later. No cross-venue signal, no maker leg — the simplest possible directional
trade, priced honestly.

Why it is worth running even though C1/C31 exist:
  * C1 established the momentum (1s autocorrelation ~0.15, 300ms ~0.18, decaying
    to zero by 20s) and exps 110/114 confirm it persists in 2026 (+0.19 at 10s).
  * C31 measured the predictability wall at ~1bp — below the round trip. But that
    was an average over all signal events; exp 99 showed the same inequality can
    flip in the TAIL, where the move per event is much larger than average.
  * Exp 105 found that laggard-venue sweeps the leader did NOT confirm CONTINUE
    rather than revert (fading them lost -4.1bps@60s at a 17% hit rate), which
    implies following them gained. That is an untested positive.

It is also the control exp 99 lacked. If plain own-venue momentum pays, the
cross-venue dislocation alpha is not special; if it does not, the cross-venue
mechanism is isolated as the thing that mattered.

Method: signal is the laggard's own mid return over a lookback L. An event opens
when |ret| > THR bps and re-arms below THR/2, with a cooldown. At event + REACT_S
we enter as a TAKER at the executable touch in the direction of the move, and
exit by CROSSING BACK at the touch after H seconds — full round trip at
transactable prices, net of taker fee tiers. Control: the same number of entries
at RANDOM times, which measures the pure round-trip cost and isolates whatever
the signal adds.

Run: python experiments/116_momentum_taker/momentum_taker.py --date 2026-07-16 --asset HL_BTC
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

LOOKBACKS_S = (1.0, 5.0)
THRESHOLDS_BPS = (5.0, 10.0, 20.0)
HORIZONS_S = (1.0, 5.0, 15.0, 60.0)
REACT_S = 0.25
COOLDOWN_S = 5.0
FEES_BPS = (4.5, 1.4)          # taker tiers
QUOTE_TOL_S = 5.0
N_PLACEBO = 20


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def round_trip(events, qt, qb, qa, mid0, horizons):
    """Enter crossing the touch in the signal direction, exit crossing back."""
    res = {}
    per_h = {h: [] for h in horizons}
    for t0, sgn in events:
        i = np.searchsorted(qt, t0 + REACT_S, side="right") - 1
        if i < 0 or (t0 + REACT_S - qt[i]) > QUOTE_TOL_S:
            continue
        entry = qa[i] if sgn > 0 else qb[i]
        for h in horizons:
            j = np.searchsorted(qt, t0 + REACT_S + h, side="right") - 1
            if j <= i or (t0 + REACT_S + h - qt[j]) > QUOTE_TOL_S:
                continue
            exit_ = qb[j] if sgn > 0 else qa[j]
            per_h[h].append(1e4 * sgn * (exit_ - entry) / mid0)
    for h in horizons:
        arr = np.array(per_h[h])
        if len(arr) < 5:
            continue
        res[f"h{h:g}s"] = {
            "n": int(len(arr)), "gross_rt_bps": float(arr.mean()),
            "p50": float(np.median(arr)), "hit": float((arr > 0).mean()),
            "net_rt_bps": {f"fee_{f}": round(float(arr.mean()) - 2 * f, 3)
                           for f in FEES_BPS}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", required=True)
    args = ap.parse_args()

    q = load_quotes(args.asset, args.date)
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = q["bid_price"].to_numpy(); qa = q["ask_price"].to_numpy()
    qm = q["mid"].to_numpy()
    mid0 = float(np.median(qm))
    hours = (qt[-1] - qt[0]) / 3600
    spread_bps = float(np.median((qa - qb) / qm) * 1e4)
    print(f"=== {args.asset} {args.date}  {hours:.1f}h  spread p50={spread_bps:.3f}bps")
    print(f"    entry crosses the touch, exit crosses back; net of taker tiers "
          f"{FEES_BPS[0]:g}/{FEES_BPS[-1]:g}bps")

    out = {"asset": args.asset, "date": args.date, "hours": round(hours, 2),
           "spread_bps": spread_bps, "runs": {}}
    rng = np.random.default_rng(0)

    for L in LOOKBACKS_S:
        prev = np.searchsorted(qt, qt - L, side="right") - 1
        ok = prev >= 0
        ret = np.full(len(qt), np.nan)
        ret[ok] = 1e4 * (qm[ok] - qm[prev[ok]]) / qm[prev[ok]]
        for thr in THRESHOLDS_BPS:
            ev, armed, last = [], True, -np.inf
            for k in range(len(qt)):
                r = ret[k]
                if not np.isfinite(r):
                    continue
                if armed and abs(r) > thr and qt[k] - last > COOLDOWN_S:
                    ev.append((qt[k], float(np.sign(r))))
                    armed = False; last = qt[k]
                elif not armed and abs(r) < thr / 2:
                    armed = True
            if len(ev) < 10:
                continue
            real = round_trip(ev, qt, qb, qa, mid0, HORIZONS_S)
            if not real:
                continue
            # control: same number of entries, random times and signs
            pl = {f"h{h:g}s": [] for h in HORIZONS_S}
            for s in range(N_PLACEBO):
                rr = np.random.default_rng(s)
                ts = np.sort(rr.uniform(qt[0], qt[-1] - 120, size=len(ev)))
                sg = rr.choice([-1.0, 1.0], size=len(ev))
                p = round_trip(list(zip(ts, sg)), qt, qb, qa, mid0, HORIZONS_S)
                for kk, v in p.items():
                    pl[kk].append(v["gross_rt_bps"])
            key = f"L{L:g}s_thr{thr:g}"
            out["runs"][key] = {"n_events": len(ev), "real": real,
                                "placebo_mean": {kk: float(np.mean(v))
                                                 for kk, v in pl.items() if v}}
            print(f"\n  lookback={L:g}s thr={thr:g}bps  events={len(ev)} "
                  f"({len(ev)/hours:.1f}/h)")
            for h in HORIZONS_S:
                kk = f"h{h:g}s"
                if kk not in real:
                    continue
                r = real[kk]
                pm = np.mean(pl[kk]) if pl[kk] else float("nan")
                print(f"    h={h:>4g}s n={r['n']:4d} gross={r['gross_rt_bps']:+7.2f} "
                      f"p50={r['p50']:+6.2f} hit={r['hit']:.2f} "
                      f"net@{FEES_BPS[0]:g}={r['net_rt_bps'][f'fee_{FEES_BPS[0]}']:+7.2f} "
                      f"net@{FEES_BPS[-1]:g}={r['net_rt_bps'][f'fee_{FEES_BPS[-1]}']:+7.2f}"
                      f"  | random entry gross={pm:+.2f}")

    with open(OUT / f"momentum_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT}/momentum_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
