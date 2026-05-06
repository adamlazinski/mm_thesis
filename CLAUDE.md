# CLAUDE.md — HFT Market Making Research Project

This file gives Claude Code the context needed to work on this project effectively.
Read it fully before making any changes.

---

## Project Overview

Master's thesis implementing and extending the Avellaneda-Stoikov (A-S) and
Guéant-Lehalle-Fernández-Tapia (GLFT) market making models on BTC/USDT tick data
from CoinAPI (Binance Spot). The goal is profitable backtested market making with
empirically grounded parameter calibration.

**GitHub:** https://github.com/adamlazinski/master
**Data:** CoinAPI BTC/USDT tick data, May 2025 (12 days) and April 2026 (2 days)

---

## Project Structure

```
master2/
├── hft_market_maker/               # Core library — the main package
│   ├── core/
│   │   ├── events.py               # TradeEvent, QuoteEvent data structures
│   │   ├── market_state.py         # Rolling microstructure stats (sigma, kappa, OFI, momentum)
│   │   ├── order_manager.py        # Order lifecycle, fill simulation, P&L accounting
│   │   ├── vol_guardrail.py        # Volatility-based risk manager
│   │   ├── kappa_estimator.py      # Rolling Poisson MLE kappa estimator
│   │   └── fill_analysis.py        # Shared fill curve / survival functions for notebooks
│   ├── strategies/
│   │   ├── avellaneda_stoikov.py   # Pure A-S baseline
│   │   ├── aggressiveness.py       # OFI, momentum, urgency extensions
│   │   │   ├── OFIAsymmetricAS
│   │   │   ├── InventoryUrgencyAS
│   │   │   ├── RuleBasedAggressiveness
│   │   │   └── FullAggressivenessAS
│   │   ├── glft.py                 # GLFT ergodic market maker
│   │   └── shifted_glft.py         # GLFT with two-component fill model
│   ├── extensions/
│   │   ├── regime_detection.py     # Hurst + vol + OFI regime classifier
│   │   └── reinforcement_learning.py
│   ├── data/
│   │   └── loader.py               # CoinAPI parquet loader
│   └── backtest.py                 # Event-driven backtest engine
│
├── scripts/
│   ├── run_daily.py                # Config-driven daily backtest runner
│   ├── random_search.py            # Config-driven random parameter search
│   └── viz.py                      # Multi-day plotting utilities
│
├── ml/
│   ├── estimate_kappa_ml.py        # XGBoost fill probability / kappa estimator
│   └── models/                     # Trained model artifacts (.pkl)
│
├── experiments/                    # One folder per experiment — each has config.json + results/
│   ├── 01_baseline_pure_as/
│   ├── 02_ofi_asymmetric/
│   ├── 03_ofi_momentum/
│   ├── 04_requote_sweep/
│   ├── 05_synthetic_validation/
│   └── 06_ml_kappa/
│
├── data/
│   ├── real/                       # BTC/USDT CoinAPI parquet files
│   └── synthetic/                  # Generated data for model validation
│
├── analysis/                       # Jupyter notebooks + output figures
│   ├── kappa_analysis.ipynb        # Kappa estimation (Approaches A and B)
│   ├── shifted_check.ipynb         # Shifted exponential model analysis
│   └── survival_analysis.ipynb     # Survival/hazard estimation notebook
│
├── search/                         # Random search CSV outputs
├── thesis_contributions.md         # Running log of thesis contributions
└── README.md
```

---

## Running the Code

Always run from `master2/` root:

```bash
# Daily backtest
python scripts/run_daily.py --config experiments/01_baseline_pure_as/config.json

# Aggregate results
python scripts/run_daily.py --config experiments/01_baseline_pure_as/config.json --aggregate

# Random parameter search
python scripts/random_search.py --config experiments/01_baseline_pure_as/search_config.json
```

**Python environment:** `.venv` — always activate before running.

---

## Data Format (CoinAPI)

```
trades parquet: time_exchange, time_coinapi, price, size, taker_side
quotes parquet: time_exchange, time_coinapi, bid_price, bid_size, ask_price, ask_size
```

Tick size: $0.01. Mid price is always at X.5 cents since market spread is almost always 1 tick.

---

## Config Format

All experiments are driven by `config.json`. Key fields:

```json
{
    "data_dir":       "data/real",
    "start":          "2025-05-13",
    "end":            "2025-05-20",
    "output_dir":     "experiments/01_baseline_pure_as/results",
    "strategy":       "pure_as",
    "gamma":          0.086,
    "t_scaling":      9702.0,
    "order_size":     0.001,
    "min_spread_bps": 0.05,
    "max_inventory":  0.02,
    "maker_fee":      0.0,
    "latency":        0.1,
    "quote_freq":     0.5,
    "vol_window":     120,
    "arrival_window": 60,
    "ewma_alpha":     0.9,
    "guardrail":      false
}
```

Available strategies: `pure_as`, `OFI`, `aggressiveness`, `regime_aware`, `tabular_rl`, `dqn`, `glft`, `shifted_glft`

---

## Key Architecture Decisions

**Fill condition:** Price-only (no aggressor side check). A trade at price P fills a
resting bid at P+ε regardless of who was the aggressor. Correct for discontinuous trade series.

**Latency model:** `active_from = timestamp + latency`, `cancel_from = timestamp + latency`.
Exposure window = `quote_interval` exactly (cancel latency extends window by same amount
activation latency delays it). Always pass timestamp to `cancel_all(timestamp)`.

**PnL:** `total_pnl = cash + inventory × last_mid`. Mark-to-market continuously.

**Order manager:** Split into `_active` (≤2 live orders) and `_archive` (dead orders).
Hot path only iterates `_active`. Performance: ~4 minutes per full day (4.2M events).

**Gap handling:** Long gaps (>30s) close inventory at last mid and reset market state.
Short gaps (2-30s) cancel orders and pause requoting.

---

## Key Empirical Findings

**Autocorrelation:** BTC/USDT 1-second return autocorrelation ≈ 0.15 at lag 1,
300ms autocorrelation ≈ 0.18. At 20s horizon autocorrelation ≈ 0. The momentum
decay horizon is ~5-10 seconds. Quoting at 300ms = quoting at peak momentum.

**Gamma calibration:** With sigma ≈ 2.9e-5/sec, sigma² ≈ 8.4e-10. Standard A-S
gamma values (0.1) produce negligible inventory skew on BTC. Need gamma ≈ 30-100
for meaningful dollar skew. GLFT uses dollar volatility: sigma_dollar = sigma × mid.

**Kappa (fill sensitivity):** Two estimation approaches implemented:
- Approach A: unconditional market trade distance from mid
- Approach B: execution-aware simulation (conditioned on latency and quote_interval)
Approach B gives kappa ≈ 0.31/tick full-day. High-quality windows (R²>0.8) give kappa ≈ 1.85/tick.

**Two-component fill model:** Empirical fill curve on BTC follows:
`λ(δ) = A_liq × exp(-κ × δ) + A_mom`
not pure exponential. A_mom ≈ 15% of total arrivals — fills invariant to spread distance
(momentum-driven). Fill probability is flat beyond 1.5 ticks (~73% regardless of spread).

**Survival analysis:** At δ=0.5 ticks: fill rate 99%, mean fill time 0.38s.
At δ≥1.5 ticks: fill rate ~73%, mean fill time 2.98s, constant across all distances.
Two distinct regimes: at-touch (liquidity-driven) and off-touch (momentum-driven).

**Hysteresis:** With 100ms recompute frequency and 0.5-tick tolerance, only 1-4%
of recompute steps trigger a requote. Effective order lifetime much longer than
the naive quote_interval assumption.

---

## Current Strategy Implementation State

**A-S (`avellaneda_stoikov.py`):**
- Reservation price: `r = mid - q × gamma × sigma² × T`
- Spread: `gamma × sigma² × T + (2/gamma) × ln(1 + gamma/kappa_scaled)`
- Uses `kappa_scaled = kappa × t_remaining` — this is a known miscalibration being addressed

**GLFT ergodic (`glft.py`):**
- Uses dollar volatility correctly: `sigma_dollar = sigma × mid`
- Reservation price: `r = mid - q × gamma × sigma_dollar² / (2 × A × kappa)`
- Spread: `(1/kappa) × ln(1 + kappa/gamma) + (1/2) × sqrt(sigma_dollar² × gamma / (2Ak) × (1+k/g)^(1+k/g))`
- kappa in 1/tick units (not 1/dollar)

**Shifted GLFT (`shifted_glft.py`):**
- Two-component fill model: `A_liq × exp(-kappa × delta) + A_mom`
- `A_total = A_liq + A_mom` replaces A in all formulas
- Adverse selection term unchanged (only liquidity flow responds to spread)
- `mom_fraction = A_mom / A_total` = fraction of fills inevitably adverse

**OFI Asymmetric (`aggressiveness.py`):**
- Shifts both quotes in direction of OFI signal
- Widens the side facing informed flow
- Combined with momentum signal: `signal = 0.5 × ofi + 0.5 × momentum`

---

## Planned Next Steps

1. **Implement hysteresis/tolerance** in backtest engine — only cancel/reinsert when
   new optimal quote diverges by > tolerance from current
2. **Decouple recompute frequency from order lifetime** — recompute every 100ms,
   cancel only when tolerance exceeded
3. **Wire KappaEstimator** into backtest — call `on_quote_posted` and `on_fill`
4. **Survival-based kappa** — use hazard MLE instead of fixed-window simulation
5. **Ablation study** — pure_as → OFI → OFI+momentum → full_aggressiveness
6. **Synthetic data validation** — show strategy profitable on mean-reverting process
7. **ML direction signal** — supervised prediction of next 5s return as reservation price signal
8. **RL** — TabularQ and DQN already scaffolded in extensions/
9. **Multi-day analysis** — run across all 12 days, compute Sharpe, drawdown, win rate
10. **Ladder quoting** — extend single-order to multi-level

---

## Coding Conventions

- All runners are config-driven — no hardcoded params in scripts
- Every experiment has a `config.json` in its folder
- Results go in `experiments/<name>/results/` — one `_metrics.json` and `_view.parquet` per day
- Core library functions are pure — no global state
- Notebook shared functions live in `hft_market_maker/core/fill_analysis.py`
- Imports always use relative paths within the package (`.kappa_estimator` not `core.kappa_estimator`)
- Always activate `.venv` before running anything

---

## Dependencies

```bash
pip install numpy pandas pyarrow matplotlib plotly statsmodels scipy scikit-learn xgboost lifelines
```

---

## Notes for Claude Code

- The project root is `master2/` — always run commands from there
- Data files are large parquet files — never print them in full
- The `.venv` virtual environment contains all dependencies
- When modifying strategy classes, check that `compute_quotes` signature matches
  `(self, stats: MicrostructureStats, inventory, timestamp, t_remaining=None, **kwargs)`
- When adding new strategies, register them in `make_strategy()` in `scripts/run_daily.py`
- The `fill_analysis.py` module is shared between notebooks — changes there affect all analysis
- `thesis_contributions.md` is the running log of findings — update it when adding new results
