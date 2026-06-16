"""
spot_alpha_sweep_confirm.py
============================
Exp 74 -- CONFIRM phase for exp73's spot_alpha triage (caveat (b) of C42).

exp73 (5-day stratified subset) found spot_alpha=1.0 (C42's value) is far from
optimal: PnL rises monotonically from -1.96 (alpha<=0.5, all bit-identical --
shift = alpha*obi*TICK doesn't cross the np.round() tick boundary below
alpha~0.5) through +25.44 (alpha=1) up to +65-68 at alpha=3-5, with growth
clearly slowing past alpha=3.

Concern: at alpha>=2 (half-spread is ~5 ticks for LINK at this calibration),
shift = alpha*obi*TICK with |obi| near 1 can reach or exceed `half`, pushing
the quote to/past the mid -- i.e. INSIDE THE SPREAD, where the L2 queue model
gives queue_ahead=0 (instant next-trade fill). That's C40's inside-spread
artifact mechanism, now triggered for the high-|obi| tail. The alpha>3 PnL
growth could be genuine fill-quality edge, or the artifact creeping back in
through the skew.

This experiment:
  1. Reruns the triage grid on the FULL 30 days (alpha in {0, 1, 1.5, 2, 2.5,
     3, 4, 5} -- 0.0 and 1.0 as consistency checks against C42/exp68/69/70 and
     exp73's 5-day estimate).
  2. Adds a diagnostic: fraction of quotes per day where |shift| >= half
     (i.e. the quote lands at/inside the mid -> queue_ahead=0 candidate),
     to disambiguate "genuine fill-quality edge growth" (inside_frac stays
     small / flat) from "artifact re-emergence" (inside_frac tracks the PnL
     growth and/or fills start climbing again like exp72's qf=0 cliff).

queue_model="l2", queue_fraction=0.5 (C42's point), latency=0.01 (10ms),
requote_interval=0.05 (50ms) -- same as exp68/69/70/73.

Run from master2/ root with .venv activated:
    python experiments/74_spot_alpha_sweep_confirm/spot_alpha_sweep_confirm.py
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
LATENCY = 0.01          # 10ms, matches exp68/69/70/73
REQUOTE_INTERVAL = 0.05  # 50ms, matches exp68/69/70/73
TAKER_FEE = 0.00045     # 4.5bps, applied post-hoc
QUEUE_FRACTION = 0.5    # C42's calibration point

SPOT_ALPHAS = [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]


class SpotSkewMM:
    """TouchMM (exp62) + spot_obi skew (exp66/68's spot1, generalized alpha).

    Tracks n_quotes / n_inside for the inside-spread (|shift| >= half)
    diagnostic requested for this confirm run.
    """

    def __init__(self, spot_alpha=0.0):
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
    inside_frac = strat.n_inside / max(strat.n_quotes, 1)
    return pnl0, pnl_fee, len(fills), len(takers), inside_frac


def main():
    days = dates()
    print(f"LINK Apr-2026 spot_alpha CONFIRM sweep (queue_model=l2, "
          f"queue_fraction={QUEUE_FRACTION}, latency={LATENCY * 1000:.0f}ms, "
          f"requote={REQUOTE_INTERVAL * 1000:.0f}ms), {len(days)} days, "
          f"spot_alpha in {SPOT_ALPHAS}\n")

    results = {a: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": [], "inside_frac": []}
               for a in SPOT_ALPHAS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for a in SPOT_ALPHAS:
            pnl0, pnl_fee, n, tk, ins = run_cell(tr, qt, a, l2_snaps)
            results[a]["pnl0"].append(pnl0)
            results[a]["pnl_fee"].append(pnl_fee)
            results[a]["fills"].append(n)
            results[a]["takers"].append(tk)
            results[a]["inside_frac"].append(ins)
            row[a] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"a={a}:{row[a]:+.2f}" for a in SPOT_ALPHAS))

    print(f"\n{'alpha':>6} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7} {'inside%':>8}")
    summary = {}
    for a in SPOT_ALPHAS:
        r = results[a]
        p0 = np.array(r["pnl0"])
        pf = np.array(r["pnl_fee"])
        f_arr = np.array(r["fills"])
        tk_arr = np.array(r["takers"])
        ins_arr = np.array(r["inside_frac"])
        taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
        print(f"{a:6.2f} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
              f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}% "
              f"{100 * ins_arr.mean():7.2f}%")
        summary[str(a)] = {
            "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
            "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
            "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
            "mean_inside_frac": float(ins_arr.mean()),
            "per_day_pnl_fee0": r["pnl0"],
            "per_day_pnl_fee45bps": r["pnl_fee"],
            "per_day_inside_frac": r["inside_frac"],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "spot_alpha_sweep_confirm.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fraction": QUEUE_FRACTION,
                   "latency": LATENCY, "requote_interval": REQUOTE_INTERVAL,
                   "taker_fee": TAKER_FEE, "spot_alphas": SPOT_ALPHAS,
                   "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
