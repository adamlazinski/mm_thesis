# Codebase State — HFT Market Making Thesis
_Last updated: 2026-05-16_

---

## What the project does

Event-driven backtesting framework for Avellaneda-Stoikov (A-S) and GLFT market making on BTC/USDT
tick data (CoinAPI, Binance Spot, May 2025, ~4.2M events/day). The core loop merges trade and quote
events into a chronological stream, updates microstructure state, asks the strategy for optimal
bid/ask prices, manages resting limit orders with a latency model, and tracks mark-to-market PnL.

---

## Architecture

```
DataLoader  →  [TradeEvent | QuoteEvent]  →  Backtest.run()
                                                  │
                                          ┌───────┴───────┐
                                    MarketState       OrderManager
                                    (sigma, kappa,    (latency model,
                                     OFI, momentum,   fill simulation,
                                     KappaEstimator)  PnL accounting)
                                          │
                                     Strategy.compute_quotes()
                                     ├── AvellanedaStoikov
                                     ├── GLFTMarketMaker
                                     ├── ShiftedGLFTMarketMaker   ─┐
                                     ├── VolInventoryMarketMaker  ─┤─ RegimeFilter (wrapper)
                                     ├── OFIAsymmetricAS           ┘
                                     └── FullAggressivenessAS
                                               └── RegimeAwareAS (wrapper)
```

**Hot path:** ~4 min per full day. `_active` dict (≤2 live orders) keeps fill checks O(1).
**Hysteresis:** skip cancel+resubmit if both quotes move less than `tolerance_ticks` from live
prices (default 0.5 ticks). Reduces churn — typically 1-4% of recomputes trigger a real requote.
**Gap handling:** `>30s` gaps close inventory at last mid and reset `MarketState`; `2-30s` gaps
cancel orders and pause requoting.

---

## GLFT Diagnostic Findings (2026-05-16)

Running the formula analytically across the real sigma distribution from a full-day backtest
of experiment 08 revealed three issues:

### 1. KappaEstimator stuck at prior
`A_hat = 2.0` (initial prior) all day — the `min_fills=50` threshold inside `KappaEstimator`
is never met. With hysteresis reducing real requotes to ~1-4%, actual MM fills are sparse. The
live `kappa_as` and `A_hat` used by GLFT's `kappa_from_stats=True` path are therefore always
at prior values, not from real calibration.

### 2. Fundamental structural mismatch: GLFT spread always in the momentum plateau

The GLFT ergodic half-spread formula (at κ/γ=1, which gives the most favourable parameter
regime) simplifies to approximately σ_dollar / √A. On BTC:
- σ_dollar = σ × mid ≈ $3.0/√s (median)
- A ≈ 22 trades/sec per side
- → half_spread ≈ $3.0 / √22 ≈ **$0.64 = 64 ticks**

The survival analysis shows a momentum plateau above 1.5 ticks: fill rate is 73% (invariant to
spread) beyond that threshold. The GLFT optimal spread is always ~40–200 ticks — deep in this
plateau. **To get sub-1.5-tick half-spreads you would need A ≈ 20,000 trades/sec; actual BTC
has 22.** No realistic parameter choice escapes this.

| Config scenario | half_spread | κ/γ | Power term | Fill prob/0.5s |
|---|---|---|---|---|
| Exp 08 (kappa=4.455 as 1/$, γ=100) | 229 ticks | 0.045 | 1.05 | 28% |
| kappa=445.5/$ (= 4.455/tick), γ=100 | 2276 ticks | 4.455 | 10452 | 0% |
| Offline calib (kappa=31/$, γ=31, A=22) | 48 ticks | 1.0 | 4.0 | 82% |
| HQ-window (kappa=185/$, γ=185, A=22) | 46 ticks | 1.0 | 4.0 | 83% |
| κ/γ=1, A=44 | 39 ticks | 1.0 | 4.0 | 86% |

Every calibration gives a spread in the momentum plateau. Properly calibrated GLFT produces
even more fills (82% fill rate vs 28%) because the spread is tighter.

### 3. min_spread_bps floor was sometimes the binding constraint

The 0.5 bps floor = $2.57 half-spread (257 ticks) overrides the formula in ~58% of quote
cycles (low-sigma periods). At high sigma the formula dominates and produces much wider spreads.
Either way all fills are in the momentum plateau. The min floor is not the root cause — even
without it the formula gives 40+ ticks.

**Conclusion:** GLFT's model structure (exponential fill intensity with realistic A) produces
spreads that are always adversely selected on BTC. This is a thesis-worthy finding: the model's
implicit assumptions about order arrival rates are calibrated to equity markets, not crypto.

---

## Three-pronged response (implemented 2026-05-16)

### Option 1 — Properly calibrated GLFT (academic, demonstrates the mismatch)

Experiments 10 and 11. kappa=31.0 (correct dollar units, from offline calibration 0.31/tick ÷
$0.01/tick), γ=31 (so κ/γ=1), A_liq=22 (realistic per-side rate), min_spread_bps=0 (formula
dominates). Expected half_spread ~$0.48 = 48 ticks at median vol — theoretically grounded but
still in the momentum plateau. Exp 11 adds RegimeFilter to test whether stopping in bad regimes
is sufficient to rescue GLFT. The regime filter is the thesis claim: "GLFT + filter is the
solution to the structural mismatch."

### Option 2 — Kappa/gamma/A as hyperparameters (data-driven search)

Search config at `experiments/08_shifted_glft/search_config.json`. Searches kappa ∈ [1, 400],
gamma ∈ [0.5, 500], A_liq ∈ [1, 100], A_mom ∈ [0, 10], min_spread_bps ∈ [0.05, 5] using
random search on one day. Scores by `mm_only_pnl` (excludes gap closures). Will reveal whether
any parameter combination works empirically, even if it lacks clean economic justification.

Run: `python scripts/random_search.py --config experiments/08_shifted_glft/search_config.json`

### Option 3 — Vol-Inventory spread (no exponential fill model)

New strategy `VolInventoryMarketMaker` (`hft_market_maker/strategies/vol_inventory.py`).
Formula:
```
half_spread  = alpha * sigma_dollar * sqrt(quote_freq)
reservation  = mid - q_norm * gamma_inv * half_spread
```
where `q_norm = inventory / max_inventory`. Parameters: alpha (spread size in sigma multiples),
gamma_inv (inventory skew strength). No kappa, no T-scaling, no exponential fill model.

Economic interpretation: alpha=0.14 at median vol gives ~30-tick half-spread (the break-even
adverse selection compensation derived from the momentum autocorrelation of 0.18 at 300ms).

Experiments 12 (plain) and 13 (with RegimeFilter). Search config at
`experiments/12_vol_inventory/search_config.json` covers alpha ∈ [0.01, 2.0] and
gamma_inv ∈ [0.1, 10.0].

Run: `python scripts/random_search.py --config experiments/12_vol_inventory/search_config.json`

---

## Experiment summary

| # | Strategy | Key params | Status | Notes |
|---|---|---|---|---|
| 01 | pure_as | γ=0.086, T=100 | 11 days done | Best so far, -$112 total |
| 07 | glft | κ=1.5, γ=1, A=live | 1 day only | Not extended |
| 08 | shifted_glft | κ=4.455, γ=100, A_liq=5 | 11 days done | -$2313 total, ~15k fills/day |
| 09 | shifted_glft_regime | same + RegimeFilter | 11 days done | -$737 total, ~5k fills/day |
| 10 | shifted_glft (calibrated) | κ=31, γ=31, A=22 | not run | Option 1, proper units |
| 11 | shifted_glft_regime (calibrated) | same + RegimeFilter | not run | Option 1 + filter |
| 12 | vol_inventory | α=0.14, γ_inv=1.5 | not run | Option 3 |
| 13 | vol_inventory_regime | same + RegimeFilter | not run | Option 3 + filter |

Ablation table covers experiments 01, 08, 09 and can be extended to 10–13:
```bash
source .venv/bin/activate && python scripts/ablation_table.py
```

---

## Running new experiments

```bash
source .venv/bin/activate

# Option 1 — properly calibrated GLFT
python scripts/run_daily.py --config experiments/10_glft_calibrated/config.json
python scripts/run_daily.py --config experiments/11_glft_calibrated_regime/config.json

# Option 2 — hyperparameter search (ShiftedGLFT)
python scripts/random_search.py --config experiments/08_shifted_glft/search_config.json

# Option 3 — vol-inventory strategy
python scripts/run_daily.py --config experiments/12_vol_inventory/config.json
python scripts/run_daily.py --config experiments/13_vol_inventory_regime/config.json

# Option 3 search
python scripts/random_search.py --config experiments/12_vol_inventory/search_config.json
```

---

## Open issues

1. **KappaEstimator never fires** — `min_fills=50` threshold too high given hysteresis.
   Consider lowering to 20 or removing the fill-count gate for GLFT experiments where
   `kappa_from_stats=False` anyway (the estimator runs but the strategy ignores it).

2. **A-S t_scaling=100** — changed from 9702 in the last session. Verify this is intended;
   T=100 gives a much tighter spread than T=9702.

3. **ablation_table.py hardcoded to exps 01/08/09** — update to include 10–13 after runs.

4. **RegimeFilter activity rate not logged** — useful metric for thesis. Can be estimated
   from fill-count ratio (base vs regime) but should be tracked explicitly.
