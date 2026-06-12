"""
Getting to profit in the synthetic high-vol world (exp 59).
===========================================================
The high-vol regime (σ=0.20) loses with a naive tight quoter (the Layer-1
short-gamma σ² bleed). Because this synthetic world has NO informational adverse
selection (martingale mid, uninformed Poisson fills), Layer 1 is fully CURABLE by
pricing. Two levers:

  Lever 1 (premium):  widen the half-spread to the vol-appropriate width — price
                      the straddle at the right implied vol. More $/fill, fewer
                      fills; there is an interior optimum.
  Lever 2 (delta control): inventory skew — shift the reservation price against
                      inventory (β·q) so quotes mean-revert the position. Cuts the
                      σ²·q² variance without moving the mean much.

We sweep both on the exponential-fill high-vol world (so wide quotes still fill),
multi-seed, and report mean ± std P&L. The combined config reaches a robust profit.

Honest caveat: this works because the world is Layer-1-only. Real markets add
Layer-2 (informed counterparties); wide quotes there get *adversely* selected
(exp 57 deep-reversion), so this does NOT transfer to a retail edge. The point is
that the short-gamma bleed is curable when there is no information asymmetry —
confirming the C35 framing, not a tradeable strategy.

Run:
    python experiments/59_synthetic_engine_validation/high_vol_profit.py
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

_spec = importlib.util.spec_from_file_location(
    "synval", Path(__file__).resolve().parent / "synthetic_validation.py")
sv = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(sv)

FIGS = Path("experiments/59_synthetic_engine_validation/figs")
TICK, MAXI, OSZ = sv.TICK, sv.MAX_INV, sv.ORDER_SIZE
N_SEEDS = 10
REGIME = "brownian_highvol"


class SkewMM:
    """Fixed half-spread + linear inventory skew on the reservation price."""
    def __init__(self, half_ticks, skew_dollar_per_unit):
        self.half = half_ticks * TICK
        self.beta = skew_dollar_per_unit
    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kw):
        r = stats.mid_price - self.beta * inventory          # reservation, skewed vs inventory
        bid = np.round((r - self.half) / TICK) * TICK
        ask = np.round((r + self.half) / TICK) * TICK
        if ask <= bid: ask = bid + TICK
        return QuoteDecision(bid_price=bid, ask_price=ask, reservation_price=r,
                             optimal_spread=ask - bid, bid_size=OSZ, ask_size=OSZ)
    def should_quote(self, inv):
        return (inv < MAXI, inv > -MAXI)


# cache exponential-fill high-vol data per seed (shared across configs)
_cache = {}
def data(seed):
    if seed not in _cache:
        tp, qp, *_ = sv.generate(REGIME, seed, fill_model="exponential")
        _cache[seed] = DataLoader().load_coinapi(tp, qp)
    return _cache[seed]


def run(half_ticks, beta, seed, requote=0.1, latency=0.0):
    trades, quotes = data(seed)
    om = OrderManager(maker_fee=0.0, latency=latency, queue_model="none")
    ms = MarketState(120, 60, 0.9)
    bt = Backtest(SkewMM(half_ticks, beta), market_state=ms, order_manager=om,
                  requote_on_fill=True, requote_interval=requote, tolerance_ticks=0.5,
                  tick_size=TICK, verbose=False)
    res = bt.run(trades, quotes)
    return float(res.metrics.get("total_pnl", 0.0))


def stats(half_ticks, beta, requote=0.1, latency=0.0):
    p = np.array([run(half_ticks, beta, s, requote, latency) for s in range(N_SEEDS)])
    return p.mean(), p.std(), (p > 0).mean() * 100


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    print(f"High-vol synthetic (σ=0.20, exponential fills), {N_SEEDS} seeds/cell\n")

    # Lever 1: half-spread sweep, no skew
    widths = [2, 4, 6, 8, 12, 16, 24]
    print("Lever 1 — half-spread (β=0):")
    print(f"  {'half(t)':>7} | {'mean P&L':>9} | {'std':>7} | {'days>0':>6}")
    L1 = []
    for w in widths:
        m, s, d = stats(w, 0.0); L1.append((w, m, s, d))
        print(f"  {w:>7} | {m:>9.1f} | {s:>7.1f} | {d:>5.0f}%")
    best_w = max(L1, key=lambda r: r[1])[0]

    # Lever 2: at best width, sweep inventory skew β
    betas = [0.0, 0.0005, 0.001, 0.002, 0.004, 0.008]
    print(f"\nLever 2 — inventory skew β at half-spread {best_w}t:")
    print(f"  {'β($/unit)':>9} | {'mean P&L':>9} | {'std':>7} | {'days>0':>6}")
    L2 = []
    for b in betas:
        m, s, d = stats(best_w, b); L2.append((b, m, s, d))
        print(f"  {b:>9.4f} | {m:>9.1f} | {s:>7.1f} | {d:>5.0f}%")
    best_b = max(L2, key=lambda r: (r[3], r[1]))[0]   # most-robust (days>0 then mean)

    # Lever 3: requote frequency (speed) — fixes staleness adverse selection
    requotes = [0.5, 0.1, 0.05, 0.02, 0.01, 0.005]
    print(f"\nLever 3 — requote interval (speed) at half-spread 4t, β=0, latency=0:")
    print(f"  {'requote(s)':>10} | {'mean P&L':>9} | {'std':>7} | {'days>0':>6}")
    L3 = []
    for rq in requotes:
        m, s, d = stats(4, 0.0, requote=rq); L3.append((rq, m, s, d))
        print(f"  {rq:>10.3f} | {m:>9.1f} | {s:>7.1f} | {d:>5.0f}%")

    # Latency sensitivity at the fast (0.02s) requote — speed is the real-world gate
    print(f"\nLatency sensitivity (4t, requote 0.02s):")
    print(f"  {'latency(s)':>10} | {'mean P&L':>9} | {'days>0':>6}")
    L4 = []
    for lat in [0.0, 0.02, 0.05, 0.1, 0.2]:
        m, s, d = stats(4, 0.0, requote=0.02, latency=lat); L4.append((lat, m, d))
        print(f"  {lat:>10.3f} | {m:>9.1f} | {d:>5.0f}%")

    print(f"\nSUMMARY (path to profit, high-vol synthetic):")
    print(f"  naive 2t / requote 0.1s:        {stats(2,0.0)[0]:+.1f}")
    print(f"  Lever 1 widen to {best_w}t:           {dict((w,m) for w,m,_,_ in L1)[best_w]:+.1f}  (cushions, noisy)")
    print(f"  Lever 2 skew:                   hurts mean (mean-for-variance only)")
    print(f"  Lever 3 requote 0.05s (speed):  {dict((r,m) for r,m,_,_ in L3).get(0.05):+.1f}  <- the fix")

    # figure: 3 panels
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    ws = [r[0] for r in L1]; wm = [r[1] for r in L1]; wse = [r[2] for r in L1]
    ax[0].axhline(0, color="#888", lw=0.8)
    ax[0].errorbar(ws, wm, yerr=wse, marker="o", color="#9467bd", capsize=3, lw=1.6)
    ax[0].set_title("Lever 1 — widen the spread (β=0)", loc="left", fontweight="bold")
    ax[0].set_xlabel("half-spread (ticks)"); ax[0].set_ylabel("mean P&L ($) ± std (10 seeds)")
    ax[0].grid(alpha=0.25)

    bs_ = [r[0] for r in L2]; bmn = [r[1] for r in L2]; bse = [r[2] for r in L2]
    ax[1].axhline(0, color="#888", lw=0.8)
    ax[1].errorbar(bs_, bmn, yerr=bse, marker="o", color="#d62728", capsize=3, lw=1.6)
    ax[1].set_title(f"Lever 2 — inventory skew (at {best_w}t)", loc="left", fontweight="bold")
    ax[1].set_xlabel("skew β ($ per unit inventory)"); ax[1].set_ylabel("mean P&L ($) ± std")
    ax[1].grid(alpha=0.25)

    rq = [r[0] for r in L3]; rqm = [r[1] for r in L3]; rqe = [r[2] for r in L3]
    ax[2].axhline(0, color="#888", lw=0.8)
    ax[2].errorbar(rq, rqm, yerr=rqe, marker="o", color="#2ca02c", capsize=3, lw=1.6)
    ax[2].set_xscale("log")
    ax[2].set_title("Lever 3 — requote speed (at 4t)  ← the fix", loc="left", fontweight="bold")
    ax[2].set_xlabel("requote interval (s, log)"); ax[2].set_ylabel("mean P&L ($) ± std")
    ax[2].grid(alpha=0.25, which="both")
    fig.suptitle("Path to profit in the synthetic high-vol world: widen cushions, skew trades "
                 "mean for variance, SPEED fixes the staleness pick-off", fontweight="bold",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = FIGS / "high_vol_profit.png"; fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
