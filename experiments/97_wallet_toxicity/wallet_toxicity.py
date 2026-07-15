"""
wallet_toxicity.py
==================
Exp 97 — Can counterparty identity isolate a benign pocket that anonymous state
(C61/exp 96) could not? The Glosten-Milgrom flow-sorting escape route, tested on
Hyperliquid, whose trade feed carries both counterparty wallets.

C61 conditioned realized half-spread on anonymous pre-quote *state* and found no
selectable benign pocket. Here the conditioning variable is the *taker wallet*.
Same markout, signed to the maker's side (D=+1 taker bought => maker sold):

    realized_half(t,h) = D * (price - mid_{t+h})     # what the maker keeps

Four questions:
  1. TOXICITY SPREAD  — per-taker mean realized_half; how much do wallets differ?
  2. CONCENTRATION    — is adverse selection carried by a few wallets?
  3. PERSISTENCE      — does a wallet's toxicity in the first half of the day
                        predict the second half? (necessary for it to be usable)
  4. BENIGN-POCKET OOS— rank takers toxic/benign on TRAIN (first half); on the
                        held-out TEST half, is realized_half for benign-taker
                        fills positive net of fees? Placebo: shuffle the wallet
                        labels (same class sizes, no identity) — the real split
                        must beat it, or the "edge" is just trading less.

Honest scope (same caution as exp 96): this measures the *potential* in the flow.
A passive maker cannot refuse a counterparty, so a positive benign pocket is a
target for an actionability test (gate quoting on toxic-wallet presence), not a
strategy by itself. A negative/placebo-level result closes the route outright.

Run: python experiments/97_wallet_toxicity/wallet_toxicity.py --date 2026-07-16 --asset HL_HYPE
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

HORIZONS = (1.0, 5.0, 30.0)
QUOTE_TOL = pd.Timedelta("2s")
MIN_FILLS = 10            # min fills for a wallet to enter persistence/ranking
FEES_BPS = (0.0, 1.0, 2.0)   # maker fee scenarios (HL has rebates at the top)
N_PLACEBO = 200
DEFAULT_ASSETS = ["HL_HYPE", "HL_BTC", "HL_ETH", "HL_SOL", "HL_LINK"]


def _asof_mid(times, q):
    left = pd.DataFrame({"time_exchange": times.to_numpy()}).sort_values("time_exchange")
    m = pd.merge_asof(left, q, on="time_exchange", direction="backward",
                      tolerance=QUOTE_TOL)
    return m["mid"].to_numpy()[np.argsort(left.index.to_numpy(), kind="stable")]


def load(asset, date):
    t = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet")
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet")
    t = t.sort_values("time_exchange").reset_index(drop=True)
    q = q.sort_values("time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    qm = q[["time_exchange", "mid"]]
    mid_t = _asof_mid(t["time_exchange"], qm)
    D = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)   # +1 => maker sold
    df = pd.DataFrame({
        "t": t["time_exchange"], "taker": t["taker_wallet"], "maker": t["maker_wallet"],
        "price": t["price"].to_numpy(), "size": t["size"].to_numpy(),
        "D": D, "mid_t": mid_t})
    for h in HORIZONS:
        mid_h = _asof_mid(t["time_exchange"] + pd.to_timedelta(h, unit="s"), qm)
        df[f"rh_{h}"] = D * (df["price"].to_numpy() - mid_h)     # $, maker-kept
    df["mid_mid"] = df["mid_t"]
    ok = (~np.isnan(mid_t)) & (~np.isnan(df[f"rh_{HORIZONS[-1]}"]))
    return df[ok].reset_index(drop=True)


def bps(x_dollars, mid):
    return 1e4 * np.nansum(x_dollars) / np.nansum(mid)   # size-agnostic mean in bps


def summarize(df, asset):
    mid = df["mid_t"].to_numpy()
    out = {"asset": asset, "n_fills": int(len(df)),
           "uniq_takers": int(df["taker"].nunique()),
           "overall_rh_bps": {str(h): float(1e4 * np.nanmean(df[f"rh_{h}"] / mid))
                              for h in HORIZONS}}

    # 1-2. per-taker toxicity + concentration (size-weighted realized at 5s)
    hkey = "rh_5.0"
    g = df.groupby("taker").agg(
        n=("price", "size"), vol=("size", "sum"),
        rh5_sum=(hkey, "sum"),
        rh5_bps=(hkey, lambda s: 1e4 * s.sum() / (df.loc[s.index, "mid_t"].sum())))
    g["adverse_usd"] = -g["rh5_sum"]                      # positive = maker loses
    tot_adverse = g["adverse_usd"].clip(lower=0).sum()
    top = g.sort_values("adverse_usd", ascending=False)
    k = max(1, int(0.05 * len(g)))
    out["concentration"] = {
        "n_takers": int(len(g)),
        "top5pct_share_of_adverse": float(top["adverse_usd"].head(k).clip(lower=0).sum()
                                          / tot_adverse) if tot_adverse > 0 else None,
        "median_taker_rh5_bps": float(g["rh5_bps"].median()),
        "iqr_taker_rh5_bps": float(g["rh5_bps"].quantile(0.75) - g["rh5_bps"].quantile(0.25))}

    # 3. persistence: first vs second half, size-weighted rh5 per taker
    tmid = df["t"].iloc[len(df) // 2]
    a, b = df[df["t"] < tmid], df[df["t"] >= tmid]

    def wmean(sub):
        r = sub.groupby("taker").apply(
            lambda s: pd.Series({"n": len(s),
                                 "rh5": 1e4 * s["rh_5.0"].sum() / s["mid_t"].sum()}),
            include_groups=False)
        return r[r["n"] >= MIN_FILLS]
    ra, rb = wmean(a), wmean(b)
    common = ra.index.intersection(rb.index)
    if len(common) >= 5:
        rho = float(pd.Series(ra.loc[common, "rh5"].values).corr(
            pd.Series(rb.loc[common, "rh5"].values), method="spearman"))
    else:
        rho = None
    out["persistence"] = {"n_common_wallets": int(len(common)),
                          "spearman_rho_train_test": rho}

    # 4. benign-pocket OOS: classify on train, evaluate on test, net of fees
    train_rank = ra["rh5"] if len(ra) else pd.Series(dtype=float)
    if len(train_rank) >= 6:
        med = train_rank.median()
        benign_w = set(train_rank[train_rank >= med].index)   # less adverse => benign
        toxic_w = set(train_rank[train_rank < med].index)
        test = b[b["taker"].isin(benign_w | toxic_w)].copy()
        test["is_benign"] = test["taker"].isin(benign_w)
        corner = {}
        for name, mask in [("benign", test["is_benign"]), ("toxic", ~test["is_benign"])]:
            sub = test[mask]
            if len(sub):
                rh5 = float(1e4 * sub["rh_5.0"].sum() / sub["mid_t"].sum())
                corner[name] = {"n": int(len(sub)), "rh5_bps": rh5,
                                "net_bps": {f"fee_{f}": round(rh5 - f, 4) for f in FEES_BPS}}
        # placebo: random benign/toxic labels of the same sizes on test wallets
        rng = np.random.default_rng(0)
        test_wallets = list(set(test["taker"]))
        nb = len(benign_w)
        placebo = []
        wlab = test.groupby("taker")
        rh_by_w = {w: (s["rh_5.0"].sum(), s["mid_t"].sum()) for w, s in wlab}
        for _ in range(N_PLACEBO):
            pick = set(rng.choice(test_wallets, size=min(nb, len(test_wallets)),
                                  replace=False))
            num = sum(rh_by_w[w][0] for w in pick)
            den = sum(rh_by_w[w][1] for w in pick)
            if den > 0:
                placebo.append(1e4 * num / den)
        placebo = np.array(placebo)
        real_benign = corner.get("benign", {}).get("rh5_bps")
        corner["placebo_benign_rh5_bps"] = {
            "mean": float(placebo.mean()) if len(placebo) else None,
            "p95": float(np.percentile(placebo, 95)) if len(placebo) else None,
            "real_pctile": float((placebo < real_benign).mean() * 100)
            if (len(placebo) and real_benign is not None) else None}
        out["benign_pocket_oos"] = corner
    else:
        out["benign_pocket_oos"] = {"note": "too few train wallets"}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", action="append", help="default: all HL_* majors")
    args = ap.parse_args()
    assets = args.asset or DEFAULT_ASSETS

    results = {}
    for asset in assets:
        if not (PROC / f"trades_{asset}_{args.date}.parquet").exists():
            print(f"=== {asset}: missing, skip"); continue
        df = load(asset, args.date)
        if len(df) < 50:
            print(f"=== {asset}: only {len(df)} fills, skip"); continue
        r = summarize(df, asset)
        results[asset] = r
        c = r["concentration"]; p = r["persistence"]; bp = r["benign_pocket_oos"]
        print(f"=== {asset}  fills={r['n_fills']:,}  takers={r['uniq_takers']:,}")
        print(f"  overall realized_half: " +
              "  ".join(f"{h}s={r['overall_rh_bps'][h]:+.2f}bps" for h in map(str, HORIZONS)))
        print(f"  toxicity spread: median={c['median_taker_rh5_bps']:+.2f}bps  "
              f"IQR={c['iqr_taker_rh5_bps']:.2f}bps  "
              f"top5%adverse={c['top5pct_share_of_adverse']}")
        print(f"  persistence(train->test) spearman={p['spearman_rho_train_test']} "
              f"(n={p['n_common_wallets']})")
        if "benign" in bp:
            bn, tx = bp["benign"], bp["toxic"]
            pl = bp["placebo_benign_rh5_bps"]
            print(f"  OOS benign rh5={bn['rh5_bps']:+.3f}bps (net@fee0={bn['net_bps']['fee_0.0']:+.3f}) "
                  f"vs toxic={tx['rh5_bps']:+.3f}bps | placebo mean={pl['mean']:+.3f} "
                  f"real@pctile={pl['real_pctile']}")
        else:
            print(f"  benign pocket: {bp.get('note')}")

    with open(OUT / f"wallet_toxicity_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "horizons": list(HORIZONS), "results": results},
                  fh, indent=2)
    print(f"\nSaved -> {OUT}/wallet_toxicity_{args.date}.json")


if __name__ == "__main__":
    main()
