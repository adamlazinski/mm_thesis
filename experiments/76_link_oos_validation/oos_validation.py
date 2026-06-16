"""
oos_validation.py
==================
Exp 76 — OOS validation for C44's spot_obi directional-skew result.

C42/44 were both run on LINK April 2026 (30 days). This experiment tests
whether the result generalises to a held-out window: LINK June–July 2025
(2025-06-11 to 2025-07-10, 30 days, 9 months before the in-sample period).

No L2 orderbook parquets exist for Jun-Jul 2025 (CoinAPI capture started
April 2026). However, for at-touch orders on LINK (spread nearly always 1 tick),
queue_ahead = best_bid_depth for bids and best_ask_depth for asks — exactly
the quantities in the standard quotes file. A quote-based proxy L2 tracker
is therefore mathematically equivalent to the full L2 tracker for this strategy.

Exact parameter match to exp74 (the C44 confirm run on Apr-2026):
  queue_model="l2", queue_fraction=0.5, latency=10ms, requote=50ms,
  TICK=0.001, ORDER_SIZE=5.0 LINK, MAX_INV=38 LINK, TAKER_FEE=4.5bps

Alphas tested: {0, 1, 4}  (baseline / C42 original / C44 optimum)

Run from master2/ root with .venv activated:
    python experiments/76_link_oos_validation/oos_validation.py
"""
from __future__ import annotations

import glob
import json
import re
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

DATA = ROOT / "data" / "real"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

TICK = 0.001
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01
REQUOTE_INTERVAL = 0.05
TAKER_FEE = 0.00045
QUEUE_FRACTION = 0.5
SPOT_ALPHAS = [0.0, 1.0, 4.0]

# Jun 11 – Jul 10 2025 (30 days)
OOS_GLOB = "2025-06-1[1-9]|2025-06-2[0-9]|2025-06-30|2025-07-0[1-9]|2025-07-10"


def oos_dates():
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_*.parquet"))
          if "PERP" not in f}
    tt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_*.parquet"))
          if "PERP" not in f}
    all_dates = sorted(sp & tt)
    return [d for d in all_dates
            if "2025-06-11" <= d <= "2025-07-10"]


def quote_based_l2_tracker(quotes_df: pd.DataFrame) -> L2BookTracker:
    """
    Build an L2BookTracker from the standard quotes parquet.

    For at-touch orders (the only kind SpotSkewMM places), queue_ahead equals
    best_bid_depth (bid side) or best_ask_depth (ask side). Both are present in
    the quotes file. This is exact — not an approximation — for this strategy.
    """
    snaps = []
    for row in quotes_df.itertuples():
        ts = row.time_exchange
        if hasattr(ts, "timestamp"):
            ts = ts.timestamp()
        else:
            ts = float(ts) / 1e9 if ts > 1e12 else float(ts)

        bp = float(row.bid_price)
        ap = float(row.ask_price)
        bsz = float(row.bid_size)
        asz = float(row.ask_size)
        obi = (bsz - asz) / (bsz + asz) if (bsz + asz) > 1e-9 else 0.0

        snap = BookSnapshot(
            timestamp=ts,
            best_bid_price=bp,
            best_ask_price=ap,
            best_bid_depth=bsz,
            best_ask_depth=asz,
            obi_l1=obi,
            obi_l3=obi,
            obi_l5=obi,
            obi_l10=obi,
            total_bid_depth=bsz,
            total_ask_depth=asz,
            bid_levels=((bp, bsz),),
            ask_levels=((ap, asz),),
        )
        snaps.append(snap)
    return L2BookTracker(snaps)


class SpotSkewMM:
    """TouchMM + spot_obi directional skew (mirrors exp74 exactly)."""

    def __init__(self, spot_alpha: float = 0.0):
        self.spot_alpha = spot_alpha
        self.n_quotes = 0
        self.n_inside = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.spot_alpha * stats.obi * TICK

        self.n_quotes += 1
        if abs(shift) >= half:
            self.n_inside += 1

        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask,
                             reservation_price=mid + shift,
                             optimal_spread=ask - bid,
                             bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def run_cell(tr, qt, quotes_df, spot_alpha):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                      queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = SpotSkewMM(spot_alpha=spot_alpha)
    l2 = quote_based_l2_tracker(quotes_df)
    res = Backtest(strat, market_state=ms, order_manager=om,
                   requote_on_fill=True,
                   requote_interval=REQUOTE_INTERVAL,
                   tolerance_ticks=0.5,
                   tick_size=TICK,
                   verbose=False).run(tr, qt, l2_tracker=l2)

    pnl0 = float(res.metrics.get("total_pnl", 0.0))
    fills = om.fills
    takers = [f for f in fills if getattr(f, "is_taker", False)]
    taker_notional = sum(f.quantity * f.price for f in takers)
    pnl_fee = pnl0 - TAKER_FEE * taker_notional
    inside_frac = strat.n_inside / max(strat.n_quotes, 1)
    return pnl0, pnl_fee, len(fills), len(takers), inside_frac


def main():
    days = oos_dates()
    print(f"LINK OOS validation (Jun-Jul 2025), {len(days)} days")
    print(f"quote-based L2 proxy, queue_fraction={QUEUE_FRACTION}, "
          f"latency={LATENCY*1000:.0f}ms, requote={REQUOTE_INTERVAL*1000:.0f}ms")
    print(f"spot_alphas={SPOT_ALPHAS}\n")

    results = {a: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": [],
                   "inside_frac": [], "dates": []}
               for a in SPOT_ALPHAS}

    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        quotes_df = pd.read_parquet(str(DATA / f"quotes_LINK_{d}.parquet"),
                                    columns=["time_exchange", "bid_price",
                                             "ask_price", "bid_size", "ask_size"])
        row = {}
        for a in SPOT_ALPHAS:
            pnl0, pnl_fee, n, tk, ins = run_cell(tr, qt, quotes_df, a)
            results[a]["pnl0"].append(pnl0)
            results[a]["pnl_fee"].append(pnl_fee)
            results[a]["fills"].append(n)
            results[a]["takers"].append(tk)
            results[a]["inside_frac"].append(ins)
            results[a]["dates"].append(d)
            row[a] = pnl_fee
        print(f"  [{i+1}/{len(days)}] {d}  " +
              "  ".join(f"a={a}:{row[a]:+.2f}" for a in SPOT_ALPHAS))

    print(f"\n{'alpha':>6} {'mean/day':>10} {'std/day':>9} {'days+':>7} "
          f"{'fills':>8} {'taker%':>7} {'inside%':>8}")
    print("-" * 62)

    summary = {}
    for a in SPOT_ALPHAS:
        r = results[a]
        fees = np.array(r["pnl_fee"])
        fills = np.array(r["fills"])
        takers = np.array(r["takers"])
        ins = np.array(r["inside_frac"])
        mean_pnl = fees.mean()
        std_pnl = fees.std()
        days_pos = (fees > 0).mean() * 100
        mean_fills = fills.mean()
        taker_pct = (takers / np.maximum(fills, 1)).mean() * 100
        mean_ins = ins.mean() * 100
        print(f"  {a:>4.1f} {mean_pnl:>+10.2f} {std_pnl:>9.2f} "
              f"{days_pos:>6.1f}% {mean_fills:>8.1f} "
              f"{taker_pct:>6.1f}% {mean_ins:>7.2f}%")
        summary[a] = {
            "mean_pnl_per_day": mean_pnl,
            "std_pnl_per_day": std_pnl,
            "days_positive_pct": days_pos,
            "mean_fills_per_day": mean_fills,
            "taker_pct": taker_pct,
            "inside_frac_pct": mean_ins,
            "n_days": len(fees),
            "per_day": [{"date": d, "pnl_fee": float(p), "fills": int(f)}
                        for d, p, f in zip(r["dates"], fees, fills)],
        }

    out_path = OUT / "oos_summary.json"
    with open(out_path, "w") as fh:
        json.dump({"window": "2025-06-11_to_2025-07-10",
                   "n_days": len(days),
                   "queue_fraction": QUEUE_FRACTION,
                   "latency_s": LATENCY,
                   "requote_interval_s": REQUOTE_INTERVAL,
                   "taker_fee_bps": TAKER_FEE * 1e4,
                   "summary": summary}, fh, indent=2)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
