"""
perp_toxicity_filter_mm.py
===========================
Exp 67 -- instead of using LINK PERP signals to SKEW spot quotes (exp66,
symmetric reservation shift -- the mechanism exp45 found tends to hurt), use a
perp-derived "something informed/large is happening right now" signal as a
DEFENSIVE spread WIDENER on spot quotes. Same multiplicative-widening pattern
as the existing SpreadMultiplierFilter (mult = min(1 + alpha*toxicity,
max_mult), spread widened symmetrically around the reservation price), but the
toxicity signal comes from the PERP venue instead of spot's own stats.

Three candidate perp toxicity signals (tested independently):
  - obi : |perp_obi(t)| (L1 order-book imbalance, in [0,1]) -- extreme
          one-sided perp book = informed flow building.
  - ret : |perp_mid log-return over the last LAG_RET (~5) perp samples|,
          z-scored over the day, clipped >=0 -- a perp mid "jump" right now.
  - vol : rolling std of perp 1-step log-returns over VOL_WINDOW (~10) perp
          samples, z-scored over the day, clipped >=0 -- elevated perp
          realised vol right now.

perp quotes are ~1Hz, so LAG_RET=5 / VOL_WINDOW=10 samples correspond to
~5s / ~10s lookbacks. Each spot quoting step looks up the as-of perp signal
value by timestamp.

Variants (7): baseline (mult=1 always, identical to exp66's TouchMM baseline)
and each of {obi, ret, vol} at alpha in {1, 2} (mult = min(1+alpha*signal, 5)).
Same engine/day-loop as exp66: queue_model="none" (fast, relative-comparison
regime), LINK Apr-2026, 30 overlapping spot+perp days.

Run from master2/ root with .venv activated:
    python experiments/67_perp_toxicity_filter/perp_toxicity_filter_mm.py
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

LAG_RET = 5        # perp samples (~5s @ ~1Hz) for the "recent jump" signal
VOL_WINDOW = 10    # perp samples (~10s @ ~1Hz) for rolling realised vol
MAX_MULT = 5.0     # spread multiplier cap, matches SpreadMultiplierFilter default

VARIANTS = {
    "baseline": dict(signal="obi", alpha=0.0),
    "obi_a1":   dict(signal="obi", alpha=1.0),
    "obi_a2":   dict(signal="obi", alpha=2.0),
    "ret_a1":   dict(signal="ret", alpha=1.0),
    "ret_a2":   dict(signal="ret", alpha=2.0),
    "vol_a1":   dict(signal="vol", alpha=1.0),
    "vol_a2":   dict(signal="vol", alpha=2.0),
}


class PerpWidenMM:
    """At-touch MM (TouchMM, exp62) + spread widened by a perp toxicity signal."""

    def __init__(self, perp_t, signal_arr, alpha=0.0, max_mult=MAX_MULT):
        self.perp_t = perp_t
        self.signal_arr = signal_arr
        self.alpha = alpha
        self.max_mult = max_mult

    def _signal_at(self, ts):
        if len(self.perp_t) == 0 or self.alpha == 0.0:
            return 0.0
        idx = np.searchsorted(self.perp_t, ts, side="right") - 1
        return float(self.signal_arr[idx]) if idx >= 0 else 0.0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        mult = min(1.0 + self.alpha * self._signal_at(ts), self.max_mult)
        half *= mult
        bid = np.round((mid - half) / TICK) * TICK
        ask = np.round((mid + half) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid,
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


def load_perp_signals(date):
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

    return t, {"obi": np.abs(obi), "ret": np.clip(ret_z, 0, None), "vol": np.clip(vol_z, 0, None)}


def run_variant(tr, qt, params, perp_t, perp_signals):
    om = OrderManager(maker_fee=0.0, latency=LATENCY, queue_model="none")
    ms = MarketState(120, 60, 0.9)
    strat = PerpWidenMM(perp_t, perp_signals[params["signal"]], alpha=params["alpha"])
    res = Backtest(strat, market_state=ms, order_manager=om, requote_on_fill=True,
                    requote_interval=REQUOTE_INTERVAL, tolerance_ticks=0.5,
                    tick_size=TICK, verbose=False).run(tr, qt)
    return float(res.metrics.get("total_pnl", 0.0)), len(om.fills)


def main():
    days = dates()
    print(f"LINK Apr-2026 perp-toxicity spread-widening test (queue_model=none, "
          f"latency={LATENCY*1000:.0f}ms), {len(days)} days, {len(VARIANTS)} variants\n")

    results = {v: [] for v in VARIANTS}
    fills = {v: [] for v in VARIANTS}
    ld = DataLoader()
    for i, d in enumerate(days):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        perp_t, perp_signals = load_perp_signals(d)

        row = {}
        for name, params in VARIANTS.items():
            pnl, n_fills = run_variant(tr, qt, params, perp_t, perp_signals)
            results[name].append(pnl)
            fills[name].append(n_fills)
            row[name] = pnl
        print(f"  [{i + 1}/{len(days)}] {d}  " +
              "  ".join(f"{k}={row[k]:+.2f}" for k in VARIANTS))

    print(f"\n{'variant':>10} {'mean_pnl':>10} {'std_pnl':>10} {'days_pos':>10} {'mean_fills':>11}")
    summary = {}
    for name in VARIANTS:
        arr = np.array(results[name])
        f_arr = np.array(fills[name])
        print(f"{name:>10} {arr.mean():10.4f} {arr.std():10.4f} {100 * (arr > 0).mean():9.1f}% "
              f"{f_arr.mean():11.1f}")
        summary[name] = {
            "mean_pnl": float(arr.mean()), "std_pnl": float(arr.std()),
            "days_pos_pct": float((arr > 0).mean()), "mean_fills": float(f_arr.mean()),
            "per_day_pnl": results[name],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "perp_toxicity_filter_mm.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "variants": VARIANTS, "results": summary}, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
