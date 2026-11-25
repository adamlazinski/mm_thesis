"""
patient_exit.py
===============
Exp 118 — The patient exit: after a fill, does holding out for a WIDER price on
the unwinding side beat flattening at the normal distance?

The rule, in the form it was asked in: quote the bid 1x the reference
half-spread from fair value; when it is hit, place the ask 3x out and wait.
Symmetrically for a short. Nothing else changes.

This is the opposite of what Avellaneda-Stoikov does. A-S skews the reservation
price AGAINST inventory, which pulls the exit side CLOSER to the mid to offload
faster and pushes the adding side away — it pays to flatten. The rule here pays
to wait instead, which in A-S terms is a NEGATIVE gamma. The project's gamma
sweeps span 5e-5 to 3.7e4 and are all positive, so this quadrant of the
parameter space has never been sampled.

It is a bet on mean reversion over the holding interval. C16 found LINK's
profitable configuration is a mean-reversion cycler with ~1,800 inventory sign
changes a day, which is exactly the regime where waiting ought to pay; whether
it survives the inventory risk that waiting adds is the question.

Two readings of "3x from the same mid", both run because they differ:
  floating  exit = current_anchor +/- k_out*half_ref   (target follows the mid)
  anchored  exit = anchor_at_fill +/- k_out*half_ref   (target fixed where the
                                                        fill happened)
`k_out = k_in` is the symmetric control and reproduces exp 111's behaviour.

Accounting is exp 111's, unchanged and honest by construction: venue tick grid,
post-only, per-fill notional cap, inventory cap, average-cost matched-volume
P&L, and the terminal residual liquidated across the closing spread
(hft_market_maker.terminal_accounting).

Run: python experiments/118_patient_exit/patient_exit.py --asset HL_HMSTR --date 2026-07-18
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
K_IN = 1.0                     # entry distance, in reference half-spreads
K_OUTS = (1.0, 2.0, 3.0, 4.0)  # exit distance; 1.0 is the symmetric control
ANCHORS = ("mid", "micro")
MODES = ("floating", "anchored")
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




def simulate(q, tr, anchor_px, k_in, k_out, half_ref, tick=None, mode="floating"):
    """
    Round-trip sim with an asymmetric, inventory-state-dependent exit distance.

    Flat        : bid and ask both at k_in * half_ref from the anchor.
    Long  (q>0) : the ASK (the unwinding side) moves to k_out * half_ref; the
                  bid stays at k_in, so the strategy may still add.
    Short (q<0) : mirrored.

    `mode="floating"` measures the exit from the CURRENT anchor, so the target
    follows the mid. `mode="anchored"` fixes it at the anchor observed when the
    position was opened, so the target stays where the fill happened and the
    strategy is genuinely waiting for a price rather than for a spread.

    k_out == k_in is the symmetric control.
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
    open_anchor = np.nan          # anchor when the current position was opened
    n_rejected = 0; n_quoted = 0
    hold_s = 0.0; n_holds = 0; t_open = None   # how long positions are carried

    for kk in range(len(tts)):
        i = iq[kk]
        if i < 0 or (tts[kk] - qt[i]) > QUOTE_TOL_S:
            continue
        fair = anchor_px[i]
        hs = half_ref[i]
        if not np.isfinite(fair) or not np.isfinite(hs) or hs <= 0:
            continue

        # exit-side reference: current anchor, or the one at position open
        exit_ref = fair
        if mode == "anchored" and inv != 0.0 and np.isfinite(open_anchor):
            exit_ref = open_anchor

        if inv > 0:                      # long: ask is the exit, bid still adds
            bid = fair - k_in * hs
            ask = exit_ref + k_out * hs
        elif inv < 0:                    # short: bid is the exit
            bid = exit_ref - k_out * hs
            ask = fair + k_in * hs
        else:
            bid = fair - k_in * hs
            ask = fair + k_in * hs

        if tick:
            bid = np.floor(bid / tick + 1e-9) * tick
            ask = np.ceil(ask / tick - 1e-9) * tick
        n_quoted += 1
        bid_ok = bid < qa[i]
        ask_ok = ask > qb[i]
        if not (bid_ok or ask_ok):
            n_rejected += 1
            continue

        mid = qm[i]
        inv_usd = inv * mid
        prev_inv = inv
        if tbuy[kk]:
            if inv_usd <= -MAX_INV_USD or not ask_ok:
                continue
            if tpx[kk] > ask:
                w = 1.0
            elif abs(tpx[kk] - ask) <= 1e-9 * max(ask, 1.0):
                w = QF
            else:
                continue
            fill = min(tusd[kk], FILL_CAP_USD) * w
            inv, avg_px, dr = ta.book(inv, avg_px, -fill / tpx[kk], tpx[kk])
            realized += dr; cash += fill
        else:
            if inv_usd >= MAX_INV_USD or not bid_ok:
                continue
            if tpx[kk] < bid:
                w = 1.0
            elif abs(tpx[kk] - bid) <= 1e-9 * max(bid, 1.0):
                w = QF
            else:
                continue
            fill = min(tusd[kk], FILL_CAP_USD) * w
            inv, avg_px, dr = ta.book(inv, avg_px, fill / tpx[kk], tpx[kk])
            realized += dr; cash -= fill
        notional += fill; nf += w

        # track the open anchor and the holding time
        if prev_inv == 0.0 and inv != 0.0:
            open_anchor = fair; t_open = tts[kk]
        elif inv == 0.0 and prev_inv != 0.0:
            if t_open is not None:
                hold_s += tts[kk] - t_open; n_holds += 1
            open_anchor = np.nan; t_open = None
        elif prev_inv != 0.0 and (inv > 0) != (prev_inv > 0):
            if t_open is not None:
                hold_s += tts[kk] - t_open; n_holds += 1
            open_anchor = fair; t_open = tts[kk]

        eq = cash + inv * mid
        min_eq = min(min_eq, eq)
        max_inv = max(max_inv, abs(inv * mid))

    out = {"notional": notional, "wfills": nf, "max_abs_inv_usd": max_inv,
           "min_equity": float(min_eq) if np.isfinite(min_eq) else None,
           "postonly_reject_frac": (n_rejected / n_quoted) if n_quoted else None,
           "tick": tick, "n_round_trips": n_holds,
           "mean_hold_s": (hold_s / n_holds) if n_holds else None}
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

    anchors = {
        "mid": q["mid"].to_numpy(),
        "micro": ((q["bid_price"] * q["ask_size"] + q["ask_price"] * q["bid_size"])
                  / (q["bid_size"] + q["ask_size"])).to_numpy(),
    }

    print(f"=== {args.asset} {args.date}  {hours:.1f}h  spread p50={spread_bps:.1f}bps  "
          f"tick={tick:g} ({tick_bps:.2f}bps, spread={spread_bps/tick_bps:.1f} ticks)")
    print(f"{'anchor':7s} {'mode':9s} {'k_out':>6s} {'fills/d':>8s} {'notional':>10s} "
          f"{'bps_liq':>8s} {'bps_real':>9s} {'$/day_liq':>10s} {'trips':>6s} {'hold_s':>8s}")
    out = {"asset": args.asset, "date": args.date, "hours": round(hours, 2),
           "spread_bps": round(spread_bps, 2), "tick": tick,
           "tick_bps": round(tick_bps, 3), "k_in": K_IN, "runs": {}}

    for aname, apx in anchors.items():
        for mode in MODES:
            for ko in K_OUTS:
                if mode == "anchored" and ko == K_IN:
                    continue            # identical to floating at k_out == k_in
                r = simulate(q, tr, apx, K_IN, ko, half_ref, tick=tick, mode=mode)
                if r["notional"] <= 0:
                    continue
                rec = {"fills_per_day": round(r["wfills"] * scale, 1),
                       "notional": round(r["notional"], 1),
                       "gross_pnl_liq_day": round(r["gross_pnl_liq"] * scale, 2),
                       "gross_pnl_day": round(r["gross_pnl"] * scale, 2),
                       "n_round_trips": r["n_round_trips"],
                       "mean_hold_s": (round(r["mean_hold_s"], 1)
                                       if r["mean_hold_s"] else None),
                       "max_abs_inv_usd": round(r["max_abs_inv_usd"], 1),
                       "end_inv_usd": round(r["end_inv_usd"], 1),
                       "postonly_reject_frac": (round(r["postonly_reject_frac"], 4)
                                                if r["postonly_reject_frac"] is not None else None)}
                rec.update(ta.bps_split(r, r["notional"]))
                key = f"{aname}_{mode}_kout{ko:g}"
                out["runs"][key] = rec
                print(f"{aname:7s} {mode:9s} {ko:>6g} {rec['fills_per_day']:>8.1f} "
                      f"{rec['notional']:>10,.0f} {rec['rt_bps_liq']:>+8.2f} "
                      f"{rec['rt_bps_realized']:>+9.2f} {rec['gross_pnl_liq_day']:>+10.2f} "
                      f"{rec['n_round_trips']:>6d} "
                      f"{(rec['mean_hold_s'] if rec['mean_hold_s'] else 0):>8.1f}")

    with open(OUT / f"patient_exit_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/patient_exit_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
