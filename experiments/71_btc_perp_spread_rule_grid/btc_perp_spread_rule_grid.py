"""
btc_perp_spread_rule_grid.py
=============================
Exp 71 -- BTC-PERP version of exp70's spread-rule x skew grid. Tests whether
the spot_obi-skew mechanism that turned LINK's zero-profit-equilibrium
baseline into +$22.32/day (exp68/69, C42) generalizes to a different
instrument (BTC perpetual @ ~$68k, tick=$0.1, ~1-tick market spread) under the
same L2-honest engine (queue_model="l2", queue_fraction=0.5, latency=0.01,
requote_interval=0.05).

Data constraint
---------------
BTC SPOT has no L2 orderbook snapshots at all (orderbooks_BTC_*.parquet does
not exist). orderbooks_BTC_PERP_2026-04-{01..05} does exist, and overlaps with
quotes_BTC_PERP / trades_BTC_PERP for the same 5 days -- so this experiment
runs ON the BTC perp itself (its own quotes/trades/L2 book), exactly analogous
to how exp70 runs on LINK spot using LINK spot's own quotes/trades/L2 book.
spot1's skew signal is BTC-PERP's OWN L1 OBI (stats.obi), not a cross-venue
signal -- only 5 days (2026-04-01..05), vs LINK's 30.

BTC-specific recalibration vs exp70
------------------------------------
  - TICK = 0.1 (empirical: BTC-PERP quotes are on a $0.1 grid, median spread
    = $0.1 = 1 tick -- consistent with CLAUDE.md's "BTC spread ~1 tick").
  - ORDER_SIZE = 0.001, MAX_INV = 0.02 (BTC units, from exp46/47 BTC RL configs).
  - CONST_HALF_TICKS = 0.5 -- half of BTC's median 1-tick spread, so "constant"
    reproduces the touch exactly when shift=0 (mid is always at a half-tick
    offset from the touch by construction).
  - AS_KAPPA_MIN = 20.0 (1/$): gives 2/kappa = $0.1 = 1 tick, matching BTC's
    natural spread (vs LINK's 200, which gave 10 ticks). The library default
    of 1.5 would give 2/kappa = $1.33 = 13.3 ticks -- too wide, same cold-start
    problem as exp70 pre-fix.
  - AS_MIN_SPREAD_BPS = 0.01: at mid~$68,000 this floors at $0.068 (~0.7
    ticks), below the kappa-driven 1-tick spread, so it doesn't dominate
    (LINK's 6.4381bps would floor at ~$43.8 on BTC -- absurd).

Run from master2/ root with .venv activated:
    python experiments/71_btc_perp_spread_rule_grid/btc_perp_spread_rule_grid.py
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

TICK = 0.1
ORDER_SIZE = 0.001
MAX_INV = 0.02
LATENCY = 0.01           # 10ms, matches exp68/69/70
REQUOTE_INTERVAL = 0.05   # 50ms, matches exp68/69/70
QUEUE_FRACTION = 0.5
TAKER_FEE = 0.00045      # 4.5bps, applied post-hoc

CONST_HALF_TICKS = 0.5   # BTC median market spread is 1 tick

# A-S zero-shot-style calibration for BTC-PERP (see module docstring)
AS_GAMMA = 1e-8
AS_T = 9702.0
AS_KAPPA_MIN = 20.0
AS_MIN_SPREAD_BPS = 0.01

SPREAD_RULES = ["touch", "as", "constant"]
SKEW_VARIANTS = {"baseline": 0.0, "spot1": 1.0}  # spot_alpha (BTC-PERP's own OBI)


class SpreadRuleMM:
    """Same architecture as exp70's SpreadRuleMM: spot_obi skew on top of one
    of three spread rules (touch / A-S gamma~0 / constant)."""

    def __init__(self, spread_rule="touch", spot_alpha=0.0):
        self.spread_rule = spread_rule
        self.spot_alpha = spot_alpha

    def _half_spread(self, stats, mid, t_remaining):
        if self.spread_rule == "touch":
            return stats.spread / 2.0 if stats.spread > 0 else CONST_HALF_TICKS * TICK
        if self.spread_rule == "constant":
            return CONST_HALF_TICKS * TICK
        # "as": Avellaneda-Stoikov optimal spread (gamma~0 BTC-PERP calibration)
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
    qq = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_BTC_PERP_2026-04-*.parquet"))}
    tt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_BTC_PERP_2026-04-*.parquet"))}
    ob = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "orderbooks_BTC_PERP_2026-04-*.parquet"))}
    return sorted(qq & tt & ob)


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
    print(f"BTC-PERP Apr-2026 spread-rule x skew grid (queue_model=l2, queue_fraction={QUEUE_FRACTION}, "
          f"latency={LATENCY * 1000:.0f}ms, requote={REQUOTE_INTERVAL * 1000:.0f}ms), "
          f"{len(days)} days, rules={SPREAD_RULES}, skew={list(SKEW_VARIANTS)}\n")

    results = {rule: {name: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []}
                       for name in SKEW_VARIANTS}
               for rule in SPREAD_RULES}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_BTC_PERP_{d}.parquet"),
                                  str(DATA / f"quotes_BTC_PERP_{d}.parquet"))
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_BTC_PERP_{d}.parquet"))

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
    out_path = OUT / "btc_perp_spread_rule_grid.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fraction": QUEUE_FRACTION, "latency": LATENCY,
                   "requote_interval": REQUOTE_INTERVAL, "taker_fee": TAKER_FEE,
                   "tick_size": TICK, "order_size": ORDER_SIZE, "max_inventory": MAX_INV,
                   "spread_rules": SPREAD_RULES, "skew_variants": SKEW_VARIANTS,
                   "const_half_ticks": CONST_HALF_TICKS,
                   "as_params": {"gamma": AS_GAMMA, "T": AS_T, "kappa_as_min": AS_KAPPA_MIN,
                                  "min_spread_bps": AS_MIN_SPREAD_BPS},
                   "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
