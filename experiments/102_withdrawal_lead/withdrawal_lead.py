"""
withdrawal_lead.py
==================
Exp 102 — Does maker withdrawal LEAD price on Hyperliquid?

On Binance the answer was no: C56/C58 showed withdrawal and repricing are the
same event at ~50ms — by the time you see the pull, the price has moved. But HL
reprices on a seconds clock. If its makers pull with the same *relative* lead,
the withdrawal precedes the mid move by an actionable margin.

Signal (bbo stream, ~5-10Hz): one-sided touch collapse —
    side's touch notional < COLLAPSE_FRAC x its own trailing MED_WIN median,
    other side still >= HEALTHY_FRAC of its median  (one-sided, not a vol spike)
Direction: toward the withdrawn side (asks pulled => makers expect up).
Cooldown per side avoids double-counting one episode.

Accounting: signed mid markout AND honest taker round trip (entry crossing the
touch at t + REACT_S — NB: entering toward the withdrawn side means crossing
into the thinned book, so the entry price is already degraded; that is the real
cost of acting on this signal) at 0.5/1/5/15s, net of HL taker tiers.
Placebo: N random timestamps, same accounting — withdrawal must beat time.

Interaction (the user's hypothesis): does taker aggression rise after
withdrawals? Report taker notional per second in the 10s after events vs the
unconditional rate.

Run: python experiments/102_withdrawal_lead/withdrawal_lead.py --date 2026-07-16 --asset HL_BTC
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

MED_WIN_S = 60.0
COLLAPSE_FRAC = 0.2
HEALTHY_FRAC = 0.5
COOLDOWN_S = 10.0
REACT_S = 0.25
HORIZONS = (0.5, 1.0, 5.0, 15.0)
FEES_BPS = (4.5, 1.4)
N_PLACEBO = 2000
QUOTE_TOL_S = 5.0


def load(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    q = q[keep].reset_index(drop=True)
    tr = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    return q, tr


def find_withdrawals(q):
    ts = q["time_exchange"].astype("int64").to_numpy() / 1e9
    bid_usd = (q["bid_price"] * q["bid_size"]).to_numpy()
    ask_usd = (q["ask_price"] * q["ask_size"]).to_numpy()
    idx = pd.to_datetime(q["time_exchange"])
    med_b = pd.Series(bid_usd, index=idx).rolling(f"{int(MED_WIN_S)}s").median().to_numpy()
    med_a = pd.Series(ask_usd, index=idx).rolling(f"{int(MED_WIN_S)}s").median().to_numpy()

    ev = []
    last = {-1.0: -np.inf, 1.0: -np.inf}
    for k in range(len(ts)):
        if med_b[k] <= 0 or med_a[k] <= 0 or ts[k] - ts[0] < MED_WIN_S:
            continue
        # asks pulled, bids healthy => expect UP (sgn +1)
        if (ask_usd[k] < COLLAPSE_FRAC * med_a[k]
                and bid_usd[k] >= HEALTHY_FRAC * med_b[k]
                and ts[k] - last[1.0] > COOLDOWN_S):
            ev.append((ts[k], 1.0)); last[1.0] = ts[k]
        elif (bid_usd[k] < COLLAPSE_FRAC * med_b[k]
                and ask_usd[k] >= HEALTHY_FRAC * med_a[k]
                and ts[k] - last[-1.0] > COOLDOWN_S):
            ev.append((ts[k], -1.0)); last[-1.0] = ts[k]
    return ev


def markouts(ev, q, mid0):
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = q["bid_price"].to_numpy(); qa = q["ask_price"].to_numpy()
    qm = q["mid"].to_numpy()

    def row_at(t):
        i = np.searchsorted(qt, t, side="right") - 1
        if i < 0 or (t - qt[i]) > QUOTE_TOL_S:
            return None
        return qb[i], qa[i], qm[i]

    res = {"n_events": len(ev)}
    per_h = {h: [] for h in HORIZONS}
    for t0, sgn in ev:
        r = row_at(t0 + REACT_S)
        if r is None:
            continue
        entry = r[1] if sgn > 0 else r[0]     # crossing into the thinned side
        for h in HORIZONS:
            r2 = row_at(t0 + REACT_S + h)
            if r2 is None:
                continue
            exit_touch = r2[0] if sgn > 0 else r2[1]
            per_h[h].append((1e4 * sgn * (r2[2] - qm[np.searchsorted(qt, t0, side='right')-1]) / mid0,
                             1e4 * sgn * (exit_touch - entry) / mid0))
    for h in HORIZONS:
        arr = np.array(per_h[h])
        if not len(arr):
            continue
        gm, gr = arr[:, 0], arr[:, 1]
        res[f"h{h:g}s"] = {"n": int(len(arr)),
                           "mid_drift_bps": float(gm.mean()),
                           "gross_rt_bps": float(gr.mean()),
                           "p50_rt_bps": float(np.median(gr)),
                           "hit_mid": float((gm > 0).mean()),
                           "net_rt_bps": {f"fee_{f}": round(float(gr.mean()) - 2 * f, 3)
                                          for f in FEES_BPS}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", default="HL_BTC")
    args = ap.parse_args()

    q, tr = load(args.asset, args.date)
    mid0 = float(np.median(q["mid"]))
    ev = find_withdrawals(q)
    real = markouts(ev, q, mid0)
    print(f"=== {args.asset} {args.date}  withdrawal events={real['n_events']} "
          f"({real['n_events']/max((q['time_exchange'].iloc[-1]-q['time_exchange'].iloc[0]).total_seconds()/3600,1):.1f}/h)")
    for h in HORIZONS:
        k = f"h{h:g}s"
        if k in real:
            r = real[k]
            print(f"  h={h:>4g}s n={r['n']:4d} mid_drift={r['mid_drift_bps']:+6.2f} "
                  f"(hit={r['hit_mid']:.2f})  rt={r['gross_rt_bps']:+7.2f} "
                  f"net@1.4={r['net_rt_bps']['fee_1.4']:+7.2f}")

    # placebo: random timestamps with random sign
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    rng = np.random.default_rng(0)
    t_rand = rng.uniform(qt[0] + MED_WIN_S, qt[-1] - 20, size=N_PLACEBO)
    s_rand = rng.choice([-1.0, 1.0], size=N_PLACEBO)
    plac = markouts(list(zip(t_rand, s_rand)), q, mid0)
    out = {"asset": args.asset, "date": args.date, "real": real, "placebo": plac}
    for h in (1.0, 5.0):
        k = f"h{h:g}s"
        if k in real and k in plac:
            print(f"  placebo h={h:g}s: mid_drift={plac[k]['mid_drift_bps']:+.2f} "
                  f"rt={plac[k]['gross_rt_bps']:+.2f}  "
                  f"(real mid_drift={real[k]['mid_drift_bps']:+.2f})")

    # interaction: taker notional rate in the 10s after events vs baseline
    tt = tr["time_exchange"].astype("int64").to_numpy() / 1e9
    tusd = (tr["price"] * tr["size"]).to_numpy()
    total_s = qt[-1] - qt[0]
    base_rate = tusd.sum() / total_s
    post = 0.0
    for t0, _ in ev:
        j0 = np.searchsorted(tt, t0); j1 = np.searchsorted(tt, t0 + 10.0)
        post += tusd[j0:j1].sum()
    post_rate = post / max(len(ev) * 10.0, 1)
    out["interaction"] = {"baseline_usd_per_s": base_rate,
                          "post_withdrawal_usd_per_s": post_rate,
                          "ratio": post_rate / base_rate if base_rate else None}
    print(f"  interaction: taker flow after withdrawal = {post_rate:,.0f} $/s "
          f"vs baseline {base_rate:,.0f} $/s  (x{post_rate/base_rate:.2f})")

    tag = f"{args.asset}_{args.date}"
    with open(OUT / f"withdrawal_lead_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/withdrawal_lead_{tag}.json")


if __name__ == "__main__":
    main()
