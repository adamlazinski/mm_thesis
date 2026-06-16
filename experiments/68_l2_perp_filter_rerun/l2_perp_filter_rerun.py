"""
l2_perp_filter_rerun.py
========================
Exp 68 -- L2-honest rerun of the best/most-informative cells from exp66
(perp_obi skew) and exp67 (perp toxicity spread-widening), under the
CORRECTED engine's honest at-touch regime (queue_model="l2", queue_fraction=0.5,
L2BookTracker from orderbooks_LINK_{date}.parquet, exp62's TouchMM/honest_mm
pattern).

Motivation
----------
exp66/exp67 ran queue_model="none" -- the "inside-spread artifact" regime
where measured PnL is roughly monotonic in fill COUNT (any fill is "good"
because first-touch = fill, with no adverse-selection-via-queue cost). Under
that regime every perp-derived skew/widening variant underperformed the
unskewed/unwidened TouchMM baseline, because each one *reduces* fill count.

But the honest L2 regime (exp62: TouchMM = -$7.93/day, 0/30 days) penalizes
fills that turn out to be adverse-selected. A filter that trades fewer, better
fills could look like a "loss" in the artifact regime and still be a net WIN
once adverse selection is priced in -- that's the gap this rerun probes.

Variants (4):
  - baseline : TouchMM, no skew/no widening -- reproduces exp62's central cell
               under latency=10ms instead of 100ms.
  - spot1    : exp66's best skew variant (spot_alpha=1, perp_alpha=0;
               +2.2% over baseline in the artifact regime).
  - obi_a1   : exp67's most aggressive widening (|perp_obi| toxicity,
               alpha=1) -- fills collapsed -87% in the artifact regime; tests
               whether suppressing fills from a persistently-imbalanced perp
               book helps once adverse selection is priced in.
  - ret_a1   : exp67's best "smart" widening (perp mid-return jump z-score,
               alpha=1) -- the most spike-like / least artifact-PnL-damaging
               of the toxicity filters.

latency=0.01 (10ms, 2026-06-15 default) and queue_fraction=0.5 per explicit
request ("run it under reasonable queue assumption and decreased latency...
probably 0.5 would be enough"). taker_fee=0.00045 (4.5bps) applied post-hoc
to is_taker fills, exactly as in exp62.

Run from master2/ root with .venv activated:
    python experiments/68_l2_perp_filter_rerun/l2_perp_filter_rerun.py
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
LATENCY = 0.01        # 10ms (2026-06-15 default, and per explicit request)
REQUOTE_INTERVAL = 0.05  # 50ms -- recompute faster to actually exploit 10ms latency
QUEUE_FRACTION = 0.5  # per explicit request
TAKER_FEE = 0.00045   # 4.5bps, applied post-hoc (matches exp62)

LAG_RET = 5
VOL_WINDOW = 10
MAX_MULT = 5.0

VARIANTS = {
    "baseline": dict(spot_alpha=0.0, perp_alpha=0.0, widen_signal=None, widen_alpha=0.0),
    "spot1":    dict(spot_alpha=1.0, perp_alpha=0.0, widen_signal=None, widen_alpha=0.0),
    "obi_a1":   dict(spot_alpha=0.0, perp_alpha=0.0, widen_signal="obi", widen_alpha=1.0),
    "ret_a1":   dict(spot_alpha=0.0, perp_alpha=0.0, widen_signal="ret", widen_alpha=1.0),
}


class PerpAugmentedMM:
    """TouchMM (exp62) + optional spot/perp OBI skew (exp66) + optional perp
    toxicity spread widening (exp67). All three mechanisms share the same
    as-of perp-timestamp lookup."""

    def __init__(self, perp_t, perp_obi, signals, spot_alpha=0.0, perp_alpha=0.0,
                 widen_signal=None, widen_alpha=0.0, max_mult=MAX_MULT):
        self.perp_t = perp_t
        self.perp_obi = perp_obi
        self.widen_arr = signals[widen_signal] if widen_signal else None
        self.spot_alpha = spot_alpha
        self.perp_alpha = perp_alpha
        self.widen_alpha = widen_alpha
        self.max_mult = max_mult

    def _at(self, arr, ts):
        if arr is None or len(self.perp_t) == 0:
            return 0.0
        idx = np.searchsorted(self.perp_t, ts, side="right") - 1
        return float(arr[idx]) if idx >= 0 else 0.0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK

        if self.widen_alpha:
            mult = min(1.0 + self.widen_alpha * self._at(self.widen_arr, ts), self.max_mult)
            half *= mult

        signal = self.spot_alpha * stats.obi + self.perp_alpha * self._at(self.perp_obi, ts)
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
    ob = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "orderbooks_LINK_2026-04-*.parquet"))}
    return sorted(sp & pp & tt & ob)


def to_epoch_seconds(ts: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(ts, utc=True).dt.tz_localize(None)
    return dt.astype("int64").to_numpy() / 1e9


def load_perp_data(date):
    """Signed perp L1 OBI (for skew, exp66) + the three exp67 toxicity
    signals (obi=|perp_obi|, ret/vol z-scored, clipped >=0)."""
    q = pd.read_parquet(DATA / f"quotes_LINK_PERP_{date}.parquet",
                         columns=["time_exchange", "bid_price", "ask_price",
                                  "bid_size", "ask_size"])
    t = to_epoch_seconds(q["time_exchange"])
    mid = (q["bid_price"].to_numpy() + q["ask_price"].to_numpy()) / 2.0
    bsz, asz = q["bid_size"].to_numpy(), q["ask_size"].to_numpy()
    obi = np.where(bsz + asz > 0, (bsz - asz) / (bsz + asz), 0.0)
    order = np.argsort(t, kind="stable")
    t, mid, obi = t[order], mid[order], obi[order]

    logmid = np.log(mid)
    ret = np.zeros(len(t))
    ret[LAG_RET:] = np.abs(logmid[LAG_RET:] - logmid[:-LAG_RET])

    step = np.diff(logmid, prepend=logmid[0])
    vol = pd.Series(step).rolling(VOL_WINDOW, min_periods=1).std().fillna(0.0).to_numpy()

    ret_z = (ret - ret.mean()) / (ret.std() + 1e-12)
    vol_z = (vol - vol.mean()) / (vol.std() + 1e-12)

    signals = {"obi": np.abs(obi), "ret": np.clip(ret_z, 0, None), "vol": np.clip(vol_z, 0, None)}
    return t, obi, signals


def run_variant(tr, qt, params, perp_t, perp_obi, signals, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    strat = PerpAugmentedMM(perp_t, perp_obi, signals, **params)
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
    print(f"LINK Apr-2026 L2-honest rerun of exp66/67 best cells "
          f"(queue_model=l2, queue_fraction={QUEUE_FRACTION}, "
          f"latency={LATENCY * 1000:.0f}ms, taker_fee={TAKER_FEE * 1e4:.1f}bps post-hoc), "
          f"{len(days)} days, {len(VARIANTS)} variants\n")

    results = {v: {"pnl0": [], "pnl_fee": [], "fills": [], "takers": []} for v in VARIANTS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        perp_t, perp_obi, signals = load_perp_data(d)
        l2_snaps = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))

        row = {}
        for name, params in VARIANTS.items():
            pnl0, pnl_fee, n, tk = run_variant(tr, qt, params, perp_t, perp_obi, signals, l2_snaps)
            results[name]["pnl0"].append(pnl0)
            results[name]["pnl_fee"].append(pnl_fee)
            results[name]["fills"].append(n)
            results[name]["takers"].append(tk)
            row[name] = pnl_fee
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"{k}={row[k]:+.2f}" for k in VARIANTS))

    print(f"\n{'variant':>10} {'fee0':>9} {'fee45bp':>9} {'std':>9} "
          f"{'days_pos':>9} {'fills':>9} {'taker%':>7}")
    summary = {}
    for name in VARIANTS:
        p0 = np.array(results[name]["pnl0"])
        pf = np.array(results[name]["pnl_fee"])
        f_arr = np.array(results[name]["fills"])
        tk_arr = np.array(results[name]["takers"])
        taker_pct = 100 * tk_arr.sum() / max(f_arr.sum(), 1)
        print(f"{name:>10} {p0.mean():9.4f} {pf.mean():9.4f} {pf.std():9.4f} "
              f"{100 * (pf > 0).mean():8.1f}% {f_arr.mean():9.1f} {taker_pct:6.1f}%")
        summary[name] = {
            "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
            "std_pnl_fee45bps": float(pf.std()), "days_pos_pct": float((pf > 0).mean()),
            "mean_fills": float(f_arr.mean()), "taker_pct": float(taker_pct),
            "per_day_pnl_fee0": results[name]["pnl0"],
            "per_day_pnl_fee45bps": results[name]["pnl_fee"],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "l2_perp_filter_rerun.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "queue_fraction": QUEUE_FRACTION, "latency": LATENCY,
                   "taker_fee": TAKER_FEE, "variants": VARIANTS, "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
