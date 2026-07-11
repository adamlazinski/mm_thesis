"""
perp_gate_april.py
===================
Exp 91 — Perp-deviation-gated at-touch quoting on LINK April 2026, at the TRUE
tick (0.01), real L2, 30 days.

Exp 90 showed perp-lead gating recovers 28-73% of the passive loss on the
captured (small-tick-regime) day but cannot flip the sign. April 2026 LINK is
the large-tick regime where the ungated at-touch baseline sits AT the
equilibrium (exp 85 alpha=0: -$0.24/day, 47% days+). Question: does gating by
the perp-implied deviation — the sharpest causal signal in the project, a
*realized* move on the leading venue (C56) — lift the maker from the
equilibrium to positive? Comparison: exp 85's alpha=0 (same engine settings)
and alpha=4 OBI-gating (+$0.36/day, null).

Signal: dev(t) = (perp_mid - spot_mid) - EWMA_60s basis, from CoinAPI
LINK_PERP quotes (event-level, verified clean 0.001 grid), lagged 15ms.
Gate: suppress the ask when dev > gate (price about to rise), bid when
dev < -gate. Engine: identical to exp 85 (qf=0.5, 10ms latency, 50ms requote,
tolerance 0.5, post_only, TICK=0.01).

Run: python experiments/91_perp_gate_april/perp_gate_april.py
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
OUT.mkdir(parents=True, exist_ok=True)

TICK = 0.01                # true April LINK tick (C54)
ORDER_SIZE = 5.0
MAX_INV = 38.0
LATENCY = 0.01
REQUOTE = 0.05
TAKER_FEE = 0.00045
SIG_LAT_S = 0.015
EWMA_HALFLIFE_S = 60.0

GATES = [0.002, 0.005]     # $ deviation = 0.2 / 0.5 spot ticks


def load_mid(path):
    df = pd.read_parquet(path, columns=["time_exchange", "bid_price", "ask_price"])
    te = df["time_exchange"]
    if te.dtype == object or pd.api.types.is_datetime64_any_dtype(te):
        t = pd.to_datetime(te, utc=True).astype("int64").to_numpy() / 1e9
    else:
        t = te.to_numpy().astype(float)
        if t[0] > 1e17: t = t / 1e9
        elif t[0] > 1e14: t = t / 1e6
    mid = (df["bid_price"].to_numpy() + df["ask_price"].to_numpy()) / 2
    good = np.isfinite(mid) & np.isfinite(t)
    t, mid = t[good], mid[good].astype(float)
    order = np.argsort(t, kind="stable")
    t, mid = t[order], mid[order]
    keep = np.concatenate([[True], np.diff(t) > 0])
    return t[keep], mid[keep]


def dev_series(ts, ms, tp, mp):
    t_all = np.concatenate([ts, tp])
    venue = np.concatenate([np.zeros(len(ts), int), np.ones(len(tp), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]
    out_d = np.empty(len(t_all))
    cur = [ms[0], mp[0]]; i_s = i_p = 0
    base = mp[0] - ms[0]; last_t = t_all[0]
    for k, (t, v) in enumerate(zip(t_all, venue)):
        if v == 0: cur[0] = ms[i_s]; i_s += 1
        else:      cur[1] = mp[i_p]; i_p += 1
        B = cur[1] - cur[0]
        alpha = 1 - 0.5 ** (max(t - last_t, 0.0) / EWMA_HALFLIFE_S)
        base += alpha * (B - base); last_t = t
        out_d[k] = B - base
    return t_all, out_d


class PerpGatedTouchMM:
    def __init__(self, td, dv, gate):
        self.td, self.dv, self.gate = td, dv, gate
        self.n_gated = 0; self.n_calls = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_calls += 1
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else TICK
        bid = np.round((mid - half) / TICK) * TICK
        ask = np.round((mid + half) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        i = np.searchsorted(self.td, ts - SIG_LAT_S, side="right") - 1
        dev = self.dv[i] if i >= 0 else 0.0
        bid_size = ORDER_SIZE if inv < MAX_INV else 0.0
        ask_size = ORDER_SIZE if inv > -MAX_INV else 0.0
        if self.gate is not None:
            if dev > self.gate:
                ask_size = 0.0; self.n_gated += 1
            elif dev < -self.gate:
                bid_size = 0.0; self.n_gated += 1
        return QuoteDecision(bid_price=bid, ask_price=ask,
                             reservation_price=mid, optimal_spread=ask - bid,
                             bid_size=bid_size, ask_size=ask_size)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


def dates():
    def stems(pat):
        return {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
                for f in glob.glob(str(DATA / pat))}
    return sorted(stems("quotes_LINK_2026-04-*.parquet")
                  & stems("trades_LINK_2026-04-*.parquet")
                  & stems("orderbooks_LINK_2026-04-*.parquet")
                  & stems("quotes_LINK_PERP_2026-04-*.parquet"))


def main():
    days = dates()
    print(f"Exp 91 — perp-gated at-touch, LINK Apr-2026 TRUE tick, {len(days)} days, "
          f"gates={GATES} (+baseline ref: exp85 alpha=0 = -$0.24/day)\n")
    ld = DataLoader()
    acc = {f"gate{g:g}": [] for g in GATES}
    gated_pct = {f"gate{g:g}": [] for g in GATES}
    fills = {f"gate{g:g}": [] for g in GATES}

    for d in days:
        ts, ms = load_mid(DATA / f"quotes_LINK_{d}.parquet")
        tp, mp = load_mid(DATA / f"quotes_LINK_PERP_{d}.parquet")
        td, dv = dev_series(ts, ms, tp, mp)
        tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                                 str(DATA / f"quotes_LINK_{d}.parquet"))
        l2s = ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet"))
        row = []
        for g in GATES:
            om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                              queue_model="l2")
            om.queue_fraction = 0.5
            strat = PerpGatedTouchMM(td, dv, g)
            res = Backtest(strat, market_state=MarketState(120, 60, 0.9),
                           order_manager=om, requote_on_fill=True,
                           requote_interval=REQUOTE, tolerance_ticks=0.5,
                           tick_size=TICK, verbose=False
                           ).run(tr, qt, l2_tracker=L2BookTracker(l2s))
            pnl = float(res.metrics["total_pnl"])
            takers = [f for f in om.fills if getattr(f, "is_taker", False)]
            pnl -= TAKER_FEE * sum(f.quantity * f.price for f in takers)
            key = f"gate{g:g}"
            acc[key].append(pnl)
            gated_pct[key].append(100 * strat.n_gated / max(strat.n_calls, 1))
            fills[key].append(len(om.fills))
            row.append(f"{key}:{pnl:+.2f}")
        print(f"  {d}  " + "  ".join(row))

    summary = {}
    print()
    for key in acc:
        arr = np.array(acc[key])
        print(f"  {key:10s} mean={arr.mean():+7.2f}  std={arr.std():5.2f}  "
              f"days+={100*(arr>0).mean():4.0f}%  fills={np.mean(fills[key]):6.0f}  "
              f"gated%={np.mean(gated_pct[key]):.1f}")
        summary[key] = {"mean_pnl": float(arr.mean()), "std": float(arr.std()),
                        "days_pos_pct": float(100 * (arr > 0).mean()),
                        "mean_fills": float(np.mean(fills[key])),
                        "mean_gated_pct": float(np.mean(gated_pct[key])),
                        "per_day": [float(x) for x in arr]}
    with open(OUT / "perp_gate_april.json", "w") as fh:
        json.dump({"n_days": len(days), "gates": GATES,
                   "baseline_ref": "exp85 alpha=0: -0.24/day, 47% days+",
                   "summary": summary}, fh, indent=2)
    print(f"\nSaved -> {OUT}/perp_gate_april.json")


if __name__ == "__main__":
    main()
