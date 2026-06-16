"""
markout_analysis.py
====================
Exp 75 -- per-fill markout (post-fill price drift / adverse selection)
analysis for caveat (c) of C42, using the new fill_analysis.compute_markouts
/ markout_summary helpers.

Compares three spot_alpha settings at queue_fraction=0.5 (C42's point),
latency=0.01 (10ms), requote_interval=0.05 (50ms), 30 days LINK Apr-2026:
  - alpha=0.0 (baseline, signal-blind) -- -$0.24/day, 46.7% days+ (C42/exp74)
  - alpha=1.0 (C42's original spot1)   -- +$22.32/day, 100% days+ (C42/exp74)
  - alpha=4.0 (exp74's optimum)         -- +$56.00/day, 100% days+ (exp74)

Question: does alpha=4's ~2.5x larger PnL correspond to measurably LESS
adverse (more positive) signed markouts than alpha=1's, confirming a genuine
fill-quality improvement -- or do markouts look similar despite the PnL gap
(pointing at some other mechanism, e.g. inventory-mix effects)?

signed_markout(h) = sign * (mid(t+h) - fill.price), sign=+1 for bid fills
(we bought), -1 for ask fills (we sold). Positive = favorable, negative =
adverse selection. Horizons: 0.5, 1, 2, 5, 10s (spans the ~5-10s momentum
decay horizon from CLAUDE.md).

Run from master2/ root with .venv activated:
    python experiments/75_markout_analysis/markout_analysis.py
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
from hft_market_maker.core.fill_analysis import compute_markouts, markout_summary
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
LATENCY = 0.01          # 10ms, matches exp68/69/70/73/74
REQUOTE_INTERVAL = 0.05  # 50ms, matches exp68/69/70/73/74
TAKER_FEE = 0.00045     # 4.5bps, applied post-hoc
QUEUE_FRACTION = 0.5    # C42's calibration point

SPOT_ALPHAS = [0.0, 1.0, 4.0]
HORIZONS = (0.5, 1.0, 2.0, 5.0, 10.0)


class SpotSkewMM:
    """TouchMM (exp62) + spot_obi skew (exp66/68's spot1, generalized alpha)."""

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


def run_cell(tr, qt, spot_alpha, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
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
    mk = compute_markouts(fills, qt, horizons=HORIZONS)
    return pnl0, pnl_fee, len(fills), len(takers), mk


def main():
    days = dates()
    print(f"LINK Apr-2026 markout analysis (queue_model=l2, "
          f"queue_fraction={QUEUE_FRACTION}, latency={LATENCY * 1000:.0f}ms, "
          f"requote={REQUOTE_INTERVAL * 1000:.0f}ms), {len(days)} days, "
          f"spot_alpha in {SPOT_ALPHAS}, horizons={HORIZONS}\n")

    pnl_results = {a: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []} for a in SPOT_ALPHAS}
    markout_frames = {a: [] for a in SPOT_ALPHAS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for a in SPOT_ALPHAS:
            pnl0, pnl_fee, n, tk, mk = run_cell(tr, qt, a, l2_snaps)
            pnl_results[a]["pnl0"].append(pnl0)
            pnl_results[a]["pnl_fee"].append(pnl_fee)
            pnl_results[a]["fills"].append(n)
            pnl_results[a]["takers"].append(tk)
            markout_frames[a].append(mk)
            row[a] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"a={a}:{row[a]:+.2f}" for a in SPOT_ALPHAS))

    print(f"\n{'alpha':>6} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7}")
    pnl_summary = {}
    for a in SPOT_ALPHAS:
        r = pnl_results[a]
        p0 = np.array(r["pnl0"])
        pf = np.array(r["pnl_fee"])
        f_arr = np.array(r["fills"])
        tk_arr = np.array(r["takers"])
        taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
        print(f"{a:6.2f} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
              f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}%")
        pnl_summary[str(a)] = {
            "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
            "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
            "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
        }

    print(f"\nMarkout summary (mean signed markout, ticks; %adverse = pct of fills with "
          f"negative markout):\n")
    markout_summaries = {}
    for a in SPOT_ALPHAS:
        pooled = pd.concat(markout_frames[a], ignore_index=True)
        ms = markout_summary(pooled, horizons=HORIZONS)
        ms["mean_markout_ticks"] = ms["mean_markout"] / TICK
        print(f"  alpha={a}")
        for _, row in ms.iterrows():
            print(f"    h={row['horizon']:>4.1f}s  side={row['side']:>3}  "
                  f"mean={row['mean_markout_ticks']:+7.4f} ticks  "
                  f"adverse={row['pct_adverse']:6.2f}%  n={int(row['n'])}")
        markout_summaries[str(a)] = ms.to_dict(orient="records")

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "markout_analysis.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fraction": QUEUE_FRACTION,
                   "latency": LATENCY, "requote_interval": REQUOTE_INTERVAL,
                   "taker_fee": TAKER_FEE, "spot_alphas": SPOT_ALPHAS,
                   "horizons": list(HORIZONS),
                   "pnl_summary": pnl_summary,
                   "markout_summary": markout_summaries}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
