"""
link_perp_baseline.py
======================
Exp 80 -- LINK PERP baseline market making at L2-honest settings.

Context: C43 showed BTC-PERP is deeply negative (-$182/day, 0/5 days) with
spot_obi skew making it WORSE (not better). BTC-PERP has a 1-tick relative
spread (~0.15 bps), the smallest in the dataset, so the spread axis is fully
arbitraged and no inside-spread room exists.

LINK PERP has:
  - 1-tick spread (~1.11 bps at $9 price) -- tight like BTC-PERP
  - 4.6x more trades than LINK spot (343k vs 74k/day)
  - Trade sizes ~4.6 LINK median (vs 2.0 LINK spot)
  - NO 10-tick natural spread => NO inside-spread placement room

NOTE ON DATA: The orderbooks_LINK_PERP files appear to contain the same
data as orderbooks_LINK (spot) -- likely a CoinAPI mislabeling (same as the
BTC PERP mislabeling in exp 62). We therefore use the QUOTE-BASED proxy
L2 tracker (as in C45), using the PERP's own best_bid_size from quotes_LINK_PERP
as the L1 queue depth.

Hypothesis: LINK PERP behaves like BTC-PERP (deeply negative) because:
  1. 1-tick spread = no inside-spread mechanism
  2. High volume = more adverse selection per unit time
  3. OBI skew on a tight-spread instrument = same negative result as C43

Tests:
  - baseline: at-touch on LINK PERP (no skew)
  - perp_obi: use PERP's own OBI (from perp quotes: bid_size vs ask_size)
    as the skew signal (perp_alpha=1, perp_alpha=4)
  - spot_obi_skew: use LINK SPOT OBI to skew PERP quotes (as in C42 on spot)
    -- tests whether the cross-venue signal (C39) helps here

L2 model: quote-proxy (best_bid_size/best_ask_size from quotes_LINK_PERP),
queue_fraction=0.5. Latency=10ms, requote=50ms. 30 days Apr-2026.

Run from master2/:
    python experiments/80_link_perp_baseline/link_perp_baseline.py
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
OUT = Path(__file__).resolve().parent / "results"

TICK = 0.001          # LINK PERP tick = $0.001 (same as LINK spot)
ORDER_SIZE = 5.0      # 5 LINK
MAX_INV = 38.0
LATENCY = 0.01        # 10ms
REQUOTE_INTERVAL = 0.05  # 50ms
TAKER_FEE = 0.00045  # 4.5bps Binance VIP0
QUEUE_FRACTION = 0.5

PERP_ALPHAS = [1.0, 4.0]
SPOT_OBI_ALPHA = 1.0  # alpha for cross-venue spot_obi -> perp quotes


def load_quote_proxy_l2(perp_quotes_path: str, queue_fraction: float = 0.5):
    """
    Build L2 snapshots from PERP quote file using bid_size/ask_size as L1 depth.
    Since the real PERP orderbook parquets are mislabeled, this is the best
    available proxy for the PERP L1 queue depth.
    """
    df = pd.read_parquet(perp_quotes_path)
    ts_arr = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bid_arr = df["bid_price"].values.astype(float)
    ask_arr = df["ask_price"].values.astype(float)
    bsz_arr = df["bid_size"].values.astype(float)
    asz_arr = df["ask_size"].values.astype(float)
    denom = bsz_arr + asz_arr
    obi_arr = np.where(denom > 0, (bsz_arr - asz_arr) / denom, 0.0)
    snaps = [
        BookSnapshot(
            timestamp=float(ts_arr[i]),
            best_bid_price=bid_arr[i],
            best_ask_price=ask_arr[i],
            best_bid_depth=bsz_arr[i],
            best_ask_depth=asz_arr[i],
            obi_l1=obi_arr[i],
            obi_l3=0.0, obi_l5=0.0, obi_l10=0.0,
            total_bid_depth=bsz_arr[i], total_ask_depth=asz_arr[i],
            bid_levels=((bid_arr[i], bsz_arr[i]),),
            ask_levels=((ask_arr[i], asz_arr[i]),),
        )
        for i in range(len(ts_arr))
    ]
    return snaps


def load_spot_obi(spot_quotes_path: str):
    """Load spot quotes to get a time-indexed OBI series for cross-venue skew."""
    df = pd.read_parquet(spot_quotes_path)
    ts_arr = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bsz = df["bid_size"].values.astype(float)
    asz = df["ask_size"].values.astype(float)
    denom = bsz + asz
    obi_arr = np.where(denom > 0, (bsz - asz) / denom, 0.0)
    return ts_arr, obi_arr


class PerpTouchMM:
    """Symmetric at-touch MM on LINK PERP (no skew)."""

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = max(stats.spread / 2.0, TICK)
        bid = np.round((mid - half) / TICK) * TICK
        ask = np.round((mid + half) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid,
                             optimal_spread=ask - bid, bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


class PerpOBISkewMM:
    """
    OBI skew on LINK PERP using PERP's own OBI signal (from quote bid_size/ask_size).
    Stats.obi is set from the L2 tracker's best_bid/ask depth.
    """

    def __init__(self, perp_alpha: float):
        self.perp_alpha = perp_alpha

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = max(stats.spread / 2.0, TICK)
        obi = stats.obi
        shift = self.perp_alpha * obi * TICK
        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid + shift,
                             optimal_spread=ask - bid, bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


class SpotOBIOnPerpMM:
    """
    OBI skew on LINK PERP using SPOT's OBI as the signal (cross-venue, as in C42/C44
    applied to spot). Tests whether C39's incremental perp_obi info or the proven
    spot_obi signal can rescue PERP market making.
    """

    def __init__(self, spot_alpha: float, spot_ts: np.ndarray, spot_obi: np.ndarray):
        self.spot_alpha = spot_alpha
        self._ts = spot_ts
        self._obi = spot_obi
        self._idx = 0

    def _get_spot_obi(self, ts: float) -> float:
        idx = np.searchsorted(self._ts, ts, side="right") - 1
        if idx < 0:
            return 0.0
        return float(self._obi[idx])

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = max(stats.spread / 2.0, TICK)
        spot_obi = self._get_spot_obi(ts)
        shift = self.spot_alpha * spot_obi * TICK
        bid = np.round((mid - half + shift) / TICK) * TICK
        ask = np.round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid + shift,
                             optimal_spread=ask - bid, bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def dates():
    perp_t = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
              for f in glob.glob(str(DATA / "trades_LINK_PERP_2026-04-*.parquet"))}
    perp_q = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
              for f in glob.glob(str(DATA / "quotes_LINK_PERP_2026-04-*.parquet"))}
    spot_q = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
              for f in glob.glob(str(DATA / "quotes_LINK_2026-04-*.parquet"))}
    return sorted(perp_t & perp_q & spot_q)


def run_cell(tr, qt, strat, l2_snaps):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY, queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms = MarketState(120, 60, 0.9)
    l2 = L2BookTracker(l2_snaps)
    res = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=REQUOTE_INTERVAL,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    ).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics["total_pnl"])
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl_fee = pnl0 - TAKER_FEE * sum(f.quantity * f.price for f in takers)
    return pnl0, pnl_fee, len(om.fills), len(takers)


def main():
    days = dates()
    print(f"LINK PERP market making: {len(days)} days Apr-2026\n"
          f"TICK={TICK}, ORDER_SIZE={ORDER_SIZE}, LATENCY={LATENCY*1000:.0f}ms, "
          f"REQUOTE={REQUOTE_INTERVAL*1000:.0f}ms, QF={QUEUE_FRACTION}\n"
          f"L2 model: quote-proxy (perp quote bid_size/ask_size)\n"
          f"NOTE: PERP OB parquets appear mislabeled as SPOT -- using quote-proxy\n")

    ld = DataLoader()
    configs = [
        ("baseline", None),
        ("perp_obi_a1", ("perp", 1.0)),
        ("perp_obi_a4", ("perp", 4.0)),
        ("spot_obi_a1", ("spot", 1.0)),
    ]
    results = {}

    for label, signal_cfg in configs:
        r_pnl0, r_fee, r_fills, r_takers = [], [], [], []

        for i, d in enumerate(days):
            # Load PERP trades and quotes
            tr, qt = ld.load_coinapi(
                str(DATA / f"trades_LINK_PERP_{d}.parquet"),
                str(DATA / f"quotes_LINK_PERP_{d}.parquet"))
            l2_snaps = load_quote_proxy_l2(
                str(DATA / f"quotes_LINK_PERP_{d}.parquet"), QUEUE_FRACTION)

            if signal_cfg is None:
                strat = PerpTouchMM()
            elif signal_cfg[0] == "perp":
                strat = PerpOBISkewMM(perp_alpha=signal_cfg[1])
            else:  # spot
                spot_ts, spot_obi = load_spot_obi(str(DATA / f"quotes_LINK_{d}.parquet"))
                strat = SpotOBIOnPerpMM(spot_alpha=signal_cfg[1],
                                        spot_ts=spot_ts, spot_obi=spot_obi)

            p0, pf, nf, ntk = run_cell(tr, qt, strat, l2_snaps)
            r_pnl0.append(p0); r_fee.append(pf)
            r_fills.append(nf); r_takers.append(ntk)

        arr = np.array(r_fee)
        print(f"  {label:<20}  mean={arr.mean():+8.2f}  std={arr.std():7.2f}  "
              f"days+={100*(arr>0).mean():4.0f}%  fills={np.mean(r_fills):.0f}  "
              f"taker%={100*sum(r_takers)/max(sum(r_fills),1):.1f}%")
        results[label] = {
            "mean_pnl_fee0": float(np.mean(r_pnl0)),
            "mean_pnl_fee45bps": float(arr.mean()),
            "std_pnl": float(arr.std()),
            "days_pos_pct": float((arr > 0).mean()),
            "mean_fills": float(np.mean(r_fills)),
            "taker_pct": float(sum(r_takers) / max(sum(r_fills), 1) * 100),
            "per_day_pnl": [float(x) for x in arr],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "link_perp_baseline.json"
    with open(out_path, "w") as f:
        json.dump({"n_days": len(days), "tick": TICK, "order_size": ORDER_SIZE,
                   "latency": LATENCY, "requote_interval": REQUOTE_INTERVAL,
                   "queue_fraction": QUEUE_FRACTION, "taker_fee": TAKER_FEE,
                   "l2_model": "quote_proxy", "results": results}, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
