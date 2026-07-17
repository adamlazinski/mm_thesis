"""
sweep_fade.py
=============
Exp 105 — Sweep-fade with a leader gate: the liquidity-demand premium.

When a burst of taker flow moves the laggard's mid WITHOUT the leader venue
confirming, no information arrived — someone paid for liquidity (a forced or
impatient trader). Microstructure theory says that move reverts; providing the
other side collects the premium. The leader-confirmed sweeps are the control:
those carried information and should NOT revert.

This is also exp 99's missing precision instrument: the thr=2bps population
was decisively negative *unconditioned*; conditioning on the CAUSE (sweep, no
leader move) may isolate the revertible subset.

Event (laggard tape): 1s window with |signed taker notional| >= FLOW_Q of the
day's 1s-flow distribution AND the mid moved >= MOVE_BPS in the flow
direction. Classification at detection (no lookahead): leader's mid move over
the same second — |lead_move| < CONFIRM_BPS => UNCONFIRMED (fade candidate),
else CONFIRMED (control). Fade = enter against the sweep at the executable
touch REACT_S later; exits at fixed horizons, full crossing round trip.

Run: python experiments/105_sweep_fade/sweep_fade.py --date 2026-07-16 \
        --laggard HL_BTC --leader BTC_PERP
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

FLOW_Q = 0.99            # 1s |signed flow| quantile -> sweep threshold
MOVE_BPS = 1.0            # laggard mid must move this much with the flow
CONFIRM_BPS = 0.5         # leader move below this = unconfirmed
REACT_S = 0.5
HORIZONS = (5.0, 15.0, 60.0, 300.0)
FEES_BPS = (4.5, 1.4)
COOLDOWN_S = 10.0
QUOTE_TOL_S = 10.0


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def mid_asof(qt, qm, t):
    i = np.searchsorted(qt, t, side="right") - 1
    if i < 0 or (t - qt[i]) > QUOTE_TOL_S:
        return np.nan
    return qm[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--laggard", default="HL_BTC")
    ap.add_argument("--leader", default="BTC_PERP")
    args = ap.parse_args()

    tr = pd.read_parquet(PROC / f"trades_{args.laggard}_{args.date}.parquet"
                         ).sort_values("time_exchange").reset_index(drop=True)
    tr["ts"] = tr["time_exchange"].astype("int64").to_numpy() / 1e9
    d = np.where(tr["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    usd = (tr["price"] * tr["size"]).to_numpy()
    ts = tr["ts"].to_numpy()

    lag_q = load_quotes(args.laggard, args.date)
    lead_q = load_quotes(args.leader, args.date)
    qt = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = lag_q["bid_price"].to_numpy(); qa = lag_q["ask_price"].to_numpy()
    qm = lag_q["mid"].to_numpy()
    lt = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
    lm = lead_q["mid"].to_numpy()
    mid0 = float(np.median(qm))

    # 1s signed flow on a rolling basis (per trade: flow in the trailing 1s)
    sgn_usd = d * usd
    csum = np.concatenate([[0.0], np.cumsum(sgn_usd)])
    lo = np.searchsorted(ts, ts - 1.0, side="left")
    F = csum[1:len(ts) + 1] - csum[lo]
    thr = float(np.quantile(np.abs(F), FLOW_Q))

    events = []
    last_t = -np.inf
    for k in range(len(ts)):
        if abs(F[k]) < thr or ts[k] - last_t < COOLDOWN_S:
            continue
        sgn = np.sign(F[k])
        m_now = mid_asof(qt, qm, ts[k])
        m_1s = mid_asof(qt, qm, ts[k] - 1.0)
        if np.isnan(m_now) or np.isnan(m_1s):
            continue
        move = 1e4 * sgn * (m_now - m_1s) / mid0
        if move < MOVE_BPS:
            continue
        l_now = mid_asof(lt, lm, ts[k])
        l_1s = mid_asof(lt, lm, ts[k] - 1.0)
        if np.isnan(l_now) or np.isnan(l_1s):
            continue
        lead_move = 1e4 * sgn * (l_now - l_1s) / mid0
        confirmed = abs(lead_move) >= CONFIRM_BPS
        events.append({"t": ts[k], "sweep_dir": float(sgn),
                       "move_bps": float(move), "lead_move_bps": float(lead_move),
                       "confirmed": bool(confirmed), "flow_usd": float(F[k])})
        last_t = ts[k]

    n_unc = sum(1 for e in events if not e["confirmed"])
    print(f"=== {args.laggard} {args.date}  sweep thr=${thr:,.0f}/1s  "
          f"events={len(events)} (unconfirmed={n_unc}, confirmed={len(events)-n_unc})")

    def rt(e_list, fade=True):
        res = {}
        per_h = {h: [] for h in HORIZONS}
        for e in e_list:
            sgn = -e["sweep_dir"] if fade else e["sweep_dir"]
            i = np.searchsorted(qt, e["t"] + REACT_S, side="right") - 1
            if i < 0:
                continue
            entry = qa[i] if sgn > 0 else qb[i]
            for h in HORIZONS:
                j = np.searchsorted(qt, e["t"] + REACT_S + h, side="right") - 1
                if j <= i:
                    continue
                exit_touch = qb[j] if sgn > 0 else qa[j]
                per_h[h].append(1e4 * sgn * (exit_touch - entry) / mid0)
        for h in HORIZONS:
            arr = np.array(per_h[h])
            if not len(arr):
                continue
            res[f"h{h:g}s"] = {
                "n": int(len(arr)), "gross_rt_bps": float(arr.mean()),
                "p50": float(np.median(arr)), "hit": float((arr > 0).mean()),
                "net_rt_bps": {f"fee_{f}": round(float(arr.mean()) - 2 * f, 3)
                               for f in FEES_BPS}}
        return res

    unc = [e for e in events if not e["confirmed"]]
    con = [e for e in events if e["confirmed"]]
    out = {"laggard": args.laggard, "leader": args.leader, "date": args.date,
           "thr_usd": thr, "n_unconfirmed": len(unc), "n_confirmed": len(con),
           "fade_unconfirmed": rt(unc, fade=True),
           "fade_confirmed_control": rt(con, fade=True)}
    for name, res in [("FADE unconfirmed", out["fade_unconfirmed"]),
                      ("FADE confirmed (control)", out["fade_confirmed_control"])]:
        print(f"  {name}:")
        for h in HORIZONS:
            k = f"h{h:g}s"
            if k in res:
                r = res[k]
                print(f"   h={h:>4g}s n={r['n']:4d} gross_rt={r['gross_rt_bps']:+7.2f} "
                      f"p50={r['p50']:+6.2f} hit={r['hit']:.2f} "
                      f"net@4.5={r['net_rt_bps']['fee_4.5']:+7.2f} "
                      f"net@1.4={r['net_rt_bps']['fee_1.4']:+7.2f}")

    tag = f"{args.laggard}_{args.date}"
    with open(OUT / f"sweep_fade_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/sweep_fade_{tag}.json")


if __name__ == "__main__":
    main()
