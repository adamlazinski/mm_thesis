"""
one_sided_quoting.py
=====================
Exp 79 -- OBI-threshold one-sided quoting.

C44 shows that at alpha=4, ~10% of fills are still adversely selected. The
asymmetry analysis (C44-E) shows bid and ask markouts are roughly symmetric
(within 0.1-0.2 ticks), suggesting the 10% adverse fills are split evenly
between bid fills when OBI < 0 (we bought into sell pressure) and ask fills
when OBI > 0 (we sold into buy pressure).

One-sided quoting: when the OBI signal is strong enough that one side is
clearly "adverse", suppress that side entirely:
  - OBI > theta: only post BID (buy pressure -> bids likely favorable,
    ask fills likely adverse = selling into buy pressure)
  - OBI < -theta: only post ASK (sell pressure -> asks likely favorable,
    bid fills likely adverse = buying into sell pressure)
  - |OBI| <= theta: quote both sides symmetrically

This is the natural complement to ask: does halting the adverse side
when OBI is clear reduce the residual 10% adverse fills without
sacrificing PnL from the suppressed fills?

Base alpha fixed at 4.0 (C44's optimum). Sweep theta in {0.0, 0.1, 0.2,
0.3, 0.5, 0.7}. theta=0.0 = always one-sided (degenerate: never quote both).
theta=1.0 = never one-sided (equivalent to symmetric alpha=4).

Also test: one-sided quoting WITHOUT skew (alpha=0, just the gate) to see
if the gate alone adds value beyond the baseline.

queue_model="l2", queue_fraction=0.5, latency=10ms, requote=50ms.
LINK Apr-2026, 30 days.

Run from master2/:
    python experiments/79_one_sided_quoting/one_sided_quoting.py
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
LATENCY = 0.01
REQUOTE_INTERVAL = 0.05
TAKER_FEE = 0.00045
QUEUE_FRACTION = 0.5

BASE_ALPHA = 4.0
# (base_alpha, threshold) pairs to test
# alpha=4 + various thresholds; alpha=0 + threshold as control
CONFIGS = [
    # symmetric reference
    {"label": "alpha4_theta_inf",  "alpha": 4.0, "theta": 1.1},  # effectively inf
    # one-sided with alpha=4
    {"label": "alpha4_theta0.1",   "alpha": 4.0, "theta": 0.1},
    {"label": "alpha4_theta0.2",   "alpha": 4.0, "theta": 0.2},
    {"label": "alpha4_theta0.3",   "alpha": 4.0, "theta": 0.3},
    {"label": "alpha4_theta0.5",   "alpha": 4.0, "theta": 0.5},
    {"label": "alpha4_theta0.7",   "alpha": 4.0, "theta": 0.7},
    # one-sided without skew (gate only, no shift)
    {"label": "alpha0_theta0.2",   "alpha": 0.0, "theta": 0.2},
    {"label": "alpha0_theta0.3",   "alpha": 0.0, "theta": 0.3},
    {"label": "alpha0_theta0.5",   "alpha": 0.0, "theta": 0.5},
    # baseline
    {"label": "alpha0_theta_inf",  "alpha": 0.0, "theta": 1.1},
]


class OneSidedSkewMM:
    """
    OBI skew with one-sided quoting gate.

    When OBI > theta: suppress the ASK (adverse to sell into buy pressure).
    When OBI < -theta: suppress the BID (adverse to buy into sell pressure).
    Otherwise: post both sides with symmetric alpha shift.
    """

    def __init__(self, spot_alpha: float, threshold: float):
        self.spot_alpha = spot_alpha
        self.threshold = threshold
        # internal state: last OBI used for gating, updated each compute_quotes
        self._last_obi = 0.0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        obi = stats.obi
        self._last_obi = obi

        shift = self.spot_alpha * obi * TICK

        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK

        # Determine which sides to quote
        quote_bid = inv < MAX_INV
        quote_ask = inv > -MAX_INV

        if obi > self.threshold:
            # Buy pressure: suppress ask (adverse to get short into a rising market)
            ask_size = 0.0 if quote_ask else 0.0
            bid_size = ORDER_SIZE if quote_bid else 0.0
        elif obi < -self.threshold:
            # Sell pressure: suppress bid (adverse to get long into a falling market)
            bid_size = 0.0 if quote_bid else 0.0
            ask_size = ORDER_SIZE if quote_ask else 0.0
        else:
            bid_size = ORDER_SIZE if quote_bid else 0.0
            ask_size = ORDER_SIZE if quote_ask else 0.0

        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + shift, optimal_spread=ask - bid,
            bid_size=bid_size, ask_size=ask_size,
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


def run_cell(tr, qt, spot_alpha, threshold, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = OneSidedSkewMM(spot_alpha=spot_alpha, threshold=threshold)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=REQUOTE_INTERVAL,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    ).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics["total_pnl"])
    fills = om.fills
    takers = [f for f in fills if getattr(f, "is_taker", False)]
    bid_fills = [f for f in fills if f.side == "bid" and not getattr(f, "is_taker", False)]
    ask_fills = [f for f in fills if f.side == "ask" and not getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    return pnl0, pnl_fee, len(fills), len(takers), len(bid_fills), len(ask_fills)


def main():
    days = dates()
    print(f"One-sided quoting sweep: LINK Apr-2026 {len(days)} days\n"
          f"Base alpha={BASE_ALPHA}, threshold sweep. L2 qf={QUEUE_FRACTION}\n")

    ld = DataLoader()
    summary = {}

    for cfg in CONFIGS:
        label = cfg["label"]
        alpha = cfg["alpha"]
        theta = cfg["theta"]

        r_pnl0, r_fee, r_fills, r_takers, r_bid, r_ask = [], [], [], [], [], []

        for d in days:
            tr, qt = ld.load_coinapi(
                str(DATA / f"trades_LINK_{d}.parquet"),
                str(DATA / f"quotes_LINK_{d}.parquet"))
            l2 = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))
            p0, pf, nf, ntk, nb, na = run_cell(tr, qt, alpha, theta, l2)
            r_pnl0.append(p0); r_fee.append(pf); r_fills.append(nf)
            r_takers.append(ntk); r_bid.append(nb); r_ask.append(na)

        arr = np.array(r_fee)
        theta_str = "inf" if theta > 1.0 else f"{theta}"
        print(f"  {label:<25}  alpha={alpha:.0f}  theta={theta_str:<4}  "
              f"mean={arr.mean():+7.2f}  std={arr.std():6.2f}  "
              f"days+={100*(arr>0).mean():4.0f}%  "
              f"fills={np.mean(r_fills):.0f} (bid={np.mean(r_bid):.0f} ask={np.mean(r_ask):.0f})")

        summary[label] = {
            "alpha": alpha, "threshold": theta,
            "mean_pnl_fee0": float(np.mean(r_pnl0)),
            "mean_pnl_fee45bps": float(arr.mean()),
            "std_pnl": float(arr.std()),
            "days_pos_pct": float((arr > 0).mean()),
            "mean_fills": float(np.mean(r_fills)),
            "mean_bid_fills": float(np.mean(r_bid)),
            "mean_ask_fills": float(np.mean(r_ask)),
            "taker_pct": float(sum(r_takers) / max(sum(r_fills), 1) * 100),
            "per_day_pnl": [float(x) for x in arr],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "one_sided_quoting.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "configs": CONFIGS, "results": summary}, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
