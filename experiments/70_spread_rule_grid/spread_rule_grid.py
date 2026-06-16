"""
spread_rule_grid.py
====================
Exp 70 -- spread-rule x skew grid under the L2-honest engine (queue_model="l2",
queue_fraction=0.5, latency=0.01, requote_interval=0.05 -- same settings as
exp68/69).

Motivation
----------
exp65-69's "TouchMM" baseline sets half_spread = current market spread / 2
(mirrors the touch, no gamma/kappa/sigma). exp68/69 found that adding a
spot_obi skew (spot1, spot_alpha=1) on top of TouchMM turns the C33
zero-profit-equilibrium baseline into +$22.32/day, 30/30 days+ (at
queue_fraction=0.5).

This experiment asks: does the spread RULE itself matter, now that latency
and requoting are realistic? Three rules x the same two skew variants:

  - touch    : half_spread = market_spread / 2 (exp68/69's baseline rule;
               LINK's market spread is ~10 ticks essentially always, so this
               is close to a 5-tick constant in practice)
  - as       : Avellaneda-Stoikov optimal spread, using the LINK zero-shot
               calibration from exp40 (gamma=1e-8, kappa_as_min=1.5,
               min_spread_bps=6.4381, T=9702.0). With gamma~0 this collapses
               to max(1/kappa_as, min_spread_bps-floor) -- i.e. a *dynamic*
               kappa-driven spread with a 6.44bps floor.
  - constant : a literal fixed half-spread of 5 ticks (matches LINK's median
               10-tick market spread / 2, and exp68/69's TouchMM fallback).

skew (spot_alpha * stats.obi * TICK) is applied identically to all three, as
an additive shift to bid/ask/reservation_price -- exactly as in exp69's
spot1.

Run from master2/ root with .venv activated:
    python experiments/70_spread_rule_grid/spread_rule_grid.py
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
LATENCY = 0.01           # 10ms, matches exp68/69
REQUOTE_INTERVAL = 0.05   # 50ms, matches exp68/69
QUEUE_FRACTION = 0.5
TAKER_FEE = 0.00045      # 4.5bps, applied post-hoc

CONST_HALF_TICKS = 5.0   # LINK median market spread is 10 ticks (see exp70 docstring)

# A-S zero-shot calibration for LINK (exp40_link_apr2026_baseline/config.json)
AS_GAMMA = 1e-8
AS_T = 9702.0
# kappa_as is in 1/$ units (market_state.py: "fill-distance sensitivity, inverse
# price"). The library default/prior of 1.5 implies adverse_selection_term =
# 2/kappa = $1.33 -- ~1330 ticks on a ~$9 LINK price, so nothing ever fills and
# the live KappaEstimator never gets data to update away from that prior (cold
# start). 200 (1/$) gives 2/kappa = $0.01 = 10 ticks, matching LINK's actual
# ~10-tick market spread -- close to the min_spread_bps floor below, so quotes
# actually fill and kappa_as can update live from there.
AS_KAPPA_MIN = 200.0
AS_MIN_SPREAD_BPS = 6.4381

SPREAD_RULES = ["touch", "as", "constant"]
SKEW_VARIANTS = {"baseline": 0.0, "spot1": 1.0}  # spot_alpha


class SpreadRuleMM:
    """spot_obi-skewed quoting (exp69's spot1 mechanism) on top of one of
    three spread rules: touch (exp68/69), A-S (gamma~0 zero-shot calibration),
    or a literal constant half-spread."""

    def __init__(self, spread_rule="touch", spot_alpha=0.0):
        self.spread_rule = spread_rule
        self.spot_alpha = spot_alpha

    def _half_spread(self, stats, mid, t_remaining):
        if self.spread_rule == "touch":
            return stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        if self.spread_rule == "constant":
            return CONST_HALF_TICKS * TICK
        # "as": Avellaneda-Stoikov optimal spread (gamma~0 LINK calibration)
        sigma_price = stats.sigma * mid
        kappa = max(stats.kappa_as, AS_KAPPA_MIN)
        if AS_GAMMA <= 1e-12:
            inv_term = 0.0
            adverse_term = 2.0 / kappa
        else:
            inv_term = AS_GAMMA * sigma_price ** 2 * t_remaining
            adverse_term = (2.0 / AS_GAMMA) * np.log1p(AS_GAMMA / kappa)
        full_spread = max(inv_term + adverse_term, 0.0)
        min_full_spread = mid * AS_MIN_SPREAD_BPS / 1e4
        return max(full_spread / 2.0, min_full_spread / 2.0)

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        if t_remaining is None:
            t_remaining = AS_T
        mid = stats.mid_price
        half = self._half_spread(stats, mid, t_remaining)
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


def run_cell(tr, qt, spread_rule, spot_alpha, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = SpreadRuleMM(spread_rule=spread_rule, spot_alpha=spot_alpha)
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
    print(f"LINK Apr-2026 spread-rule x skew grid (queue_model=l2, queue_fraction={QUEUE_FRACTION}, "
          f"latency={LATENCY * 1000:.0f}ms, requote={REQUOTE_INTERVAL * 1000:.0f}ms), "
          f"{len(days)} days, rules={SPREAD_RULES}, skew={list(SKEW_VARIANTS)}\n")

    results = {rule: {name: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []}
                       for name in SKEW_VARIANTS}
               for rule in SPREAD_RULES}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for rule in SPREAD_RULES:
            for name, spot_alpha in SKEW_VARIANTS.items():
                pnl0, pnl_fee, n, tk = run_cell(tr, qt, rule, spot_alpha, l2_snaps)
                results[rule][name]["pnl0"].append(pnl0)
                results[rule][name]["pnl_fee"].append(pnl_fee)
                results[rule][name]["fills"].append(n)
                results[rule][name]["takers"].append(tk)
                row[(rule, name)] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"{rule}/{name}={row[(rule, name)]:+.2f}"
                        for rule in SPREAD_RULES for name in SKEW_VARIANTS))

    print(f"\n{'rule':>10} {'variant':>10} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7}")
    summary = {rule: {} for rule in SPREAD_RULES}
    for rule in SPREAD_RULES:
        for name in SKEW_VARIANTS:
            r = results[rule][name]
            p0 = np.array(r["pnl0"])
            pf = np.array(r["pnl_fee"])
            f_arr = np.array(r["fills"])
            tk_arr = np.array(r["takers"])
            taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
            print(f"{rule:>10} {name:>10} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
                  f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}%")
            summary[rule][name] = {
                "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
                "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
                "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
                "per_day_pnl_fee0": r["pnl0"],
                "per_day_pnl_fee45bps": r["pnl_fee"],
            }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "spread_rule_grid.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fraction": QUEUE_FRACTION, "latency": LATENCY,
                   "requote_interval": REQUOTE_INTERVAL, "taker_fee": TAKER_FEE,
                   "spread_rules": SPREAD_RULES, "skew_variants": SKEW_VARIANTS,
                   "const_half_ticks": CONST_HALF_TICKS,
                   "as_params": {"gamma": AS_GAMMA, "T": AS_T, "kappa_as_min": AS_KAPPA_MIN,
                                  "min_spread_bps": AS_MIN_SPREAD_BPS},
                   "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
