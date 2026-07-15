"""
wallet_follow.py
================
Exp 98 — Follow the toxic wallets: the inverse of exp 97. If the top taker
wallets carry most adverse selection (exp 97: top 5% carry 60-80%), their trades
are price predictions published on the public tape with the author's address
attached. Instead of being the maker they hit, be the taker who copies them.

This is the first signal in the project with a plausible shot at clearing a fee
wall: C57's perp-lead was ~1.7bps gross vs a 2-10bps wall; an informed wallet's
1-minute markout can be much larger, and here it is measured per wallet, with
train/test persistence and a placebo.

Method (analysis, no engine — exp 90 Part-1 style, priced honestly):
  TRAIN (first half of day): per-wallet signed markout
      m_w = mean over w's trades of d * (mid_{t+H} - mid_t)/mid_t   (bps),
      d = +1 taker BUY, -1 taker SELL; keep wallets with >= MIN_FILLS trades.
      Follow set = wallets with m_w >= SCORE_MIN (bps) at H = SCORE_H.
  TEST (second half): every trade by a followed wallet = an event (per-wallet
      cooldown to avoid double-counting bursts). We copy the direction as a
      TAKER after REACT_S reaction latency, entering at the prevailing
      *executable* touch (ask for buys, bid for sells). For each horizon h:
        gross_mid  = d * (mid_{t+h} - entry_px)/mid          (exit at mid, mark)
        gross_rt   = d * (exit_touch_{t+h} - entry_px)/mid   (exit crossing back:
                     sell at bid / buy back at ask — full honest round trip)
      Net = gross_rt - 2*fee for taker fee tiers (HL base 4.5bps -> tiered).
  PLACEBO: N draws of an equally-sized random follow set from all train wallets
      with >= MIN_FILLS; the real set's test performance must beat the placebo
      distribution, or "wallet alpha" is just market beta of active hours.

Run: python experiments/98_wallet_follow/wallet_follow.py --date 2026-07-16 --asset HL_HYPE
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

HORIZONS = (10.0, 30.0, 60.0, 300.0)
SCORE_H = 60.0            # horizon used to score wallets on train
SCORE_MIN = 3.0           # bps: min train markout to follow a wallet
MIN_FILLS = 8             # min train trades to score a wallet
REACT_S = 1.0             # reaction latency before our entry
COOLDOWN_S = 5.0          # per-wallet event cooldown on test
FEES_BPS = (4.5, 3.0, 1.4)   # HL taker fee tiers (base -> high-volume)
N_PLACEBO = 200
QUOTE_TOL = pd.Timedelta("5s")
DEFAULT_ASSETS = ["HL_HYPE", "HL_BTC", "HL_ETH", "HL_SOL", "HL_LINK"]


def _asof(times, q, cols):
    left = pd.DataFrame({"time_exchange": times.to_numpy()}).sort_values("time_exchange")
    m = pd.merge_asof(left, q, on="time_exchange", direction="backward",
                      tolerance=QUOTE_TOL)
    order = np.argsort(left.index.to_numpy(), kind="stable")
    return {c: m[c].to_numpy()[order] for c in cols}


def load(asset, date):
    t = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    qq = q[["time_exchange", "bid_price", "ask_price", "mid"]]
    d = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    mid0 = _asof(t["time_exchange"], qq, ["mid"])["mid"]
    df = pd.DataFrame({"t": t["time_exchange"], "wallet": t["taker_wallet"],
                       "d": d, "mid0": mid0})
    return df[~np.isnan(mid0)].reset_index(drop=True), qq


def train_scores(df, qq):
    """Per-wallet signed markout at SCORE_H on the train half."""
    mid_h = _asof(df["t"] + pd.to_timedelta(SCORE_H, unit="s"), qq, ["mid"])["mid"]
    mk = 1e4 * df["d"].to_numpy() * (mid_h - df["mid0"].to_numpy()) / df["mid0"].to_numpy()
    s = pd.DataFrame({"wallet": df["wallet"], "mk": mk}).dropna()
    g = s.groupby("wallet")["mk"].agg(["mean", "count"])
    return g[g["count"] >= MIN_FILLS]


def test_follow(df_test, qq, follow: set):
    """Copy followed wallets' trades on the test half; return per-event table."""
    ev = df_test[df_test["wallet"].isin(follow)].copy()
    if not len(ev):
        return None
    # per-wallet cooldown
    keep = []
    last: dict = {}
    for i, (w, ts) in enumerate(zip(ev["wallet"], ev["t"])):
        if w not in last or (ts - last[w]).total_seconds() >= COOLDOWN_S:
            keep.append(i)
            last[w] = ts
    ev = ev.iloc[keep].reset_index(drop=True)

    entry_t = ev["t"] + pd.to_timedelta(REACT_S, unit="s")
    q_at = _asof(entry_t, qq, ["bid_price", "ask_price", "mid"])
    d = ev["d"].to_numpy()
    entry_px = np.where(d > 0, q_at["ask_price"], q_at["bid_price"])  # cross in
    mid_ref = q_at["mid"]
    ok = ~np.isnan(entry_px) & ~np.isnan(mid_ref)

    res = {"n_events": int(ok.sum())}
    for h in HORIZONS:
        q_h = _asof(entry_t + pd.to_timedelta(h, unit="s"), qq,
                    ["bid_price", "ask_price", "mid"])
        exit_touch = np.where(d > 0, q_h["bid_price"], q_h["ask_price"])  # cross out
        m = ok & ~np.isnan(q_h["mid"]) & ~np.isnan(exit_touch)
        if m.sum() == 0:
            continue
        gross_mid = 1e4 * d[m] * (q_h["mid"][m] - entry_px[m]) / mid_ref[m]
        gross_rt = 1e4 * d[m] * (exit_touch[m] - entry_px[m]) / mid_ref[m]
        res[f"h{h:g}s"] = {
            "gross_mid_bps": float(np.mean(gross_mid)),
            "gross_rt_bps": float(np.mean(gross_rt)),
            "hit_rate_rt": float(np.mean(gross_rt > 0)),
            "net_rt_bps": {f"fee_{f}": round(float(np.mean(gross_rt)) - 2 * f, 3)
                           for f in FEES_BPS}}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", action="append")
    args = ap.parse_args()
    assets = args.asset or DEFAULT_ASSETS

    results = {}
    for asset in assets:
        if not (PROC / f"trades_{asset}_{args.date}.parquet").exists():
            print(f"=== {asset}: missing, skip"); continue
        df, qq = load(asset, args.date)
        if len(df) < 200:
            print(f"=== {asset}: only {len(df)} trades, skip"); continue
        tmid = df["t"].iloc[len(df) // 2]
        tr, te = df[df["t"] < tmid], df[df["t"] >= tmid]

        g = train_scores(tr, qq)
        follow = set(g[g["mean"] >= SCORE_MIN].index)
        print(f"=== {asset}  trades={len(df):,}  train wallets scored={len(g)}  "
              f"followed={len(follow)}")
        if not follow:
            results[asset] = {"note": "no wallet cleared SCORE_MIN on train"}
            print("  no wallet cleared the follow threshold")
            continue

        real = test_follow(te, qq, follow)
        if real is None or real["n_events"] == 0:
            results[asset] = {"note": "followed wallets inactive on test"}
            print("  followed wallets produced no test events")
            continue

        # placebo: same-size random follow sets from all scored train wallets
        rng = np.random.default_rng(0)
        pool = list(g.index)
        # placebo horizon: SCORE_H if measured, else the longest available
        avail = [h for h in HORIZONS if f"h{h:g}s" in real]
        pl_h = SCORE_H if f"h{SCORE_H:g}s" in real else (avail[-1] if avail else None)
        pl_key = f"h{pl_h:g}s" if pl_h else None
        placebo = []
        if pl_key:
            for _ in range(N_PLACEBO):
                pick = set(rng.choice(pool, size=min(len(follow), len(pool)),
                                      replace=False))
                r = test_follow(te, qq, pick)
                if r and pl_key in r:
                    placebo.append(r[pl_key]["gross_rt_bps"])
        placebo = np.array(placebo)
        real_rt = real.get(pl_key, {}).get("gross_rt_bps") if pl_key else None
        pl = {"mean": float(placebo.mean()) if len(placebo) else None,
              "p95": float(np.percentile(placebo, 95)) if len(placebo) else None,
              "real_pctile": float((placebo < real_rt).mean() * 100)
              if (len(placebo) and real_rt is not None) else None}

        results[asset] = {"n_train_scored": int(len(g)), "n_followed": len(follow),
                          "followed_train_mk": {w: round(float(g.loc[w, "mean"]), 2)
                                                for w in list(follow)[:20]},
                          "test": real, "placebo_rt_at_scoreH": pl}
        print(f"  test events={real['n_events']}")
        for h in HORIZONS:
            k = f"h{h:g}s"
            if k in real:
                r = real[k]
                print(f"   h={h:>5g}s gross_mid={r['gross_mid_bps']:+7.2f} "
                      f"gross_rt={r['gross_rt_bps']:+7.2f} hit={r['hit_rate_rt']:.2f} "
                      f"net@4.5={r['net_rt_bps']['fee_4.5']:+7.2f} "
                      f"net@1.4={r['net_rt_bps']['fee_1.4']:+7.2f}")
        print(f"  placebo gross_rt@{SCORE_H:g}s: mean={pl['mean']} p95={pl['p95']} "
              f"real@pctile={pl['real_pctile']}")

    with open(OUT / f"wallet_follow_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "score_h": SCORE_H, "score_min": SCORE_MIN,
                   "react_s": REACT_S, "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/wallet_follow_{args.date}.json")


if __name__ == "__main__":
    main()
