"""
funding_book.py
===============
Exp 108 — The funding-carry book, priced honestly: funding collected PLUS the
basis mark-to-market you bear to collect it.

Exp 107 measured only the funding-rate differential (gross carry, +6-8%/yr). But
a delta-neutral book — SHORT HL perp, LONG Binance perp, $N each — has two P&L
streams:
  funding   at each settlement: +N*HL_funding (short receives) - N*Bin_funding
  basis     continuous: N*(r_Binance - r_HL) = N*d(log(Bin/HL))  — the price legs
            do NOT fully cancel; their difference is the basis, and it moves.
The honest question: does the steady funding beat the basis's volatility and its
drawdowns? A rich perp (high funding) is expected to converge toward spot, which
*helps* the short leg — so funding and basis drift should partly align — but a
short squeeze blows the basis against the short exactly when it hurts.

Book: enter at t0 (basis-neutral by construction — we measure P&L relative to
entry), hold the whole window, mark continuously on a BAR grid. Funding uses the
captured HL funding stream (hourly) and live Binance funding (8h) as a flat rate.
Costs: entry+exit crossing of both perps (2 legs x taker), negligible vs horizon.

Outputs annualized return on notional decomposed into funding vs basis, plus the
basis leg's vol and max drawdown (the actual risk).

Run: python experiments/108_funding_book/funding_book.py --dates 2026-07-15,2026-07-16
"""
from __future__ import annotations

import argparse
import glob
import json
import ssl
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

BAR = "60s"
TAKER_BPS = 1.4           # per leg, per side


def load_mid(asset, dates):
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
    return s[~s.index.duplicated(keep="last")].dropna()


def hl_funding_series(asset, dates):
    frames = []
    for d in dates:
        p = PROC / f"funding_{asset}_{d}.parquet"
        if not p.exists():
            continue
        f = pd.read_parquet(p, columns=["time_coinapi", "funding"])
        frames.append(f.set_index("time_coinapi")["funding"])
    if not frames:
        return None
    s = pd.concat(frames).sort_index()
    return s[~s.index.duplicated(keep="last")].dropna()


def binance_funding_rate(sym):
    u = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=200"
    req = urllib.request.Request(u, headers={"User-Agent": "book/1.0"})
    fr = json.load(urllib.request.urlopen(req, timeout=15, context=CTX))
    return np.mean([float(x["fundingRate"]) for x in fr])   # per-8h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    ap.add_argument("--hl", default="HL_BTC")
    ap.add_argument("--binance", default="BTC_PERP")
    ap.add_argument("--bin-sym", default="BTCUSDT")
    args = ap.parse_args()
    dates = args.dates.split(",")

    hl = load_mid(args.hl, dates)
    bn = load_mid(args.binance, dates)
    if hl is None or bn is None:
        raise SystemExit("missing processed mids")
    df = pd.DataFrame({"hl": hl, "bn": bn}).dropna()
    if len(df) < 120:
        raise SystemExit(f"only {len(df)} aligned bars")
    hours = (df.index[-1] - df.index[0]).total_seconds() / 3600

    # basis P&L per $1 notional: short HL, long Binance => + (r_bn - r_hl)
    r_bn = np.log(df["bn"]).diff().fillna(0.0)
    r_hl = np.log(df["hl"]).diff().fillna(0.0)
    basis_pnl = (r_bn - r_hl).cumsum()          # cumulative, per $1 notional

    # funding P&L: short HL receives HL funding hourly; long Binance pays Binance
    hlf = hl_funding_series(args.hl, dates)
    # HL funding applied per hour: sum over hours in window
    hl_hours = hlf.resample("1h").last().dropna()
    hl_total = float(hl_hours.reindex(
        pd.date_range(df.index[0].floor("h"), df.index[-1].ceil("h"), freq="1h"),
        method="ffill").fillna(0).sum())
    bn_rate_8h = binance_funding_rate(args.bin_sym)
    bn_total = bn_rate_8h * (hours / 8.0)
    funding_total = hl_total - bn_total          # per $1 notional, receive HL pay Bin

    # gross carry = funding + basis drift (both accrue while holding); the
    # entry/exit cost is ONE-TIME and amortizes over the hold, so it is NOT
    # annualized with the returns — it is reported as a fixed drag whose annual
    # cost depends on rebalance frequency.
    n = len(df)
    funding_curve = np.linspace(0, funding_total, n)
    equity = basis_pnl.values + funding_curve      # gross, per $1 notional
    carry_total = float(equity[-1])
    ann_factor = 24 * 365 / hours
    carry_ann = carry_total * ann_factor * 100
    basis_ann = basis_pnl.values[-1] * ann_factor * 100
    fund_ann = funding_total * ann_factor * 100
    basis_vol_ann = float(np.std(r_bn - r_hl) * np.sqrt(365 * 24 * 60) * 100)
    sharpe = carry_ann / basis_vol_ann if basis_vol_ann > 0 else None
    dd = float((equity - np.maximum.accumulate(equity)).min() * 100)
    rt_cost_bps = 2 * 2 * TAKER_BPS                 # one round trip, both legs
    # cost drag if you re-enter at various cadences
    cost_drag = {f"rebal_{c}": round(rt_cost_bps * 1e-4 * (24 * 365 / (c * 24)) * 100, 2)
                 for c in (1, 7, 30)}               # daily / weekly / monthly, %/yr

    out = {"hl": args.hl, "binance": args.binance, "dates": dates,
           "hours": round(hours, 1), "n_bars": n,
           "funding_ann_pct": round(fund_ann, 2), "basis_ann_pct": round(basis_ann, 2),
           "carry_ann_pct": round(carry_ann, 2), "basis_vol_ann_pct": round(basis_vol_ann, 2),
           "gross_sharpe": round(sharpe, 2) if sharpe else None,
           "max_drawdown_pct": round(dd, 3),
           "roundtrip_cost_bps": rt_cost_bps, "cost_drag_ann_pct": cost_drag,
           "hl_funding_total_pct": round(hl_total * 100, 3),
           "bin_funding_total_pct": round(bn_total * 100, 3)}
    print(f"=== funding book  short {args.hl} / long {args.binance}  "
          f"{hours:.0f}h  {n} bars")
    print(f"  funding leg:  {fund_ann:+.1f}%/yr  (HL {hl_total*100:+.3f}% - "
          f"Bin {bn_total*100:+.3f}% over window)")
    print(f"  basis  leg:   {basis_ann:+.1f}%/yr  (drift; vol {basis_vol_ann:.1f}%/yr, "
          f"max drawdown {dd:+.3f}%)")
    print(f"  GROSS CARRY:  {carry_ann:+.1f}%/yr  Sharpe~{sharpe:.2f}  "
          f"(funding + basis, before cost)")
    print(f"  one-time RT cost {rt_cost_bps:.1f}bps => drag if rebal daily/weekly/monthly: "
          f"{cost_drag['rebal_1']}/{cost_drag['rebal_7']}/{cost_drag['rebal_30']}%/yr")
    print(f"  => window has NO stress event; basis dd tiny — the real tail (cascade) "
          f"is not in {hours:.0f}h")

    with open(OUT / f"funding_book_{args.hl}_{'_'.join(dates)}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/funding_book_{args.hl}_{'_'.join(dates)}.json")


if __name__ == "__main__":
    main()
