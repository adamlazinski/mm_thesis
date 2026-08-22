"""
regime_gated_maker.py
=====================
Exp 115 — The steelman of regime-aware market making: use the regime to govern
INVENTORY HOLDING, not per-fill selection.

Exp 114 showed a 30s-scale mean-reversion regime does not predict a maker's
per-fill markout — unsurprising, since a quote is exposed for seconds while the
regime lives on minutes. But there is a second, untested channel where the
timescales do match: a maker who is filled must WAREHOUSE the position, and the
Grossman-Miller premium is paid precisely when price reverts over that holding
window. Exp 103 died because trend flow filled the maker to its inventory cap and
price never came back; exp 111's immediacy premium works where it does come back.

So: quote only when the market is mean-reverting, stand down when it trends, and
price it with the ROUND-TRIP inventory simulation (the accounting that killed
exp 103 and exp 111's depth rule), not per-fill markout.

Gate: causal VR(k) on a trailing window of BAR-second bars (exp 114's estimator).
Quote when VR <= VR_MAX; suppress both sides otherwise. Ablated against ungated.

Run on the route-5 tail books, where the immediacy premium exists at all:
  python experiments/115_regime_gated_maker/regime_gated_maker.py \
      --date 2026-07-18 --asset HL_HMSTR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "experiments" / "111_fair_value_wide"))
sys.path.insert(0, str(ROOT / "experiments" / "114_regime_markout"))
import fair_value_wide as fvw          # noqa: E402
import regime_markout as rgm           # noqa: E402

BAR_S = 30.0
WIN_BARS = 60
VR_GATES = (0.9, 1.0, 1.1, None)       # None = ungated baseline
K_QUOTE = 1.0                          # quote distance, in median half-spreads
QUOTE_TOL_S = 30.0


def simulate_gated(q, tr, anchor_px, k, half_ref, vr_t, vr_max, qf=fvw.QF,
                   placebo_frac=None, seed=0):
    """fvw.simulate with a regime gate: skip fills while VR > vr_max."""
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qm = q["mid"].to_numpy()
    tts = tr["ts"].to_numpy(); tpx = tr["price"].to_numpy()
    tbuy = tr["buy"].to_numpy(); tusd = tr["usd"].to_numpy()
    iq = np.searchsorted(qt, tts, side="right") - 1

    rng = np.random.default_rng(seed)
    # placebo: stand down the same FRACTION of the time, at random, in blocks of
    # the same regime bar so the suppression has comparable serial structure
    keep_rand = None
    if placebo_frac is not None:
        blk = np.floor((tts - tts[0]) / BAR_S).astype(np.int64)
        nb = int(blk.max()) + 1
        keep_blk = rng.random(nb) < placebo_frac
        keep_rand = keep_blk[blk]

    cash = 0.0; inv = 0.0; notional = 0.0; nf = 0.0
    max_inv = 0.0; quoting = 0; total = 0
    for kk in range(len(tts)):
        i = iq[kk]
        if i < 0 or (tts[kk] - qt[i]) > QUOTE_TOL_S:
            continue
        total += 1
        if keep_rand is not None:
            if not keep_rand[kk]:
                continue                      # placebo stand-down
        elif vr_max is not None:
            v = vr_t[kk]
            if not np.isfinite(v) or v > vr_max:
                continue                      # stand down in trending regimes
        quoting += 1
        fair = anchor_px[i]
        hs = half_ref[i]
        if not (np.isfinite(fair) and np.isfinite(hs) and hs > 0):
            continue
        bid, ask = fair - k * hs, fair + k * hs
        mid = qm[i]
        inv_usd = inv * mid
        if tbuy[kk]:
            if inv_usd <= -fvw.MAX_INV_USD:
                continue
            if tpx[kk] > ask:
                w = 1.0
            elif abs(tpx[kk] - ask) <= 1e-9 * max(ask, 1.0):
                w = qf
            else:
                continue
            fill = min(tusd[kk], fvw.FILL_CAP_USD) * w
            inv -= fill / tpx[kk]; cash += fill
        else:
            if inv_usd >= fvw.MAX_INV_USD:
                continue
            if tpx[kk] < bid:
                w = 1.0
            elif abs(tpx[kk] - bid) <= 1e-9 * max(bid, 1.0):
                w = qf
            else:
                continue
            fill = min(tusd[kk], fvw.FILL_CAP_USD) * w
            inv += fill / tpx[kk]; cash -= fill
        notional += fill; nf += w
        max_inv = max(max_inv, abs(inv * qm[i]))
    return {"gross_pnl": cash + inv * qm[-1], "notional": notional,
            "wfills": nf, "max_abs_inv_usd": max_inv,
            "end_inv_usd": inv * qm[-1],
            "quoting_frac": quoting / max(total, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", required=True)
    ap.add_argument("--bar", type=float, default=BAR_S)
    ap.add_argument("--win", type=int, default=WIN_BARS)
    args = ap.parse_args()

    q, tr = fvw.load(args.asset, args.date)
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    hours = (qt[-1] - qt[0]) / 3600
    scale = 24 / hours

    rgm.BAR_S, rgm.WIN_BARS = args.bar, args.win
    bars_t, vr, _ac = rgm.regime_series(qt, q["mid"].to_numpy())
    vr_t = rgm.asof(bars_t, vr, tr["ts"].to_numpy(), tol=5 * args.bar)

    half_ref = pd.Series(q["half"].to_numpy()).rolling(
        200, min_periods=20).median().to_numpy()
    micro = q["micro"].to_numpy()

    print(f"=== {args.asset} {args.date}  {hours:.1f}h  "
          f"regime bar={args.bar:g}s win={args.win}  anchor=micro k={K_QUOTE:g}")
    print(f"    VR distribution: p10={np.nanpercentile(vr,10):.2f} "
          f"p50={np.nanpercentile(vr,50):.2f} p90={np.nanpercentile(vr,90):.2f}")
    print(f"{'gate':>10s} {'quoting%':>9s} {'fills/day':>10s} {'notional':>10s} "
          f"{'gross/day':>10s} {'bps':>8s}")
    out = {"asset": args.asset, "date": args.date, "hours": round(hours, 2),
           "bar_s": args.bar, "win_bars": args.win, "runs": {}}
    runs = [("gate", g) for g in VR_GATES]
    for kind, g in runs:
        r = simulate_gated(q, tr, micro, K_QUOTE, half_ref, vr_t, g)
        if r["notional"] <= 0:
            continue
        bps = 1e4 * r["gross_pnl"] / r["notional"]
        lab = "ungated" if g is None else f"VR<={g:g}"
        if g is not None:
            # matched-frequency placebo: same quoting fraction, random timing
            pl = [simulate_gated(q, tr, micro, K_QUOTE, half_ref, vr_t, None,
                                 placebo_frac=r["quoting_frac"], seed=s_)
                  for s_ in range(8)]
            pl_bps = float(np.mean([1e4*x["gross_pnl"]/x["notional"]
                                    for x in pl if x["notional"] > 0]))
            pl_day = float(np.mean([x["gross_pnl"]*scale for x in pl]))
            out.setdefault("placebo", {})[lab] = {"bps": round(pl_bps, 2),
                                                  "pnl_day": round(pl_day, 2)}
        out["runs"][lab] = {"quoting_frac": round(r["quoting_frac"], 3),
                            "fills_per_day": round(r["wfills"] * scale, 1),
                            "notional": round(r["notional"], 1),
                            "gross_pnl_day": round(r["gross_pnl"] * scale, 2),
                            "bps_of_notional": round(bps, 2),
                            "max_abs_inv_usd": round(r["max_abs_inv_usd"], 1)}
        extra = ""
        if g is not None:
            pb = out["placebo"][lab]
            extra = f"   placebo: {pb['pnl_day']:+.0f}$/d {pb['bps']:+.2f}bps"
        print(f"{lab:>10s} {r['quoting_frac']*100:>8.0f}% {r['wfills']*scale:>10.1f} "
              f"{r['notional']:>10,.0f} {r['gross_pnl']*scale:>+10.2f} {bps:>+8.2f}{extra}")

    with open(OUT / f"regime_gated_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/regime_gated_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
