"""
proxy_vs_real.py
=================
Exp 87 — Same day, same strategy, real reconstructed L2 vs quote-proxy L2.

The C45/C50/C51 numbers used a single-level "quote-proxy" L2 tracker because no
real orderbook data existed for their windows. This experiment measures the
proxy's bias directly: identical strategy and engine on one captured day
(processed by scripts/process_binance_capture.py), run twice —

  REAL : full 20-level book reconstructed from depth diffs (every depth event)
  PROXY: single-level tracker built from the same day's top-of-book quotes
         (the exp 81–84 construction)

Assets: LINK spot (now genuinely tick=0.001, one-tick spread) and BTC spot
(tick=0.01). Configs: alpha ∈ {0, 4} symmetric OBI skew, engine settings as
C44 (qf=0.5, latency=10ms, requote=50ms, tolerance=0.5 ticks, post_only).

Run from master2/ (after process_binance_capture.py for the date):
    python experiments/87_proxy_vs_real/proxy_vs_real.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import json
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

PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

LATENCY = 0.01
REQUOTE = 0.05
TAKER_FEE = 0.00045
QF = 0.5

ASSETS = {
    "LINK": {"tick": 0.001, "order_size": 5.0, "max_inv": 38.0},
    "BTC":  {"tick": 0.01, "order_size": 0.0004, "max_inv": 0.003},
}
ALPHAS = [0.0, 4.0]


class SpotSkewMM:
    def __init__(self, alpha, tick, order_size, max_inv):
        self.alpha, self.tick = alpha, tick
        self.order_size, self.max_inv = order_size, max_inv

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * self.tick
        shift = self.alpha * stats.obi * self.tick
        bid = np.round((mid - half + shift) / self.tick) * self.tick
        ask = np.round((mid + half + shift) / self.tick) * self.tick
        if ask <= bid:
            ask = bid + self.tick
        return QuoteDecision(bid_price=bid, ask_price=ask,
                             reservation_price=mid + shift,
                             optimal_spread=ask - bid,
                             bid_size=self.order_size, ask_size=self.order_size)

    def should_quote(self, inv):
        return (inv < self.max_inv, inv > -self.max_inv)


def real_tracker(ob_path: str) -> L2BookTracker:
    """Fast BookSnapshot loader (vectorised; load_orderbook's iterrows is slow)."""
    df = pd.read_parquet(ob_path)
    ts = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    snaps = []
    for t, bids, asks in zip(ts, df["bids"].values, df["asks"].values):
        bl = tuple((float(l["price"]), float(l["size"])) for l in bids)
        al = tuple((float(l["price"]), float(l["size"])) for l in asks)
        if not bl or not al:
            continue
        b10 = sum(s for _, s in bl[:10]); a10 = sum(s for _, s in al[:10])

        def obi(n):
            b = sum(s for _, s in bl[:n]); a = sum(s for _, s in al[:n])
            return (b - a) / (b + a) if b + a > 0 else 0.0
        snaps.append(BookSnapshot(
            timestamp=float(t),
            best_bid_price=bl[0][0], best_ask_price=al[0][0],
            best_bid_depth=bl[0][1], best_ask_depth=al[0][1],
            obi_l1=obi(1), obi_l3=obi(3), obi_l5=obi(5), obi_l10=obi(10),
            total_bid_depth=b10, total_ask_depth=a10,
            bid_levels=bl, ask_levels=al))
    return L2BookTracker(snaps)


def proxy_tracker(quotes_path: str) -> L2BookTracker:
    df = pd.read_parquet(quotes_path,
                         columns=["time_exchange", "bid_price", "ask_price",
                                  "bid_size", "ask_size"])
    ts = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bp = df["bid_price"].values.astype(float)
    ap = df["ask_price"].values.astype(float)
    bs = df["bid_size"].values.astype(float)
    az = df["ask_size"].values.astype(float)
    d = bs + az
    obi = np.where(d > 0, (bs - az) / d, 0.0)
    return L2BookTracker([
        BookSnapshot(timestamp=float(ts[i]),
                     best_bid_price=bp[i], best_ask_price=ap[i],
                     best_bid_depth=bs[i], best_ask_depth=az[i],
                     obi_l1=obi[i], obi_l3=obi[i], obi_l5=obi[i], obi_l10=obi[i],
                     total_bid_depth=bs[i], total_ask_depth=az[i],
                     bid_levels=((bp[i], bs[i]),), ask_levels=((ap[i], az[i]),))
        for i in range(len(ts))])


def run(tr, qt, l2, cfg, alpha):
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                      queue_model="l2")
    om.queue_fraction = QF
    strat = SpotSkewMM(alpha, cfg["tick"], cfg["order_size"], cfg["max_inv"])
    res = Backtest(strat, market_state=MarketState(120, 60, 0.9),
                   order_manager=om, requote_on_fill=True,
                   requote_interval=REQUOTE, tolerance_ticks=0.5,
                   tick_size=cfg["tick"], verbose=False).run(tr, qt, l2_tracker=l2)
    pnl = float(res.metrics["total_pnl"])
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    pnl -= TAKER_FEE * sum(f.quantity * f.price for f in takers)
    return pnl, len(om.fills), len(takers)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    args = p.parse_args()

    ld = DataLoader()
    results = {}
    for asset, cfg in ASSETS.items():
        tr, qt = ld.load_coinapi(str(PROC / f"trades_{asset}_{args.date}.parquet"),
                                 str(PROC / f"quotes_{asset}_{args.date}.parquet"))
        trackers = {
            "real": real_tracker(str(PROC / f"orderbooks_{asset}_{args.date}.parquet")),
            "proxy": proxy_tracker(str(PROC / f"quotes_{asset}_{args.date}.parquet")),
        }
        for alpha in ALPHAS:
            for mode, l2 in trackers.items():
                pnl, nf, ntk = run(tr, qt, l2, cfg, alpha)
                key = f"{asset}_a{alpha:g}_{mode}"
                results[key] = {"pnl": pnl, "fills": nf, "takers": ntk}
                print(f"  {key:24s} pnl={pnl:+9.4f}  fills={nf:6d}  takers={ntk}")

    with open(OUT / f"proxy_vs_real_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "results": results}, fh, indent=2)
    print(f"Saved -> {OUT}/proxy_vs_real_{args.date}.json")


if __name__ == "__main__":
    main()
