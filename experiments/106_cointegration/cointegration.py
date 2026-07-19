"""
cointegration.py
================
Exp 106 — Cross-asset intraday cointegration / pairs, tested honestly.

The user's question: statistical arbitrage like cointegration. Crypto majors are
all high-beta to BTC, so the real question is whether the market-neutral residual
of a pair mean-reverts intraday FASTER than the round-trip cost of trading it.

Sample caveat, stated up front: cointegration is a lower-frequency phenomenon
usually tested on months-years of daily data. We have ~4 days of intraday ticks
on one venue (HL: BTC/ETH/SOL/LINK/HYPE). This is therefore an *intraday*
mean-reversion probe, not a claim about long-run cointegration — and the multiple-
testing trap (10 pairs) plus the short sample mean any single p-value is weak.
The backtest is in-sample (first 60%) / out-of-sample (last 40%) with real costs.

Per pair (A, B):
  - Engle-Granger coint p-value on log-mid (full sample), OLS hedge beta.
  - spread = logA - beta*logB; half-life from AR(1) (Ornstein-Uhlenbeck).
  - z = (spread - roll_mean)/roll_std (ROLL bars, causal); enter |z|>Z_IN,
    exit |z|<Z_OUT; each leg pays HALF_SPREAD_BPS+FEE_BPS on entry and exit.
  - report IS and OOS: n_trades, gross bps/trade, net bps/trade, total net.

Run: python experiments/106_cointegration/cointegration.py --dates 2026-07-15,2026-07-16,2026-07-17,2026-07-18
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.stattools import adfuller, coint
    HAVE_SM = True
except Exception:
    HAVE_SM = False

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

ASSETS = ["HL_BTC", "HL_ETH", "HL_SOL", "HL_LINK", "HL_HYPE"]
BAR = "60s"
ROLL = 60                 # bars for the z-score window (=1h at 60s)
Z_IN, Z_OUT = 2.0, 0.5
HALF_SPREAD_BPS = 0.75    # per leg, per side (HL major ~1.5bps spread)
FEE_BPS = 1.4             # taker per leg per side
IS_FRAC = 0.6


def load_bars(asset, dates):
    frames = []
    for d in dates:
        p = PROC / f"quotes_{asset}_{d}.parquet"
        if not p.exists():
            continue
        q = pd.read_parquet(p, columns=["time_exchange", "bid_price", "ask_price"])
        q = q.sort_values("time_exchange").set_index("time_exchange")
        mid = (q["bid_price"] + q["ask_price"]) / 2.0
        frames.append(mid.resample(BAR).last())
    if not frames:
        return None
    s = pd.concat(frames).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return np.log(s.dropna())


def half_life(spread):
    s = spread.dropna()
    ds = s.diff().dropna()
    lag = s.shift(1).dropna().loc[ds.index]
    b = np.polyfit(lag.values, ds.values, 1)[0]
    return -np.log(2) / b if b < 0 else np.inf


def backtest(spread, z):
    """Long-spread when z<-Z_IN, short when z>Z_IN, flat at |z|<Z_OUT."""
    pos = 0
    entry = 0.0
    trades = []
    sp = spread.values
    zz = z.values
    for i in range(len(sp)):
        if np.isnan(zz[i]):
            continue
        if pos == 0:
            if zz[i] > Z_IN:
                pos = -1; entry = sp[i]
            elif zz[i] < -Z_IN:
                pos = 1; entry = sp[i]
        elif (pos == 1 and zz[i] > -Z_OUT) or (pos == -1 and zz[i] < Z_OUT):
            gross = pos * (sp[i] - entry) * 1e4     # bps (spread is log)
            cost = 2 * (HALF_SPREAD_BPS + FEE_BPS)  # both legs, entry+exit ~2x
            trades.append(gross - 2 * cost)         # 2 legs
            pos = 0
    arr = np.array(trades)
    if not len(arr):
        return {"n": 0}
    return {"n": int(len(arr)), "net_bps_mean": float(arr.mean()),
            "net_total_bps": float(arr.sum()), "win_rate": float((arr > 0).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    args = ap.parse_args()
    dates = args.dates.split(",")

    bars = {a: load_bars(a, dates) for a in ASSETS}
    bars = {a: b for a, b in bars.items() if b is not None and len(b) > 200}
    df = pd.DataFrame(bars).dropna()
    print(f"aligned bars: {len(df)} x {len(df.columns)} assets ({BAR})  "
          f"statsmodels={'yes' if HAVE_SM else 'NO — coint p-values skipped'}")

    results = {}
    for a, b in itertools.combinations(df.columns, 2):
        la, lb = df[a], df[b]
        beta = np.polyfit(lb.values, la.values, 1)[0]
        spread = la - beta * lb
        hl = half_life(spread)
        pval = float(coint(la, lb)[1]) if HAVE_SM else None
        adf_p = float(adfuller(spread.dropna())[1]) if HAVE_SM else None

        n = len(spread); cut = int(IS_FRAC * n)
        rec = {"beta": float(beta), "coint_p": pval, "adf_resid_p": adf_p,
               "half_life_bars": float(hl)}
        for tag, sl in [("IS", slice(0, cut)), ("OOS", slice(cut, n))]:
            sp = spread.iloc[sl]
            z = (sp - sp.rolling(ROLL).mean()) / sp.rolling(ROLL).std()
            rec[tag] = backtest(sp, z)
        results[f"{a}/{b}"] = rec
        oos = rec["OOS"]
        print(f"  {a[3:]:5s}/{b[3:]:5s} beta={beta:+.2f} coint_p={pval if pval is None else round(pval,3)} "
              f"HL={hl:6.1f}b  IS net={rec['IS'].get('net_bps_mean', float('nan')):+.1f}bps/t(n={rec['IS'].get('n',0)})  "
              f"OOS net={oos.get('net_bps_mean', float('nan')):+.1f}bps/t(n={oos.get('n',0)}) "
              f"tot={oos.get('net_total_bps', 0):+.0f}bps")

    with open(OUT / "cointegration.json", "w") as fh:
        json.dump({"bar": BAR, "n_bars": len(df), "assets": list(df.columns),
                   "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/cointegration.json")


if __name__ == "__main__":
    main()
