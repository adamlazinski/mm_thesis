"""
spot_alpha_sweep_triage.py
===========================
Exp 73 -- FAST TRIAGE for caveat (b) of C42: spot_alpha=1.0 was C40's best
cell in the artifact regime, never optimized under the L2-honest engine.

Triage pattern (per the new sweep workflow): scan a wide spot_alpha grid on a
small stratified subset of days (5 of exp69's 30) to find the interesting
region, THEN confirm the winning candidate(s) on the full 30 days in a
follow-up experiment. This trades precision for speed -- 9 alphas x 5 days =
45 cells vs exp69's 300, so it should finish in ~15 min instead of ~1.5-2h.

shift = spot_alpha * stats.obi * TICK, applied additively to bid/ask/
reservation_price (same SpotSkewMM as exp68/69/70). At spot_alpha=1 the max
shift (|obi|=1) is 1 tick, small vs the ~5-tick LINK half-spread. This sweep
goes up to spot_alpha=5 (max shift = 5 ticks, comparable to the half-spread)
to look for where the mechanism saturates or breaks down.

queue_model="l2", queue_fraction=0.5 (C42's calibration point), latency=0.01
(10ms), requote_interval=0.05 (50ms) -- same as exp68/69/70.

Run from master2/ root with .venv activated:
    python experiments/73_spot_alpha_sweep_triage/spot_alpha_sweep_triage.py
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
LATENCY = 0.01          # 10ms, matches exp68/69/70
REQUOTE_INTERVAL = 0.05  # 50ms, matches exp68/69/70
TAKER_FEE = 0.00045     # 4.5bps, applied post-hoc
QUEUE_FRACTION = 0.5    # C42's calibration point

SPOT_ALPHAS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]


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
    return pnl0, pnl_fee, len(fills), len(takers)


def main():
    all_days = dates()
    days = all_days[::6]  # stratified subset: 5 of the 30 days
    print(f"LINK Apr-2026 spot_alpha TRIAGE sweep (queue_model=l2, "
          f"queue_fraction={QUEUE_FRACTION}, latency={LATENCY * 1000:.0f}ms, "
          f"requote={REQUOTE_INTERVAL * 1000:.0f}ms), {len(days)}/{len(all_days)} days "
          f"(stratified every 6th), spot_alpha in {SPOT_ALPHAS}\n")
    print(f"Days: {days}\n")

    results = {a: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []} for a in SPOT_ALPHAS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for a in SPOT_ALPHAS:
            pnl0, pnl_fee, n, tk = run_cell(tr, qt, a, l2_snaps)
            results[a]["pnl0"].append(pnl0)
            results[a]["pnl_fee"].append(pnl_fee)
            results[a]["fills"].append(n)
            results[a]["takers"].append(tk)
            row[a] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"a={a}:{row[a]:+.2f}" for a in SPOT_ALPHAS))

    print(f"\n{'alpha':>6} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7}")
    summary = {}
    for a in SPOT_ALPHAS:
        r = results[a]
        p0 = np.array(r["pnl0"])
        pf = np.array(r["pnl_fee"])
        f_arr = np.array(r["fills"])
        tk_arr = np.array(r["takers"])
        taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
        print(f"{a:6.2f} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
              f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}%")
        summary[str(a)] = {
            "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
            "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
            "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
            "per_day_pnl_fee0": r["pnl0"],
            "per_day_pnl_fee45bps": r["pnl_fee"],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "spot_alpha_sweep_triage.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "days": days, "queue_fraction": QUEUE_FRACTION,
                   "latency": LATENCY, "requote_interval": REQUOTE_INTERVAL,
                   "taker_fee": TAKER_FEE, "spot_alphas": SPOT_ALPHAS,
                   "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
