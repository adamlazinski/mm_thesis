# Codebase State — HFT Market Making Thesis
_Last updated: 2026-06-12 — see "Current Status" for what supersedes the 2026-05-16
diagnostics below_

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

The diagram above shows the core data-flow, not an exhaustive strategy inventory — the
strategy and regime-filter set has grown substantially since (e.g. `forecast_as.py`,
`avallenda2.py`, and ~10 filter variants in `extensions/regime_detection.py`).

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

> This is the special case of a general law: Contribution 33 (`thesis_contributions.md`) shows
> κ is pinned to σ by zero-profit (`κ_eq ≈ √A/σ_$`), so any fixed-κ model — not just GLFT — is
> calibrated to the wrong equilibrium once σ moves. The "momentum plateau" above is what that
> mismatch looks like on BTC specifically.

---

## Current Status (2026-06-12)

The "three-pronged response" of 2026-05-16 (Options 1-3 below, exps 10-15) was the plan at
the time for fixing the calibration mismatch above. **None of exps 10-15 were ever run** —
the investigation took a different path and superseded this plan entirely. Kept here only as
a historical record of the abandoned plan; do not run these configs expecting them to be
current.

<details>
<summary>Abandoned plan (exps 10-15, never run)</summary>

- **Option 1 — properly calibrated GLFT** (exps 10/11): kappa=31.0 (correct dollar units),
  γ=31 (κ/γ=1), A_liq=22, min_spread_bps=0. Exp 11 adds RegimeFilter.
- **Option 2 — kappa/gamma/A as hyperparameters**: random search over
  `experiments/08_shifted_glft/search_config.json`.
- **Option 3 — Vol-Inventory spread** (exps 12-15): `VolInventoryMarketMaker`
  (`hft_market_maker/strategies/vol_inventory.py`), `half_spread = alpha * sigma_dollar *
  sqrt(quote_freq)`, no kappa / no exponential fill model. Exps 12-13 plain/regime, 14-15 a
  wider variant (α=0.3, tolerance=10).

</details>

### What actually happened instead

Rather than search for a calibration that escapes the momentum plateau, the project asked
*why* every calibration lands there — and generalized the answer (C33): κ is pinned to σ by
zero-profit, so it isn't a free knob to search over. From there the investigation moved to
testing whether *any* strategy (classical or RL) profits honestly, which led to the
queue-priority verdict (C30) as the central thesis result.

The authoritative sources for where the project stands now:

- **`thesis_contributions.md`** — the full numbered contribution log (C1–C37). C30 is the
  central result; C33 generalizes it into a zero-profit equilibrium law; C35 frames MM as a
  written straddle; C36 closes the cross-venue (spot↔perp) escape route; C37 maps the
  latency-tolerant corner of the *curable* (Layer-1) part of the problem.
- **`thesis_conclusions.md`** — the synthesis chapter: headline result, evidentiary chain,
  and limitations/further work, written for direct use in the thesis.
- **`hypotheses.md`** — the hypothesis register (sections A–G + meta-hypothesis), tracking
  confirmed/refuted/nuanced/pending status for every claim tested.

### Genuinely open items

- BTC perp data re-pull (CoinAPI trades endpoint mislabeled) — needed for the C36 BTC
  cross-asset symmetry check. User-side action, not yet done.
- Two small untested threads in `hypotheses.md` §F: whether a lower perp fee tier makes the
  taker viable (reasoned "likely no" but untested), and funding rate as a queue-independent
  carry return (a different strategy class, not market making).
