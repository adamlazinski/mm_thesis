"""
book_geometry.py
=================
Exp 92 — Deep order-book geometry and liquidity dynamics from the live capture
(event-level, 20 levels, true price grids, all four books).

A. STATIC SHAPE (sampled every 100th depth event): spread; touch depth ($);
   cumulative depth within {1,2,5,10} ticks of mid ($); occupied levels within
   10 ticks. The honest, true-grid redo of the C21 "hollow touch" analysis.

B. TOUCH-FLOW DECOMPOSITION: every reduction of best-level depth is allocated
   to traded volume (trades at that price since the previous diff) vs
   cancellation (the remainder). Reported as cancel:trade volume ratio and the
   fraction of touch-level *disappearances* caused by cancels — the direct
   population quantity behind exp 86's queue_fraction bounds.

C. RESILIENCE: each time the spread widens beyond one tick, the time until it
   repairs back to one tick. The speed with which queue rents police the
   spread (Wyart-Bouchaud enforcement, observed).

D. KURTH TAXONOMY: volatility-normalised tick rho = tick / daily-sigma($),
   relative tick (bps), median touch depth ($) — the dense/sparse axis of
   Kurth et al. (2026) computed for all four books (feeds the C52 rebuild).

Run: python experiments/92_book_geometry/book_geometry.py --date 2026-07-11
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.data.binance_capture import (
    BookReplayer, capture_files, iter_records)

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

INSTRUMENTS = {
    "LINKUSDT":      ("spot", 0.001),
    "BTCUSDT":       ("spot", 0.01),
    "LINKUSDT_PERP": ("perp", 0.001),
    "BTCUSDT_PERP":  ("perp", 0.1),   # fapi BTC tick is 0.10
}
SAMPLE_EVERY = 100
BANDS_TICKS = [1, 2, 5, 10]


class GeometryStats:
    def __init__(self, tick: float):
        self.tick = tick
        # A: sampled shape
        self.spread = []
        self.touch_bid_usd = []
        self.band_bid_usd = {k: [] for k in BANDS_TICKS}
        self.occupied10 = []
        # B: touch flow
        self.traded_vol = 0.0
        self.cancel_vol = 0.0
        self.gone_by_trade = 0
        self.gone_by_cancel = 0
        # C: resilience
        self._wide_since = None
        self.repair_s = []
        self.n_widenings = 0
        # D: vol
        self.mid_1s = []            # (t, mid) sampled ~1s
        self._last_mid_t = 0.0
        # internals
        self._prev_bid_px = None
        self._prev_bid_depth = None
        self._trades_at = {}        # price -> sell volume since last diff
        self.n_events = 0

    def on_trade(self, t, price, qty, side):
        if side == "SELL":          # hits the bid side (what we track)
            self._trades_at[price] = self._trades_at.get(price, 0.0) + qty

    def on_depth(self, t, rep):
        self.n_events += 1
        bid = max(rep.bids) if rep.bids else 0.0
        ask = min(rep.asks) if rep.asks else 0.0
        if not bid or not ask:
            return
        mid = (bid + ask) / 2
        sp_ticks = (ask - bid) / self.tick

        # C: spread repair clock
        if sp_ticks > 1.0 + 1e-9:
            if self._wide_since is None:
                self._wide_since = t
                self.n_widenings += 1
        elif self._wide_since is not None:
            self.repair_s.append(t - self._wide_since)
            self._wide_since = None

        # B: allocate best-bid depth reductions
        if self._prev_bid_px is not None:
            cur = rep.bids.get(self._prev_bid_px, 0.0)
            fall = self._prev_bid_depth - cur
            if fall > 1e-12:
                traded = min(self._trades_at.get(self._prev_bid_px, 0.0), fall)
                self.traded_vol += traded
                self.cancel_vol += fall - traded
                if cur <= 0:
                    if traded >= self._prev_bid_depth - 1e-9:
                        self.gone_by_trade += 1
                    else:
                        self.gone_by_cancel += 1
        self._trades_at.clear()
        self._prev_bid_px = bid
        self._prev_bid_depth = rep.bids.get(bid, 0.0)

        # D: ~1s mid series
        if t - self._last_mid_t >= 1.0:
            self.mid_1s.append(mid)
            self._last_mid_t = t

        # A: sampled shape
        if self.n_events % SAMPLE_EVERY:
            return
        self.spread.append(sp_ticks)
        self.touch_bid_usd.append(rep.bids[bid] * bid)
        occupied = 0
        for k in BANDS_TICKS:
            lo = mid - k * self.tick
            s = sum(q * p for p, q in rep.bids.items() if p >= lo)
            self.band_bid_usd[k].append(s)
        self.occupied10.append(sum(1 for p in rep.bids
                                   if p >= mid - 10 * self.tick))

    def summary(self):
        mids = np.array(self.mid_1s)
        ret = np.diff(np.log(mids)) if len(mids) > 2 else np.array([0.0])
        sigma_daily_usd = float(np.std(ret) * np.sqrt(86400) * np.median(mids))
        mid_med = float(np.median(mids)) if len(mids) else 0.0

        def pct(a):
            a = np.array(a)
            return {"p25": float(np.percentile(a, 25)),
                    "p50": float(np.percentile(a, 50)),
                    "p75": float(np.percentile(a, 75))} if len(a) else None

        tot_gone = self.gone_by_trade + self.gone_by_cancel
        return {
            "n_depth_events": self.n_events,
            "A_spread_ticks": pct(self.spread),
            "A_touch_bid_usd": pct(self.touch_bid_usd),
            "A_band_bid_usd": {f"within_{k}t": pct(self.band_bid_usd[k])
                               for k in BANDS_TICKS},
            "A_occupied_levels_10t": pct(self.occupied10),
            "B_cancel_to_trade_ratio": (self.cancel_vol / self.traded_vol
                                        if self.traded_vol > 0 else None),
            "B_touch_gone_by_cancel_pct": (100 * self.gone_by_cancel / tot_gone
                                           if tot_gone else None),
            "B_n_touch_disappearances": tot_gone,
            "C_widenings_per_day": self.n_widenings,
            "C_repair_ms": {k: float(v * 1e3) for k, v in
                            (pct(self.repair_s) or {}).items()} if self.repair_s else None,
            "D_mid_median": mid_med,
            "D_rel_tick_bps": 1e4 * self.tick / mid_med if mid_med else None,
            "D_sigma_daily_usd": sigma_daily_usd,
            "D_kurth_rho": (self.tick / sigma_daily_usd
                            if sigma_daily_usd > 0 else None),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--capture-dir", default="data/live")
    args = ap.parse_args()

    results = {}
    for label, (market, tick) in INSTRUMENTS.items():
        print(f"=== {label} {args.date}")
        rep = BookReplayer(market=market, symbol_id=label)
        rep.collect_tables = False
        g = GeometryStats(tick)
        rep.on_depth = g.on_depth
        rep.on_trade = g.on_trade
        files = capture_files(args.capture_dir, label, args.date)
        if not files:
            print("  no files, skipping")
            continue
        for rec in iter_records(files):
            rep.process(rec)
        results[label] = g.summary()
        s = results[label]
        print(f"  spread p50={s['A_spread_ticks']['p50']:.2f}t  "
              f"touch=${s['A_touch_bid_usd']['p50']:,.0f}  "
              f"cancel:trade={s['B_cancel_to_trade_ratio']:.1f}  "
              f"gone-by-cancel={s['B_touch_gone_by_cancel_pct']:.0f}%  "
              f"widenings={s['C_widenings_per_day']}  "
              f"repair p50={(s['C_repair_ms'] or {}).get('p50', float('nan')):.0f}ms  "
              f"rel_tick={s['D_rel_tick_bps']:.2f}bps  "
              f"kurth_rho={s['D_kurth_rho']:.4f}")

    with open(OUT / f"book_geometry_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/book_geometry_{args.date}.json")


if __name__ == "__main__":
    main()
