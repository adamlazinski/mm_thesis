"""
Synthetic engine-validation harness (exp 59).
==============================================
A ground-truth test of the backtest engine's fill + P&L accounting, run on
markets whose profitability we know in closed form. If the engine does NOT show
the expected profit here, the fill or accounting logic is broken — and every
real-data conclusion would be suspect.

Three regimes for the *true value* V(t), each with the same Poisson order flow
quoting around it:

  1. CONSTANT     V(t) = V0.  No adverse selection at all: every fill earns
                  exactly the half-spread vs. true value. Expected P&L is exactly
                  n_fills * half_spread_$ * size. The engine MUST match this.

  2. OU           V(t) mean-reverts to V0 (Ornstein-Uhlenbeck). Inventory taken
                  at deviations is unwound favourably on reversion -> still highly
                  profitable, arguably more than constant.

  3. BROWNIAN     V(t) is a driftless random walk (martingale). This is the
                  classic Avellaneda-Stoikov world: spread capture vs. inventory
                  adverse selection. Profitability depends on spread vs. vol; with
                  a spread wide relative to per-fill vol it stays positive, and it
                  is the LEAST profitable of the three — the expected ordering is
                  constant >~ OU >> brownian.

Market construction (per regime):
  - BBO is a symmetric band around V: bid = V - S/2, ask = V + S/2  (S = market
    spread, a few ticks). Quotes are emitted whenever V moves by >= 1 tick or at
    a steady heartbeat.
  - Taker market orders arrive as a Poisson process; side is 50/50. A taker BUY
    prints at the current ask, a taker SELL at the current bid. With the engine's
    price-only fill rule, a taker buy at the ask fills a resting MM ask, etc.
  - The MM (FixedSpreadMM) quotes a fixed half-spread; quoting AT the BBO makes
    every fill an unambiguous spread capture (no inside-spread / queue subtlety).

Run:
    python experiments/59_synthetic_engine_validation/synthetic_validation.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

OUT = Path("experiments/59_synthetic_engine_validation")
DATA = OUT / "data"
RES = OUT / "results"

# ---------------------------------------------------------------------------
# Market parameters (shared across regimes)
# ---------------------------------------------------------------------------
TICK        = 0.01
V0          = 100.00          # starting true value ($)
N_SECONDS   = 6 * 3600        # 6 hours of data
TRADE_RATE  = 2.0             # taker market orders / sec (Poisson)
MKT_SPREAD_TICKS = 4          # market BBO spread in ticks -> half = 2 ticks
MM_HALF_TICKS    = 2          # MM quotes AT the BBO (half-spread = 2 ticks)
ORDER_SIZE  = 1.0            # MM order size (units)
MAX_INV     = 50.0           # MM inventory cap (units)

# Per-regime true-value dynamics
# Anchor the synthetic clock to a real date. The loader autodetects the
# timestamp unit from the FIRST value, so it must look like a modern epoch
# (~1.7e18 ns) rather than 0.
EPOCH       = pd.Timestamp("2026-01-01", tz="UTC")
OU_THETA    = 0.05            # OU mean-reversion speed (1/sec)
OU_SIGMA    = 0.02            # OU instantaneous vol ($/sqrt(sec))
BM_SIGMA     = 0.01           # brownian step vol ($/sqrt(sec)) — mild
BM_SIGMA_MED = 0.05           # medium vol: short-gamma cost noticeable, beatable
BM_SIGMA_HI  = 0.20           # high vol: short-gamma cost dominates a tight spread


# ---------------------------------------------------------------------------
# Fixed-spread market maker — the simplest possible strategy, so the test
# probes the ENGINE, not strategy calibration.
# ---------------------------------------------------------------------------
class FixedSpreadMM:
    """Quote a constant half-spread around the mid; cap inventory."""

    def __init__(self, half_ticks: int, tick: float, size: float, max_inv: float):
        self.half = half_ticks * tick
        self.tick = tick
        self.size = size
        self.max_inv = max_inv

    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kwargs):
        mid = stats.mid_price
        bid = np.floor((mid - self.half) / self.tick + 1e-9) * self.tick
        ask = np.ceil((mid + self.half) / self.tick - 1e-9) * self.tick
        if ask <= bid:
            ask = bid + self.tick
        return QuoteDecision(
            bid_price=bid, ask_price=ask, reservation_price=mid,
            optimal_spread=ask - bid, bid_size=self.size, ask_size=self.size,
        )

    def should_quote(self, inventory):
        # Stop adding to a side once the inventory cap is hit.
        return (inventory < self.max_inv, inventory > -self.max_inv)


# ---------------------------------------------------------------------------
# True-value generators
# ---------------------------------------------------------------------------
def true_value_path(regime: str, t: np.ndarray, rng) -> np.ndarray:
    dt = np.diff(t, prepend=t[0])
    if regime == "constant":
        return np.full_like(t, V0)
    if regime == "ou":
        v = np.empty_like(t)
        v[0] = V0
        for i in range(1, len(t)):
            d = dt[i]
            v[i] = (v[i - 1] + OU_THETA * (V0 - v[i - 1]) * d
                    + OU_SIGMA * np.sqrt(d) * rng.standard_normal())
        return v
    if regime in ("brownian", "brownian_medvol", "brownian_highvol"):
        sig = {"brownian": BM_SIGMA, "brownian_medvol": BM_SIGMA_MED,
               "brownian_highvol": BM_SIGMA_HI}[regime]
        steps = sig * np.sqrt(dt) * rng.standard_normal(len(t))
        steps[0] = 0.0
        return V0 + np.cumsum(steps)
    raise ValueError(regime)


# Exponential fill model: penetration depth of each taker order, in ticks.
# A taker order penetrates to mid ± depth, so a resting MM quote at half-spread
# δ fills iff depth >= δ. The rate of orders reaching δ is Λ·exp(-κ·δ) — exactly
# the Avellaneda-Stoikov fill intensity. Mean depth = 1/κ ticks.
EXP_KAPPA_TICK = 0.5          # fill-intensity decay (1/tick); mean depth 2 ticks


def generate(regime: str, seed: int = 0, fill_model: str = "bbo"):
    """Build CoinAPI-format trades + quotes parquets for one regime.

    fill_model:
      'bbo'         — every taker prints at the BBO (±2 ticks). Fills only quotes
                      at/inside the touch. Used for the engine gold check.
      'exponential' — each taker penetrates to a random depth ~ Exp(κ) ticks, so
                      quotes at ANY width fill with intensity ∝ exp(-κδ). The
                      native Avellaneda-Stoikov world — needed to test A-S fairly.
    """
    rng = np.random.default_rng(seed)
    half_mkt = MKT_SPREAD_TICKS / 2 * TICK

    # --- Trade arrival times (Poisson) ---
    n_trades = rng.poisson(TRADE_RATE * N_SECONDS)
    t_trades = np.sort(rng.uniform(0, N_SECONDS, n_trades))

    # --- True value sampled on a fine grid; quotes emitted on tick moves ---
    grid = np.arange(0, N_SECONDS, 0.1)
    v_grid = true_value_path(regime, grid, rng)

    # Quote stream: snap V to a tick mid, emit a quote whenever the snapped mid
    # changes (plus a 1 Hz heartbeat so mark-to-market stays fresh).
    snapped = np.round(v_grid / TICK) * TICK
    emit = np.ones(len(grid), dtype=bool)
    emit[1:] = (np.abs(np.diff(snapped)) > 1e-9) | (np.arange(1, len(grid)) % 10 == 0)
    qt = grid[emit]
    qv = snapped[emit]
    q_bid = np.round((qv - half_mkt) / TICK) * TICK
    q_ask = np.round((qv + half_mkt) / TICK) * TICK

    quotes_df = pd.DataFrame({
        "time_exchange": EPOCH + pd.to_timedelta(qt, unit="s"),
        "time_coinapi":  EPOCH + pd.to_timedelta(qt, unit="s"),
        "bid_price": q_bid, "bid_size": np.full(len(qt), 1000.0),
        "ask_price": q_ask, "ask_size": np.full(len(qt), 1000.0),
    })

    # --- Trade prices ---
    v_at_trade = np.interp(t_trades, grid, v_grid)
    snapped_tr = np.round(v_at_trade / TICK) * TICK
    side = rng.integers(0, 2, len(t_trades))   # 0 = sell, 1 = buy
    taker = np.where(side == 1, "buy", "sell")
    if fill_model == "exponential":
        # Penetration depth ~ Exp(κ) ticks; print at mid ± depth. The MM earns its
        # quoted price (maker), so a deep print fills any same-side quote within it.
        depth_ticks = rng.exponential(1.0 / EXP_KAPPA_TICK, len(t_trades))
        depth = np.maximum(depth_ticks, MKT_SPREAD_TICKS / 2) * TICK  # >= touch
        depth = np.round(depth / TICK) * TICK
        price = np.where(side == 1, snapped_tr + depth, snapped_tr - depth)
    else:
        bid_tr = np.round((snapped_tr - half_mkt) / TICK) * TICK
        ask_tr = np.round((snapped_tr + half_mkt) / TICK) * TICK
        price = np.where(side == 1, ask_tr, bid_tr)

    trades_df = pd.DataFrame({
        "time_exchange": EPOCH + pd.to_timedelta(t_trades, unit="s"),
        "time_coinapi":  EPOCH + pd.to_timedelta(t_trades, unit="s"),
        "price": price, "size": np.full(len(t_trades), 5.0),
        "taker_side": taker,
    })

    DATA.mkdir(parents=True, exist_ok=True)
    tag = regime if fill_model == "bbo" else f"{regime}_exp"
    tp = DATA / f"trades_SYN_{tag}.parquet"
    qp = DATA / f"quotes_SYN_{tag}.parquet"
    trades_df.to_parquet(tp)
    quotes_df.to_parquet(qp)
    return str(tp), str(qp), len(t_trades), len(qt)


# ---------------------------------------------------------------------------
# Run one regime through the real engine
# ---------------------------------------------------------------------------
def run_regime(regime: str, seed: int = 0) -> dict:
    tp, qp, n_tr, n_q = generate(regime, seed)
    loader = DataLoader()
    trades, quotes = loader.load_coinapi(tp, qp)

    strat = FixedSpreadMM(MM_HALF_TICKS, TICK, ORDER_SIZE, MAX_INV)
    om = OrderManager(maker_fee=0.0, latency=0.0, queue_model="none")
    ms = MarketState(vol_window=120, arrival_window=60, ewma_alpha=0.9)
    bt = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=0.1,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    )
    res = bt.run(trades, quotes)
    m = res.metrics if hasattr(res, "metrics") else {}

    n_fills = int(m.get("total_fills", m.get("n_fills", 0)))
    total_pnl = float(m.get("total_pnl", 0.0))
    # Closed-form expectation for the CONSTANT regime: each fill earns the
    # half-spread vs. true value, on ORDER_SIZE units.
    half_spread_dollar = MM_HALF_TICKS * TICK
    expected_constant = n_fills * half_spread_dollar * ORDER_SIZE

    out = {
        "regime": regime,
        "n_trades_generated": n_tr,
        "n_quotes_generated": n_q,
        "n_fills": n_fills,
        "total_pnl": round(total_pnl, 4),
        "final_inventory": round(float(om.inventory), 4),
        "cash": round(float(om.cash), 4),
        "inv_marktomarket": round(float(om.inventory) * float(ms.stats.mid_price), 4),
        "pnl_per_fill": round(total_pnl / n_fills, 5) if n_fills else None,
        "half_spread_dollar": half_spread_dollar,
    }
    if regime == "constant":
        out["expected_pnl_constant"] = round(expected_constant, 4)
        out["realized_minus_expected"] = round(total_pnl - expected_constant, 4)
    return out


def main():
    RES.mkdir(parents=True, exist_ok=True)
    results = []
    for regime in ["constant", "ou", "brownian", "brownian_highvol"]:
        print(f"\n{'='*70}\nREGIME: {regime}\n{'='*70}")
        r = run_regime(regime, seed=0)
        results.append(r)
        for k, v in r.items():
            print(f"  {k:28s} {v}")

    with open(RES / "validation_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    print(f"  {'regime':>10} | {'fills':>7} | {'PnL($)':>12} | {'PnL/fill':>9} | {'final_inv':>9}")
    for r in results:
        print(f"  {r['regime']:>10} | {r['n_fills']:>7} | {r['total_pnl']:>12.2f} | "
              f"{(r['pnl_per_fill'] or 0):>9.4f} | {r['final_inventory']:>9.2f}")
    print("\nExpected ordering: constant >~ ou >> brownian.")
    print("Constant regime is the gold check: realized P&L should equal")
    print("n_fills * half_spread * size to floating precision.")
    print(f"Saved -> {RES / 'validation_results.json'}")


if __name__ == "__main__":
    main()
