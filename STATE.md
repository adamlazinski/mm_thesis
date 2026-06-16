# Codebase State — HFT Market Making Thesis
_Last updated: 2026-06-16 (checkpoint after 10ms/LINK perp-signal arc, weekend engine work)_

---

## CHECKPOINT — 2026-06-16

### Last clean commit
`a8d18ae` — "Add thesis Chapters 1-3 drafts (Introduction, Theory, Data/Methodology)"
- thesis_contributions.md: C1–C38 committed
- thesis_theory.md, thesis_intro.md, thesis_data.md: initial chapter drafts
- Engine: taker-on-arrival fix already committed in `cafc7ae` (L2 queue model baseline)

### Weekend work (uncommitted — done, needs commit)

**Engine additions** (new strategy classes, not the bug fixes in `cafc7ae`):
- `hft_market_maker/strategies/forecast_as.py` (new): `ForecastAS` — A-S with XGBoost
  1-second mid-price direction overlay (`forecast_alpha × tick × signal` reservation shift)
- `TradeSpikeFilter` wrapper (halts quoting during 3× trade-rate spikes, cooldown period)
- `DailyLossLimit` wrapper
- `run_daily.py`: `forecast_as`, `pure_as_spike`, `forecast_as_spike` strategy names registered
- `order_manager.py`: per-fill markout tracking added (needed for exp75 / C44 section E)
- `fill_analysis.py`: calibration utilities, `fill_intensity_calibration.json` output
- `l2_features.py`: minor L2 queue feature improvements

**BTC experiments (all complete)**:
- `exp49_zero_latency` — BTC pure_as, Jun 11–15 2025, latency=0 vs 0.1s (price-only fills)
  Result: +$1.07/day (0ms) and +$0.24/day (0.1s) over 5 days — ARTIFACT REGIME (no queue_model)
- `exp50_forecast_as` — BTC ForecastAS OOS test, Jun 23–27 2025, 5 variants
  Result: XGBoost overlay adds nothing (vs baseline: -$0.22/day); spike filter alone halves
  loss (-$46.67 → -$22.56 over 5 days); all 5 variants net negative OOS

**Analytical/feasibility studies (all complete, written up as C31–C38 in thesis_contributions.md)**:
- `exp51_crossing_intensity` — LINK + BTC fill-curve analysis with L2 conditioning (C25-area)
- `exp52_link_classical_mm` — LINK Apr 2026, calibrated A-S 30-day run (feeds C28)
- `exp53_link_spread_sweep` — LINK spread-rule grid
- `exp54_link_perp_micro` — LINK spot↔perp microstructure
- `exp55_taker_feasibility` — BTC OBI taker, latency sweep 10ms–500ms (C31):
  OBI signal ~1 bps net (after 3.6bps fees) at 10ms, 100% days+ on JunJul2025 (30 days).
  XGBoost model trained: `ml/models/xgb_taker_h10.pkl`
- `exp56_lowfreq_mm` — LINK lowfreq MM, risk vs price requote policy (queue_model=l2)
- `exp57_deep_reversion` — BTC/LINK conditional reversion analysis (C32)
- `exp60_foresight_oracle` — LINK honest touch-quoter + perfect-foresight ceiling (C34):
  Causal ~$2/day; 10s foresight ~$24/day; queue artifact $45–58/day
- `exp63_shifted_glft_numerical` — BTC, HJB PDE two-component fill model (C38)
- `exp64_glft_calibrated` — BTC, GLFT with calibrated A/kappa baseline (C38 ablation)

### Today (this session, 2026-06-15/16 — uncommitted thesis text changes)

**LINK perp-signal / 10ms latency arc (C39–C44):**
- C39 (exp65): perp OBI/OFI cross-venue signal characterization — real but incremental
- C40 (exp66): perp_obi as skew signal under artifact engine — null in artifact regime
- C41 (exp67): perp toxicity spread-widening — null in artifact regime
- C42 (exp68): **MAJOR FINDING** — L2-honest 10ms/50ms rerun on LINK Apr 2026:
  - baseline: -$0.24/day (zero-profit equilibrium confirmed at 10ms)
  - **spot_obi skew alpha=1: +$22.32/day, 30/30 days+ (100%), taker_pct=0%**
  - obi/ret perp widening: null or worse
- C43 (exp71): BTC-PERP same grid — uniformly -$182/day, spot1 makes it WORSE (-$233/day).
  BTC fully arbitraged (relative tick ~70× smaller than LINK)
- C44 (exp69/70/72/74/75): C42 robustness pass — all 3 caveats resolved:
  - (A/B) queue_fraction flat on [0.1, 0.7], cliff at 0 (artifact regime boundary)
  - (C) spread-rule axis inert (A-S formula collapses to constant at these params)
  - (D) true optimum is **alpha≈4 at +$56.00/day, 100% days+**, not alpha=1
  - (E) per-fill markouts confirm fill-QUALITY mechanism:
    alpha=0: 54–63% adverse; alpha=1: 31–34%; **alpha=4: ~10% adverse**
  - Only caveat (d) open: OOS validation (all from same 30-day LINK Apr 2026 window)

**Theory addition:**
- `thesis_theory.md` §5: Guilbaud & Pham (2013) model added (3 paragraphs) — spread as
  finite Markov chain on tick multiples, `{B,B+}` priority control with `λ(B+,s)>λ(B,s)`,
  QVI/IDE system with no closed form; forward-links to C42/C44

**All changes written up in `thesis_contributions.md` (C39–C44) and `thesis_conclusions.md`**

### What is uncommitted (to commit next)
1. Engine additions: `forecast_as.py` (new), edits to `backtest.py`, `order_manager.py`,
   `fill_analysis.py`, `l2_features.py`, `market_state.py`, `loader.py`, `aggressiveness.py`,
   `avellaneda_stoikov.py`, `glft.py`, `scripts/run_daily.py`, `random_search.py`
2. New experiments: exp49, exp50, exp52–57, exp60, exp63, exp64 (results + configs)
3. Thesis text: C39–C44 additions to `thesis_contributions.md`, `thesis_conclusions.md`,
   `thesis_theory.md` §5 (Guilbaud-Pham)
4. Analysis artifacts: `analysis/fill_intensity_calibration.json`,
   `experiments/55_taker_feasibility/analysis/`, `experiments/57_deep_reversion/analysis/`,
   etc.

### Open threads
1. **C44 caveat (d) — OOS validation**: +$22.32/day (alpha=1) and +$56.00/day (alpha=4)
   both from same 30-day LINK Apr 2026 window. Need a held-out window (different month
   or different large-relative-tick asset). Natural next: rerun C42/44 on LINK Jun 2025.
2. **BTC taker exploration** (exp55 followup): XGBoost 1s direction model trained, ~1 bps
   net edge at 10ms OBI signal confirmed. Next: proper taker backtest or signal sweep.
3. **Uncommitted commit**: the entire body above needs a single commit.

---

_Historical STATE.md content below (kept for reference) — superseded by checkpoint above_

---

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
