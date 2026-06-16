"""
grid_resolution_check.py
=========================
Part B of exp 59 found the high-vol brownian world (sigma=0.20, fixed 2-tick
quoter, BBO fills, latency=0, grid dt=0.1s) robustly NEGATIVE: mean PnL ~
-$920 (12 seeds).

Per the calibrate_zeta / explicit-PnL-formula derivation, the bleed term is

    B(delta) = 2*A*sigma_trade*[z*Phi(-z) - phi(z)],   z = delta/sigma_trade

where sigma_trade is the std of the price move BETWEEN MM requotes. In
synthetic_validation.py, V(t) is simulated on a grid of step dt, and the MM
requotes at the same cadence (requote_interval = dt = 0.1s), so
sigma_trade = sigma * sqrt(dt) ~ $0.063 vs delta = 2 ticks = $0.02
  -> z = delta/sigma_trade ~ 0.32  (deep in the "bad" / large-bleed regime).

Hypothesis (per the user): the negative result is a DISCRETIZATION artifact
-- "jumps between timesteps" that overshoot the half-spread. As dt -> 0 (finer
grid, MM requotes proportionally faster), sigma_trade = sigma*sqrt(dt) -> 0,
z -> infinity, and B(delta) -> 0 (Gaussian tail, faster than any 1/dt blow-up
in fill rate). In the continuous-requoting limit, every fill happens exactly
at distance delta (pure theta, no overshoot) -> PnL should turn positive.

This script reruns Part B's exact setup (sigma=0.20, half=2 ticks, BBO fills,
latency=0) at a sweep of grid dt (== requote_interval), holding everything
else fixed, and reports mean PnL vs the predicted sigma_trade and z=delta/sigma_trade.

Run from master2/ root with .venv activated:
    python experiments/59_synthetic_engine_validation/grid_resolution_check.py
"""
from __future__ import annotations

import sys
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
DATA = OUT / "data" / "grid_check"

TICK = 0.01
V0 = 100.00
TRADE_RATE = 2.0
MKT_SPREAD_TICKS = 4
MM_HALF_TICKS = 2
ORDER_SIZE = 1.0
MAX_INV = 50.0
BM_SIGMA_HI = 0.20
EPOCH = pd.Timestamp("2026-01-01", tz="UTC")

DELTA = MM_HALF_TICKS * TICK  # $0.02


class FixedSpreadMM:
    """Quote a constant half-spread around the mid; cap inventory."""

    def __init__(self, half_ticks, tick, size, max_inv):
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
        return (inventory < self.max_inv, inventory > -self.max_inv)


def generate(grid_dt: float, seed: int, n_seconds: float):
    """Brownian-highvol world, BBO fill model, true-value grid at step grid_dt."""
    rng = np.random.default_rng(seed)
    half_mkt = MKT_SPREAD_TICKS / 2 * TICK

    n_trades = rng.poisson(TRADE_RATE * n_seconds)
    t_trades = np.sort(rng.uniform(0, n_seconds, n_trades))

    grid = np.arange(0, n_seconds, grid_dt)
    dt = np.diff(grid, prepend=grid[0])
    steps = BM_SIGMA_HI * np.sqrt(dt) * rng.standard_normal(len(grid))
    steps[0] = 0.0
    v_grid = V0 + np.cumsum(steps)

    snapped = np.round(v_grid / TICK) * TICK
    heartbeat_every = max(1, int(round(1.0 / grid_dt)))
    emit = np.ones(len(grid), dtype=bool)
    emit[1:] = (np.abs(np.diff(snapped)) > 1e-9) | (np.arange(1, len(grid)) % heartbeat_every == 0)
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

    v_at_trade = np.interp(t_trades, grid, v_grid)
    snapped_tr = np.round(v_at_trade / TICK) * TICK
    side = rng.integers(0, 2, len(t_trades))
    taker = np.where(side == 1, "buy", "sell")
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
    tag = f"dt{grid_dt}_{seed}"
    tp = DATA / f"trades_{tag}.parquet"
    qp = DATA / f"quotes_{tag}.parquet"
    trades_df.to_parquet(tp)
    quotes_df.to_parquet(qp)
    return str(tp), str(qp)


def run_one(grid_dt: float, seed: int, n_seconds: float):
    tp, qp = generate(grid_dt, seed, n_seconds)
    trades, quotes = DataLoader().load_coinapi(tp, qp)

    strat = FixedSpreadMM(MM_HALF_TICKS, TICK, ORDER_SIZE, MAX_INV)
    om = OrderManager(maker_fee=0.0, latency=0.0, queue_model="none")
    ms = MarketState(vol_window=120, arrival_window=60, ewma_alpha=0.9)
    bt = Backtest(
        strat, market_state=ms, order_manager=om,
        requote_on_fill=True, requote_interval=grid_dt,
        tolerance_ticks=0.5, tick_size=TICK, verbose=False,
    )
    res = bt.run(trades, quotes)
    m = res.metrics if hasattr(res, "metrics") else {}
    pnl = float(m.get("total_pnl", 0.0))
    n_fills = int(m.get("total_fills", m.get("n_fills", 0)))
    return pnl, n_fills


def main():
    n_seconds = 2 * 3600  # 2h per seed
    n_seeds = 10
    grid_dts = [0.1, 0.05, 0.02, 0.01, 0.005]

    print(f"Brownian high-vol (sigma={BM_SIGMA_HI}), BBO fills, half-spread={MM_HALF_TICKS}t "
          f"(delta=${DELTA}), latency=0, requote_interval=grid_dt, {n_seconds}s/seed, "
          f"{n_seeds} seeds\n")
    print(f"{'grid_dt':>8} {'sigma_trade':>12} {'z=delta/sig':>12} "
          f"{'mean PnL':>10} {'std':>8} {'days>0':>7} {'mean fills':>10}")

    for dt in grid_dts:
        sigma_trade = BM_SIGMA_HI * np.sqrt(dt)
        z = DELTA / sigma_trade
        pnls, fills = [], []
        for s in range(n_seeds):
            pnl, n_fills = run_one(dt, s, n_seconds)
            pnls.append(pnl)
            fills.append(n_fills)
        pnls = np.array(pnls)
        print(f"{dt:>8.4f} {sigma_trade:>12.5f} {z:>12.3f} "
              f"{pnls.mean():>10.2f} {pnls.std():>8.2f} "
              f"{100*(pnls > 0).mean():>6.0f}% {np.mean(fills):>10.1f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
