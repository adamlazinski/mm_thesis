"""
smart_requote.py
=================
Exp 81 — Smart-gated requoting on LINK spot OBI skew.

Baseline (C45 / exp 76): 50ms recompute, 0.5-tick tolerance, alpha=1 → +$27.04/day OOS.

Hypothesis: queue priority is valuable. Every cancel loses it. The current 50ms cycle
already uses hysteresis (0.5 tick) but still triggers too many cancels on OBI noise.

Design: recompute every 10ms (fast reaction), but the STRATEGY itself gates the cancel.
The gate returns last-posted prices when the change isn't large enough, causing the
backtest hysteresis to see zero movement and skip. Actual cancel only fires when:
  1. Ideal bid has moved by > gate_ticks from last-posted bid (genuine OBI shift), OR
  2. Mid has drifted by > mid_drift_ticks from the mid at last post (quote stale).

Gate condition 1 catches OBI sign flips and sustained OBI moves.
Gate condition 2 catches mid drift that makes the current quote irrelevant.

Parameters:
  requote_interval = 0.01   (10ms recompute — fast poll)
  tolerance_ticks  = 0      (strategy handles all gating; backtest is just the engine)
  alpha            ∈ {1, 4} (proven OBI configs)
  gate_ticks       ∈ {0.5, 1.5, 3.0}  (0.5 = old baseline; sweep for optimal)
  mid_drift_ticks  = 5      (cancel if mid moves > 5 ticks from last post)

Runs on both windows (direct C44/C45 comparison):
  In-sample:  Apr 2026 (30 days)
  OOS:        Jun–Jul 2025 (30 days)

Run from master2/:
    python experiments/81_smart_requote/smart_requote.py
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
REQUOTE_INTERVAL = 0.01      # 10ms recompute — fast poll
TAKER_FEE        = 0.00045
QUEUE_FRACTION   = 0.5
MID_DRIFT_TICKS  = 5         # cancel if mid moves > 5 ticks from last post

ALPHAS      = [1.0, 4.0]
GATE_TICKS  = [0.5, 1.5, 3.0]


class GatedSpotSkewMM:
    """
    OBI skew with strategy-level cancel gate.

    compute_quotes is called every 10ms. It returns last-posted prices unless
    a cancel trigger fires, in which case it returns the new ideal prices.
    The backtest hysteresis (tolerance_ticks=0) then sees exactly what the
    strategy decided: 0 movement (skip) or the new prices (cancel+resubmit).
    """

    def __init__(self, spot_alpha: float, gate_ticks: float,
                 mid_drift_ticks: float = MID_DRIFT_TICKS):
        self.spot_alpha     = spot_alpha
        self.gate_ticks     = gate_ticks
        self.mid_drift_ticks = mid_drift_ticks
        # State from last actual cancel+resubmit
        self._last_bid: float | None = None
        self._last_ask: float | None = None
        self._last_mid: float | None = None
        # Diagnostics
        self.n_recomputes = 0
        self.n_cancels    = 0

    def _ideal(self, stats):
        mid  = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.spot_alpha * stats.obi * TICK
        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return bid, ask, mid

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_recomputes += 1
        ideal_bid, ideal_ask, mid = self._ideal(stats)

        should_cancel = False

        if self._last_bid is None:
            # First ever quote — must post
            should_cancel = True
        else:
            # Trigger 1: OBI shift moved ideal bid by > gate_ticks
            if (abs(ideal_bid - self._last_bid) > self.gate_ticks * TICK or
                    abs(ideal_ask - self._last_ask) > self.gate_ticks * TICK):
                should_cancel = True
            # Trigger 2: mid has drifted — current quote is stale
            elif abs(mid - self._last_mid) > self.mid_drift_ticks * TICK:
                should_cancel = True

        if should_cancel:
            self.n_cancels += 1
            self._last_bid = ideal_bid
            self._last_ask = ideal_ask
            self._last_mid = mid
            bid, ask = ideal_bid, ideal_ask
        else:
            bid, ask = self._last_bid, self._last_ask

        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + self.spot_alpha * stats.obi * TICK,
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


def run_cell(tr, qt, quotes_path: str, spot_alpha: float, gate_ticks: float):
    strat = GatedSpotSkewMM(spot_alpha=spot_alpha, gate_ticks=gate_ticks)
    om    = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                         queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms    = MarketState(120, 60, 0.9)
    l2    = quote_based_l2_tracker(quotes_path)
    res   = Backtest(strat, market_state=ms, order_manager=om,
                     requote_on_fill=True,
                     requote_interval=REQUOTE_INTERVAL,
                     tolerance_ticks=0,        # strategy gates; backtest is neutral
                     tick_size=TICK,
                     verbose=False).run(tr, qt, l2_tracker=l2)

    pnl0   = float(res.metrics.get("total_pnl", 0.0))
    fills  = om.fills
    takers = [f for f in fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    cancel_rate = strat.n_cancels / max(strat.n_recomputes, 1)
    return pnl0, pnl_fee, len(fills), cancel_rate


def get_dates(pattern: str) -> list[str]:
    qt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_*.parquet"))
          if "PERP" not in f}
    tr = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_*.parquet"))
          if "PERP" not in f}
    return sorted(d for d in qt & tr if re.match(pattern, d))


def run_window(label: str, dates: list[str], ld: DataLoader) -> dict:
    configs = [(a, g) for a in ALPHAS for g in GATE_TICKS]
    data    = {k: {"pnl": [], "fills": [], "cancel_rate": []}
               for k in configs}

    print(f"\n=== {label} ({len(dates)} days) ===")
    for i, d in enumerate(dates):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                  str(DATA / f"quotes_LINK_{d}.parquet"))
        qp = str(DATA / f"quotes_LINK_{d}.parquet")
        row = {}
        for a, g in configs:
            _, pf, n, cr = run_cell(tr, qt, qp, a, g)
            data[(a, g)]["pnl"].append(pf)
            data[(a, g)]["fills"].append(n)
            data[(a, g)]["cancel_rate"].append(cr)
            row[(a, g)] = pf
        print(f"  [{i+1:2}/{len(dates)}] {d}  " +
              "  ".join(f"a{a}g{g}:{row[(a,g)]:+.2f}" for a, g in configs))

    print(f"\n  {'alpha':>5} {'gate':>5} {'mean/day':>10} {'std':>8} "
          f"{'days+':>7} {'fills':>8} {'cancel%':>8}")
    print("  " + "-" * 60)
    summary = {}
    for a, g in configs:
        r   = data[(a, g)]
        arr = np.array(r["pnl"])
        fls = np.array(r["fills"])
        cr  = np.array(r["cancel_rate"])
        print(f"  {a:>4.1f}  {g:>4.1f}  {arr.mean():>+9.2f}  {arr.std():>7.2f}  "
              f"{100*(arr>0).mean():>6.1f}%  {fls.mean():>7.1f}  "
              f"{100*cr.mean():>7.2f}%")
        summary[f"a{a}_g{g}"] = {
            "alpha": a, "gate_ticks": g,
            "mean_pnl_per_day": float(arr.mean()),
            "std_pnl_per_day":  float(arr.std()),
            "days_positive_pct": float(100 * (arr > 0).mean()),
            "mean_fills_per_day": float(fls.mean()),
            "mean_cancel_pct": float(100 * cr.mean()),
            "n_days": len(arr),
            "per_day": [float(p) for p in arr],
        }
    return summary


def main():
    print(
        f"Exp 81 — Smart-gated requote, LINK spot OBI skew\n"
        f"requote_interval={REQUOTE_INTERVAL*1000:.0f}ms (10ms recompute, strategy gates cancel)\n"
        f"mid_drift_ticks={MID_DRIFT_TICKS}, alphas={ALPHAS}, gate_ticks={GATE_TICKS}\n"
        f"Baseline comparison: C45 alpha=1 gate=0.5(equiv) → +$27.04/day OOS"
    )
    is_dates  = get_dates(r"2026-04-\d{2}")
    oos_dates = [d for d in get_dates(r"2025-0[67]-\d{2}")
                 if "2025-06-11" <= d <= "2025-07-10"]

    ld = DataLoader()
    is_sum  = run_window("IN-SAMPLE  Apr 2026",     is_dates,  ld)
    oos_sum = run_window("OOS        Jun-Jul 2025", oos_dates, ld)

    out = {
        "requote_interval_s": REQUOTE_INTERVAL,
        "latency_s": LATENCY,
        "mid_drift_ticks": MID_DRIFT_TICKS,
        "queue_fraction": QUEUE_FRACTION,
        "taker_fee_bps": TAKER_FEE * 1e4,
        "in_sample":  {"window": "2026-04",                    "summary": is_sum},
        "oos":        {"window": "2025-06-11_to_2025-07-10",   "summary": oos_sum},
    }
    with open(OUT / "smart_requote.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT / 'smart_requote.json'}")


if __name__ == "__main__":
    main()
