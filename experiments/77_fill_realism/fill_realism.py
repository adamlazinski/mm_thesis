"""
fill_realism.py
================
Exp 77 -- Inside-spread fill realism analysis for the alpha=4 OBI-skew result.

Central question: at alpha=4 with the L2 honest engine, how many fills are
actually INSIDE the natural spread (bid_price > natural_best_bid at activation),
and how do their markouts compare to at-touch and outside-spread fills?

This distinguishes two scenarios:
  (A) The edge lives in inside-spread fills (queue_ahead=0, new NBBO) --
      mechanically correct only if our order would truly become the NBBO and
      get first-priority against arriving sell takers.
  (B) The edge also lives in at-touch fills, meaning OBI's directional
      quality improvement operates even within the standard L2 queue.

Method: for alpha in {0, 4}, run 5 days of LINK Apr-2026 with the L2-honest
engine. For each fill, record:
  - fill.price, fill.side, fill.timestamp
  - natural_best_bid (or best_ask) from the L2 snapshot nearest to fill time
  - fill category: inside_spread / at_touch / outside_spread
  - forward mid returns at 0.5, 1, 5, 10s (signed markout)

Run from master2/ root:
    python experiments/77_fill_realism/fill_realism.py
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
from hft_market_maker.core.fill_analysis import compute_markouts, markout_summary
from hft_market_maker.core.l2_features import L2BookTracker, load_snapshots
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import Fill, OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT = Path(__file__).resolve().parent / "results"

TICK = 0.001
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01
REQUOTE_INTERVAL = 0.05
TAKER_FEE = 0.00045
QUEUE_FRACTION = 0.5
HORIZONS = (0.5, 1.0, 5.0, 10.0)

# Use 5 days (Apr 1-5) for speed; enough to categorize fills
N_DAYS = 5
EPS = TICK * 0.1


class SpotSkewMM:
    def __init__(self, spot_alpha: float = 0.0):
        self.spot_alpha = spot_alpha

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.spot_alpha * stats.obi * TICK
        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + shift, optimal_spread=ask - bid,
            bid_size=ORDER_SIZE, ask_size=ORDER_SIZE,
        )

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def categorize_fill(fill: Fill, snaps, snap_ts) -> str:
    """Inside-spread / at-touch / outside based on natural NBBO at fill time."""
    idx = np.searchsorted(snap_ts, fill.timestamp, side="right") - 1
    if idx < 0:
        return "unknown"
    snap = snaps[idx]
    if fill.side == "bid":
        if fill.price > snap.best_bid_price + EPS:
            return "inside_spread"
        if fill.price >= snap.best_bid_price - EPS:
            return "at_touch"
        return "outside_spread"
    else:
        if fill.price < snap.best_ask_price - EPS:
            return "inside_spread"
        if fill.price <= snap.best_ask_price + EPS:
            return "at_touch"
        return "outside_spread"


def dates():
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_2026-04-*.parquet"))}
    tt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_2026-04-*.parquet"))}
    ob = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "orderbooks_LINK_2026-04-*.parquet"))}
    return sorted(sp & tt & ob)[:N_DAYS]


def run_day(tr, qt, spot_alpha, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = SpotSkewMM(spot_alpha=spot_alpha)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=REQUOTE_INTERVAL,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    ).run(tr, qt, l2_tracker=l2)
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = float(res.metrics["total_pnl"]) - TAKER_FEE * sum(
        f.quantity * f.price for f in takers)
    return om.fills, l2_snaps, pnl_fee


def main():
    days = dates()
    print(f"Fill realism analysis: LINK Apr-2026 {days[0]}..{days[-1]} "
          f"({len(days)} days), alpha in {{0, 4}}, "
          f"queue_model=l2, qf={QUEUE_FRACTION}, lat={LATENCY*1000:.0f}ms\n")

    ld = DataLoader()
    all_results = {}

    for spot_alpha in [0.0, 4.0]:
        cats = {"inside_spread": [], "at_touch": [], "outside_spread": [], "unknown": []}
        per_cat_markouts = {c: {h: [] for h in HORIZONS} for c in cats}
        pnl_days = []

        for d in days:
            tr, qt = ld.load_coinapi(
                str(DATA / f"trades_LINK_{d}.parquet"),
                str(DATA / f"quotes_LINK_{d}.parquet"))
            l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

            fills, snaps, pnl_fee = run_day(tr, qt, spot_alpha, l2_snaps)
            pnl_days.append(pnl_fee)

            # Compute markouts for all fills (needs mid price series)
            mko_df = compute_markouts(fills, qt, HORIZONS)

            snap_ts = np.array([s.timestamp for s in snaps])

            for i, fill in enumerate(fills):
                if getattr(fill, "is_taker", False):
                    continue
                cat = categorize_fill(fill, snaps, snap_ts)
                cats[cat].append(fill)
                row = mko_df.iloc[i]
                for h in HORIZONS:
                    v = row[f"markout_{h}"]
                    if not np.isnan(v):
                        per_cat_markouts[cat][h].append(float(v))

        print(f"alpha={spot_alpha:.1f}  mean_pnl={np.mean(pnl_days):+.2f}/day")
        total_fills = sum(len(v) for v in cats.values())
        for cat in ["inside_spread", "at_touch", "outside_spread"]:
            n = len(cats[cat])
            pct = 100 * n / max(total_fills, 1)
            mko_1s = per_cat_markouts[cat][1.0]
            mko_mean = np.mean(mko_1s) / TICK if mko_1s else float("nan")
            mko_adv = 100 * np.mean([m < 0 for m in mko_1s]) if mko_1s else float("nan")
            print(f"  {cat:<18} n={n:5d} ({pct:5.1f}%)  "
                  f"markout_1s={mko_mean:+.2f}t  adverse%={mko_adv:.1f}%")
        print()

        all_results[str(spot_alpha)] = {
            "mean_pnl": float(np.mean(pnl_days)),
            "categories": {
                cat: {
                    "n_fills": len(cats[cat]),
                    "pct_of_total": float(len(cats[cat]) / max(total_fills, 1)),
                    "markout_by_horizon": {
                        str(h): {
                            "mean_ticks": float(np.mean(per_cat_markouts[cat][h]) / TICK)
                                          if per_cat_markouts[cat][h] else None,
                            "pct_adverse": float(
                                np.mean([m < 0 for m in per_cat_markouts[cat][h]]))
                            if per_cat_markouts[cat][h] else None,
                            "n": len(per_cat_markouts[cat][h]),
                        }
                        for h in HORIZONS
                    },
                }
                for cat in cats
            },
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "fill_realism.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
