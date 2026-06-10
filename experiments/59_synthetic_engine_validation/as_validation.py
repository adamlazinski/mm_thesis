"""
A-S & GLFT strategy validation on their native synthetic world (exp 59b).
=========================================================================
Companion to synthetic_validation.py. That script validated the ENGINE with a
fixed-spread quoter. This one validates the STRATEGIES: the real
AvellanedaStoikov and GLFTMarketMaker, each fed the TRUE volatility, run through
the real engine on an A-S/GLFT-faithful market (arithmetic-BM mid + exponential
Poisson fills at all depths).

Claim under test (user): a vol-aware market maker given the TRUE volatility should
be positive even in the high-vol regime where a fixed too-tight spread loses. In
the model's own world there is no informational adverse selection (the mid is a
martingale) — but a passive MM is structurally short-gamma, so the realized
inventory-variance cost scales with σ². The optimal spread must WIDEN ∝ σ to
offset it. That is exactly the γσ²-term in A-S and the θ-term in GLFT.

Because the high-vol regime has enormous per-path variance (σ=0.20 $/√s wanders
the price ~±$29 over 6 h), every cell is averaged over multiple seeds — a single
path is not informative.

We inject the true σ directly (the "provide the true measure" condition) and feed
the true fill-decay κ and rate A. GLFT uses dollar units natively; A-S uses
fractional units, so its κ is the per-fraction decay κ_$·mid.

Run:
    python experiments/59_synthetic_engine_validation/as_validation.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import AvellanedaStoikov
from hft_market_maker.strategies.glft import GLFTMarketMaker

_spec = importlib.util.spec_from_file_location(
    "synval", Path(__file__).resolve().parent / "synthetic_validation.py")
synval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synval)

TICK, V0 = synval.TICK, synval.V0
EXP_KAPPA_TICK = synval.EXP_KAPPA_TICK
ORDER_SIZE, MAX_INV = synval.ORDER_SIZE, synval.MAX_INV
RES = synval.RES
N_SEEDS = 6

# True per-regime volatility in DOLLARS/sqrt(s).
TRUE_SIGMA_DOLLAR = {
    "constant":         0.0,
    "brownian":         synval.BM_SIGMA,      # 0.01
    "brownian_medvol":  synval.BM_SIGMA_MED,  # 0.05
    "brownian_highvol": synval.BM_SIGMA_HI,   # 0.20
}
KAPPA_DOLLAR = EXP_KAPPA_TICK / TICK          # 0.5/0.01 = 50 per $  (GLFT units)
KAPPA_FRAC   = KAPPA_DOLLAR * V0              # 5000 per fraction     (A-S units)
A_RATE       = 1.0                            # per-side baseline fill rate (fills/s)
T_HORIZON    = 60.0                           # A-S rolling horizon (s)


class TrueSigmaAS(AvellanedaStoikov):
    def __init__(self, true_sigma_frac, true_kappa_frac, **kw):
        super().__init__(**kw)
        self._s, self._k = true_sigma_frac, true_kappa_frac

    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kw):
        stats.sigma, stats.kappa_as = self._s, self._k
        return super().compute_quotes(stats, inventory, timestamp, t_remaining, **kw)


class TrueSigmaGLFT(GLFTMarketMaker):
    def __init__(self, true_sigma_frac, **kw):
        super().__init__(**kw)
        self._s = true_sigma_frac

    def compute_quotes(self, stats, inventory, timestamp, t_remaining=None, **kw):
        stats.sigma = self._s
        return super().compute_quotes(stats, inventory, timestamp, t_remaining, **kw)


# Cache generated data per (regime, seed) so the two strategies see identical paths.
_cache = {}
def _data(regime, seed):
    key = (regime, seed)
    if key not in _cache:
        tp, qp, *_ = synval.generate(regime, seed, fill_model="exponential")
        _cache[key] = DataLoader().load_coinapi(tp, qp)
    return _cache[key]


def _run(strat, regime, seed):
    trades, quotes = _data(regime, seed)
    om = OrderManager(maker_fee=0.0, latency=0.0, queue_model="none")
    ms = MarketState(vol_window=120, arrival_window=60, ewma_alpha=0.9)
    bt = Backtest(strat, market_state=ms, order_manager=om, requote_on_fill=True,
                  requote_interval=0.1, tolerance_ticks=0.5, tick_size=TICK, verbose=False)
    res = bt.run(trades, quotes)
    m = res.metrics
    half_t = float(m.get("avg_spread_bps", 0.0)) / 1e4 * V0 / TICK / 2
    return float(m.get("total_pnl", 0.0)), int(m.get("total_fills", 0)), half_t


def make_as(regime, gamma):
    return TrueSigmaAS(
        true_sigma_frac=TRUE_SIGMA_DOLLAR[regime] / V0, true_kappa_frac=KAPPA_FRAC,
        gamma=gamma, T=T_HORIZON, order_size=ORDER_SIZE, min_spread_bps=0.0,
        max_inventory=MAX_INV, tick_size=TICK, kappa_as_min=0.0)


def make_glft(regime, gamma):
    return TrueSigmaGLFT(
        true_sigma_frac=TRUE_SIGMA_DOLLAR[regime] / V0, gamma=gamma, A=A_RATE,
        kappa=KAPPA_DOLLAR, order_size=ORDER_SIZE, min_spread_bps=0.0,
        max_inventory=MAX_INV, tick_size=TICK, kappa_from_stats=False)


def sweep(name, make_fn, gammas):
    print(f"\n{'#'*78}\n# {name}  (true σ injected; {N_SEEDS} seeds/cell)\n{'#'*78}")
    rows = []
    for regime in ["constant", "brownian", "brownian_medvol", "brownian_highvol"]:
        print(f"\n  REGIME {regime}  (σ_$={TRUE_SIGMA_DOLLAR[regime]})")
        print(f"    {'γ':>6} | {'mean PnL':>9} | {'std':>7} | {'days>0':>6} | "
              f"{'mean fills':>10} | {'half-spr(t)':>11}")
        for g in gammas:
            strat_runs = [_run(make_fn(regime, g), regime, s) for s in range(N_SEEDS)]
            p = np.array([r[0] for r in strat_runs])
            f = np.mean([r[1] for r in strat_runs])
            h = np.mean([r[2] for r in strat_runs])
            row = {"strategy": name, "regime": regime, "gamma": g,
                   "mean_pnl": round(float(p.mean()), 2), "std_pnl": round(float(p.std()), 2),
                   "days_pos_pct": round(float((p > 0).mean() * 100), 0),
                   "mean_fills": round(float(f), 0), "half_spread_ticks": round(float(h), 2)}
            rows.append(row)
            print(f"    {g:>6} | {row['mean_pnl']:>9.1f} | {row['std_pnl']:>7.1f} | "
                  f"{row['days_pos_pct']:>5.0f}% | {row['mean_fills']:>10.0f} | "
                  f"{row['half_spread_ticks']:>11.2f}")
    return rows


def main():
    RES.mkdir(parents=True, exist_ok=True)
    out = []
    out += sweep("Avellaneda-Stoikov", make_as,   [0.1, 1.0, 10.0])
    out += sweep("GLFT (ergodic)",     make_glft, [10.0, 50.0, 100.0])
    with open(RES / "as_glft_validation.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved -> {RES / 'as_glft_validation.json'}")
    print("\nReading the result: a strategy that widens its half-spread with σ should")
    print("stay positive in ALL regimes. The high-vol regime is the discriminator —")
    print("a fixed 2-tick quoter loses ~$900 there (short-gamma inventory cost); the")
    print("vol-appropriate width (~8t) is the profitable zone.")


if __name__ == "__main__":
    main()
