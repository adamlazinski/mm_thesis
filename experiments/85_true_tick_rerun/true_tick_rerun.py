"""
true_tick_rerun.py
===================
Exp 85 — C42/C44 rerun at LINK's TRUE tick size (0.01).

Discovery (2026-07-10, live-capture validation): every price in the historical
LINK dataset (Jun 2025 – Apr 2026) sits on a 0.01 grid — LINK's exchange tick
was 0.01, not the 0.001 assumed by every LINK experiment. The "10-tick spread"
was one real tick; every inside-spread placement of the C42–C51 mechanism was
at an exchange-invalid price. (Binance's current tickSize for LINKUSDT is
0.001 — the change came after April 2026; live capture confirms a 1-tick
spread on the new grid too.)

This experiment reruns the core OBI-skew configs with TICK=0.01 on the same
30-day, real-L2, Apr-2026 window as C44/exp 78, engine settings identical
(queue_model="l2", qf=0.5, latency=10ms, requote=50ms, tolerance=0.5 ticks,
post_only). Prediction: with no room inside the one-tick spread, the OBI shift
either rounds back to the touch or crosses and is post_only-rejected — the
mechanism collapses to OBI-gated quote suppression (C47's LINK-PERP mechanism),
and the +$56/day disappears.

Run from master2/:
    python experiments/85_true_tick_rerun/true_tick_rerun.py
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

TICK = 0.01                  # the TRUE historical LINK tick
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01
REQUOTE_INTERVAL = 0.05
TAKER_FEE = 0.00045
QUEUE_FRACTION = 0.5

ALPHAS = [0.0, 1.0, 4.0]


class SpotSkewMM:
    """Symmetric OBI skew (exp-78 strategy) at configurable tick."""

    def __init__(self, alpha: float):
        self.alpha = alpha

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.alpha * stats.obi * TICK
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


def dates():
    def stems(pat):
        return {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
                for f in glob.glob(str(DATA / pat))}
    return sorted(stems("quotes_LINK_2026-04-*.parquet")
                  & stems("trades_LINK_2026-04-*.parquet")
                  & stems("orderbooks_LINK_2026-04-*.parquet"))


def run_cell(tr, qt, alpha, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                      queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = SpotSkewMM(alpha=alpha)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=REQUOTE_INTERVAL,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    ).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics["total_pnl"])
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    n_rej = sum(1 for o in getattr(om, "_archive", [])
                if getattr(o, "status", "") == "rejected")
    return pnl_fee, len(om.fills), len(takers), n_rej


def main():
    days = dates()
    print(f"Exp 85 — TRUE-tick (0.01) rerun, LINK Apr-2026, {len(days)} days, "
          f"alphas={ALPHAS}, real L2 qf={QUEUE_FRACTION}\n")

    ld = DataLoader()
    results = {}
    for alpha in ALPHAS:
        r_pnl, r_fills, r_tk, r_rej = [], [], [], []
        for d in days:
            tr, qt = ld.load_coinapi(
                str(DATA / f"trades_LINK_{d}.parquet"),
                str(DATA / f"quotes_LINK_{d}.parquet"))
            l2 = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))
            pf, nf, ntk, nrej = run_cell(tr, qt, alpha, l2)
            r_pnl.append(pf); r_fills.append(nf)
            r_tk.append(ntk); r_rej.append(nrej)
        arr = np.array(r_pnl)
        print(f"  alpha={alpha:.0f}  mean={arr.mean():+8.2f}  std={arr.std():6.2f}  "
              f"days+={100*(arr>0).mean():4.0f}%  fills={np.mean(r_fills):6.0f}  "
              f"rejected={np.mean(r_rej):6.0f}")
        results[f"alpha{alpha:g}"] = {
            "alpha": alpha,
            "mean_pnl": float(arr.mean()), "std_pnl": float(arr.std()),
            "days_pos_pct": float(100 * (arr > 0).mean()),
            "mean_fills": float(np.mean(r_fills)),
            "mean_rejected": float(np.mean(r_rej)),
            "taker_pct": float(sum(r_tk) / max(sum(r_fills), 1) * 100),
            "per_day_pnl": [float(x) for x in arr],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "true_tick.json", "w") as f:
        json.dump({"tick": TICK, "n_days": len(days), "results": results},
                  f, indent=2)
    print(f"\nSaved -> {OUT / 'true_tick.json'}")


if __name__ == "__main__":
    main()
