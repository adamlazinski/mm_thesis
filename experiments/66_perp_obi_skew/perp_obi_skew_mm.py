"""
perp_obi_skew_mm.py
====================
Exp 66 -- does adding LINK PERP order-book imbalance (perp_obi) as a second
skew term to a spot-OBI-adjusted at-touch market maker change PnL relative to
a spot-OBI-only skew, or to no skew at all?

Background
----------
- exp45 (as_obi_loss_limit, obi_alpha=0.00154) found that a SYMMETRIC OBI-based
  reservation-price shift HURTS: it doubles fills but lowers per-fill quality,
  despite spot OBI's IC ~0.20 (exp44). That strategy's code no longer exists in
  the current (engine-fixed) tree, so the "spot_obi only" cell is reproduced
  here from scratch on the corrected engine.
- exp65 (1s and 10ms grids, 30 LINK Apr-2026 days) found perp_obi carries a
  real but small (IC ~0.04-0.06), mostly-incremental (redundancy ~0.04 with
  spot_obi) cross-venue signal for spot forward returns, with no sub-second
  spike -- the edge builds over multiple seconds.
- The queue-priority verdict (exp59/62): the HONEST (L2 queue, latency-aware)
  at-touch engine gives -$7.93/day for plain TouchMM. This script instead uses
  queue_model="none" (first-touch = fill, the "inside-spread artifact" regime)
  -- the SAME regime exp45 used -- so this is a FAST, exploratory, RELATIVE
  comparison of skew variants against each other and against the unskewed
  TouchMM control, not an absolute honest-PnL claim.

Mechanism
---------
Symmetric reservation-price shift (same pattern as ForecastAS / exp45):
    signal = spot_alpha * spot_obi(t) + perp_alpha * perp_obi(t)
    shift  = signal * tick_size
    bid, ask -> bid + shift, ask + shift  (spread unchanged)
spot_obi = stats.obi (L1, live from MarketState). perp_obi = L1 OBI of
LINK-PERP quotes, as-of looked up by timestamp (perp quotes are ~1Hz; spot
backtest timestamps are looked up against this coarser perp grid).

alpha is in ticks per unit OBI (OBI in [-1, 1]), so alpha=1 means a fully
imbalanced book shifts both quotes by exactly 1 tick.

Variants (7): baseline (no skew), spot-only at alpha={1,2} (intuitive sign,
re-establishing the exp45-style cell), and spot=1 crossed with
perp_alpha in {+1, +2, -1, -2} (perp_obi's sign is NOT assumed -- exp45 found
the "intuitive" sign of OBI skew hurt, so testing the fade direction too is
the actual open question, not a hunch).

Run from master2/ root with .venv activated:
    python experiments/66_perp_obi_skew/perp_obi_skew_mm.py
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
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT = Path(__file__).resolve().parent / "results"

TICK = 0.001
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01     # 10ms (2026-06-15 default for new experiment scripts)
REQUOTE_INTERVAL = 0.5

VARIANTS = {
    "baseline":       dict(spot_alpha=0.0, perp_alpha=0.0),
    "spot1":          dict(spot_alpha=1.0, perp_alpha=0.0),
    "spot2":          dict(spot_alpha=2.0, perp_alpha=0.0),
    "spot1_perp1":    dict(spot_alpha=1.0, perp_alpha=1.0),
    "spot1_perpneg1": dict(spot_alpha=1.0, perp_alpha=-1.0),
    "spot1_perp2":    dict(spot_alpha=1.0, perp_alpha=2.0),
    "spot1_perpneg2": dict(spot_alpha=1.0, perp_alpha=-2.0),
}


class OBISkewMM:
    """At-touch MM (TouchMM, exp62) + symmetric spot/perp OBI reservation shift."""

    def __init__(self, spot_alpha=0.0, perp_alpha=0.0, perp_t=None, perp_obi=None):
        self.spot_alpha = spot_alpha
        self.perp_alpha = perp_alpha
        self.perp_t = perp_t if perp_t is not None else np.array([])
        self.perp_obi = perp_obi if perp_obi is not None else np.array([])

    def _perp_obi_at(self, ts):
        if len(self.perp_t) == 0:
            return 0.0
        idx = np.searchsorted(self.perp_t, ts, side="right") - 1
        return float(self.perp_obi[idx]) if idx >= 0 else 0.0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        signal = self.spot_alpha * stats.obi + self.perp_alpha * self._perp_obi_at(ts)
        shift = signal * TICK
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
    return sorted(sp & pp & tt)


def to_epoch_seconds(ts: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(ts, utc=True).dt.tz_localize(None)
    return dt.astype("int64").to_numpy() / 1e9


def load_perp_obi(date):
    q = pd.read_parquet(DATA / f"quotes_LINK_PERP_{date}.parquet",
                         columns=["time_exchange", "bid_size", "ask_size"])
    t = to_epoch_seconds(q["time_exchange"])
    bsz, asz = q["bid_size"].to_numpy(), q["ask_size"].to_numpy()
    obi = np.where(bsz + asz > 0, (bsz - asz) / (bsz + asz), 0.0)
    order = np.argsort(t, kind="stable")
    return t[order], obi[order]


def run_variant(tr, qt, params, perp_t, perp_obi):
    om = OrderManager(maker_fee=0.0, latency=LATENCY, queue_model="none")
    ms = MarketState(120, 60, 0.9)
    strat = OBISkewMM(perp_t=perp_t, perp_obi=perp_obi, **params)
    res = Backtest(strat, market_state=ms, order_manager=om, requote_on_fill=True,
                    requote_interval=REQUOTE_INTERVAL, tolerance_ticks=0.5,
                    tick_size=TICK, verbose=False).run(tr, qt)
    return float(res.metrics.get("total_pnl", 0.0)), len(om.fills)


def main():
    days = dates()
    print(f"LINK Apr-2026 perp-OBI skew test (queue_model=none, latency={LATENCY*1000:.0f}ms), "
          f"{len(days)} days, {len(VARIANTS)} variants\n")

    results = {v: [] for v in VARIANTS}
    fills = {v: [] for v in VARIANTS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        perp_t, perp_obi = load_perp_obi(d)

        row = {}
        for name, params in VARIANTS.items():
            pnl, n_fills = run_variant(tr, qt, params, perp_t, perp_obi)
            results[name].append(pnl)
            fills[name].append(n_fills)
            row[name] = pnl
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"{k}={row[k]:+.2f}" for k in VARIANTS))

    print(f"\n{'variant':>16} {'mean_pnl':>10} {'std_pnl':>10} {'days_pos':>10} {'mean_fills':>11}")
    summary = {}
    for name in VARIANTS:
        arr = np.array(results[name])
        f_arr = np.array(fills[name])
        print(f"{name:>16} {arr.mean():10.4f} {arr.std():10.4f} {100 * (arr > 0).mean():9.1f}% "
              f"{f_arr.mean():11.1f}")
        summary[name] = {
            "mean_pnl": float(arr.mean()), "std_pnl": float(arr.std()),
            "days_pos_pct": float((arr > 0).mean()), "mean_fills": float(f_arr.mean()),
            "per_day_pnl": results[name],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "perp_obi_skew_mm.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "variants": VARIANTS, "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
