"""
spread_viability.py
====================
Exp 83 — Spread width as a profitability gate: LINK vs BTC comparison.

Hypothesis: Inside-spread queue placement (the mechanism behind C44/C45/exp81/82
profitability on LINK) requires a wide enough bid-ask spread to place a hidden level
between best_bid and best_ask. Narrow-spread assets provide no such room and the
strategy degrades to zero-profit.

Same GatedSpotSkewMM strategy (alpha=4 gate=1.5) applied to both assets on the
SAME 30-day window (Jun 11 – Jul 10 2025) with notional-normalized order sizes:

  LINK: ORDER_SIZE=5 units  @ ~$9   → ~$45 notional/order
  BTC:  ORDER_SIZE=0.0004 BTC @ ~$110K → ~$44 notional/order

Key per-day diagnostics:
  - mean_spread_ticks: average spread in tick units (10 for LINK, ~1.2 for BTC)
  - pnl: daily PnL after taker fees
  - cancel_rate: fraction of recomputes that trigger a cancel (gate fires)
  - fills: total fills
  - pnl_per_fill: PnL per trade in dollars (normalized earning power)
  - spread_captured_pct: % of half-spread earned per round-trip (efficiency)

The scatter of pnl vs mean_spread_ticks is the central result: one regression
across both assets validates the "spread = profitability gateway" mechanism.

Also runs alpha=1 gate=0.5 as the conservative reference config.

Run from master2/:
    python experiments/83_spread_viability/spread_viability.py
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

LATENCY          = 0.01
REQUOTE_INTERVAL = 0.01
TAKER_FEE        = 0.00045
QUEUE_FRACTION   = 0.5
MID_DRIFT_TICKS  = 5

# Asset-specific params — normalised to ~$44-45 notional per order
ASSETS = {
    "LINK": {
        "tick":       0.001,
        "order_size": 5.0,
        "max_inv":    38.0,          # 7.6× order size
        "prefix":     "LINK",
    },
    "BTC": {
        "tick":       0.01,
        "order_size": 0.0004,        # ~$44 at $110K
        "max_inv":    0.003,         # 7.5× order size → ~$330 max notional
        "prefix":     "BTC",
    },
}

CONFIGS = [
    (4.0, 1.5),   # best config from exp81
    (1.0, 0.5),   # C45 reference
]

# Shared OOS window: dates present in BOTH assets
OOS_MONTHS_PATTERN = r"2025-0[67]-\d{2}"
OOS_CLIP = ("2025-06-11", "2025-07-10")


class GatedSpotSkewMM:
    def __init__(self, spot_alpha: float, gate_ticks: float, tick: float,
                 max_inv: float, order_size: float,
                 mid_drift_ticks: float = MID_DRIFT_TICKS):
        self.spot_alpha      = spot_alpha
        self.gate_ticks      = gate_ticks
        self.tick            = tick
        self.max_inv         = max_inv
        self.order_size      = order_size
        self.mid_drift_ticks = mid_drift_ticks
        self._last_bid: float | None = None
        self._last_ask: float | None = None
        self._last_mid: float | None = None
        self.n_recomputes    = 0
        self.n_cancels       = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_recomputes += 1
        mid   = stats.mid_price
        half  = stats.spread / 2.0 if stats.spread > 0 else 5 * self.tick
        shift = self.spot_alpha * stats.obi * self.tick
        ideal_bid = np.round((mid - half + shift) / self.tick) * self.tick
        ideal_ask = np.round((mid + half + shift) / self.tick) * self.tick
        if ideal_ask <= ideal_bid:
            ideal_ask = ideal_bid + self.tick

        if self._last_bid is None:
            should_cancel = True
        else:
            should_cancel = (
                abs(ideal_bid - self._last_bid) > self.gate_ticks * self.tick or
                abs(ideal_ask - self._last_ask) > self.gate_ticks * self.tick or
                abs(mid - self._last_mid) > self.mid_drift_ticks * self.tick
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
            bid_size=self.order_size, ask_size=self.order_size,
        )

    def should_quote(self, inv):
        return (inv < self.max_inv, inv > -self.max_inv)


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


def mean_spread_ticks(quotes_path: str, tick: float) -> float:
    df = pd.read_parquet(quotes_path, columns=["bid_price", "ask_price"])
    return float(((df["ask_price"] - df["bid_price"]) / tick).mean())


def run_cell(tr, qt, quotes_path: str, asset_cfg: dict, alpha: float, gate: float):
    tick       = asset_cfg["tick"]
    order_size = asset_cfg["order_size"]
    max_inv    = asset_cfg["max_inv"]

    strat = GatedSpotSkewMM(spot_alpha=alpha, gate_ticks=gate,
                             tick=tick, max_inv=max_inv, order_size=order_size)
    om    = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                         queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms    = MarketState(120, 60, 0.9)
    l2    = quote_based_l2_tracker(quotes_path)
    res   = Backtest(strat, market_state=ms, order_manager=om,
                     requote_on_fill=True,
                     requote_interval=REQUOTE_INTERVAL,
                     tolerance_ticks=0,
                     tick_size=tick,
                     verbose=False).run(tr, qt, l2_tracker=l2)

    pnl0    = float(res.metrics.get("total_pnl", 0.0))
    takers  = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    cancel_rate = strat.n_cancels / max(strat.n_recomputes, 1)
    n_fills = len(om.fills)
    pnl_per_fill = pnl_fee / n_fills if n_fills > 0 else 0.0
    return pnl_fee, n_fills, cancel_rate, pnl_per_fill


def get_dates(prefix: str) -> list[str]:
    qt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / f"quotes_{prefix}_*.parquet"))
          if "PERP" not in f}
    tr = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / f"trades_{prefix}_*.parquet"))
          if "PERP" not in f}
    return sorted(d for d in qt & tr
                  if re.match(OOS_MONTHS_PATTERN, d)
                  and OOS_CLIP[0] <= d <= OOS_CLIP[1])


def run_asset(asset: str, cfg: dict, dates: list[str], ld: DataLoader) -> dict:
    tick   = cfg["tick"]
    prefix = cfg["prefix"]
    result = {c: {"pnl": [], "fills": [], "cancel_rate": [],
                  "pnl_per_fill": [], "spread_ticks": [], "dates": []}
              for c in CONFIGS}

    print(f"\n=== {asset} ({len(dates)} days) ===")
    for i, d in enumerate(dates):
        tr, qt = ld.load_coinapi(str(DATA / f"trades_{prefix}_{d}.parquet"),
                                  str(DATA / f"quotes_{prefix}_{d}.parquet"))
        qp  = str(DATA / f"quotes_{prefix}_{d}.parquet")
        sp  = mean_spread_ticks(qp, tick)
        row = {}
        for (a, g) in CONFIGS:
            pf, n, cr, ppf = run_cell(tr, qt, qp, cfg, a, g)
            result[(a, g)]["pnl"].append(pf)
            result[(a, g)]["fills"].append(n)
            result[(a, g)]["cancel_rate"].append(cr)
            result[(a, g)]["pnl_per_fill"].append(ppf)
            result[(a, g)]["spread_ticks"].append(sp)
            result[(a, g)]["dates"].append(d)
            row[(a, g)] = pf
        print(f"  [{i+1:2}/{len(dates)}] {d}  sp={sp:.1f}tk  " +
              "  ".join(f"a{a}g{g}:{row[(a,g)]:+.4f}" for a, g in CONFIGS))

    print(f"\n  {'config':<12} {'mean/day':>10} {'std':>8} {'days+':>7} "
          f"{'fills':>7} {'cancel%':>8} {'$/fill':>8}")
    print("  " + "-" * 62)
    summary = {}
    for (a, g) in CONFIGS:
        r   = result[(a, g)]
        arr = np.array(r["pnl"])
        fls = np.array(r["fills"])
        cr  = np.array(r["cancel_rate"])
        ppf = np.array(r["pnl_per_fill"])
        sp  = np.array(r["spread_ticks"])
        lbl = f"a{a}_g{g}"
        print(f"  {lbl:<12} {arr.mean():>+9.4f}  {arr.std():>7.4f}  "
              f"{100*(arr>0).mean():>6.1f}%  {fls.mean():>6.1f}  "
              f"{100*cr.mean():>7.2f}%  {ppf.mean():>7.5f}")
        summary[lbl] = {
            "alpha": a, "gate_ticks": g,
            "mean_pnl_per_day": float(arr.mean()),
            "std_pnl_per_day":  float(arr.std()),
            "days_positive_pct": float(100 * (arr > 0).mean()),
            "mean_fills_per_day": float(fls.mean()),
            "mean_cancel_pct": float(100 * cr.mean()),
            "mean_pnl_per_fill": float(ppf.mean()),
            "mean_spread_ticks": float(sp.mean()),
            "n_days": len(arr),
            "per_day": [
                {"date": d, "pnl": float(p), "spread_ticks": float(s),
                 "fills": int(f), "cancel_rate": float(c)}
                for d, p, s, f, c in zip(r["dates"], arr, sp, fls, cr)
            ],
        }
    return summary


def main():
    print("Exp 83 — Spread width as profitability gate: LINK vs BTC\n"
          f"Window: {OOS_CLIP[0]} to {OOS_CLIP[1]} (same dates both assets)\n"
          f"Order sizes: LINK=5 units (~$45), BTC=0.0004 (~$44 at $110K)\n"
          f"Strategy: GatedSpotSkewMM, 10ms recompute, strategy-level gate\n"
          f"Configs: {CONFIGS}\n")

    ld = DataLoader()
    all_dates = {}
    for asset, cfg in ASSETS.items():
        all_dates[asset] = get_dates(cfg["prefix"])
        print(f"  {asset}: {len(all_dates[asset])} days")

    # Use the intersection of dates present in both assets
    common = sorted(set(all_dates["LINK"]) & set(all_dates["BTC"]))
    print(f"\n  Common dates: {len(common)} days ({common[0]} to {common[-1]})\n")

    results = {}
    for asset, cfg in ASSETS.items():
        # Each asset runs on common dates only for clean comparison
        asset_dates = [d for d in all_dates[asset] if d in common]
        results[asset] = run_asset(asset, cfg, asset_dates, ld)

    # Cross-asset summary
    print("\n" + "=" * 70)
    print("CROSS-ASSET COMPARISON (alpha=4 gate=1.5, notional-normalised)")
    print("=" * 70)
    for asset in ASSETS:
        r = results[asset].get("a4.0_g1.5", {})
        print(f"  {asset:<6}  spread={r.get('mean_spread_ticks', 0):.1f} ticks  "
              f"pnl/day={r.get('mean_pnl_per_day', 0):+.4f}  "
              f"days+={r.get('days_positive_pct', 0):.0f}%  "
              f"cancel={r.get('mean_cancel_pct', 0):.1f}%  "
              f"$/fill={r.get('mean_pnl_per_fill', 0):+.6f}")

    out = {
        "window": f"{OOS_CLIP[0]}_to_{OOS_CLIP[1]}",
        "n_common_days": len(common),
        "order_sizes": {a: ASSETS[a]["order_size"] for a in ASSETS},
        "ticks": {a: ASSETS[a]["tick"] for a in ASSETS},
        "requote_interval_s": REQUOTE_INTERVAL,
        "mid_drift_ticks": MID_DRIFT_TICKS,
        "results": results,
    }
    with open(OUT / "spread_viability.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT / 'spread_viability.json'}")


if __name__ == "__main__":
    main()
