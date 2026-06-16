"""
queue_fraction_sweep_low.py
============================
Exp 72 -- extends exp69's queue_fraction sweep DOWNWARD, toward the "no queue"
extreme (queue_fraction=0).

Motivation
----------
exp69 swept queue_fraction in {0.3, 0.4, 0.5, 0.6, 0.7} and found spot1's edge
essentially flat (21.93-22.32) and 100% days+ across the whole range, while
baseline drifted from -0.45 (qf=0.3) to -0.08 (qf=0.7) -- i.e. baseline gets
*worse* as queue_fraction decreases toward the front of the queue (more fills,
closer to the old "artifact regime" of C40/41).

This sweeps queue_fraction in {0.0, 0.1, 0.2} -- continuing that trend down to
the extreme where queue_ahead = 0 always (every order behaves as if it were at
the very front the moment it activates, the L2-honest analogue of
queue_model="none"). Question: does spot1's edge stay flat as baseline
continues to degrade (edge over baseline GROWS), or does spot1 degrade too?

Same engine settings as exp68/69: queue_model="l2", latency=0.01 (10ms),
requote_interval=0.05 (50ms), 30 days LINK Apr 2026.

Run from master2/ root with .venv activated:
    python experiments/72_queue_fraction_sweep_low/queue_fraction_sweep_low.py
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.l2_features import L2BookTracker
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT = Path(__file__).resolve().parent / "results"

TICK = 0.001
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01          # 10ms, matches exp68/69
REQUOTE_INTERVAL = 0.05  # 50ms, matches exp68/69
TAKER_FEE = 0.00045     # 4.5bps, applied post-hoc

QUEUE_FRACTIONS = [0.0, 0.1, 0.2]
VARIANTS = {"baseline": 0.0, "spot1": 1.0}  # spot_alpha


class SpotSkewMM:
    """TouchMM (exp62) + optional spot_obi skew (exp66/68's spot1)."""

    def __init__(self, spot_alpha=0.0):
        self.spot_alpha = spot_alpha

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.spot_alpha * stats.obi * TICK

        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid + shift,
                              optimal_spread=ask - bid, bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def dates():
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_2026-04-*.parquet"))}
    pp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_PERP_2026-04-*.parquet"))}
    tt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_2026-04-*.parquet"))}
    ob = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "orderbooks_LINK_2026-04-*.parquet"))}
    return sorted(sp & pp & tt & ob)


def run_cell(tr, qt, spot_alpha, queue_fraction, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = queue_fraction
    ms = MarketState(120, 60, 0.9)
    strat = SpotSkewMM(spot_alpha=spot_alpha)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(strat, market_state=ms, order_manager=om, requote_on_fill=True,
                    requote_interval=REQUOTE_INTERVAL, tolerance_ticks=0.5,
                    tick_size=TICK, verbose=False).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics.get("total_pnl", 0.0))
    fills = om.fills
    takers = [f for f in fills if getattr(f, "is_taker", False)]
    taker_notional = sum(f.quantity * f.price for f in takers)
    pnl_fee = pnl0 - TAKER_FEE * taker_notional
    return pnl0, pnl_fee, len(fills), len(takers)


def main():
    days = dates()
    print(f"LINK Apr-2026 LOW queue_fraction sweep for exp68/69's baseline/spot1 "
          f"(queue_model=l2, latency={LATENCY * 1000:.0f}ms, requote={REQUOTE_INTERVAL * 1000:.0f}ms), "
          f"{len(days)} days, queue_fraction in {QUEUE_FRACTIONS}\n")

    results = {name: {qf: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []}
                       for qf in QUEUE_FRACTIONS}
               for name in VARIANTS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for name, spot_alpha in VARIANTS.items():
            for qf in QUEUE_FRACTIONS:
                pnl0, pnl_fee, n, tk = run_cell(tr, qt, spot_alpha, qf, l2_snaps)
                results[name][qf]["pnl0"].append(pnl0)
                results[name][qf]["pnl_fee"].append(pnl_fee)
                results[name][qf]["fills"].append(n)
                results[name][qf]["takers"].append(tk)
                row[(name, qf)] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"{name}@{qf}={row[(name, qf)]:+.2f}"
                        for name in VARIANTS for qf in QUEUE_FRACTIONS))

    print(f"\n{'variant':>10} {'qf':>5} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7}")
    summary = {name: {} for name in VARIANTS}
    for name in VARIANTS:
        for qf in QUEUE_FRACTIONS:
            r = results[name][qf]
            p0 = np.array(r["pnl0"])
            pf = np.array(r["pnl_fee"])
            f_arr = np.array(r["fills"])
            tk_arr = np.array(r["takers"])
            taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
            print(f"{name:>10} {qf:5.2f} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
                  f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}%")
            summary[name][str(qf)] = {
                "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
                "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
                "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
                "per_day_pnl_fee0": r["pnl0"],
                "per_day_pnl_fee45bps": r["pnl_fee"],
            }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "queue_fraction_sweep_low.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fractions": QUEUE_FRACTIONS,
                   "latency": LATENCY, "requote_interval": REQUOTE_INTERVAL,
                   "taker_fee": TAKER_FEE, "variants": VARIANTS, "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
