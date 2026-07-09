"""
asymmetric_skew.py
===================
Exp 78 -- Asymmetric bid/ask OBI alpha sweep.

C44 found that symmetric OBI skew (bid_shift == ask_shift = alpha * obi * TICK)
is optimal at alpha=4 (+$56/day, 100% days+, 10% adverse fills). The question
is whether DECOUPLING bid and ask alphas can improve further.

When OBI > 0 (buy pressure, price likely UP):
  bid_shift = +bid_alpha * obi * TICK  (lean bid into spread, get favorable buys)
  ask_shift = +ask_alpha * obi * TICK  (pull ask away from adverse hits)

The symmetric case has bid_alpha = ask_alpha. The asymmetric sweep asks:
  - Should the bid lean harder (bid_alpha > 4) while ask stays conservative?
  - Should the ask be pulled further (ask_alpha > 4) for more ask protection?
  - Is the optimal (bid_alpha, ask_alpha) off the diagonal?

Grid: bid_alpha x ask_alpha in {0, 2, 4, 6, 8} x {0, 2, 4, 6, 8}
with the symmetric diagonal (0,0), (2,2), (4,4), (6,6) for consistency with C44.

queue_model="l2", queue_fraction=0.5, latency=10ms, requote=50ms -- same as C44.
LINK Apr-2026, 30 days.

Run from master2/:
    python experiments/78_asymmetric_skew/asymmetric_skew.py
"""
from __future__ import annotations

import glob
import json
import re
import sys
from itertools import product
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
LATENCY = 0.01
REQUOTE_INTERVAL = 0.05
TAKER_FEE = 0.00045
QUEUE_FRACTION = 0.5

BID_ALPHAS = [0, 2, 4, 6, 8]
ASK_ALPHAS = [0, 2, 4, 6, 8]


class AsymmetricSkewMM:
    """
    OBI skew with separate bid and ask alpha.

    When OBI > 0 (buy pressure):
      bid shifts up by bid_alpha * OBI * TICK  (new NBBO / inside spread)
      ask shifts up by ask_alpha * OBI * TICK  (protection from adverse asks)

    When OBI < 0 (sell pressure): sign flips for both, same logic reversed.
    """

    def __init__(self, bid_alpha: float, ask_alpha: float):
        self.bid_alpha = bid_alpha
        self.ask_alpha = ask_alpha

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        obi = stats.obi

        bid_shift = self.bid_alpha * obi * TICK
        ask_shift = self.ask_alpha * obi * TICK

        bid = np.round((mid - half + bid_shift) / TICK) * TICK
        ask = np.round((mid + half + ask_shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK

        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + 0.5 * (bid_shift + ask_shift),
            optimal_spread=ask - bid,
            bid_size=ORDER_SIZE, ask_size=ORDER_SIZE,
        )

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def dates():
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_2026-04-*.parquet"))}
    tt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_2026-04-*.parquet"))}
    ob = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "orderbooks_LINK_2026-04-*.parquet"))}
    return sorted(sp & tt & ob)


def run_cell(tr, qt, bid_alpha, ask_alpha, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = AsymmetricSkewMM(bid_alpha=bid_alpha, ask_alpha=ask_alpha)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=REQUOTE_INTERVAL,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    ).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics["total_pnl"])
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    return pnl0, pnl_fee, len(om.fills), len(takers)


def main():
    days = dates()
    grid = list(product(BID_ALPHAS, ASK_ALPHAS))
    print(f"Asymmetric OBI skew sweep: LINK Apr-2026 {len(days)} days, "
          f"{len(grid)} cells (bid_alpha x ask_alpha)\n")

    ld = DataLoader()
    results = {}

    for bid_a, ask_a in grid:
        r_pnl0, r_fee, r_fills, r_takers = [], [], [], []

        for i, d in enumerate(days):
            tr, qt = ld.load_coinapi(
                str(DATA / f"trades_LINK_{d}.parquet"),
                str(DATA / f"quotes_LINK_{d}.parquet"))
            l2 = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))
            p0, pf, nf, ntk = run_cell(tr, qt, bid_a, ask_a, l2)
            r_pnl0.append(p0); r_fee.append(pf); r_fills.append(nf); r_takers.append(ntk)

        arr = np.array(r_fee)
        sym = "(*sym*)" if bid_a == ask_a else ""
        print(f"  bid={bid_a} ask={ask_a}  {sym:7s}  "
              f"mean={arr.mean():+7.2f}  std={arr.std():6.2f}  "
              f"days+={100*(arr>0).mean():.0f}%  fills={np.mean(r_fills):.0f}")
        results[f"{bid_a}_{ask_a}"] = {
            "bid_alpha": bid_a, "ask_alpha": ask_a,
            "mean_pnl_fee0": float(np.mean(r_pnl0)),
            "mean_pnl_fee45bps": float(arr.mean()),
            "std_pnl": float(arr.std()),
            "days_pos_pct": float((arr > 0).mean()),
            "mean_fills": float(np.mean(r_fills)),
            "taker_pct": float(sum(r_takers) / max(sum(r_fills), 1) * 100),
            "per_day_pnl": [float(x) for x in arr],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "asymmetric_skew.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "bid_alphas": BID_ALPHAS,
                   "ask_alphas": ASK_ALPHAS, "results": results}, f, indent=2)
    print(f"\nSaved to {out_path}")

    # Print sorted summary table
    rows = sorted(results.values(), key=lambda x: -x["mean_pnl_fee45bps"])
    print("\n--- Top 10 cells by mean PnL ---")
    print(f"{'bid_a':>6} {'ask_a':>6} {'mean':>9} {'std':>8} {'days+':>7} {'fills':>7}")
    for r in rows[:10]:
        print(f"  {r['bid_alpha']:4d}   {r['ask_alpha']:4d}   "
              f"{r['mean_pnl_fee45bps']:+8.2f}  {r['std_pnl']:7.2f}  "
              f"{r['days_pos_pct']*100:5.0f}%  {r['mean_fills']:6.0f}")


if __name__ == "__main__":
    main()
