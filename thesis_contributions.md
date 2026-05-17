# Thesis Contributions

Empirical and methodological contributions from the implementation and analysis of
Avellaneda-Stoikov and GLFT market making on BTC/USDT tick data (CoinAPI, Binance Spot,
May 2025 and April 2026).

---

## 1. Adverse Selection at the Requote Frequency

**Finding:** BTC/USDT return autocorrelation at the 300ms horizon — the exact requote
frequency of the baseline strategy — is approximately 0.18 at lag 1 and 0.08 at lag 2,
both statistically significant. At the 20-second horizon autocorrelation is indistinguishable
from zero.

**Implication:** A market maker requoting at 300ms operates at precisely the frequency where
momentum is strongest. Each fill is systematically adverse: after a bid fill, price continues
downward with approximately 59% probability (0.5 + 0.18/2). This is not parameter
miscalibration — it is a structural feature of BTC microstructure at that timescale.

**Evidence:** Round-trip analysis of backtest fills shows that losing round trips have
significantly shorter hold times than winning ones (94s vs 299s average), confirming
immediate adverse selection rather than slow inventory drift.

**Contribution:** Quantifies the relationship between requote frequency and adverse selection
on a major crypto venue. Demonstrates that the optimal requote interval lies between the
momentum decay horizon (~5s) and the inventory accumulation horizon, providing an empirically
grounded framework for requote frequency selection.

---

## 2. Requote Interval Sweep with Theoretically Scaled Spreads

**Finding:** PnL varies non-monotonically with requote interval. Too frequent = systematic
adverse selection from momentum. Too infrequent = inventory accumulation and stale quotes.

**Method:** Swept requote intervals from 0.3s to 60s with minimum spread scaled to the
theoretically correct level at each interval:

```
min_spread = 2 × sigma × sqrt(exposure_window)
```

where `exposure_window = requote_interval` (cancel latency extends the window by exactly
as much as activation latency delays it).

**Contribution:** Derives the theoretically correct minimum spread as a function of exposure
window and volatility. Shows that naive spread floors ignore the relationship between quoting
frequency and required adverse selection compensation.

---

## 3. A-S Gamma Miscalibration on BTC

**Finding:** The A-S inventory skew formula:

```
r = mid - inventory × gamma × sigma² × T
```

produces negligible skew on BTC at standard gamma values (e.g. gamma=0.1). With
sigma≈2.9e-5 per second, `sigma² = 8.4e-10` — squaring an already tiny number renders
the inventory penalty effectively zero for any practical gamma value used in the equity
market literature.

**Implication:** Gamma must be in the range 30-100 on BTC to produce dollar-meaningful
inventory skew. Papers calibrated to equity markets (Ho-Stoll, original A-S) use gamma≈0.1
which is approximately 400x too small for crypto at these volatility levels.

**Contribution:** Provides the correct gamma scaling for BTC and derives the minimum gamma
required to produce meaningful reservation price deviation:

```
gamma_min = target_skew_dollars × 2 × A × kappa / (sigma_dollar² × inventory)
```

---

## 4. Kappa Conflation in A-S and GLFT

**Finding:** Both A-S and GLFT use a parameter variously called kappa or lambda that conflates
two distinct quantities: (1) the baseline order arrival rate A (trades per second), and (2)
the price sensitivity of order flow kappa (how quickly fill probability decays with spread).

In the A-S literature kappa is typically proxied by total trade arrival rate (~44/sec on BTC).
This proxy produces spreads that are either negligibly small (when T is large) or unrealistically
wide (when T is small), with no stable calibration.

**Contribution:** Separates A and kappa estimation:
- A is estimated directly from the fill probability at the touch (δ=0.5 ticks)
- kappa is estimated by fitting the exponential decay to the fill curve beyond the touch
- Shows that kappa so estimated is regime-dependent and approximately follows a power law
  in dollar volatility: `kappa(σ_$) ∝ σ_$^(-b)` with b≈1

---

## 5. Execution-Aware Kappa Estimation

**Finding:** The standard approach to kappa estimation uses the unconditional distribution
of market trade distances from mid. This is an overestimate of fill sensitivity because it
includes trades that occur outside the market maker's exposure window.

**Method:** Proposed execution-aware simulation: at each requote interval (0.5s), place a
synthetic limit order and check whether any market trade during the exposure window
`[t + latency, t + quote_interval + latency]` would have filled it. Sweeping over spread
distances gives a fill rate curve conditioned on actual execution parameters.

**Finding:** Execution-aware kappa (Approach B) is approximately 5x higher than the
unconditional estimate (0.311 vs 0.065 on 2025-05-13), and produces a better fit (R²=0.46
vs 0.38). This makes intuitive sense: large price moves that produce trades far from mid
typically occur over timescales longer than the 0.5s exposure window and would not fill a
resting order.

**Contribution:** Introduces execution-aware kappa estimation as a calibration methodology
for market making strategies. Shows that standard kappa estimates significantly understate
fill sensitivity, leading to spreads that are too wide relative to the strategy's actual
execution.

---

## 6. Two-Component Fill Probability Model

**Finding:** Empirical fill probability on BTC/USDT does not follow the pure exponential
decay assumed by GLFT:

```
lambda(delta) = A × exp(-kappa × delta)     [GLFT assumption — incorrect]
```

Instead it follows a two-component structure:

```
lambda(delta) = A_liq × exp(-kappa × delta) + A_mom
```

Where:
- `A_liq × exp(-kappa × delta)` is the liquidity component — uninformed traders crossing
  the spread. This decays rapidly (kappa≈1.85/tick in good windows, halving every 0.37 ticks).
- `A_mom` is the momentum component — informed momentum traders moving price through multiple
  levels. This is invariant to spread distance and creates a flat floor in the fill curve.

**Evidence:** Even in the best-fitting 15-minute windows (R²>0.8), fill probability stabilises
at approximately 10% for spreads beyond 1.5 ticks rather than decaying to zero. Poor windows
show floors as high as 42%. The pure exponential cannot capture this structure.

**Implication:** `A_mom / (A_liq + A_mom)` is the fraction of fills that are inevitably
adverse regardless of spread width. The market maker cannot escape momentum adverse selection
by widening quotes — only liquidity-driven fills respond to spread choice.

**Contribution:** Proposes and fits the shifted exponential model. Derives the modified GLFT
ergodic solution under this fill intensity, showing that A in all formulas is replaced by
`A_total = A_liq + A_mom`, tightening the inventory skew while leaving the adverse selection
spread term unchanged.

---

## 7. Regime-Dependent Model Validity

**Finding:** The exponential fill model (and therefore GLFT) is only empirically valid during
approximately 12% of 15-minute windows in the dataset (34/276 windows with R²>0.8). These
windows are characterised by:
- Dollar volatility below σ_$≈3 $/√s
- Concentration in EU morning (06:00-11:00 UTC) and US evening (19:00-21:00 UTC) sessions
- High-quality windows yield kappa≈1.85/tick (vs 0.31 full-day average)

**Implication:** GLFT is not universally applicable on BTC. The Poisson exponential assumption
holds during calm, liquidity-driven periods but breaks down during momentum/trending regimes
when informed flow dominates.

**Contribution:** Proposes a regime filter for GLFT application: quote with the calibrated
model only when rolling volatility is below threshold and the exponential fit quality is
acceptable. Outside these windows, either pause quoting or widen spreads significantly to
account for elevated momentum flow.

---

## 8. Latency Model and Exposure Window

**Finding:** The standard backtest implementation of cancel latency (`cancel_all()` without
timestamp) effectively disables latency modelling for cancellations, as `cancel_from = 0 +
latency` is immediately effective for all Unix timestamps.

**Contribution:** Corrects the latency model to pass current timestamp to all cancel calls.
Derives the correct exposure window formula:

```
exposure_window = quote_interval
```

Cancel latency extends the live window by exactly as much as activation latency delays the
start, so the two effects cancel and exposure equals the requote interval exactly. This is
non-obvious and commonly misimplemented.

---

## 9. Fill Condition for Discontinuous Trade Series

**Finding:** Standard A-S fill models condition on aggressor side:
- Bid fills when a SELL trade arrives at price ≤ bid
- Ask fills when a BUY trade arrives at price ≥ ask

This is appropriate for continuous order book data but incorrect for CoinAPI trade series,
which may be discontinuous. A trade printing at $101,900 with a resting bid at $102,000 means
the market traded through that price level — the bid would have been filled regardless of
aggressor side.

**Contribution:** Implements price-only fill condition for discontinuous trade series and
quantifies the impact on fill rate and PnL relative to the side-conditioned model.

---

## 10. OFI and Momentum Integration

**Finding:** Order Flow Imbalance (OFI) and short-horizon price momentum (measured as
log return over a configurable window, normalised by expected sigma move) provide directional
signals that partially predict the direction of price moves after fills.

**Contribution:** Implements OFIAsymmetricAS — an extension of A-S that uses OFI and momentum
to asymmetrically skew quotes. When buy pressure is high, raises both quotes and widens the
ask. When sell pressure or downward momentum is detected, lowers both quotes and widens the
bid. Provides ablation study comparing: pure A-S → OFI asymmetric → OFI + momentum → full
aggressiveness stack.

---

## 11. GLFT Ergodic Solution Implementation and Sigma Units

**Finding:** The GLFT paper uses dollar volatility σ_$ = σ × S (arithmetic Brownian motion,
price in dollars) while market data provides log-return volatility σ (geometric Brownian
motion). Plugging log-return sigma directly into the GLFT formula produces inventory skew
that is 10,000x too small at BTC price levels.

**Contribution:** Implements the GLFT ergodic closed-form solution with correct unit
conversion: `sigma_dollar = sigma_log_return × mid_price`. Provides the first open-source
implementation of the GLFT ergodic solution calibrated to crypto tick data, with a
`ShiftedGLFTMarketMaker` class extending the framework to the two-component fill model.

---

## 12. Post-Fill Markout Analysis and Adverse Selection Quantification

**Finding:** By measuring the mid price 1 second after each fill and comparing to fill price,
we can directly quantify adverse selection per fill across strategies and regimes — a direct
replication of the metric used in Albers et al. 2025.

**Implementation:** Added `avg_markout_bps` and `pct_adverse_fills` to every backtest metrics
output. For a bid fill at price P and mid M one second later:

```
markout = (M - P) / P × 10000 bps
```

Positive = favorable (price moved up after buying). Negative = adverse selection.

**Findings on June 2025 data (all strategies):**
- 60–100% of fills are adversely selected
- Mean markout ranges from −1.4 bps to −12.6 bps depending on strategy and day
- Wider spreads do not eliminate adverse selection — they only reduce fill rate
- Jun 12 is the worst day: directional trending caused inventory to accumulate to the cap

**Contribution:** Provides an empirical adverse selection benchmark for BTC market making
that is directly comparable with academic literature. Confirms that the June 2025 regime
is structurally unfavorable for passive market making under all tested strategies.

---

## 13. Regime Contrast: May vs June 2025

**Finding:** Pure A-S is profitable on May 2025 (calmer, mean-reverting) but not on June
2025 (volatile, directional). Random search over gamma and T on May 13–15 found:

| gamma | T_scaling | Mean PnL/day | Fills/day |
|-------|-----------|--------------|-----------|
| 0.010 | 6535      | +$11.48      | 465       |
| 0.002 | 4278      | +$2.56       | 167       |
| 0.003 | 4094      | +$2.15       | 136       |

The same strategy on June 2025 produced a best result of −$4.89/day. This contrast is itself
a thesis contribution: it isolates regime as the primary determinant of market making
profitability, not model or parameter choice.

**Contribution:** Provides quantitative evidence that market making profitability on BTC is
highly regime-dependent. Characterises the May vs June 2025 contrast in terms of sigma,
autocorrelation, fill rate, and adverse selection metrics. Motivates the regime filter as a
necessary (not optional) component of any practical market making strategy on crypto.

---

## 14. OBI-Based Counter-Trade Strategy and Queue Limitation

**Finding:** Albers et al. 2025 ("The Market Maker's Dilemma") show that counter-trading
the instantaneous order book imbalance (OBI = (bid_size − ask_size)/(bid_size + ask_size))
achieves near-zero adverse selection (−0.058 bps markout) on BTC perpetuals. We replicated
this finding using `OBIDirectedFilter` — post ASK when OBI > threshold (buy pressure), post
BID when OBI < −threshold (sell pressure), suppress both when balanced.

**Implementation:** Added `stats.obi` (instantaneous top-of-book size imbalance) to
`MicrostructureStats`, distinct from the lagged 60s trade-flow `stats.ofi`. Implemented
`OBIDirectedFilter` wrapping any base strategy.

**Finding:** The OBI counter-trade strategy is unprofitable in our backtest (best: −$238/day
on June data). The mechanism requires queue position — the paper's orders fill during
reversals because they are at the front of the queue and only get hit when the expected move
doesn't materialise. Our fill model fills any order at the price level immediately, regardless
of queue depth, so the reversal-selection mechanism cannot operate.

**Contribution:** Identifies the queue position gap between the Albers et al. mechanism and
a standard backtest fill model. Validates the paper's core finding (adverse selection
asymmetry documented via markout analysis) while demonstrating that replication requires
LOB depth data not available in trade/quote tick feeds.

---

## Planned Extensions

- ML-based kappa estimation: XGBoost fill probability model conditioned on regime features
  (sigma, OFI, hour), extracting implied kappa as a function of market state
- Reinforcement learning for spread and skew control (TabularQ and DQN scaffolded)
- Multi-level ladder quoting extending the single-order framework
- Out-of-sample validation on April 2026 data after in-sample calibration on May 2025
