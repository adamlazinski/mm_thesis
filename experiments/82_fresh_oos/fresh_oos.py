"""
fresh_oos.py
=============
Exp 82 — Fresh OOS validation of best config from exp 81.

Exp 81 found alpha=4 gate=1.5 gives:
  IS  Apr 2026:       +$54.75/day (100% days+, 1.89% cancel rate)
  OOS Jun-Jul 2025:   +$98.97/day (100% days+, 4.79% cancel rate)

This experiment tests on 6 completely untouched months (Oct 2025 – Mar 2026,
182 days) to get an unbiased estimate free of any IS/OOS window overlap.

Also tests alpha=1 gate=0.5 as a reference point (proven OOS config from C45).

Same engine: GatedSpotSkewMM, 10ms recompute, strategy-level gate, tolerance=0.

Run from master2/:
    python experiments/82_fresh_oos/fresh_oos.py
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
OUT  = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

TICK             = 0.001
ORDER_SIZE       = 5.0
MAX_INV          = 38.0
LATENCY          = 0.01
REQUOTE_INTERVAL = 0.01
TAKER_FEE        = 0.00045
QUEUE_FRACTION   = 0.5
MID_DRIFT_TICKS  = 5

# Best config from exp 81 + reference
CONFIGS = [
    (4.0, 1.5),   # best IS+OOS from exp 81
    (1.0, 0.5),   # C45 reference (proven OOS alpha=1)
]


class GatedSpotSkewMM:
    def __init__(self, spot_alpha: float, gate_ticks: float,
                 mid_drift_ticks: float = MID_DRIFT_TICKS):
        self.spot_alpha      = spot_alpha
        self.gate_ticks      = gate_ticks
        self.mid_drift_ticks = mid_drift_ticks
        self._last_bid: float | None = None
        self._last_ask: float | None = None
        self._last_mid: float | None = None
        self.n_recomputes    = 0
        self.n_cancels       = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_recomputes += 1
        mid   = stats.mid_price
        half  = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.spot_alpha * stats.obi * TICK
        ideal_bid = np.round((mid - half + shift) / TICK) * TICK
        ideal_ask = np.round((mid + half + shift) / TICK) * TICK
        if ideal_ask <= ideal_bid:
            ideal_ask = ideal_bid + TICK

        if self._last_bid is None:
            should_cancel = True
        else:
            should_cancel = (
                abs(ideal_bid - self._last_bid) > self.gate_ticks * TICK or
                abs(ideal_ask - self._last_ask) > self.gate_ticks * TICK or
                abs(mid - self._last_mid) > self.mid_drift_ticks * TICK
            )

        if should_cancel:
            self.n_cancels += 1
            self._last_bid, self._last_ask, self._last_mid = ideal_bid, ideal_ask, mid
            bid, ask = ideal_bid, ideal_ask
        else:
            bid, ask = self._last_bid, self._last_ask

        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + shift,
            optimal_spread=ask - bid,
            bid_size=ORDER_SIZE, ask_size=ORDER_SIZE,
        )

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def quote_based_l2_tracker(quotes_path: str) -> L2BookTracker:
    df  = pd.read_parquet(quotes_path,
                          columns=["time_exchange", "bid_price", "ask_price",
                                   "bid_size", "ask_size"])
    ts  = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bp  = df["bid_price"].values.astype(float)
    ap  = df["ask_price"].values.astype(float)
    bsz = df["bid_size"].values.astype(float)
    asz = df["ask_size"].values.astype(float)
    d   = bsz + asz
    obi = np.where(d > 0, (bsz - asz) / d, 0.0)
    return L2BookTracker([
        BookSnapshot(
            timestamp=float(ts[i]),
            best_bid_price=bp[i], best_ask_price=ap[i],
            best_bid_depth=bsz[i], best_ask_depth=asz[i],
            obi_l1=obi[i], obi_l3=obi[i], obi_l5=obi[i], obi_l10=obi[i],
            total_bid_depth=bsz[i], total_ask_depth=asz[i],
            bid_levels=((bp[i], bsz[i]),), ask_levels=((ap[i], asz[i]),),
        )
        for i in range(len(ts))
    ])


def run_cell(tr, qt, quotes_path: str, alpha: float, gate: float):
    strat = GatedSpotSkewMM(spot_alpha=alpha, gate_ticks=gate)
    om    = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                         queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms    = MarketState(120, 60, 0.9)
    l2    = quote_based_l2_tracker(quotes_path)
    res   = Backtest(strat, market_state=ms, order_manager=om,
                     requote_on_fill=True,
                     requote_interval=REQUOTE_INTERVAL,
                     tolerance_ticks=0,
                     tick_size=TICK,
                     verbose=False).run(tr, qt, l2_tracker=l2)
    pnl0    = float(res.metrics.get("total_pnl", 0.0))
    takers  = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    cancel_rate = strat.n_cancels / max(strat.n_recomputes, 1)
    return pnl_fee, len(om.fills), cancel_rate


def get_dates(months: list[str]) -> list[str]:
    qt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_*.parquet"))
          if "PERP" not in f}
    tr = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_*.parquet"))
          if "PERP" not in f}
    return sorted(d for d in qt & tr
                  if any(d.startswith(m) for m in months))


def main():
    months = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]
    dates  = get_dates(months)
    print(f"Exp 82 — Fresh OOS validation (Oct 2025 – Mar 2026, {len(dates)} days)\n"
          f"Configs: alpha=4 gate=1.5 (best exp81), alpha=1 gate=0.5 (C45 reference)\n"
          f"10ms recompute, strategy-level gate, mid_drift={MID_DRIFT_TICKS} ticks\n")

    data = {cfg: {"pnl": [], "fills": [], "cancel_rate": [], "dates": []}
            for cfg in CONFIGS}

    ld = DataLoader()
    for i, d in enumerate(dates):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        qp = str(DATA / f"quotes_LINK_{d}.parquet")
        row = {}
        for cfg in CONFIGS:
            pf, n, cr = run_cell(tr, qt, qp, *cfg)
            data[cfg]["pnl"].append(pf)
            data[cfg]["fills"].append(n)
            data[cfg]["cancel_rate"].append(cr)
            data[cfg]["dates"].append(d)
            row[cfg] = pf
        print(f"  [{i+1:3}/{len(dates)}] {d}  " +
              "  ".join(f"a{a}g{g}:{row[(a,g)]:+.2f}" for a, g in CONFIGS))

    print(f"\n  {'config':<14} {'mean/day':>10} {'std':>8} {'days+':>7} "
          f"{'fills':>8} {'cancel%':>8}")
    print("  " + "-" * 58)
    summary = {}
    for a, g in CONFIGS:
        r   = data[(a, g)]
        arr = np.array(r["pnl"])
        fls = np.array(r["fills"])
        cr  = np.array(r["cancel_rate"])
        lbl = f"a{a}_g{g}"
        print(f"  {lbl:<14} {arr.mean():>+9.2f}  {arr.std():>7.2f}  "
              f"{100*(arr>0).mean():>6.1f}%  {fls.mean():>7.1f}  "
              f"{100*cr.mean():>7.2f}%")

        # Per-month breakdown
        month_pnl = {}
        for date, pnl in zip(r["dates"], r["pnl"]):
            m = date[:7]
            month_pnl.setdefault(m, []).append(pnl)
        print("    Monthly: " + "  ".join(
            f"{m}:{np.mean(v):+.0f}" for m, v in sorted(month_pnl.items())))

        summary[lbl] = {
            "alpha": a, "gate_ticks": g,
            "mean_pnl_per_day": float(arr.mean()),
            "std_pnl_per_day":  float(arr.std()),
            "days_positive_pct": float(100 * (arr > 0).mean()),
            "mean_fills_per_day": float(fls.mean()),
            "mean_cancel_pct": float(100 * cr.mean()),
            "n_days": len(arr),
            "per_day": [{"date": d, "pnl": float(p)} for d, p in zip(r["dates"], arr)],
        }

    out = {
        "window": "2025-10_to_2026-03",
        "n_days": len(dates),
        "months": months,
        "requote_interval_s": REQUOTE_INTERVAL,
        "mid_drift_ticks": MID_DRIFT_TICKS,
        "summary": summary,
    }
    with open(OUT / "fresh_oos.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT / 'fresh_oos.json'}")


if __name__ == "__main__":
    main()
