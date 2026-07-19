"""
funding_carry.py
================
Exp 107 — Cross-venue funding-spread carry (route F).

Hyperliquid runs persistently hotter funding than Binance over the captured
window. A delta-neutral book — SHORT HL perp, LONG Binance perp on the same
coin — collects HL funding, pays Binance funding, and the price legs cancel.
Net carry = HL_funding - Binance_funding, annualized.

This is CARRY, not microstructure alpha: compensation for warehousing basis
risk (the HL-Binance basis gaps during dislocations/cascades — exp 99 — and can
force liquidation if under-margined) and for funding-regime risk (the spread
compresses as arbs enter and can flip in stress). The number is gross of
borrow/margin/execution/rebalancing. Documented crypto basis trade; here
measured on captured HL funding + live Binance funding.

Run: python experiments/107_funding_carry/funding_carry.py
"""
from __future__ import annotations

import glob
import json
import ssl
import urllib.request
from datetime import date
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

PAIRS = [("HL_BTC", "BTCUSDT"), ("HL_ETH", "ETHUSDT"), ("HL_LINK", "LINKUSDT"),
         ("HL_SOL", "SOLUSDT")]


def hl_funding(asset):
    fs = sorted(glob.glob(str(PROC / f"funding_{asset}_2026-*.parquet")))
    if not fs:
        return None
    f = pd.concat([pd.read_parquet(x) for x in fs])["funding"].dropna()
    return f if len(f) else None


def binance_funding(sym):
    u = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=200"
    req = urllib.request.Request(u, headers={"User-Agent": "carry/1.0"})
    fr = json.load(urllib.request.urlopen(req, timeout=15, context=CTX))
    return np.array([float(x["fundingRate"]) for x in fr])


def main():
    rows = {}
    print(f"{'coin':6s} {'HL ann':>9s} {'%HL>0':>6s} {'Binance ann':>12s} "
          f"{'NET ann':>9s}")
    for hl, bn in PAIRS:
        f = hl_funding(hl)
        if f is None:
            continue
        hl_ann = float(f.mean() * 24 * 365 * 100)     # HL funds hourly
        frac_pos = float((f > 0).mean() * 100)
        br = binance_funding(bn)
        bn_ann = float(br.mean() * 3 * 365 * 100)      # Binance funds every 8h
        net = hl_ann - bn_ann
        rows[hl] = {"hl_ann_pct": round(hl_ann, 2), "hl_frac_pos": round(frac_pos, 1),
                    "binance_ann_pct": round(bn_ann, 2), "net_carry_ann_pct": round(net, 2)}
        print(f"{hl[3:]:6s} {hl_ann:+8.1f}% {frac_pos:5.0f}% {bn_ann:+11.1f}% "
              f"{net:+8.1f}%")

    out = {"date": date.today().isoformat(),
           "structure": "short HL perp / long Binance perp, delta-neutral",
           "caveats": "carry not alpha; gross of margin/borrow/execution; "
                      "basis-gap + funding-regime tail risk; short window",
           "rows": rows}
    with open(OUT / "funding_carry.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT}/funding_carry.json")


if __name__ == "__main__":
    main()
