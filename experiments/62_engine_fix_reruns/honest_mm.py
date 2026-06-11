"""
Corrected honest at-touch LINK MM (exp 62 — engine-fix rerun).
==============================================================
Re-runs the honest at-touch market maker under the CORRECTED engine (marketable-
on-arrival orders are takers that bypass the L2 queue; commit 24a687f) across all
LINK April 2026 days with L2 order-book data. This regenerates the central
C29/C30 honest-regime cell with the realistic latency-adverse-selection fills the
old engine suppressed.

Config: TouchMM (quote at the touch), queue_model='l2', queue_fraction=0.5,
latency=0.1s. Maker fee 0 (per the zero-fee convention). The taker fee is applied
post-hoc from the recorded taker fills (fee = qty*price*rate), so PnL at fee=0 and
fee=4.5bps come from a single pass.

Run:
    python experiments/62_engine_fix_reruns/honest_mm.py
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.core.l2_features import L2BookTracker
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT = Path("experiments/62_engine_fix_reruns/results")
TICK = 0.001
QF = 0.5
TAKER_FEE = 0.00045   # 4.5 bps, applied post-hoc


class TouchMM:
    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        mid = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        bid = np.round((mid - half) / TICK) * TICK
        ask = np.round((mid + half) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=mid,
                             optimal_spread=ask - bid, bid_size=5.0, ask_size=5.0)
    def should_quote(self, inv):
        return (inv < 38.0, inv > -38.0)


def dates():
    ds = []
    for f in sorted(glob.glob(str(DATA / "orderbooks_LINK_2026-04-*.parquet"))):
        d = re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
        if (DATA / f"trades_LINK_{d}.parquet").exists() and (DATA / f"quotes_LINK_{d}.parquet").exists():
            ds.append(d)
    return ds


def run_day(d):
    ld = DataLoader()
    tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{d}.parquet"),
                             str(DATA / f"quotes_LINK_{d}.parquet"))
    l2 = L2BookTracker(ld.load_orderbook(str(DATA / f"orderbooks_LINK_{d}.parquet")))
    om = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=0.1, queue_model="l2")
    om.queue_fraction = QF
    ms = MarketState(120, 60, 0.9)
    res = Backtest(TouchMM(), market_state=ms, order_manager=om, requote_on_fill=True,
                   requote_interval=0.1, tolerance_ticks=0.5, tick_size=TICK,
                   verbose=False).run(tr, qt, l2_tracker=l2)
    pnl0 = float(res.metrics.get("total_pnl", 0.0))
    n = len(om.fills)
    tk = [f for f in om.fills if getattr(f, "is_taker", False)]
    taker_notional = sum(f.quantity * f.price for f in tk)
    pnl_fee = pnl0 - TAKER_FEE * taker_notional
    return {"date": d, "fills": n, "takers": len(tk),
            "pnl_fee0": round(pnl0, 2), "pnl_fee45bps": round(pnl_fee, 2),
            "fee_cost": round(TAKER_FEE * taker_notional, 2)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ds = dates()
    print(f"Honest at-touch LINK MM (corrected engine), L2 qf={QF}, latency 0.1s, {len(ds)} days")
    print(f"  {'date':>12} | {'fills':>6} | {'taker%':>6} | {'pnl(fee0)':>9} | {'pnl(4.5bps)':>11}")
    rows = []
    for d in ds:
        try:
            r = run_day(d); rows.append(r)
            print(f"  {d:>12} | {r['fills']:>6} | {100*r['takers']/max(r['fills'],1):>5.1f}% | "
                  f"{r['pnl_fee0']:>+9.2f} | {r['pnl_fee45bps']:>+11.2f}")
        except Exception as e:
            print(f"  {d}: ERROR {e}")
    if rows:
        p0 = np.array([r["pnl_fee0"] for r in rows])
        pf = np.array([r["pnl_fee45bps"] for r in rows])
        print(f"\n  MEAN/day  fee=0:    {p0.mean():+.2f}  (days>0 {100*(p0>0).mean():.0f}%)")
        print(f"  MEAN/day  fee=4.5b: {pf.mean():+.2f}  (days>0 {100*(pf>0).mean():.0f}%)")
        json.dump({"queue_fraction": QF, "taker_fee": TAKER_FEE, "latency": 0.1,
                   "per_day": rows,
                   "mean_pnl_fee0": float(p0.mean()), "mean_pnl_fee45bps": float(pf.mean()),
                   "days_pos_fee0": float((p0 > 0).mean()), "days_pos_fee45bps": float((pf > 0).mean())},
                  open(OUT / "honest_mm.json", "w"), indent=2)
        print(f"Saved -> {OUT / 'honest_mm.json'}")


if __name__ == "__main__":
    main()
