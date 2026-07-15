"""
oracle_lag.py
=============
Exp 99 — Cross-venue lag taker: does a fast leader move produce a laggard drift
big enough to cross the laggard's spread AND its taker fee?

C57 killed this for Binance-perp -> Binance-spot: ~1.7bps gross vs a 2-10bps
wall, on a 40-100ms lead. The new venues change both sides of the inequality:
Hyperliquid's mid can trail a fast CEX move on a *seconds* scale (its oracle
updates ~3s and its makers reprice around oracle/mark), so the drift per event
can be much larger — but HL's taker fee (4.5bps base) is a fatter wall. This
measures the inequality directly, per threshold, priced honestly.

Method (exp 90 Part-1 style, generalized to any processed leader/laggard pair):
  dev(t) = leader_mid - laggard_mid, EWMA-detrended (removes USDT/USD stablecoin
  basis and any perp basis). Event: |dev| crosses THR bps of laggard mid (armed/
  re-armed at THR/2, so bursts count once). Sign = sign(dev). At event + REACT_S
  we enter as a TAKER on the laggard at the executable touch (ask for buys);
  for each horizon we mark exit at mid (mark) and at the crossed touch (honest
  round trip), net of taker fee tiers.

Run:
  python experiments/99_oracle_lag/oracle_lag.py --date 2026-07-16 \
      --leader BTC --laggard HL_BTC --fees 4.5,3.0,1.4
  (leader/laggard are processed asset names; Binance spot BTC leader = "BTC")
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

EWMA_HL_S = 60.0
REACT_S = 0.25            # signal capture path + order send
THRESHOLDS_BPS = (2.0, 5.0, 10.0)
HORIZONS = (1.0, 5.0, 15.0, 60.0)
QUOTE_TOL = pd.Timedelta("5s")


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def dev_series(tl, ml, tg, mg):
    """Merged-event deviation dev(t)=leader-laggard, EWMA-detrended."""
    t_all = np.concatenate([tl, tg])
    venue = np.concatenate([np.zeros(len(tl), int), np.ones(len(tg), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]
    out_t = np.empty(len(t_all)); out_d = np.empty(len(t_all))
    cur = [ml[0], mg[0]]; i_l = i_g = 0
    base = ml[0] - mg[0]; last_t = t_all[0]
    for k, (t, v) in enumerate(zip(t_all, venue)):
        if v == 0:
            cur[0] = ml[i_l]; i_l += 1
        else:
            cur[1] = mg[i_g]; i_g += 1
        B = cur[0] - cur[1]
        alpha = 1 - 0.5 ** (max(t - last_t, 0.0) / EWMA_HL_S)
        base += alpha * (B - base); last_t = t
        out_t[k] = t; out_d[k] = B - base
    return out_t, out_d


def events(td, dv, thr_abs):
    """Divergence openings, armed/re-armed at thr/2."""
    ev = []
    armed = True
    for k in range(len(td)):
        if armed and abs(dv[k]) > thr_abs:
            ev.append((td[k], np.sign(dv[k])))
            armed = False
        elif not armed and abs(dv[k]) < thr_abs / 2:
            armed = True
    return ev


def _asof_row(qt, qbid, qask, qmid, t):
    i = np.searchsorted(qt, t, side="right") - 1
    if i < 0 or (t - qt[i]) > QUOTE_TOL.total_seconds():
        return None
    return qbid[i], qask[i], qmid[i]


def markouts(ev, lag_q, fees, mid0):
    qt = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = lag_q["bid_price"].to_numpy(); qa = lag_q["ask_price"].to_numpy()
    qm = lag_q["mid"].to_numpy()
    res = {"n_events": len(ev)}
    per_h = {h: [] for h in HORIZONS}
    for t0, sgn in ev:
        row = _asof_row(qt, qb, qa, qm, t0 + REACT_S)
        if row is None:
            continue
        bid, ask, mid = row
        entry = ask if sgn > 0 else bid          # cross in on the laggard
        for h in HORIZONS:
            r2 = _asof_row(qt, qb, qa, qm, t0 + REACT_S + h)
            if r2 is None:
                continue
            b2, a2, m2 = r2
            exit_touch = b2 if sgn > 0 else a2   # cross out
            per_h[h].append((1e4 * sgn * (m2 - entry) / mid0,
                             1e4 * sgn * (exit_touch - entry) / mid0))
    for h in HORIZONS:
        arr = np.array(per_h[h])
        if not len(arr):
            continue
        gm, gr = arr[:, 0], arr[:, 1]
        res[f"h{h:g}s"] = {
            "n": int(len(arr)),
            "gross_mid_bps": float(gm.mean()),
            "gross_rt_bps": float(gr.mean()),
            "p50_rt_bps": float(np.median(gr)),
            "hit_rate_rt": float((gr > 0).mean()),
            "net_rt_bps": {f"fee_{f}": round(float(gr.mean()) - 2 * f, 3)
                           for f in fees}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--leader", required=True, help="processed asset name (e.g. BTC)")
    ap.add_argument("--laggard", required=True, help="processed asset name (e.g. HL_BTC)")
    ap.add_argument("--fees", default="4.5,3.0,1.4",
                    help="laggard taker fee tiers, bps, comma-sep")
    args = ap.parse_args()
    fees = tuple(float(x) for x in args.fees.split(","))

    lead_q = load_quotes(args.leader, args.date)
    lag_q = load_quotes(args.laggard, args.date)
    tl = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
    tg = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    # clip to the overlapping window
    t0, t1 = max(tl[0], tg[0]), min(tl[-1], tg[-1])
    if t1 - t0 < 300:
        raise SystemExit(f"overlap between {args.leader} and {args.laggard} is "
                         f"{t1-t0:.0f}s — not enough")
    lm = lead_q["mid"].to_numpy(); gm = lag_q["mid"].to_numpy()
    kl = (tl >= t0) & (tl <= t1); kg = (tg >= t0) & (tg <= t1)
    td, dv = dev_series(tl[kl], lm[kl], tg[kg], gm[kg])
    mid0 = float(np.median(gm[kg]))
    lag_spread_bps = float(np.median(
        1e4 * (lag_q["ask_price"] - lag_q["bid_price"])[kg] / gm[kg]))

    print(f"=== {args.leader} -> {args.laggard} {args.date}  "
          f"overlap={(t1-t0)/3600:.1f}h  laggard spread p50={lag_spread_bps:.2f}bps")
    out = {"date": args.date, "leader": args.leader, "laggard": args.laggard,
           "overlap_h": (t1 - t0) / 3600, "laggard_spread_p50_bps": lag_spread_bps,
           "react_s": REACT_S, "thresholds": {}}
    for thr in THRESHOLDS_BPS:
        ev = events(td, dv, thr * 1e-4 * mid0)
        r = markouts(ev, lag_q[kg].reset_index(drop=True), fees, mid0)
        out["thresholds"][f"{thr:g}"] = r
        print(f"  thr={thr:g}bps  events={r['n_events']}")
        for h in HORIZONS:
            k = f"h{h:g}s"
            if k in r:
                x = r[k]
                print(f"   h={h:>4g}s n={x['n']:5d} gross_mid={x['gross_mid_bps']:+7.2f} "
                      f"gross_rt={x['gross_rt_bps']:+7.2f} hit={x['hit_rate_rt']:.2f} "
                      f"net@{fees[0]:g}={x['net_rt_bps'][f'fee_{fees[0]}']:+7.2f} "
                      f"net@{fees[-1]:g}={x['net_rt_bps'][f'fee_{fees[-1]}']:+7.2f}")

    tag = f"{args.leader}_to_{args.laggard}_{args.date}"
    with open(OUT / f"oracle_lag_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/oracle_lag_{tag}.json")


if __name__ == "__main__":
    main()
