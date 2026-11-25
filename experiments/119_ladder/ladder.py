"""
ladder.py
=========
Exp 119 — Multi-level (ladder) quoting: does posting at several distances at
once change the verdict?

The hypothesis register carried this as an outstanding gap: every simulation in
this thesis quotes a SINGLE order per side, and a real maker ladders. The
register's prior is that it changes nothing, because the queue-priority argument
of C29/C30 applies at each level independently — a ladder is N single-level
quotes, each with its own queue, not a way around the queue. This tests that.

Design: N levels per side at k = k_0, k_0 + step, ... from the fair-value
anchor, each carrying `size_mult^level` of the base clip (so a flat ladder and a
front-loaded ladder are both reachable). N = 1 is exactly exp 111 and is the
control. Inventory is capped across the WHOLE ladder, not per level, which is
what a real risk limit does.

Accounting is exp 111's, unchanged: venue tick grid (each level snapped
independently, and levels that collide after snapping are dropped — on a
one-tick book a ladder has nowhere to go, which is itself the finding),
post-only, per-fill notional cap, average-cost matched-volume P&L, and terminal
residual liquidated at the closing touch.

Run: python experiments/119_ladder/ladder.py --asset HL_HMSTR --date 2026-07-18
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hft_market_maker import terminal_accounting as ta

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

QF = 0.5
FILL_CAP_USD = 500.0
MAX_INV_USD = 2_000.0
QUOTE_TOL_S = 30.0            # tail books quote sparsely
HALF_LIFE_S = 30.0
LADDERS = ((1, 0.0, 1.0), (2, 0.5, 1.0), (3, 0.5, 1.0), (5, 0.5, 1.0),
           (3, 1.0, 1.0), (3, 0.5, 0.5))   # (n_levels, step, size_mult)
ANCHORS = ("mid", "micro")
K0 = 1.0
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


def infer_tick(q):
    """
    The venue's price grid, recovered from the day's own quotes as the GCD of
    the gaps between distinct observed prices.

    This is not cosmetic. Contribution 54 retracted an entire arc of this
    thesis because a strategy had been quoting at prices the exchange's grid
    did not contain, and the same error reappears here the moment a continuous
    fair-value anchor is used without snapping to the grid. On HMSTR the tick
    is ~56 bps -- the whole quoted spread is ONE tick -- so an unrounded quote
    at `anchor +/- k*half_spread` sits at a price that cannot be submitted.
    """
    from math import gcd
    px = np.unique(np.round(np.concatenate(
        [q["bid_price"].to_numpy(float), q["ask_price"].to_numpy(float)]), 12))
    d = np.diff(px); d = d[d > 0]
    if len(d) == 0:
        return None
    for scale in (10 ** e for e in range(0, 13)):
        sd = d * scale
        r = np.round(sd)
        if np.allclose(sd, r, atol=1e-6) and r.min() >= 1:
            g = 0
            for v in np.unique(r).astype(np.int64)[:4000]:
                g = gcd(g, int(v))
            return g / scale
    return None




def simulate(q, tr, anchor_px, half_ref, n_levels, step, size_mult, tick=None):
    """
    Ladder sim: n_levels per side at k0, k0+step, k0+2*step, ... from the
    anchor, each sized size_mult**level of the base clip.

    Every level is snapped to the venue grid independently and levels that
    collapse onto the same price afterwards are dropped, because the exchange
    would hold one order there, not two. On a one-tick book that reduces the
    whole ladder to its first level, which is the point: a ladder needs a grid
    fine enough to have distinct places to stand.

    The inventory cap applies across the ladder, not per level.
    """
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qm = q["mid"].to_numpy()
    qb = q["bid_price"].to_numpy(); qa = q["ask_price"].to_numpy()
    tts = tr["ts"].to_numpy(); tpx = tr["price"].to_numpy()
    tbuy = tr["buy"].to_numpy(); tusd = tr["usd"].to_numpy()
    iq = np.searchsorted(qt, tts, side="right") - 1

    cash = 0.0; inv = 0.0; notional = 0.0; nf = 0.0
    avg_px = 0.0; realized = 0.0
    max_inv = 0.0; min_eq = np.inf
    levels_live = []            # distinct levels actually postable, per quote
    n_collapsed = 0; n_quotes = 0

    for kk in range(len(tts)):
        i = iq[kk]
        if i < 0 or (tts[kk] - qt[i]) > QUOTE_TOL_S:
            continue
        fair = anchor_px[i]; hs = half_ref[i]
        if not np.isfinite(fair) or not np.isfinite(hs) or hs <= 0:
            continue

        # build the ladder, snap each level, drop duplicates and crossers
        bids, asks = [], []
        seen_b, seen_a = set(), set()
        for lv in range(n_levels):
            k = K0 + step * lv
            w_sz = size_mult ** lv
            b = fair - k * hs
            a = fair + k * hs
            if tick:
                b = np.floor(b / tick + 1e-9) * tick
                a = np.ceil(a / tick - 1e-9) * tick
            if b < qa[i] and b not in seen_b:
                seen_b.add(b); bids.append((b, w_sz))
            if a > qb[i] and a not in seen_a:
                seen_a.add(a); asks.append((a, w_sz))
        n_quotes += 1
        n_collapsed += (n_levels - max(len(bids), len(asks)))
        levels_live.append(max(len(bids), len(asks)))
        if not bids and not asks:
            continue

        mid = qm[i]
        inv_usd = inv * mid
        if tbuy[kk]:
            if inv_usd <= -MAX_INV_USD:
                continue
            book_side = asks
            hit = [(px, w) for px, w in book_side
                   if tpx[kk] > px or abs(tpx[kk] - px) <= 1e-9 * max(px, 1.0)]
            if not hit:
                continue
            # a taker buy sweeping up fills the lowest asks first
            hit.sort()
            # the per-fill notional budget is the SAME across ladder depths --
            # a maker with a fixed risk limit splits one clip over its levels
            # rather than posting a full clip at each. Without this the first
            # level absorbs the whole budget and the ladder cannot be tested.
            tot_w = sum(x[1] for x in asks) or 1.0
            remaining = min(tusd[kk], FILL_CAP_USD)
            for px, w_sz in hit:
                if remaining <= 0:
                    break
                w = 1.0 if tpx[kk] > px else QF
                fill = min(remaining, FILL_CAP_USD * w_sz / tot_w) * w
                if fill <= 0:
                    continue
                remaining -= fill
                inv, avg_px, dr = ta.book(inv, avg_px, -fill / px, px)
                realized += dr; cash += fill
                notional += fill; nf += w
        else:
            if inv_usd >= MAX_INV_USD:
                continue
            hit = [(px, w) for px, w in bids
                   if tpx[kk] < px or abs(tpx[kk] - px) <= 1e-9 * max(px, 1.0)]
            if not hit:
                continue
            hit.sort(reverse=True)      # a taker sell sweeps down, highest bids first
            tot_w = sum(x[1] for x in bids) or 1.0
            remaining = min(tusd[kk], FILL_CAP_USD)
            for px, w_sz in hit:
                if remaining <= 0:
                    break
                w = 1.0 if tpx[kk] < px else QF
                fill = min(remaining, FILL_CAP_USD * w_sz / tot_w) * w
                if fill <= 0:
                    continue
                remaining -= fill
                inv, avg_px, dr = ta.book(inv, avg_px, fill / px, px)
                realized += dr; cash -= fill
                notional += fill; nf += w

        eq = cash + inv * mid
        min_eq = min(min_eq, eq)
        max_inv = max(max_inv, abs(inv * mid))

    out = {"notional": notional, "wfills": nf, "max_abs_inv_usd": max_inv,
           "min_equity": float(min_eq) if np.isfinite(min_eq) else None,
           "tick": tick, "n_levels_nominal": n_levels,
           "mean_levels_postable": (float(np.mean(levels_live))
                                    if levels_live else None)}
    out.update(ta.terminal(cash, inv, avg_px, realized, qb[-1], qa[-1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", required=True)
    args = ap.parse_args()

    q, tr = load(args.asset, args.date)
    if q is None or tr is None or len(tr) < 50:
        print(f"=== {args.asset} {args.date}: insufficient data, skipping")
        return
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    hours = (qt[-1] - qt[0]) / 3600
    scale = 24.0 / hours if hours > 0 else 1.0

    q["half"] = (q["ask_price"] - q["bid_price"]) / 2.0
    half_ref = q["half"].rolling(200, min_periods=20).median().to_numpy()
    spread_bps = float(np.nanmedian(2 * q["half"] / q["mid"]) * 1e4)
    tick = infer_tick(q)
    tick_bps = (1e4 * tick / float(np.nanmedian(q["mid"]))) if tick else float("nan")

    anchors = {"mid": q["mid"].to_numpy(),
               "micro": ((q["bid_price"] * q["ask_size"] + q["ask_price"] * q["bid_size"])
                         / (q["bid_size"] + q["ask_size"])).to_numpy()}

    print(f"=== {args.asset} {args.date}  {hours:.1f}h  spread p50={spread_bps:.1f}bps  "
          f"tick={tick:g} ({tick_bps:.2f}bps, spread={spread_bps/tick_bps:.1f} ticks)")
    print(f"{'anchor':7s} {'ladder':16s} {'live_lvls':>10s} {'fills/d':>8s} {'notional':>10s} "
          f"{'bps_liq':>8s} {'bps_real':>9s} {'$/day_liq':>10s}")
    out = {"asset": args.asset, "date": args.date, "hours": round(hours, 2),
           "spread_bps": round(spread_bps, 2), "tick": tick,
           "tick_bps": round(tick_bps, 3), "k0": K0, "runs": {}}

    for aname, apx in anchors.items():
        for (n, step, sm) in LADDERS:
            r = simulate(q, tr, apx, half_ref, n, step, sm, tick=tick)
            if r["notional"] <= 0:
                continue
            rec = {"n_levels": n, "step": step, "size_mult": sm,
                   "mean_levels_postable": (round(r["mean_levels_postable"], 2)
                                            if r["mean_levels_postable"] else None),
                   "fills_per_day": round(r["wfills"] * scale, 1),
                   "notional": round(r["notional"], 1),
                   "gross_pnl_liq_day": round(r["gross_pnl_liq"] * scale, 2),
                   "max_abs_inv_usd": round(r["max_abs_inv_usd"], 1),
                   "end_inv_usd": round(r["end_inv_usd"], 1)}
            rec.update(ta.bps_split(r, r["notional"]))
            tag = f"n{n}_step{step:g}_sz{sm:g}"
            out["runs"][f"{aname}_{tag}"] = rec
            ctrl = "  <-- control (single order)" if n == 1 else ""
            print(f"{aname:7s} {tag:16s} {(rec['mean_levels_postable'] or 0):>10.2f} "
                  f"{rec['fills_per_day']:>8.1f} {rec['notional']:>10,.0f} "
                  f"{rec['rt_bps_liq']:>+8.2f} {rec['rt_bps_realized']:>+9.2f} "
                  f"{rec['gross_pnl_liq_day']:>+10.2f}{ctrl}")

    with open(OUT / f"ladder_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/ladder_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
