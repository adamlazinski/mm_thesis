"""
premium_gated.py
================
Exp 109 — Premium-gated dislocation: unify the two live edges (exp 99 dislocation
taker + exp 107/108 funding/basis) by conditioning the dislocation trade on HL's
own premium.

Two independent reads of the same "HL is stretched from fair value":
  dev      = leader_mid - HL_mid (cross-venue, tick-fast; our exp 99 signal)
  premium  = HL mark/mid - HL oracle (HL's internal, oracle updates ~1-3s;
             captured in the funding stream)
When both agree HL is stretched, the move is over-extension that reverts (the
exp 99 win case). When they DISAGREE, the dislocation may be a genuine repricing
that HL's oracle already reflects — the continuation case that loses.

For each exp-99 dislocation event (|dev| > THR), sign = sign(dev) = the direction
we trade (dev>0: HL cheap vs consensus, BUY expecting up-reversion). Record the
prevailing premium and classify:
  CONFIRMED : premium agrees HL is stretched the same way (sign(premium) opposes
              the reversion direction, i.e. premium * sgn < 0) AND |premium| large
  OPPOSED   : premium disagrees (premium * sgn > 0)
  NEUTRAL   : small |premium|
Report the exp-99 round-trip reversion (gross_rt@5s, net of taker tiers) per group.
If CONFIRMED >> OPPOSED, the premium is a real filter that sharpens exp 99.

Run: python experiments/109_premium_gated/premium_gated.py --date 2026-07-16 \
        --laggard HL_BTC --leader BTC_PERP
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

THRESHOLDS_BPS = (3.0, 5.0)
REACT_S = 0.25
H = 5.0
FEES_BPS = (4.5, 1.4)
QUOTE_TOL_S = 10.0


def load_premium(asset, dates):
    frames = []
    for d in dates:
        p = PROC / f"funding_{asset}_{d}.parquet"
        if not p.exists():
            continue
        f = pd.read_parquet(p, columns=["time_coinapi", "premium", "mid_px",
                                        "oracle_px", "funding"])
        frames.append(f)
    if not frames:
        return None
    df = pd.concat(frames).sort_values("time_coinapi").reset_index(drop=True)
    df["t"] = df["time_coinapi"].astype("int64").to_numpy() / 1e9
    # HL 'premium' is a fraction; fall back to (mid-oracle)/oracle if absent
    prem = df["premium"].to_numpy(dtype=float)
    bad = ~np.isfinite(prem)
    if bad.any():
        prem[bad] = ((df["mid_px"] - df["oracle_px"]) / df["oracle_px"]).to_numpy()[bad]
    df["prem"] = prem
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--laggard", default="HL_BTC")
    ap.add_argument("--leader", default="BTC_PERP")
    args = ap.parse_args()
    dates = args.date.split(",")

    ol = _mod = importlib.util.spec_from_file_location(
        "ol", ROOT / "experiments/99_oracle_lag/oracle_lag.py")
    ol = importlib.util.module_from_spec(ol); _mod.loader.exec_module(ol)

    def all_q(asset):
        fr = [pd.read_parquet(PROC / f"quotes_{asset}_{d}.parquet") for d in dates
              if (PROC / f"quotes_{asset}_{d}.parquet").exists()]
        q = pd.concat(fr).sort_values("time_exchange").reset_index(drop=True)
        q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
        t = q["time_exchange"].astype("int64").to_numpy() / 1e9
        keep = np.concatenate([[True], np.diff(t) > 0])
        return q[keep].reset_index(drop=True)

    lag_q, lead_q = all_q(args.laggard), all_q(args.leader)
    tg = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    tl = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
    t0, t1 = max(tl[0], tg[0]), min(tl[-1], tg[-1])
    kl = (tl >= t0) & (tl <= t1); kg = (tg >= t0) & (tg <= t1)
    td, dv = ol.dev_series(tl[kl], lead_q["mid"].to_numpy()[kl],
                           tg[kg], lag_q["mid"].to_numpy()[kg])
    mid0 = float(np.median(lag_q["mid"].to_numpy()[kg]))

    prem_df = load_premium(args.laggard, dates)
    if prem_df is None:
        raise SystemExit("no premium/funding stream")
    pt, pv = prem_df["t"].to_numpy(), prem_df["prem"].to_numpy()

    qk = lag_q[kg].reset_index(drop=True)
    qkt = qk["time_exchange"].astype("int64").to_numpy() / 1e9
    qkb = qk["bid_price"].to_numpy(); qka = qk["ask_price"].to_numpy()

    # sanity: correlation of dev and premium at event grid (should be negative:
    # dev>0 => HL cheap => premium<0)
    out = {"laggard": args.laggard, "leader": args.leader, "dates": dates,
           "thresholds": {}}
    print(f"=== {args.leader}->{args.laggard} {args.date}")

    for thr in THRESHOLDS_BPS:
        ev = ol.events(td, dv, thr * 1e-4 * mid0)
        rows = []
        for t0e, sgn in ev:
            ip = np.searchsorted(pt, t0e, side="right") - 1
            if ip < 0 or (t0e - pt[ip]) > 5.0:
                continue
            prem = pv[ip]
            j = np.searchsorted(qkt, t0e + REACT_S, side="right") - 1
            k = np.searchsorted(qkt, t0e + REACT_S + H, side="right") - 1
            if j < 0 or k <= j:
                continue
            entry = qka[j] if sgn > 0 else qkb[j]
            exit_ = qkb[k] if sgn > 0 else qka[k]
            rt = 1e4 * sgn * (exit_ - entry) / mid0
            rows.append({"sgn": sgn, "prem": float(prem), "rt": rt,
                         "prem_signed": float(prem * sgn)})   # <0 = confirmed
        if not rows:
            continue
        df = pd.DataFrame(rows)
        # classify by prem_signed terciles; confirmed = most negative tercile
        qlo, qhi = df["prem_signed"].quantile([0.33, 0.66])
        groups = {"confirmed(prem opposes reversion, stretched)": df[df["prem_signed"] <= qlo],
                  "neutral": df[(df["prem_signed"] > qlo) & (df["prem_signed"] < qhi)],
                  "opposed(prem agrees w/ move)": df[df["prem_signed"] >= qhi]}
        corr = float(np.corrcoef(df["sgn"] * df["prem"], df["sgn"])[0, 1]) if len(df) > 2 else None
        rec = {"n": len(df), "all_rt_bps": float(df["rt"].mean()),
               "dev_prem_align_corr": corr, "groups": {}}
        print(f"  thr={thr:g}bps  n={len(df)}  all rt@5s={df['rt'].mean():+.2f}bps")
        for name, g in groups.items():
            if not len(g):
                continue
            m = float(g["rt"].mean())
            rec["groups"][name] = {"n": int(len(g)), "rt_bps": m,
                                   "hit": float((g["rt"] > 0).mean()),
                                   "net_bps": {f"fee_{f}": round(m - 2 * f, 2) for f in FEES_BPS}}
            print(f"     {name[:38]:38s} n={len(g):4d} rt={m:+7.2f} hit={float((g['rt']>0).mean()):.2f} "
                  f"net@1.4={m-2*1.4:+7.2f}")
        out["thresholds"][f"{thr:g}"] = rec

    tag = f"{args.laggard}_{args.date.replace(',', '_')}"
    with open(OUT / f"premium_gated_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/premium_gated_{tag}.json")


if __name__ == "__main__":
    main()
