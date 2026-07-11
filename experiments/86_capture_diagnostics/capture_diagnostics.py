"""
capture_diagnostics.py
=======================
Exp 86 — Queue-fraction calibration and inside-spread level lifetimes from the
live Binance L2 capture (raw depth diffs + trades; no backtest engine).

A. QUEUE-FRACTION CALIBRATION
   The engine's L2 queue model assigns a virtual order at the touch
   `queue_ahead = queue_fraction × displayed_depth` and decrements it with
   traded volume only. Here we place a *virtual* order at the best bid every
   PLACE_EVERY_S seconds with the full displayed depth ahead (the physical
   truth for a newly arriving order) and replay reality forward under two
   L2-identifiable bounds:

     - trades-only (pessimistic): queue shrinks only via sell trades at our
       price — every cancellation is assumed behind us;
     - pro-rata (neutral): non-trade depth decreases at our price are
       cancellations attributed pro-rata ahead/behind.

   For each episode that clears while its level is still the best bid, the
   engine-comparable statistic is
       effective_qf = (traded volume before our position cleared) / D0
   i.e. the queue_fraction that would make the engine's trades-only model
   fill at the same moment reality (under each bound) does. Episodes ending
   otherwise are censored and reported: price moved up (stale), level became
   the front (best bid dropped), timeout.

B. INSIDE-SPREAD LEVEL LIFETIMES ("dealer window", theory ch. §7)
   Whenever a diff creates a new best bid/ask strictly inside the previous
   spread, track that level until: joined (depth increases at the level),
   traded, cancelled (depth to zero), or the price moves away. The time to
   `joined` measures how long a quoter posting a new inside-spread level
   would remain alone — the empirical dealer window. Requires spread > 1
   tick, so BTC (mean 1.16 ticks) supplies most events.

Run from master2/ (after some capture exists in data/live):
    python experiments/86_capture_diagnostics/capture_diagnostics.py --date 2026-07-10
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

PLACE_EVERY_S = 10.0        # virtual-order placement cadence
EPISODE_TIMEOUT_S = 120.0
TICKS = {"LINKUSDT": 0.001, "BTCUSDT": 0.01}


class QfCalibrator:
    """Virtual resting order at best bid; measures effective queue_fraction."""

    def __init__(self, tick: float):
        self.tick = tick
        self.ep = None                  # active episode
        self.last_place_t = 0.0
        self.results = []               # dicts per finished episode

    def _start(self, t, price, depth):
        if depth <= 0:
            return
        self.ep = dict(t0=t, price=price, d0=depth,
                       q_trades=depth,      # trades-only bound
                       q_prorata=depth,     # pro-rata bound
                       traded=0.0, prev_depth=depth,
                       cleared_trades=None, cleared_prorata=None)

    def _finish(self, t, outcome):
        ep = self.ep
        self.ep = None
        self.results.append(dict(
            outcome=outcome, dur=t - ep["t0"], d0=ep["d0"],
            traded=ep["traded"],
            qf_trades=(ep["cleared_trades"] / ep["d0"]
                       if ep["cleared_trades"] is not None else None),
            qf_prorata=(ep["cleared_prorata"] / ep["d0"]
                        if ep["cleared_prorata"] is not None else None)))

    def on_depth(self, t, rep):
        bid, _ = rep._top()
        depth = rep.bids.get(bid, 0.0)

        if self.ep is not None:
            ep = self.ep
            if t - ep["t0"] > EPISODE_TIMEOUT_S:
                self._finish(t, "timeout")
            elif bid > ep["price"] + 1e-12:
                self._finish(t, "price_up_stale")
            elif bid < ep["price"] - 1e-12:
                self._finish(t, "became_front")
            else:
                # cancellations: depth fell by more than trades since last look
                cur = rep.bids.get(ep["price"], 0.0)
                fall = ep["prev_depth"] - cur
                if fall > 1e-12:
                    # traded volume was already applied via on_trade;
                    # remaining fall is cancellation
                    cancel = max(fall - ep.pop("_traded_since", 0.0), 0.0)
                    if cancel > 0 and cur + cancel > 0:
                        frac = ep["q_prorata"] / (cur + cancel)
                        ep["q_prorata"] -= cancel * min(frac, 1.0)
                        if ep["q_prorata"] <= 1e-9 and ep["cleared_prorata"] is None:
                            ep["cleared_prorata"] = ep["traded"]
                else:
                    ep.pop("_traded_since", None)
                ep["prev_depth"] = cur

        if self.ep is None and t - self.last_place_t >= PLACE_EVERY_S and bid > 0:
            self.last_place_t = t
            self._start(t, bid, depth)

    def on_trade(self, t, price, qty, side):
        ep = self.ep
        if ep is None or side != "SELL":
            return
        if price <= ep["price"] + 1e-12:
            ep["traded"] += qty
            ep["q_trades"] -= qty
            ep["q_prorata"] -= qty
            ep["_traded_since"] = ep.get("_traded_since", 0.0) + qty
            if ep["q_trades"] <= 1e-9 and ep["cleared_trades"] is None:
                ep["cleared_trades"] = ep["traded"]
            if ep["q_prorata"] <= 1e-9 and ep["cleared_prorata"] is None:
                ep["cleared_prorata"] = ep["traded"]
            if ep["cleared_trades"] is not None and ep["cleared_prorata"] is not None:
                self._finish(t, "cleared")


class LevelLifetimes:
    """Tracks newly-created inside-spread levels until joined/traded/gone."""

    def __init__(self, tick: float):
        self.tick = tick
        self.prev_bid = self.prev_ask = None
        self.watch = None               # (side, price, t0, initial_depth)
        self.events = []
        self.n_snaps = 0
        self.spread_ticks = []

    def on_depth(self, t, rep):
        bid, ask = rep._top()
        if not bid or not ask:
            return
        self.n_snaps += 1
        if self.n_snaps % 10 == 0:
            self.spread_ticks.append((ask - bid) / self.tick)

        if self.watch is not None:
            side, price, t0, d0 = self.watch
            book = rep.bids if side == "bid" else rep.asks
            cur = book.get(price, 0.0)
            done = None
            if cur <= 0:
                done = "gone"           # cancelled or fully traded
            elif cur > d0 * 1.5 + 1e-12:
                done = "joined"
            elif (side == "bid" and bid > price) or (side == "ask" and ask < price):
                done = "overtaken"      # someone posted even deeper inside
            elif t - t0 > 60:
                done = "timeout_alone"
            if done:
                self.events.append(dict(side=side, alone_s=t - t0, outcome=done))
                self.watch = None

        if (self.watch is None and self.prev_bid and self.prev_ask):
            if self.prev_bid < bid < self.prev_ask - 1e-12:
                self.watch = ("bid", bid, t, rep.bids.get(bid, 0.0))
            elif self.prev_bid + 1e-12 < ask < self.prev_ask:
                self.watch = ("ask", ask, t, rep.asks.get(ask, 0.0))
        self.prev_bid, self.prev_ask = bid, ask


def run_symbol(symbol: str, date: str, capture_dir: str) -> dict:
    tick = TICKS[symbol]
    rep = BookReplayer(market="spot",
                       symbol_id=f"BINANCE_SPOT_{symbol[:-4]}_USDT")
    rep.collect_tables = False
    qf = QfCalibrator(tick)
    ll = LevelLifetimes(tick)
    rep.on_depth = lambda t, r: (qf.on_depth(t, r), ll.on_depth(t, r))
    rep.on_trade = qf.on_trade

    for rec in iter_records(capture_files(capture_dir, symbol, date)):
        rep.process(rec)

    res = qf.results
    cleared = [r for r in res if r["qf_prorata"] is not None]
    out = {
        "n_episodes": len(res),
        "outcomes": {o: sum(1 for r in res if r["outcome"] == o)
                     for o in set(r["outcome"] for r in res)},
        "n_cleared_prorata": len(cleared),
        "spread_ticks_mean": float(np.mean(ll.spread_ticks)) if ll.spread_ticks else None,
        "spread_ticks_p90": float(np.percentile(ll.spread_ticks, 90)) if ll.spread_ticks else None,
    }
    for key in ("qf_trades", "qf_prorata"):
        vals = np.array([r[key] for r in res if r[key] is not None])
        if len(vals):
            out[key] = {"n": len(vals),
                        "p25": float(np.percentile(vals, 25)),
                        "p50": float(np.percentile(vals, 50)),
                        "p75": float(np.percentile(vals, 75)),
                        "mean": float(vals.mean())}
    ev = ll.events
    out["level_events"] = {
        "n": len(ev),
        "outcomes": {o: sum(1 for e in ev if e["outcome"] == o)
                     for o in set(e["outcome"] for e in ev)},
        "alone_s_p50": float(np.median([e["alone_s"] for e in ev])) if ev else None,
        "alone_s_joined_p50": (float(np.median(
            [e["alone_s"] for e in ev if e["outcome"] == "joined"]))
            if any(e["outcome"] == "joined" for e in ev) else None),
    }
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--capture-dir", default="data/live")
    args = p.parse_args()

    results = {}
    for sym in ("LINKUSDT", "BTCUSDT"):
        print(f"=== {sym} {args.date}")
        results[sym] = run_symbol(sym, args.date, args.capture_dir)
        print(json.dumps(results[sym], indent=1)[:1200])

    with open(OUT / f"diagnostics_{args.date}.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nSaved -> {OUT}/diagnostics_{args.date}.json")


if __name__ == "__main__":
    main()
