"""
link_harvest.py
================
Exp 94 — "try everything" on the one book with a real window.

Exp 93 showed LINK spot is the only captured book whose realized half-spread
stays positive past the touch: adverse-selection horizon ~75-87ms, impact only
~0.13t at 15ms. Exp 90 showed the 15ms perp-gated maker improves from
-$23.5/day to -$17/day but stays negative. This experiment throws the full
lever set at LINK spot, honestly (real L2, post_only, qf=0.5, 10ms order
latency), to find the floor of the loss and the rebate that would close it:

  LEVER 1  gate threshold      how strong a perp deviation suppresses a side
  LEVER 2  signal latency      how fast we see the leader (5/10/15/30ms)
  LEVER 3  response mode        gate (pull side) | widen (1 tick back) |
                                lean (pull toxic + double favorable side)
  LEVER 4  queue fraction      qf in {0.0 back, 0.5 mid, 1.0 front} robustness
  LEVER 5  breakeven rebate    maker rebate (bps) that lifts best config to 0

Phased so the grid stays ~16 runs: sweep gate at 15ms/gate-mode, take best
gate, sweep latency, then mode, then qf + rebate on the winner.

Run: python experiments/94_link_harvest/link_harvest.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.l2_features import BookSnapshot, L2BookTracker
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

EWMA_HALFLIFE_S = 60.0
LATENCY = 0.01
REQUOTE = 0.01

CFG = {"tick": 0.001, "order_size": 5.0, "max_inv": 38.0, "thr": 0.002}

GATES = [0.00005, 0.0001, 0.0002, 0.0003, 0.0005, 0.001]
SIG_LATS = [0.005, 0.010, 0.015, 0.030]
MODES = ["gate", "widen", "lean"]
QFS = [0.0, 0.5, 1.0]


# ── shared helpers (from exp 90) ──────────────────────────────────────────────

def load_mid(asset, date):
    df = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet",
                         columns=["time_exchange", "bid_price", "ask_price"])
    t = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    mid = (df["bid_price"].values + df["ask_price"].values) / 2
    keep = np.concatenate([[True], np.diff(t) > 0])
    return t[keep], mid[keep].astype(float)


def dev_series(ts, ms, tp, mp):
    """Merged-event deviation dev(t) = (perp - spot) - EWMA basis."""
    t_all = np.concatenate([ts, tp])
    venue = np.concatenate([np.zeros(len(ts), int), np.ones(len(tp), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]
    out_t = np.empty(len(t_all)); out_d = np.empty(len(t_all))
    cur = [ms[0], mp[0]]; i_s = i_p = 0
    base = mp[0] - ms[0]; last_t = t_all[0]
    for k, (t, v) in enumerate(zip(t_all, venue)):
        if v == 0:
            cur[0] = ms[i_s]; i_s += 1
        else:
            cur[1] = mp[i_p]; i_p += 1
        B = cur[1] - cur[0]
        alpha = 1 - 0.5 ** (max(t - last_t, 0.0) / EWMA_HALFLIFE_S)
        base += alpha * (B - base); last_t = t
        out_t[k] = t; out_d[k] = B - base
    return out_t, out_d


def real_tracker(ob_path):
    df = pd.read_parquet(ob_path)
    ts = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    snaps = []
    for t, bids, asks in zip(ts, df["bids"].values, df["asks"].values):
        bl = tuple((float(l["price"]), float(l["size"])) for l in bids)
        al = tuple((float(l["price"]), float(l["size"])) for l in asks)
        if not bl or not al:
            continue
        b = sum(s for _, s in bl[:5]); a = sum(s for _, s in al[:5])
        obi = (b - a) / (b + a) if b + a else 0.0
        snaps.append(BookSnapshot(
            timestamp=float(t), best_bid_price=bl[0][0], best_ask_price=al[0][0],
            best_bid_depth=bl[0][1], best_ask_depth=al[0][1],
            obi_l1=obi, obi_l3=obi, obi_l5=obi, obi_l10=obi,
            total_bid_depth=b, total_ask_depth=a,
            bid_levels=bl, ask_levels=al))
    return L2BookTracker(snaps)


# ── strategy: perp-signal response with pluggable mode ────────────────────────

class PerpResponseMM:
    def __init__(self, td, dv, gate, tick, order_size, max_inv, sig_lat, mode):
        self.td, self.dv = td, dv
        self.gate, self.tick = gate, tick
        self.order_size, self.max_inv = order_size, max_inv
        self.sig_lat, self.mode = sig_lat, mode
        self.n_gated = 0
        self.n_calls = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_calls += 1
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else self.tick
        bid = np.round((mid - half) / self.tick) * self.tick
        ask = np.round((mid + half) / self.tick) * self.tick
        if ask <= bid:
            ask = bid + self.tick

        i = np.searchsorted(self.td, ts - self.sig_lat, side="right") - 1
        dev = self.dv[i] if i >= 0 else 0.0

        bid_size = self.order_size if inv < self.max_inv else 0.0
        ask_size = self.order_size if inv > -self.max_inv else 0.0

        if self.gate is not None and abs(dev) > self.gate:
            self.n_gated += 1
            rising = dev > 0                      # price about to rise
            if self.mode == "gate":
                if rising:
                    ask_size = 0.0                # don't sell into the rise
                else:
                    bid_size = 0.0                # don't buy into the fall
            elif self.mode == "widen":
                # keep the toxic side but 1 tick back off the touch
                if rising:
                    ask = ask + self.tick
                else:
                    bid = bid - self.tick
            elif self.mode == "lean":
                # pull toxic side AND double the favorable side to accumulate
                # directional inventory ahead of the move
                if rising:
                    ask_size = 0.0
                    if inv < self.max_inv:
                        bid_size = 2.0 * self.order_size
                else:
                    bid_size = 0.0
                    if inv > -self.max_inv:
                        ask_size = 2.0 * self.order_size
        return QuoteDecision(bid_price=bid, ask_price=ask,
                             reservation_price=mid, optimal_spread=ask - bid,
                             bid_size=bid_size, ask_size=ask_size)

    def should_quote(self, inv):
        return (inv < self.max_inv, inv > -self.max_inv)


def run_one(date, td, dv, gate, ld, l2, sig_lat=0.015, mode="gate", qf=0.5,
            dv_shift=0):
    if dv_shift:
        dv = np.roll(dv, dv_shift)      # placebo: same magnitudes, wrong timing
    tr, qt = ld.load_coinapi(str(PROC / f"trades_LINK_{date}.parquet"),
                             str(PROC / f"quotes_LINK_{date}.parquet"))
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                      queue_model="l2")
    om.queue_fraction = qf
    strat = PerpResponseMM(td, dv, gate, CFG["tick"], CFG["order_size"],
                           CFG["max_inv"], sig_lat, mode)
    res = Backtest(strat, market_state=MarketState(120, 60, 0.9),
                   order_manager=om, requote_on_fill=True,
                   requote_interval=REQUOTE, tolerance_ticks=0,
                   tick_size=CFG["tick"], verbose=False).run(tr, qt, l2_tracker=l2)
    pnl = float(res.metrics["total_pnl"])
    maker_notional = sum(f.quantity * f.price for f in om.fills
                         if not getattr(f, "is_taker", False))
    gate_pct = 100 * strat.n_gated / max(strat.n_calls, 1)
    # rebate (bps of maker notional) that lifts this run to breakeven
    be_rebate = (-pnl / maker_notional * 1e4) if maker_notional > 0 else None
    return {"pnl": pnl, "fills": len(om.fills), "gated_pct": gate_pct,
            "maker_notional": maker_notional, "be_rebate_bps": be_rebate}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--validate", action="store_true",
                    help="run winner config + placebo controls instead of the sweep")
    ap.add_argument("--gate", type=float, default=5e-05)
    ap.add_argument("--sig-lat", type=float, default=0.030)
    args = ap.parse_args()
    ld = DataLoader()

    ts, ms = load_mid("LINK", args.date)
    tp, mp = load_mid("LINK_PERP", args.date)
    td, dv = dev_series(ts, ms, tp, mp)
    l2 = real_tracker(str(PROC / f"orderbooks_LINK_{args.date}.parquet"))

    def line(tag, r):
        be = f"{r['be_rebate_bps']:.3f}bps" if r['be_rebate_bps'] is not None else "n/a"
        print(f"  {tag:26s} pnl={r['pnl']:+9.3f}  fills={r['fills']:6d}  "
              f"gated%={r['gated_pct']:5.1f}  be_rebate={be}")

    if args.validate:
        # Does the perp signal actually help, or is -$0.48 just "trade 20%"?
        # Compare the winner config against time-scrambled and inverted signals
        # at the SAME gate/lat (=> same gating frequency, no real information).
        print(f"=== LINK {args.date} VALIDATE  gate={args.gate:g} "
              f"sig_lat={args.sig_lat*1000:g}ms mode=gate qf=0.5")
        shift = len(dv) // 3          # scramble timing, keep magnitude distribution
        runs = {
            "real_signal":  run_one(args.date, td, dv, args.gate, ld, l2,
                                    sig_lat=args.sig_lat),
            "placebo_shift": run_one(args.date, td, dv, args.gate, ld, l2,
                                     sig_lat=args.sig_lat, dv_shift=shift),
            "anti_signal":  run_one(args.date, td, -dv, args.gate, ld, l2,
                                    sig_lat=args.sig_lat),
            "no_signal":    run_one(args.date, td, dv, None, ld, l2),
        }
        for k, r in runs.items():
            line(k, r)
        edge = runs["real_signal"]["pnl"] - runs["placebo_shift"]["pnl"]
        print(f"    signal edge vs placebo = {edge:+.3f}/day "
              f"({'real signal helps beyond suppression' if edge > 0 else 'no signal — pure suppression'})")
        with open(OUT / f"link_harvest_validate_{args.date}.json", "w") as fh:
            json.dump({"date": args.date, "gate": args.gate,
                       "sig_lat": args.sig_lat, "runs": runs}, fh, indent=2)
        print(f"Saved -> {OUT}/link_harvest_validate_{args.date}.json")
        return

    out = {"date": args.date}

    def line(tag, r):
        be = f"{r['be_rebate_bps']:.3f}bps" if r['be_rebate_bps'] is not None else "n/a"
        print(f"  {tag:24s} pnl={r['pnl']:+9.3f}  fills={r['fills']:6d}  "
              f"gated%={r['gated_pct']:5.1f}  be_rebate={be}")

    # baseline (no gate)
    print(f"=== LINK {args.date}  (honest: real L2, post_only, qf=0.5, 10ms lat)")
    base = run_one(args.date, td, dv, None, ld, l2)
    out["baseline"] = base
    line("baseline(no signal)", base)

    # LEVER 1: gate threshold @ 15ms, gate-mode
    print("--- LEVER 1: gate threshold (sig_lat=15ms, mode=gate)")
    gate_res = {}
    for g in GATES:
        r = run_one(args.date, td, dv, g, ld, l2, sig_lat=0.015, mode="gate")
        gate_res[f"{g:g}"] = r
        line(f"gate={g:g}", r)
    out["gate_sweep"] = gate_res
    best_g = max(GATES, key=lambda g: gate_res[f"{g:g}"]["pnl"])
    print(f"    -> best gate = {best_g:g}  (pnl={gate_res[f'{best_g:g}']['pnl']:+.3f})")

    # LEVER 2: signal latency @ best gate, gate-mode
    print(f"--- LEVER 2: signal latency (gate={best_g:g}, mode=gate)")
    lat_res = {}
    for sl in SIG_LATS:
        r = run_one(args.date, td, dv, best_g, ld, l2, sig_lat=sl, mode="gate")
        lat_res[f"{sl:g}"] = r
        line(f"sig_lat={sl*1000:g}ms", r)
    out["lat_sweep"] = lat_res
    best_sl = max(SIG_LATS, key=lambda s: lat_res[f"{s:g}"]["pnl"])

    # LEVER 3: response mode @ best gate + best latency
    print(f"--- LEVER 3: response mode (gate={best_g:g}, sig_lat={best_sl*1000:g}ms)")
    mode_res = {}
    for m in MODES:
        r = run_one(args.date, td, dv, best_g, ld, l2, sig_lat=best_sl, mode=m)
        mode_res[m] = r
        line(f"mode={m}", r)
    out["mode_sweep"] = mode_res
    best_m = max(MODES, key=lambda m: mode_res[m]["pnl"])

    # LEVER 4: queue-fraction robustness on the winner
    print(f"--- LEVER 4: queue fraction (gate={best_g:g}, "
          f"sig_lat={best_sl*1000:g}ms, mode={best_m})")
    qf_res = {}
    for qf in QFS:
        r = run_one(args.date, td, dv, best_g, ld, l2,
                    sig_lat=best_sl, mode=best_m, qf=qf)
        qf_res[f"{qf:g}"] = r
        line(f"qf={qf:g}", r)
    out["qf_sweep"] = qf_res

    out["winner"] = {"gate": best_g, "sig_lat": best_sl, "mode": best_m,
                     "pnl": mode_res[best_m]["pnl"],
                     "be_rebate_bps": mode_res[best_m]["be_rebate_bps"]}
    print(f"\nWINNER: gate={best_g:g} sig_lat={best_sl*1000:g}ms mode={best_m} "
          f"-> pnl={mode_res[best_m]['pnl']:+.3f}/day, "
          f"breakeven rebate={mode_res[best_m]['be_rebate_bps']:.3f}bps")

    with open(OUT / f"link_harvest_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/link_harvest_{args.date}.json")


if __name__ == "__main__":
    main()
