"""
Perfect-foresight oracle: the in-sample upper bound on honest MM (exp 60).
==========================================================================
Exp 58 showed no *causal* RL policy over observable microstructure state profits
under the honest L2-queue fill model. That is NOT the same as "no in-sample profit
exists." A strategy that could see the future would profit even honestly, by
selecting only the favourable fills from a zero-MEAN fill distribution. This script
quantifies that gap directly on the real LINK Apr 1-3 2026 L2 data.

Method:
  1. Run an honest touch-quoter (post at best_bid / best_ask) through the real
     engine under queue_model='l2' (real standing queue at the touch). This yields
     the set of fills a realistic honest MM actually gets.
  2. For each fill, compute the forward markout at several horizons H:
        bid fill (we bought):  m = mid(t+H) - fill_price
        ask fill (we sold):    m = fill_price - mid(t+H)
     PnL contribution = quantity * m  (dollars).
  3. Compare:
        Sum over ALL fills        = the honest MM's markout PnL  (≈ breakeven, what
                                     you get with NO foresight — the C30 honest cell)
        Sum over POSITIVE fills   = the perfect-foresight ORACLE ceiling (skip every
                                     adverse fill — needs to know the future)
     The gap between them is the value of perfect 10s foresight: the in-sample edge
     that exists but is not retail-accessible (it requires knowing the future, or
     equivalently the queue priority that lets uninformed flow fill you first).

This is the honest complement to exp 58: profit is zero CAUSALLY, positive with
FORESIGHT. The thesis is that the foresight (or its queue-priority substitute) is
the inaccessible part.

Run:
    python experiments/60_foresight_oracle/foresight_oracle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.core.l2_features import L2BookTracker
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT = Path("experiments/60_foresight_oracle/results")
TICK = 0.001                       # LINK tick
ORDER_SIZE = 5.0
MAX_INV = 38.0
QUEUE_FRACTION = 0.5               # realistic retail share of the touch queue
DAYS = ["2026-04-01", "2026-04-02", "2026-04-03"]
HORIZONS = [1.0, 5.0, 10.0, 30.0]  # markout horizons (s)


class TouchMM:
    """Quote exactly at the touch (best_bid / best_ask), capped inventory."""

    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        bid = np.round((mid - half) / TICK) * TICK
        ask = np.round((mid + half) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid,
                             optimal_spread=ask - bid, bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inventory):
        return (inventory < MAX_INV, inventory > -MAX_INV)


def forward_mid(quote_ts, mid, fill_ts, h):
    """mid at (fill_ts + h), via last quote <= that time (vectorized)."""
    idx = np.searchsorted(quote_ts, fill_ts + h, side="right") - 1
    idx = np.clip(idx, 0, len(mid) - 1)
    return mid[idx]


def run_day(date):
    loader = DataLoader()
    trades, quotes = loader.load_coinapi(
        str(DATA / f"trades_LINK_{date}.parquet"),
        str(DATA / f"quotes_LINK_{date}.parquet"))
    ob_path = DATA / f"orderbooks_LINK_{date}.parquet"
    l2 = L2BookTracker(loader.load_orderbook(str(ob_path))) if ob_path.exists() else None

    om = OrderManager(maker_fee=0.0, latency=0.1, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(vol_window=120, arrival_window=60, ewma_alpha=0.9)
    bt = Backtest(TouchMM(), market_state=ms, order_manager=om,
                  requote_on_fill=True, requote_interval=0.1, tolerance_ticks=0.5,
                  tick_size=TICK, verbose=False)
    res = bt.run(trades, quotes, l2_tracker=l2)

    fills = res.trade_log
    if fills is None or len(fills) == 0:
        return None
    # trade_log has a float-seconds 'timestamp' column and a RangeIndex.
    f_ts = fills["timestamp"].to_numpy().astype(float)
    side = fills["side"].to_numpy()
    price = fills["price"].to_numpy().astype(float)
    qty = fills["quantity"].to_numpy().astype(float)

    q_ts = np.array([q.timestamp for q in quotes])
    q_mid = np.array([(q.best_bid + q.best_ask) / 2.0 for q in quotes])

    per_h = {}
    for h in HORIZONS:
        fmid = forward_mid(q_ts, q_mid, f_ts, h)
        # Signed markout in price units: bid fill = bought (gain if mid rises),
        # ask fill = sold (gain if mid falls).
        m = np.where(side == "bid", fmid - price, price - fmid)
        pnl = qty * m
        per_h[h] = {
            "n_fills": int(len(pnl)),
            "sum_all": float(pnl.sum()),            # honest MM markout PnL
            "sum_positive": float(pnl[pnl > 0].sum()),  # oracle ceiling
            "frac_positive": float((pnl > 0).mean()),
            "mean_markout_ticks": float((m / TICK).mean()),
        }
    return per_h


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    days = {}
    for d in DAYS:
        print(f"\n=== {d} ===")
        r = run_day(d)
        if r is None:
            print("  no fills, skip"); continue
        days[d] = r

    # Aggregate (mean per day)
    agg = {}
    for h in HORIZONS:
        n = np.mean([days[d][h]["n_fills"] for d in days])
        all_ = np.mean([days[d][h]["sum_all"] for d in days])
        pos = np.mean([days[d][h]["sum_positive"] for d in days])
        fp = np.mean([days[d][h]["frac_positive"] for d in days])
        mk = np.mean([days[d][h]["mean_markout_ticks"] for d in days])
        agg[h] = {"fills_per_day": round(n), "honest_pnl_per_day": round(all_, 2),
                  "oracle_ceiling_per_day": round(pos, 2), "frac_positive": round(fp, 3),
                  "mean_markout_ticks": round(mk, 4)}

    print(f"\n{'='*78}\nPERFECT-FORESIGHT ORACLE — LINK Apr 1-3, honest L2 touch quoting (qf={QUEUE_FRACTION})")
    print(f"{'='*78}")
    print(f"  {'H(s)':>5} | {'fills/day':>9} | {'honest PnL/day':>14} | "
          f"{'oracle ceiling/day':>18} | {'% fills +':>9} | {'mean markout(t)':>15}")
    for h in HORIZONS:
        a = agg[h]
        print(f"  {h:>5.0f} | {a['fills_per_day']:>9} | ${a['honest_pnl_per_day']:>13.2f} | "
              f"${a['oracle_ceiling_per_day']:>17.2f} | {a['frac_positive']*100:>8.1f}% | "
              f"{a['mean_markout_ticks']:>15.4f}")

    json.dump({"per_day": days, "aggregate": {str(k): v for k, v in agg.items()},
               "queue_fraction": QUEUE_FRACTION},
              open(OUT / "foresight_oracle.json", "w"), indent=2)
    print(f"\nSaved -> {OUT / 'foresight_oracle.json'}")
    print("\nHonest PnL/day (sum of ALL fills' markout) ≈ the C30 breakeven cell — what you")
    print("get with no foresight. Oracle ceiling (sum of POSITIVE fills only) is what perfect")
    print("10s foresight buys by skipping adverse fills. The gap = the in-sample edge that")
    print("exists but needs the future (or the queue priority that substitutes for it).")


if __name__ == "__main__":
    main()
