"""
maker_competition.py
====================
Exp 120 — How much does a new maker cost the incumbents, and is this thesis's
simulated maker a plausible participant?

Both questions are usually answered by building a queue-reactive simulator and
assuming a reaction model: do competitors withdraw when we quote, at what
latency, with what probability. Every one of those is unmeasured, so the output
is a monotone function of the assumptions.

On Hyperliquid they do not have to be assumed. Every trade carries the
`maker_wallet` that was filled, so the competitive structure of the book is
directly observable, and the entry of a new maker is a natural experiment for
exactly the counterfactual "what if we joined this book".

Two measurements:

  (1) COMPETITION ELASTICITY. Per book-hour, M = distinct maker wallets filled.
      Regress log(an incumbent's fills) on log(M) and log(total flow), with book
      fixed effects. An elasticity of -1 is exactly Grossman-Miller's 1/M
      (Ch2 §7); 0 would mean a new maker costs incumbents nothing.

  (2) FILL-MODEL VALIDATION. Compare exp 103's simulated fills per day against
      what real makers on the SAME book-day actually achieved. The fill model
      has been audited against L2 queue clearing (C20) but never against ground
      truth. If the simulator out-fills the busiest real participant, it is
      claiming a queue position nobody held.

Run: python experiments/120_maker_competition/maker_competition.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics as st
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

MAJORS = {"HL_BTC", "HL_ETH", "HL_SOL", "HL_HYPE", "HL_LINK"}
MIN_TRADES_HOUR = 30


def book_hours():
    rows = []
    for f in sorted(glob.glob(str(PROC / "trades_HL_*_2026-0*.parquet"))):
        m = re.match(r"trades_(HL_[A-Z]+)_(2026-\d\d-\d\d)", os.path.basename(f))
        if not m:
            continue
        a, d = m.groups()
        if a in MAJORS:
            continue
        t = pd.read_parquet(f, columns=["time_exchange", "maker_wallet", "price", "size"])
        if len(t) < 200:
            continue
        t["hr"] = t.time_exchange.dt.floor("h")
        t["usd"] = t.price * t["size"]
        for hr, g in t.groupby("hr"):
            if len(g) < MIN_TRADES_HOUR:
                continue
            vc = g.maker_wallet.value_counts()
            rows.append({"book": a, "date": d, "hr": str(hr),
                         "M": int(g.maker_wallet.nunique()), "trades": len(g),
                         "usd": float(g.usd.sum()),
                         "fills_top": int(vc.iloc[0]),
                         "fills_med": float(vc.median()),
                         "usd_top": float(g[g.maker_wallet == vc.index[0]].usd.sum())})
    return pd.DataFrame(rows)


def elasticity(df, ycol):
    """log(y) ~ log(M) + log(flow) + book FE. Returns (beta_M, se, n)."""
    d = df[(df[ycol] > 0) & (df.M > 1)].copy()
    y = np.log(d[ycol].to_numpy())
    cols = [np.log(d.M.to_numpy()), np.log(d.trades.to_numpy())]
    for b in sorted(d.book.unique())[1:]:
        cols.append((d.book == b).to_numpy().astype(float))
    X = np.column_stack([np.ones(len(d))] + cols)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    se = np.sqrt(np.diag(np.linalg.pinv(X.T @ X)) * (res @ res) / (len(d) - X.shape[1]))
    return float(beta[1]), float(se[1]), float(beta[2]), len(d)


def fill_validation():
    """exp 103's simulated fills/day against real makers on the same book-day."""
    real = {}
    for f in sorted(glob.glob(str(PROC / "trades_HL_*_2026-07-*.parquet"))):
        m = re.match(r"trades_(HL_[A-Z]+)_(2026-\d\d-\d\d)", os.path.basename(f))
        a, d = m.groups()
        if a in MAJORS:
            continue
        t = pd.read_parquet(f, columns=["time_exchange", "maker_wallet"])
        if len(t) < 100:
            continue
        hrs = (t.time_exchange.max() - t.time_exchange.min()).total_seconds() / 3600
        sc = 24 / hrs if hrs > 0 else 1.0
        vc = t.maker_wallet.value_counts()
        real[(a, d)] = {"M": int(t.maker_wallet.nunique()),
                        "top_fills_day": float(vc.iloc[0] * sc),
                        "med_fills_day": float(vc.median() * sc)}
    out = []
    for f in sorted(glob.glob(str(ROOT / "experiments/103_defended_maker/results"
                                        / "defended_maker_HL_*_inv_qf0.5.json"))):
        j = json.load(open(f))
        k = (j["asset"], j["date"])
        if k not in real or j["asset"] == "HL_LINK":
            continue
        sim = j["configs"]["none"]["weighted_fills"] * 24 / j["day_h"]
        r = real[k]
        out.append({"book": k[0], "date": k[1], "M": r["M"], "sim_fills_day": round(sim, 1),
                    "real_top_fills_day": round(r["top_fills_day"], 1),
                    "real_median_fills_day": round(r["med_fills_day"], 2),
                    "sim_over_top": round(sim / r["top_fills_day"], 3),
                    "sim_over_median": round(sim / max(r["med_fills_day"], 1e-9), 1)})
    return out


def main():
    df = book_hours()
    res = {"n_book_hours": len(df), "n_books": int(df.book.nunique()),
           "elasticities": {}}
    print(f"=== {len(df)} book-hours across {df.book.nunique()} books\n")
    print("Competition elasticity: log(incumbent fills) ~ log(M) + log(flow) + book FE")
    print("  (-1.00 is exactly Grossman-Miller 1/M; 0.00 is no displacement)\n")
    for col, lbl in (("fills_top", "top maker's fills"),
                     ("fills_med", "median maker's fills"),
                     ("usd_top", "top maker's notional")):
        b, se, bf, n = elasticity(df, col)
        res["elasticities"][col] = {"beta_M": round(b, 4), "se": round(se, 4),
                                    "beta_flow": round(bf, 4), "n": n}
        print(f"  {lbl:24s} {b:+.3f} (se {se:.3f})   [95% CI "
              f"{b-1.96*se:+.3f}, {b+1.96*se:+.3f}]   flow {bf:+.3f}")
    v = fill_validation()
    res["fill_validation"] = v
    ratios = [x["sim_over_top"] for x in v]
    med_ratios = [x["sim_over_median"] for x in v]
    res["sim_over_top_median"] = round(st.median(ratios), 3)
    res["sim_over_median_median"] = round(st.median(med_ratios), 1)
    print(f"\nFill-model validation, {len(v)} book-days:")
    print(f"  simulated fills / BUSIEST real maker's fills : median {st.median(ratios):.2f} "
          f"(range {min(ratios):.2f}-{max(ratios):.2f})")
    print(f"  simulated fills / MEDIAN real maker's fills  : median {st.median(med_ratios):.0f}x")
    byb = {}
    for x in v:
        byb.setdefault(x["book"], []).append(x["sim_over_top"])
    print("\n  per book (sim / busiest real maker):")
    for b in sorted(byb, key=lambda z: -st.median(byb[z])):
        flag = "  <-- exceeds the busiest real participant" if st.median(byb[b]) > 1.2 else ""
        print(f"    {b[3:]:8s} {st.median(byb[b]):.2f}{flag}")
    with open(OUT / "maker_competition.json", "w") as fh:
        json.dump(res, fh, indent=2)
    print(f"\nSaved -> {OUT}/maker_competition.json")


if __name__ == "__main__":
    main()
