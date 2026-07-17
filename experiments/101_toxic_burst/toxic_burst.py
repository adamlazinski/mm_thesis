"""
toxic_burst.py
==============
Exp 101 — Toxic-flow aggression bursts: behavior of identified participants as
a signal. Exp 98 showed single toxic-wallet trades carry ~1bp — under the fee
wall. This tests the regime version: when the informed tier's *aggregate signed
flow* surges, informed capital is arriving in size; bursts should carry
multi-bps drift (fewer, bigger events — the shape that beat the wall in exp 99).

TRAIN (day D-1): per-taker-wallet signed markout at SCORE_H (exp 98 machinery).
  informed set = wallets with n >= MIN_FILLS and markout >= SCORE_MIN bps.
  Burst threshold THR = the TRAIN day's QUANTILE of |rolling signed informed
  notional| (no test-day peeking).
TEST (day D): S(t) = rolling WINDOW_S signed USD notional of informed-set
  trades. Event when |S| crosses THR (re-armed at THR/2), direction sign(S).
  Honest taker round trip on the laggard venue's touch after REACT_S, horizons
  1/5/30/120s, net of HL taker tiers.
PLACEBO: N random same-size wallet sets from all scored train wallets, each
  with its own train-quantile threshold — the real set must beat the
  distribution, or "toxic bursts" is just "volume bursts".
PART B (gate): recompute exp-99 dislocation events (leader vs HL); split their
  round-trip returns by burst alignment at event time. A dislocation *driven by*
  informed flow is a leading move, not a stale lag — the one way exp 99 loses.

Run: python experiments/101_toxic_burst/toxic_burst.py --train 2026-07-15 \
         --date 2026-07-16 --asset HL_BTC --leader CB_BTC
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

SCORE_H = 60.0
TOP_K = 100               # informed set = top-K train wallets by markout
MIN_FILLS = 20
WINDOW_S = 30.0           # burst aggregation window
QUANTILE = 0.99           # train-day quantile of |S| -> base threshold
LADDER = (0.25, 0.5, 1.0)  # threshold multipliers (vol regimes differ by day)
GATE_RUNG = 0.5           # rung used for the placebo comparison
GATE_ABS_USD = 100_000.0  # |S| bar for exp-99 alignment classification only
                          # (classification needs sensitivity, not tradability)
REACT_S = 0.25
HORIZONS = (1.0, 5.0, 30.0, 120.0)
FEES_BPS = (4.5, 1.4)
N_PLACEBO = 100
QUOTE_TOL_S = 5.0
GATE_THR_BPS = 5.0        # exp-99 threshold for Part B


def load_trades(asset, date):
    t = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    t["ts"] = t["time_exchange"].astype("int64").to_numpy() / 1e9
    t["d"] = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    t["usd"] = t["price"] * t["size"]
    return t


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def wallet_scores(tr, q):
    """Signed markout (bps) at SCORE_H per taker wallet."""
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qm = q["mid"].to_numpy()
    i0 = np.searchsorted(qt, tr["ts"].to_numpy(), side="right") - 1
    i1 = np.searchsorted(qt, tr["ts"].to_numpy() + SCORE_H, side="right") - 1
    ok = (i0 >= 0) & (i1 > i0)
    mk = np.full(len(tr), np.nan)
    mk[ok] = 1e4 * tr["d"].to_numpy()[ok] * (qm[i1[ok]] - qm[i0[ok]]) / qm[i0[ok]]
    s = pd.DataFrame({"wallet": tr["taker_wallet"], "mk": mk}).dropna()
    g = s.groupby("wallet")["mk"].agg(["mean", "count"])
    return g[g["count"] >= MIN_FILLS]


def burst_series(tr, wallets: set):
    """Rolling WINDOW_S signed USD notional of the given wallets' trades."""
    m = tr["taker_wallet"].isin(wallets).to_numpy()
    ts = tr["ts"].to_numpy()[m]
    sgn_usd = (tr["d"] * tr["usd"]).to_numpy()[m]
    if len(ts) == 0:
        return ts, sgn_usd
    csum = np.concatenate([[0.0], np.cumsum(sgn_usd)])
    lo = np.searchsorted(ts, ts - WINDOW_S, side="left")
    S = csum[1:len(ts) + 1] - csum[lo]
    return ts, S


def find_bursts(ts, S, thr):
    ev = []
    armed = True
    for k in range(len(ts)):
        if armed and abs(S[k]) > thr:
            ev.append((ts[k], np.sign(S[k])))
            armed = False
        elif not armed and abs(S[k]) < thr / 2:
            armed = True
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
        entry = r[1] if sgn > 0 else r[0]
        for h in HORIZONS:
            r2 = row_at(t0 + REACT_S + h)
            if r2 is None:
                continue
            exit_touch = r2[0] if sgn > 0 else r2[1]
            per_h[h].append((1e4 * sgn * (r2[2] - entry) / mid0,
                             1e4 * sgn * (exit_touch - entry) / mid0))
    for h in HORIZONS:
        arr = np.array(per_h[h])
        if not len(arr):
            continue
        gm, gr = arr[:, 0], arr[:, 1]
        res[f"h{h:g}s"] = {"n": int(len(arr)),
                           "gross_mid_bps": float(gm.mean()),
                           "gross_rt_bps": float(gr.mean()),
                           "p50_rt_bps": float(np.median(gr)),
                           "hit_rt": float((gr > 0).mean()),
                           "net_rt_bps": {f"fee_{f}": round(float(gr.mean()) - 2 * f, 3)
                                          for f in FEES_BPS}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", default="HL_BTC")
    ap.add_argument("--leader", default="CB_BTC")
    args = ap.parse_args()

    tr_train = load_trades(args.asset, args.train)
    q_train = load_quotes(args.asset, args.train)
    tr_test = load_trades(args.asset, args.date)
    q_test = load_quotes(args.asset, args.date)
    mid0 = float(np.median(q_test["mid"]))

    g = wallet_scores(tr_train, q_train)
    gk = g[g["count"] >= MIN_FILLS].sort_values("mean", ascending=False)
    informed = set(gk.head(TOP_K).index)
    ts_tr, S_tr = burst_series(tr_train, informed)
    thr_base = float(np.quantile(np.abs(S_tr), QUANTILE)) if len(S_tr) else np.inf
    print(f"=== {args.asset}  train={args.train} test={args.date}")
    print(f"  scored wallets={len(g)}  informed=top{len(informed)} "
          f"(train mk range {gk['mean'].iloc[min(TOP_K,len(gk))-1]:+.1f}.."
          f"{gk['mean'].iloc[0]:+.1f}bps)  base THR=${thr_base:,.0f} (train q{QUANTILE})")

    ts_te, S_te = burst_series(tr_test, informed)
    out = {"asset": args.asset, "train": args.train, "date": args.date,
           "n_informed": len(informed), "thr_base_usd": thr_base, "rungs": {}}
    real_gate = None
    thr = thr_base * GATE_RUNG
    for mult in LADDER:
        ev = find_bursts(ts_te, S_te, thr_base * mult)
        real = markouts(ev, q_test, mid0)
        out["rungs"][f"{mult:g}"] = real
        if mult == GATE_RUNG:
            real_gate = real
        print(f"  rung x{mult:g} (${thr_base*mult:,.0f}): bursts={real['n_events']}")
        for h in HORIZONS:
            k = f"h{h:g}s"
            if k in real:
                r = real[k]
                print(f"   h={h:>5g}s n={r['n']:4d} gross_rt={r['gross_rt_bps']:+7.2f} "
                      f"p50={r['p50_rt_bps']:+6.2f} hit={r['hit_rt']:.2f} "
                      f"net@4.5={r['net_rt_bps']['fee_4.5']:+7.2f} "
                      f"net@1.4={r['net_rt_bps']['fee_1.4']:+7.2f}")
    real = real_gate

    # placebo: random same-size sets from all scored wallets, own train THR each
    rng = np.random.default_rng(0)
    pool = list(g[g["count"] >= MIN_FILLS].index)
    pl = []
    key = "h30s"
    for _ in range(N_PLACEBO):
        pick = set(rng.choice(pool, size=min(len(informed), len(pool)),
                              replace=False))
        tsp, Sp = burst_series(tr_train, pick)
        thr_p = (float(np.quantile(np.abs(Sp), QUANTILE)) * GATE_RUNG
                 if len(Sp) else np.inf)
        tse, Se = burst_series(tr_test, pick)
        r = markouts(find_bursts(tse, Se, thr_p), q_test, mid0)
        if key in r:
            pl.append(r[key]["gross_rt_bps"])
    pl = np.array(pl)
    real30 = real.get(key, {}).get("gross_rt_bps")
    out["placebo_rt_30s"] = {
        "mean": float(pl.mean()) if len(pl) else None,
        "p95": float(np.percentile(pl, 95)) if len(pl) else None,
        "real_pctile": float((pl < real30).mean() * 100)
        if (len(pl) and real30 is not None) else None}
    print(f"  placebo(gross_rt@30s): mean={out['placebo_rt_30s']['mean']} "
          f"p95={out['placebo_rt_30s']['p95']} "
          f"real@pctile={out['placebo_rt_30s']['real_pctile']}")

    # PART B: gate exp-99 dislocation events by burst alignment
    if not (PROC / f"quotes_{args.leader}_{args.date}.parquet").exists():
        print(f"  PART B skipped (no leader {args.leader})")
        tag = f"{args.asset}_{args.date}"
        with open(OUT / f"toxic_burst_{tag}.json", "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"Saved -> {OUT}/toxic_burst_{tag}.json")
        return
    spec = importlib.util.spec_from_file_location(
        "ol", ROOT / "experiments/99_oracle_lag/oracle_lag.py")
    ol = importlib.util.module_from_spec(spec); spec.loader.exec_module(ol)
    lead_q = ol.load_quotes(args.leader, args.date)
    tl = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
    tg = q_test["time_exchange"].astype("int64").to_numpy() / 1e9
    t0_, t1_ = max(tl[0], tg[0]), min(tl[-1], tg[-1])
    kl = (tl >= t0_) & (tl <= t1_); kg = (tg >= t0_) & (tg <= t1_)
    td, dvs = ol.dev_series(tl[kl], lead_q["mid"].to_numpy()[kl],
                            tg[kg], q_test["mid"].to_numpy()[kg])
    d_ev = ol.events(td, dvs, GATE_THR_BPS * 1e-4 * mid0)
    qk = q_test[kg].reset_index(drop=True)
    qkt = qk["time_exchange"].astype("int64").to_numpy() / 1e9
    qkb = qk["bid_price"].to_numpy(); qka = qk["ask_price"].to_numpy()
    groups = {"aligned": [], "neutral": [], "anti": []}
    for t0e, sgn in d_ev:
        # burst state just before the event
        i = np.searchsorted(ts_te, t0e, side="right") - 1
        s_now = S_te[i] if i >= 0 and (t0e - ts_te[i]) < WINDOW_S else 0.0
        if abs(s_now) > GATE_ABS_USD:
            grp = "aligned" if np.sign(s_now) == sgn else "anti"
        else:
            grp = "neutral"
        j = np.searchsorted(qkt, t0e + REACT_S, side="right") - 1
        k2 = np.searchsorted(qkt, t0e + REACT_S + 5.0, side="right") - 1
        if j < 0 or k2 <= j:
            continue
        entry = qka[j] if sgn > 0 else qkb[j]
        exit_ = qkb[k2] if sgn > 0 else qka[k2]
        groups[grp].append(1e4 * sgn * (exit_ - entry) / mid0)
    out["gate_exp99"] = {}
    print(f"  PART B — exp-99 (thr={GATE_THR_BPS:g}bps) events by burst state:")
    for gname, vals in groups.items():
        v = np.array(vals)
        rec = {"n": int(len(v)),
               "gross_rt_5s_bps": float(v.mean()) if len(v) else None}
        out["gate_exp99"][gname] = rec
        if len(v):
            print(f"    {gname:8s} n={len(v):3d}  gross_rt@5s={v.mean():+6.2f}bps")
        else:
            print(f"    {gname:8s} n=0")

    tag = f"{args.asset}_{args.date}"
    with open(OUT / f"toxic_burst_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/toxic_burst_{tag}.json")


if __name__ == "__main__":
    main()
