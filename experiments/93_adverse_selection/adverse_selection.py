"""
adverse_selection.py
====================
Exp 93 — model-free Glosten-Milgrom / Hasbrouck spread decomposition of the
captured tape (all four books, per day). No engine, no queue_fraction, no
strategy: this is a property of the trades+quotes stream, not of any quoter.

For every market trade, taken from the perspective of the resting maker it
executes against (a taker-BUY lifts the ask => the ask-maker SOLD, D=+1; a
taker-SELL hits the bid => the bid-maker BOUGHT, D=-1):

    effective_half(t) = D * (price - mid_t)              gross edge at fill
    impact_half(t,h)  = D * (mid_{t+h} - mid_t)          adverse-selection drift
    realized_half(t,h)= effective - impact = D*(price - mid_{t+h})  what maker keeps

mid_t is the prevailing top-of-book mid at or just before the trade; mid_{t+h}
is the prevailing mid h seconds later (as-of, backward). Reported per book in
ticks, bps of mid, and $ per unit, per-trade and size-weighted, across horizons.

The C33 reading: at equilibrium realized_half -> ~0 as h grows (impact eats the
whole effective spread). The horizon where realized crosses zero is the
adverse-selection horizon; realized(h)*2 in bps vs the maker fee is the fee gate.

Run: python experiments/93_adverse_selection/adverse_selection.py --date 2026-07-11
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

PROC = ROOT / "data" / "live" / "processed"

# processed-parquet stem -> tick size
INSTRUMENTS = {
    "LINK":      0.001,
    "BTC":       0.01,
    "LINK_PERP": 0.001,
    "BTC_PERP":  0.10,
    # cross-venue wide books (July 2026 capture)
    "HL_LINK":      0.001,
    "CB_LINK_PERP": 0.001,
}
HORIZONS = (0.015, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0, 10.0)
QUOTE_TOL = pd.Timedelta("0.5s")   # prevailing quote must be this fresh
CAP_TICKS = 5.0                    # drop trades matched to a stale/crossed mid


def _asof_mid(times: pd.Series, q: pd.DataFrame) -> np.ndarray:
    """Prevailing mid at each time, requiring a quote within QUOTE_TOL (else NaN)."""
    left = pd.DataFrame({"time_exchange": times.to_numpy()})
    left = left.sort_values("time_exchange")
    m = pd.merge_asof(left, q, on="time_exchange", direction="backward",
                      tolerance=QUOTE_TOL)
    # restore original order
    return m["mid"].to_numpy()[np.argsort(left.index.to_numpy(), kind="stable")]


def decompose(trades: pd.DataFrame, quotes: pd.DataFrame, tick: float):
    q = quotes[["time_exchange", "bid_price", "ask_price"]].copy()
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    q = q[["time_exchange", "mid"]].sort_values("time_exchange").reset_index(drop=True)

    t = trades[["time_exchange", "price", "size", "taker_side"]].copy()
    t = t.sort_values("time_exchange").reset_index(drop=True)
    D = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    price = t["price"].to_numpy()
    sz = t["size"].to_numpy()

    mid_t = _asof_mid(t["time_exchange"], q)
    eff = D * (price - mid_t)                         # effective half-spread ($)

    # clean population: fresh two-sided quote AND executed at/near the touch
    base = ~np.isnan(mid_t) & (np.abs(eff) <= CAP_TICKS * tick)
    out = {"n_trades": int(len(t)),
           "n_clean": int(base.sum()),
           "clean_frac": float(base.mean()),
           "mean_mid": float(np.nanmedian(mid_t[base]))}

    def agg(x, mask):
        xs, w, mid = x[mask], sz[mask], mid_t[mask]
        if len(xs) == 0:
            return None
        mean_d = float(np.average(xs))
        wmean_d = float(np.average(xs, weights=w)) if w.sum() > 0 else mean_d
        return {
            "ticks": mean_d / tick,
            "bps": float(1e4 * np.average(xs / mid)),
            "usd_per_unit": mean_d,
            "sw_ticks": wmean_d / tick,
            "sw_bps": float(1e4 * np.average(xs / mid, weights=w)) if w.sum() > 0 else None,
        }

    effective, realized, impact = {}, {}, {}
    for h in HORIZONS:
        mid_h = _asof_mid(t["time_exchange"] + pd.to_timedelta(h, unit="s"), q)
        mask = base & ~np.isnan(mid_h)                # same sample for the identity
        imp = D * (mid_h - mid_t)
        rea = D * (price - mid_h)
        effective[str(h)] = agg(eff, mask)            # eff on the per-h sample
        impact[str(h)] = agg(imp, mask)
        realized[str(h)] = agg(rea, mask)             # == effective - impact exactly
    out["effective_half"] = effective
    out["impact_half"] = impact
    out["realized_half"] = realized

    # adverse-selection horizon: linear interpolation of realized_half(ticks)=0
    # between the last positive-realized horizon and the first non-positive one.
    adv_h = None
    prev_h, prev_r = None, None
    for h in HORIZONS:
        r = realized[str(h)]
        if r is None:
            continue
        cur = r["ticks"]
        if cur <= 0:
            if prev_r is not None and prev_r > 0:
                # crossing is between prev_h (positive) and h (<=0)
                frac = prev_r / (prev_r - cur)
                adv_h = float(prev_h + frac * (h - prev_h))
            else:
                # already negative at the first measured horizon
                adv_h = float(h)
            break
        prev_h, prev_r = h, cur
    out["adverse_selection_horizon_s"] = adv_h
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    results = {}
    for stem, tick in INSTRUMENTS.items():
        tp = PROC / f"trades_{stem}_{args.date}.parquet"
        qp = PROC / f"quotes_{stem}_{args.date}.parquet"
        if not tp.exists() or not qp.exists():
            print(f"=== {stem}: missing parquet, skipping")
            continue
        print(f"=== {stem} {args.date}")
        tr = pd.read_parquet(tp)
        qt = pd.read_parquet(qp)
        r = decompose(tr, qt, tick)
        results[stem] = r
        eff = r["effective_half"]["1.0"]
        r1 = r["realized_half"]["1.0"]
        r5 = r["realized_half"]["5.0"]
        i5 = r["impact_half"]["5.0"]
        print(f"  eff_half={eff['ticks']:.3f}t ({eff['bps']:.3f}bps)  "
              f"realized@1s={r1['ticks']:+.3f}t ({r1['bps']:+.3f}bps)  "
              f"realized@5s={r5['ticks']:+.3f}t ({r5['bps']:+.3f}bps)  "
              f"impact@5s={i5['ticks']:.3f}t  "
              f"adv_h={r['adverse_selection_horizon_s']}s  "
              f"clean={r['clean_frac']*100:.0f}%  n={r['n_trades']:,}")

    with open(OUT / f"adverse_selection_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "horizons": list(HORIZONS),
                   "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/adverse_selection_{args.date}.json")


if __name__ == "__main__":
    main()
