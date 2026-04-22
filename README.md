# HFT Market Making Framework

A research-grade, event-driven market making simulator built for a Master's thesis
exploring the Avellaneda-Stoikov model and extensions on BTC/USDT tick data.

---

## Quick Start

### 1. Install dependencies
```bash
pip install numpy pandas pyarrow matplotlib plotly statsmodels scipy scikit-learn xgboost
```

### 2. Clone and set up
```bash
git clone https://github.com/adamlazinski/master.git master2
cd master2
```

### 3. Get data
The framework expects CoinAPI-format parquet files in `data/real/`. Each day needs two files:
```
data/real/trades_BTC_2025-05-13.parquet
data/real/quotes_BTC_2025-05-13.parquet
```
CoinAPI provides these directly when you subscribe to tick data for `BINANCE_SPOT_BTC_USDT`.
Alternatively generate synthetic data for a quick sanity check (see Synthetic Data below).

### 4. Run your first backtest
Copy the template config and edit the date range and output directory:
```bash
cp experiments/01_baseline_pure_as/config.json experiments/my_first_run/config.json
```

Edit `config.json` to point at your data and dates, then:
```bash
python scripts/run_daily.py --config experiments/my_first_run/config.json
```

Results land in `experiments/my_first_run/results/` — one `_metrics.json` and
one `_view.parquet` per day, plus a rolling `summary.csv`.

### 5. Inspect results
```bash
python scripts/run_daily.py --config experiments/my_first_run/config.json --aggregate
```

Or load the view parquet directly:
```python
import pandas as pd
df = pd.read_parquet("experiments/my_first_run/results/2025-05-13_view.parquet")
print(df[["close", "pnl", "inv", "spread_bps"]].describe())
```

### 6. Find better parameters
Create a search config and run:
```bash
python scripts/random_search.py --config experiments/my_first_run/search_config.json
```

Results are ranked by score (default: mean daily PnL) in a CSV. Take the top
row params and plug them back into your run config.

---

## Synthetic Data

If you don't have real tick data, generate synthetic BTC-like data for validation:

```python
import numpy as np
import pandas as pd

def generate_synthetic(n_seconds=86400, mid=102000., sigma=0.000029,
                       autocorr=-0.05, trade_rate=44., quote_rate=8.,
                       spread=0.5, seed=42):
    rng = np.random.default_rng(seed)
    dt = 1.0 / quote_rate
    n_q = int(n_seconds * quote_rate)
    sig = sigma * np.sqrt(dt)
    rets = np.zeros(n_q)
    noise = rng.normal(0, sig, n_q)
    for i in range(1, n_q):
        rets[i] = autocorr * rets[i-1] + noise[i] * np.sqrt(1 - autocorr**2)
    mids = mid * np.exp(np.cumsum(rets))
    ts_q = np.arange(n_q) * dt

    quotes = pd.DataFrame({
        "time_exchange": ts_q, "time_coinapi": ts_q,
        "bid_price": mids - spread/2, "ask_price": mids + spread/2,
        "bid_size": rng.uniform(0.5, 2., n_q),
        "ask_size": rng.uniform(0.5, 2., n_q),
    })

    n_t = int(n_seconds * trade_rate)
    tt = np.sort(rng.uniform(0, n_seconds, n_t))
    idx = np.searchsorted(ts_q, tt).clip(0, n_q-1)
    sides = rng.choice(["buy", "sell"], n_t)
    prices = np.where(sides=="buy", mids[idx]+spread/2, mids[idx]-spread/2)

    trades = pd.DataFrame({
        "time_exchange": tt, "time_coinapi": tt,
        "price": prices, "size": rng.uniform(0.001, 0.05, n_t),
        "taker_side": sides,
    })
    return trades, quotes

trades, quotes = generate_synthetic(autocorr=-0.05)  # mean-reverting
trades.to_parquet("data/synthetic/trades_BTC_synthetic.parquet")
quotes.to_parquet("data/synthetic/quotes_BTC_synthetic.parquet")
```

Set `autocorr=-0.05` for a mean-reverting process where A-S should be profitable,
`autocorr=0.0` for a random walk, and `autocorr=+0.18` to replicate the BTC
momentum structure that causes adverse selection.

Rename the files to match a real date (`trades_BTC_2025-01-01.parquet`) and point
your config at `data/synthetic/` to run the backtest as normal.

---

## Key Parameters

| Parameter | What it does | Typical range |
|-----------|-------------|---------------|
| `gamma` | Risk aversion — controls how aggressively inventory skews quotes | 0.001–0.1 for BTC |
| `t_scaling` | Time horizon T in A-S formula — scales spread width | 1000–20000 |
| `quote_freq` | Requote interval in seconds — lower = more fills = more adverse selection | 0.3–20s |
| `latency` | Simulated order placement/cancel latency | 0.05–0.20s |
| `min_spread_bps` | Minimum quoted spread floor | 0.05–2.0 bps |
| `max_inventory` | Hard inventory limit in BTC — stops quoting beyond this | 0.01–0.1 |
| `vol_window` | Number of quote ticks for volatility estimation | 60–500 |
| `arrival_window` | Seconds of history for kappa (trade arrival rate) | 30–120s |

The most important interaction: `quote_freq` must be significantly larger than
`latency`. Your orders are only live for `quote_freq - latency` seconds per cycle.
If `quote_freq ≈ latency` you get essentially zero fills.

---

## Backtest Mechanics

The engine merges trades and quotes into a single chronological event stream.
Trades are processed before quotes at identical timestamps (fills before requotes).

**Fill condition:** a resting bid fills when a trade prints at or below the bid price,
regardless of aggressor side. This is appropriate for discontinuous trade series
where you cannot always determine who was the aggressor.

**Latency model:** submitted orders are matchable only after `timestamp + latency`.
Cancelled orders remain matchable until `timestamp + latency` — modelling the
cancel/fill race at the exchange.

**PnL accounting:** `total_pnl = cash + inventory × last_mid`. Cash is debited
on buys and credited on sells at fill price. Inventory is marked to market
continuously. With zero fees this is a clean measure of spread capture minus
adverse selection costs.

**Gap handling:** data gaps longer than `long_gap` seconds (default 30s) trigger
a position closure at last known mid and a market state reset. Gaps between
`short_gap` and `long_gap` seconds cancel orders and pause requoting briefly.

---

## Project Structure

```
master2/
├── hft_market_maker/               # Core library
│   ├── core/
│   │   ├── events.py               # TradeEvent, QuoteEvent data structures
│   │   ├── market_state.py         # Rolling microstructure stats (σ, κ, OFI, momentum)
│   │   ├── order_manager.py        # Order lifecycle, fill simulation, P&L accounting
│   │   └── vol_guardrail.py        # Volatility-based risk manager
│   ├── strategies/
│   │   ├── avellaneda_stoikov.py   # Pure A-S baseline
│   │   └── aggressiveness.py       # OFI, momentum, urgency extensions
│   │       ├── OFIAsymmetricAS     # Asymmetric quoting from order flow
│   │       ├── InventoryUrgencyAS  # Exponential inventory penalty
│   │       ├── RuleBasedAggressiveness
│   │       └── FullAggressivenessAS (all combined via MRO)
│   ├── extensions/
│   │   ├── regime_detection.py     # Hurst + vol + OFI regime classifier
│   │   └── reinforcement_learning.py  # TabularQLearning, DQNMarketMaker
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
├── experiments/                    # One folder per experiment
│   ├── 01_baseline_pure_as/
│   │   ├── config.json             # Exact params used
│   │   └── results/                # Per-day outputs + summary.csv
│   ├── 02_ofi_asymmetric/
│   ├── 03_ofi_momentum/
│   ├── 04_requote_sweep/
│   ├── 05_synthetic_validation/
│   └── 06_ml_kappa/
│
├── data/
│   ├── real/                       # BTC/USDT tick data (CoinAPI format)
│   └── synthetic/                  # Generated data for validation
│
├── search/                         # Random search CSV outputs
├── analysis/                       # Notebooks and figures
└── README.md
```

---

## Running Experiments

All runners are config-driven. Copy a template config, edit params, run.

### Daily backtest
```bash
python scripts/run_daily.py --config experiments/01_baseline_pure_as/config.json
```

### Aggregate results
```bash
python scripts/run_daily.py --config experiments/01_baseline_pure_as/config.json --aggregate
```

### Random parameter search
```bash
python scripts/random_search.py --config experiments/01_baseline_pure_as/search_config.json
```

---

## Config Format

### run_daily config
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

    "guardrail":      false,
    "notes":          "baseline pure A-S"
}
```

### random_search config
```json
{
    "data_dir":  "data/real",
    "start":     "2025-05-13",
    "end":       "2025-05-17",
    "output":    "search/01_baseline_search.csv",
    "strategy":  "pure_as",

    "fixed": {
        "latency":        0.1,
        "quote_freq":     0.5,
        "min_spread_bps": 0.05,
        "max_inventory":  0.02,
        "vol_window":     120,
        "arrival_window": 60
    },

    "search": {
        "gamma":     ["log_uniform", 0.001, 0.015],
        "t_scaling": ["log_uniform", 4000, 18000]
    },

    "scoring": {
        "metric":        "mean_pnl",
        "min_fills":     10,
        "min_fill_rate": 0.001
    },

    "n_trials":  100,
    "n_workers": 7
}
```

---

## Data Format (CoinAPI)

### Trades parquet
```
time_exchange, time_coinapi, price, size, taker_side
```

### Quotes parquet
```
time_exchange, time_coinapi, bid_price, bid_size, ask_price, ask_size
```

---

## Strategy Overview

### Pure Avellaneda-Stoikov (`pure_as`)
Closed-form optimal market making. Quotes symmetrically around a reservation price
that skews with inventory.

- Reservation price: `r = mid - inventory × γ × σ² × T`
- Optimal spread: `δ* = γ × σ² × T + (2/γ) × ln(1 + γ/κ)`

Key finding: on BTC/USDT the σ² term is ~8.4e-10, making the inventory skew
negligible at standard gamma values. Gamma must be scaled to O(10-100) for
meaningful skew.

### OFI Asymmetric (`OFI`)
Extends A-S with order flow imbalance signal. When buy pressure is high,
raises both quotes and widens the ask. When sell pressure is high, lowers
both quotes and widens the bid.

### Full Aggressiveness (`aggressiveness`)
Combines OFI asymmetry + dynamic gamma from volatility/OFI signals +
exponential inventory urgency via Python MRO.

---

## Key Findings So Far

**Adverse selection at 300ms:** BTC/USDT return autocorrelation at the 300ms
horizon is ~0.18 — the exact requote frequency. This means fills are
systematically adverse: price continues against you after each fill with 59%
probability. Vanilla A-S is structurally unprofitable at this frequency.

**Autocorrelation decay:** The momentum signal decays to ~0 by 20s. Requoting
at 5-20s eliminates the adverse selection from momentum but requires wider
spreads to compensate for longer exposure windows.

**Minimum spread scaling:** Theoretically correct minimum spread for a given
exposure window is `2 × σ × sqrt(exposure_window)`. This should scale with
requote interval in any sweep.

**Gamma calibration:** With σ per-second ~2.9e-5, meaningful inventory skew
requires gamma ~30-100, not the O(0.1) values used in equity A-S implementations.

**Fill logic:** Fill condition is price-based only (no aggressor side check),
since trade series may be discontinuous. A trade at price P with your bid at
P+ε means you were filled regardless of who was the aggressor.

---

## Planned Extensions

- Requote interval sweep with theoretically scaled spreads
- Momentum filter integrated into OFI asymmetric quoting
- Classical regime-based kappa estimation (curve fitting per vol quartile)
- ML kappa estimation (XGBoost on fill probability curve from trade history)
- Supervised direction prediction as reservation price signal
- Reinforcement learning (tabular Q and DQN already scaffolded)
- Multi-level ladder quoting

---

## References

- Avellaneda, M. & Stoikov, S. (2008). *High-frequency trading in a limit order book.*
  Quantitative Finance, 8(3), 217–224.
- Cartea, Á., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency Trading.*
  Cambridge University Press.
- Spooner, T. et al. (2018). *Market Making via Reinforcement Learning.* AAMAS 2018.
- Ho, T. & Stoll, H. (1981). *Optimal dealer pricing under transactions and return uncertainty.*
  Journal of Financial Economics, 9(1), 47–73.
- Glosten, L. & Milgrom, P. (1985). *Bid, ask and transaction prices in a specialist market
  with heterogeneously informed traders.* Journal of Financial Economics, 14(1), 71–100.