"""
consensus_maker.py
==================
Exp 100 — The maker expression of the exp 99 alpha: instead of paying taker
fees to chase an HL dislocation, stand on the receiving side of it.

When HL_BTC dislocates below CEX consensus (dev > +thr), HL's stale/momentum
sellers keep hitting bids while the price converges up. A consensus-pegged
maker posts a bid there and is *paid* the dislocation: entry below consensus,
maker fee (or rebate) instead of taker fee on the entry leg. Symmetric for
dev < -thr with an ask. This is what a prop desk would actually run — "be the
fast maker on the slow venue" — and unlike the generic route-3 objection, the
other makers' slowness here is measured (exp 99), not assumed.

Honest mechanics, no engine (the HL tape carries every trade):
  EVENT   exp-99 dev series (leader mid vs HL mid, EWMA-detrended basis);
          |dev| > thr opens, re-arms at thr/2.
  POST    at t0 + REACT_S, join the prevailing best bid (dev>0) / best ask
          (dev<0). No book improvement is assumed (v1; improving when the
          spread allows would only raise fill rates).
  FILL    the project's standard price-only convention with a queue haircut:
          a taker SELL printing strictly BELOW our bid fills us in full
          (level swept); a print AT our price fills us with queue_fraction=0.5
          weight on its volume. (v1 used strictly-below only and isolated the
          winner's curse perfectly: 1% fill rate, 8% hit — the maker filled
          only when the convergence failed. Kept in git history as a result in
          its own right.)
  LIFE    order lives until the event closes (|dev| < thr/2) or MAX_LIFE_S.
          Unfilled -> cancel, zero cost.
  EXIT    cross the HL touch at t_fill + H (same accounting as exp 99's exit;
          hedging the fill on Binance perp instead is a later refinement).
  FEES    entry maker tiers {1.5, 0.0, -0.3}bps (HL base -> top rebate),
          exit taker tiers {4.5, 1.4}bps.

Run: python experiments/100_consensus_maker/consensus_maker.py --date 2026-07-15 \
         --leader BTC_PERP --laggard HL_BTC
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

EWMA_HL_S = 60.0
REACT_S = 0.25
THRESHOLDS_BPS = (2.0, 5.0, 10.0)
H_EXIT_S = 5.0
MAX_LIFE_S = 10.0
MAKER_FEES_BPS = (1.5, 0.0, -0.3)
TAKER_FEES_BPS = (4.5, 1.4)
CAPS_USD = (1_000.0, 10_000.0)
QUOTE_TOL_S = 5.0
QUEUE_FRACTION = 0.5      # weight on tape volume printing AT our price


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def load_trades(asset, date):
    t = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    return t


def dev_series(tl, ml, tg, mg):
    t_all = np.concatenate([tl, tg])
    venue = np.concatenate([np.zeros(len(tl), int), np.ones(len(tg), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]
    out_t = np.empty(len(t_all)); out_d = np.empty(len(t_all))
    cur = [ml[0], mg[0]]; i_l = i_g = 0
    base = ml[0] - mg[0]; last_t = t_all[0]
    for k, (t, v) in enumerate(zip(t_all, venue)):
        if v == 0:
            cur[0] = ml[i_l]; i_l += 1
        else:
            cur[1] = mg[i_g]; i_g += 1
        B = cur[0] - cur[1]
        alpha = 1 - 0.5 ** (max(t - last_t, 0.0) / EWMA_HL_S)
        base += alpha * (B - base); last_t = t
        out_t[k] = t; out_d[k] = B - base
    return out_t, out_d


def find_events(td, dv, thr_abs):
    ev = []
    armed = True
    open_i = None
    for k in range(len(td)):
        if armed and abs(dv[k]) > thr_abs:
            ev.append([td[k], np.sign(dv[k]), None])   # [t_open, sign, t_close]
            armed = False
        elif not armed and abs(dv[k]) < thr_abs / 2:
            ev[-1][2] = td[k]
            armed = True
    if ev and ev[-1][2] is None:
        ev[-1][2] = td[-1]
    return ev


def simulate(events_list, lag_q, lag_tr, mid0):
    """Per event: post, fill from tape (price-strict), exit crossing at +H."""
    qt = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = lag_q["bid_price"].to_numpy(); qa = lag_q["ask_price"].to_numpy()
    tt = lag_tr["time_exchange"].astype("int64").to_numpy() / 1e9
    tpx = lag_tr["price"].to_numpy(); tsz = lag_tr["size"].to_numpy()
    tside = (lag_tr["taker_side"].str.upper() == "BUY").to_numpy()  # True=BUY

    rows = []
    for t0, sgn, t_close in events_list:
        t_active = t0 + REACT_S
        i = np.searchsorted(qt, t_active, side="right") - 1
        if i < 0 or (t_active - qt[i]) > QUOTE_TOL_S:
            continue
        # post: join the receiving side's touch
        px = qb[i] if sgn > 0 else qa[i]
        t_end = min(t_close, t0 + MAX_LIFE_S)
        if t_end <= t_active:
            continue
        j0 = np.searchsorted(tt, t_active, side="left")
        j1 = np.searchsorted(tt, t_end, side="right")
        eps = 1e-9 * px
        if sgn > 0:     # our bid: SELL prints at (qf-weighted) or below (full)
            hit_at = (~tside[j0:j1]) & (np.abs(tpx[j0:j1] - px) <= eps)
            hit_below = (~tside[j0:j1]) & (tpx[j0:j1] < px - eps)
        else:           # our ask: BUY prints at (qf-weighted) or above (full)
            hit_at = (tside[j0:j1]) & (np.abs(tpx[j0:j1] - px) <= eps)
            hit_below = (tside[j0:j1]) & (tpx[j0:j1] > px + eps)
        mfill = hit_at | hit_below
        if not mfill.any():
            rows.append({"filled": False, "sign": sgn})
            continue
        idx = np.flatnonzero(mfill) + j0
        t_fill = tt[idx[0]]
        w = np.where(hit_below[mfill], 1.0, QUEUE_FRACTION)  # qf haircut at-price
        vol_usd = float((tsz[idx] * tpx[idx] * w).sum())
        # exit: cross the touch at t_fill + H
        k = np.searchsorted(qt, t_fill + H_EXIT_S, side="right") - 1
        if k < 0 or k >= len(qt):
            continue
        exit_px = qb[k] if sgn > 0 else qa[k]
        gross_bps = 1e4 * sgn * (exit_px - px) / mid0
        rows.append({"filled": True, "sign": sgn, "t_fill": t_fill,
                     "entry_px": float(px), "exit_px": float(exit_px),
                     "gross_bps": float(gross_bps), "tape_usd": vol_usd})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--leader", required=True)
    ap.add_argument("--laggard", required=True)
    args = ap.parse_args()

    lead_q = load_quotes(args.leader, args.date)
    lag_q = load_quotes(args.laggard, args.date)
    lag_tr = load_trades(args.laggard, args.date)
    tl = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
    tg = lag_q["time_exchange"].astype("int64").to_numpy() / 1e9
    t0, t1 = max(tl[0], tg[0]), min(tl[-1], tg[-1])
    if t1 - t0 < 300:
        raise SystemExit("not enough overlap")
    kl = (tl >= t0) & (tl <= t1); kg = (tg >= t0) & (tg <= t1)
    td, dv = dev_series(tl[kl], lead_q["mid"].to_numpy()[kl],
                        tg[kg], lag_q["mid"].to_numpy()[kg])
    mid0 = float(np.median(lag_q["mid"].to_numpy()[kg]))
    overlap_h = (t1 - t0) / 3600
    lqk = lag_q[kg].reset_index(drop=True)

    print(f"=== MAKER {args.leader} -> {args.laggard} {args.date}  "
          f"overlap={overlap_h:.1f}h")
    out = {"date": args.date, "leader": args.leader, "laggard": args.laggard,
           "overlap_h": overlap_h, "h_exit_s": H_EXIT_S,
           "max_life_s": MAX_LIFE_S, "thresholds": {}}
    scale = 24.0 / overlap_h

    for thr in THRESHOLDS_BPS:
        evs = find_events(td, dv, thr * 1e-4 * mid0)
        rows = simulate(evs, lqk, lag_tr, mid0)
        filled = [r for r in rows if r.get("filled")]
        res = {"n_events": len(rows), "n_filled": len(filled),
               "fill_rate": round(len(filled) / max(len(rows), 1), 3)}
        if filled:
            g = np.array([r["gross_bps"] for r in filled])
            res["gross_bps"] = {"mean": float(g.mean()), "p50": float(np.median(g)),
                                "hit": float((g > 0).mean())}
            # fee matrix (entry maker + exit taker), on gross mean
            res["net_bps"] = {f"m{m:g}_t{t:g}": round(float(g.mean()) - m - t, 3)
                              for m in MAKER_FEES_BPS for t in TAKER_FEES_BPS}
            # capacity: filled notional = min(tape through our px, cap)
            pnl = {c: 0.0 for c in CAPS_USD}
            for r in filled:
                for c in CAPS_USD:
                    pnl[c] += min(r["tape_usd"], c) * (r["gross_bps"] * 1e-4)
            # net PnL/day at the good tier (maker 0.0, taker 1.4)
            fee = (0.0 + 1.4) * 1e-4
            pnl_net = {c: 0.0 for c in CAPS_USD}
            for r in filled:
                for c in CAPS_USD:
                    pnl_net[c] += min(r["tape_usd"], c) * (r["gross_bps"] * 1e-4 - fee)
            res["pnl_per_day"] = {
                "gross": {f"cap_{int(c)}": round(pnl[c] * scale, 2) for c in CAPS_USD},
                "net_m0_t1.4": {f"cap_{int(c)}": round(pnl_net[c] * scale, 2)
                                for c in CAPS_USD}}
            tape = np.array([r["tape_usd"] for r in filled])
            res["tape_usd_p50"] = float(np.median(tape))
        out["thresholds"][f"{thr:g}"] = res
        print(f"  thr={thr:g}bps events={res['n_events']} filled={res['n_filled']} "
              f"({res['fill_rate']*100:.0f}%)")
        if filled:
            print(f"    gross mean={res['gross_bps']['mean']:+.2f}bps "
                  f"p50={res['gross_bps']['p50']:+.2f} hit={res['gross_bps']['hit']:.2f}  "
                  f"tape_p50=${res['tape_usd_p50']:,.0f}")
            print(f"    net/event: base(m1.5+t4.5)={res['net_bps']['m1.5_t4.5']:+.2f}  "
                  f"good(m0+t1.4)={res['net_bps']['m0_t1.4']:+.2f}  "
                  f"best(m-0.3+t1.4)={res['net_bps']['m-0.3_t1.4']:+.2f}")
            print(f"    PnL/day net(m0+t1.4): " +
                  " ".join(f"@{k.split('_')[1]}$={v:+.2f}"
                           for k, v in res['pnl_per_day']['net_m0_t1.4'].items()))

    tag = f"{args.leader}_to_{args.laggard}_{args.date}"
    with open(OUT / f"consensus_maker_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/consensus_maker_{tag}.json")


if __name__ == "__main__":
    main()
