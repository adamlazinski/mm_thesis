"""
fair_value_wide.py
==================
Exp 111 — Fair-value-anchored wide quoting: quote around an estimate of fair
value (not the mid) at a chosen distance, on the books that have room.

Motivation, from our own failures/results:
  * exp 103's defended maker died mechanically: MID-anchored quotes keep buying
    into a downtrend (mid lags), inventory pins at the cap. An anchor that LEADS
    the mid should skew away from the trend and cut that.
  * C58: dense books are 1-tick — "wider" means behind the touch, i.e. no fills.
    Only the route-5 tail books (9-56bps spreads, adverse-selection horizons >5s,
    exp 93) have room to place at a chosen distance.
  * Economic description: selling immediacy at a distance from fair value and
    being paid when price reverts (Grossman-Miller), with a better anchor.

Anchors (all causal, computed from data available at quote time):
  mid    (bid+ask)/2                                   — baseline
  micro  (bid*ask_sz + ask*bid_sz)/(bid_sz+ask_sz)     — Stoikov imbalance-weighted
  ewma   EWMA of trade prices (HALF_LIFE_S)            — where trades actually print
  blend  0.5*micro + 0.5*ewma

Quoting: bid = fair - k*half_ref, ask = fair + k*half_ref, where half_ref is a
rolling median half-spread of the book (so k is in units of the book's own
spread). k swept; k=1 is roughly "at the touch", k>1 is wider.

Accounting: the exp-103 round-trip inventory sim — position tracking, cash +
inv*mid, per-fill notional cap, inventory cap, fills from the tape with the
project-standard price-only + qf weight at price. NO mark-to-mid headline.

Run: python experiments/111_fair_value_wide/fair_value_wide.py \
        --date 2026-07-18 --asset HL_HMSTR
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

QF = 0.5
FILL_CAP_USD = 500.0
MAX_INV_USD = 2_000.0
QUOTE_TOL_S = 30.0            # tail books quote sparsely
HALF_LIFE_S = 30.0
KS = (0.5, 1.0, 1.5, 2.5)
ANCHORS = ("mid", "micro", "ewma", "blend")
MAKER_FEES_BPS = (1.5, 0.0, -0.3)


def load(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    sz = q["bid_size"] + q["ask_size"]
    q["micro"] = np.where(
        sz > 0,
        (q["bid_price"] * q["ask_size"] + q["ask_price"] * q["bid_size"]) / sz.replace(0, np.nan),
        q["mid"])
    q["half"] = (q["ask_price"] - q["bid_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    q = q[keep].reset_index(drop=True)
    tr = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    tr["ts"] = tr["time_exchange"].astype("int64").to_numpy() / 1e9
    tr["buy"] = tr["taker_side"].str.upper() == "BUY"
    tr["usd"] = tr["price"] * tr["size"]
    return q, tr


def trade_ewma(tr, qt, half_life_s):
    """Causal EWMA of trade prices, sampled onto the quote grid."""
    tts = tr["ts"].to_numpy(); tpx = tr["price"].to_numpy()
    out = np.full(len(tts), np.nan)
    val = None; last = None
    for i in range(len(tts)):
        if val is None:
            val = tpx[i]
        else:
            dt = max(tts[i] - last, 0.0)
            a = 1 - 0.5 ** (dt / half_life_s)
            val += a * (tpx[i] - val)
        last = tts[i]; out[i] = val
    idx = np.searchsorted(tts, qt, side="right") - 1
    res = np.full(len(qt), np.nan)
    ok = idx >= 0
    res[ok] = out[idx[ok]]
    return res


def simulate(q, tr, anchor_px, k, half_ref):
    """Round-trip inventory sim with quotes at anchor -/+ k*half_ref."""
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qm = q["mid"].to_numpy()
    tts = tr["ts"].to_numpy(); tpx = tr["price"].to_numpy()
    tbuy = tr["buy"].to_numpy(); tusd = tr["usd"].to_numpy()
    iq = np.searchsorted(qt, tts, side="right") - 1

    cash = 0.0; inv = 0.0; notional = 0.0; nf = 0.0
    max_inv = 0.0; min_eq = np.inf
    for kk in range(len(tts)):
        i = iq[kk]
        if i < 0 or (tts[kk] - qt[i]) > QUOTE_TOL_S:
            continue
        fair = anchor_px[i]
        if not np.isfinite(fair):
            continue
        hs = half_ref[i]
        if not np.isfinite(hs) or hs <= 0:
            continue
        bid = fair - k * hs
        ask = fair + k * hs
        mid = qm[i]
        inv_usd = inv * mid
        if tbuy[kk]:
            if inv_usd <= -MAX_INV_USD:
                continue
            if tpx[kk] > ask:
                w = 1.0
            elif abs(tpx[kk] - ask) <= 1e-9 * max(ask, 1.0):
                w = QF
            else:
                continue
            fill = min(tusd[kk], FILL_CAP_USD) * w
            inv -= fill / tpx[kk]; cash += fill
        else:
            if inv_usd >= MAX_INV_USD:
                continue
            if tpx[kk] < bid:
                w = 1.0
            elif abs(tpx[kk] - bid) <= 1e-9 * max(bid, 1.0):
                w = QF
            else:
                continue
            fill = min(tusd[kk], FILL_CAP_USD) * w
            inv += fill / tpx[kk]; cash -= fill
        notional += fill; nf += w
        eq = cash + inv * mid
        min_eq = min(min_eq, eq)
        max_inv = max(max_inv, abs(inv * mid))
    final = cash + inv * qm[-1]
    return {"gross_pnl": final, "notional": notional, "wfills": nf,
            "max_abs_inv_usd": max_inv,
            "min_equity": float(min_eq) if np.isfinite(min_eq) else None,
            "end_inv_usd": inv * qm[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", required=True)
    args = ap.parse_args()

    q, tr = load(args.asset, args.date)
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    hours = (qt[-1] - qt[0]) / 3600
    scale = 24 / hours
    # rolling median half-spread as the distance unit (causal)
    half_ref = pd.Series(q["half"].to_numpy()).rolling(200, min_periods=20).median().to_numpy()
    ewma_px = trade_ewma(tr, qt, HALF_LIFE_S)
    micro = q["micro"].to_numpy(); mid = q["mid"].to_numpy()
    anchors = {"mid": mid, "micro": micro, "ewma": ewma_px,
               "blend": 0.5 * micro + 0.5 * np.where(np.isnan(ewma_px), micro, ewma_px)}

    spread_bps = float(np.nanmedian(2 * q["half"] / q["mid"]) * 1e4)
    print(f"=== {args.asset} {args.date}  {hours:.1f}h  spread p50={spread_bps:.1f}bps  "
          f"trades={len(tr):,}")
    print(f"{'anchor':7s} {'k':>4s} {'fills/d':>8s} {'notional':>10s} "
          f"{'gross/day':>10s} {'bps':>7s} {'net@base':>9s} {'net@reb':>8s} {'max|inv|':>9s}")
    out = {"asset": args.asset, "date": args.date, "hours": round(hours, 2),
           "spread_bps": round(spread_bps, 2), "runs": {}}
    for name in ANCHORS:
        a = anchors[name]
        for k in KS:
            r = simulate(q, tr, a, k, half_ref)
            if r["notional"] <= 0:
                continue
            bps = 1e4 * r["gross_pnl"] / r["notional"]
            gd = r["gross_pnl"] * scale
            nets = {f"fee_{f:g}": (r["gross_pnl"] - f * 1e-4 * r["notional"]) * scale
                    for f in MAKER_FEES_BPS}
            out["runs"][f"{name}_k{k:g}"] = {
                "fills_per_day": round(r["wfills"] * scale, 1),
                "notional": round(r["notional"], 1),
                "gross_pnl_day": round(gd, 2), "bps_of_notional": round(bps, 2),
                "net_day": {kk: round(v, 2) for kk, v in nets.items()},
                "max_abs_inv_usd": round(r["max_abs_inv_usd"], 1),
                "end_inv_usd": round(r["end_inv_usd"], 1)}
            print(f"{name:7s} {k:>4g} {r['wfills']*scale:>8.1f} {r['notional']:>10,.0f} "
                  f"{gd:>+10.2f} {bps:>+7.2f} {nets['fee_1.5']:>+9.2f} "
                  f"{nets['fee_-0.3']:>+8.2f} {r['max_abs_inv_usd']:>9,.0f}")

    with open(OUT / f"fair_value_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/fair_value_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
