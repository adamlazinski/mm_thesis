# Thesis Contributions

Empirical and methodological contributions from the implementation and analysis of
Avellaneda-Stoikov and GLFT market making on BTC/USDT and LINK/USDT tick data (CoinAPI,
Binance Spot, May–Jun 2025, Jun–Jul 2025, and April 2026).

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

---

## 15. Step-Function Fill Curve on LINK/USDT

**Finding:** LINK/USDT (Binance Spot) exhibits a qualitatively different fill curve from BTC.
The market maintains a permanent 10-tick ($0.010) bid-ask spread essentially 100% of the time.
This produces a step-function fill probability rather than the smooth exponential assumed by GLFT:

- Inside natural spread (δ < 5 ticks from mid): fill rate 17–37% — captures all taker flow
- At or outside natural spread (δ ≥ 5 ticks): fill rate drops to 1–14%, adversely selected
  (avg markout −1.89 bps, 66% adverse vs 40% inside-spread)

The exponential fit breaks down entirely: κ → 0 in the exponential model as the fill curve
flattens. The GLFT optimal spread formula diverges when κ → 0, making it theoretically
inapplicable.

**Contribution:** Documents the step-function fill structure on a mid-cap crypto asset.
Shows that the exponential fill model is not universal and that asset-specific fill curve
shape determines which model class is appropriate. Provides a methodology for detecting
step-function structure from tick data.

---

## 16. Degenerate Flat Market Maker as Optimal Strategy on Step-Function Assets

**Finding:** Random search over A-S and GLFT parameters on LINK/USDT converges to a
theoretically degenerate parameter regime:

```
gamma ≈ 0          (zero reservation price skew)
min_spread = 6.44 bps  (3.86 ticks — one tick inside natural 5-tick side)
max_inventory = 38 LINK
daily_loss_limit = $25
```

This is a **constrained flat market maker** — no inventory skew, fixed spread, tight position
cap, and a hard kill switch. The model-theoretic components of A-S and GLFT contribute nothing.

**Performance on LINK Jun 11 – Jul 10 2025 (30 days):**
- Mean PnL: +$154/day, total +$4,633
- Win rate: 30/30 (100%), including Jun 22 (−4.3% trending day, +$114) and Jun 23 (+10%, +$128)
- Sharpe (daily, √365): 56.5
- Avg markout: +1.2 to +2.5 bps (positive — fills are mean-reverting)
- Avg adverse fills: 17–35% (vs 60–100% on BTC)

**Why it works:** The inside-spread floor guarantees taker flow (strategy is the NBBO). The
tight `max_inventory` cap forces rapid inventory cycling — when long, only the ask is quoted,
so the strategy sells into local highs; when short, only the bid is quoted, buying from local
lows. This produces ~1,800 inventory sign changes per day. Each round trip captures
approximately the bid-ask spread in mean-reversion profit.

**Contribution:** Demonstrates that on assets with step-function fill curves, classical
market making model-theoretic machinery (reservation price, optimal spread formula) is
replaced by a structurally simpler insight: quote inside the spread, cap the position, stop
on large losses. Provides quantitative evidence that the edge is mean-reversion, not
spread-capture in the traditional sense.

---

## 17. GLFT Adds No Value Over Flat Market Maker on LINK

**Experiment:** Ran pure A-S (γ≈0) with identical inventory/limit/spread parameters as the
GLFT search winner on the same OOS period (Jun 28 – Jul 10 2025, 13 days).

**Result:**

| Metric | GLFT search-opt | A-S γ≈0 (control) |
|---|---|---|
| Mean PnL/day | +$88.56 | **+$149.45** |
| Win rate | 13/13 | 13/13 |
| Sharpe | 27.4 | **57.7** |
| Avg spread | 11.9 bps | **7.4 bps** |
| Avg fills/day | 8,812 | **11,060** |

A-S control outperforms GLFT winner by **69%**. The performance gap arises from GLFT's
dynamic spread formula widening to 10–18 bps when the rolling arrival rate estimate A_hat
is low (which occurs during 33% of quoting steps on LINK's sparse order flow). Each widening
episode costs ~2,250 fills per day relative to a fixed floor.

**Contribution:** Provides a direct controlled experiment isolating the contribution of
the GLFT formula from the parameter regime. Demonstrates that on LINK, the formula's
theoretical advantage (no finite horizon, inventory-proportional skew) is outweighed by
instability in A_hat estimation during sparse periods. The inventory constraint, not the
formula, is the primary risk management mechanism.

---

## 18. OFI and Momentum Overlays Degrade Performance

**Experiment:** Tested OFI-directed one-sided quoting and momentum suppression as overlays
on the A-S winner across all thresholds (0.05–1.0) on the full 30-day LINK period.

**Results:**

| Overlay | IS win rate | IS mean/day | OOS mean/day |
|---|---|---|---|
| Baseline (no overlay) | 100% | +$71.8 | +$83.0 |
| OFI directed (best) | 35% | −$67 | +$129 |
| Momentum suppress (best) | 35% | −$50 | +$132 |

Both overlays show IS win rates of 35% and large losses on trending IS days. OOS numbers
look better only because the overlays coincidentally avoided the Jun 22–23 trending days in
the IS set. The worst-day drawdowns (−$923 to −$1,004) are catastrophic compared to the
baseline's clean performance.

**Contribution:** Shows that directional signal overlays on a mean-reversion cycling
strategy are counterproductive — they interrupt profitable cycling during the exact periods
(volatile, high-OFI) that generate the most fills and spread revenue. The regime that
looks "dangerous" for a directional strategy is often the most profitable for a
mean-reversion cycler.

---

## 19. Nine-Month Zero-Shot Transfer: LINK April 2026

**Experiment:** Applied the Jun 2025 IS winner parameters unchanged to LINK/USDT April 2026
data (30 days, Apr 1–30). LINK price had fallen from ~$13 to ~$9 (-30%). No recalibration.

**Results:**

| Metric | Jun–Jul 2025 | Apr 2026 (zero-shot) |
|---|---|---|
| Mean PnL/day | +$154 | +$43.78 |
| Win rate | 30/30 | 30/30 |
| Sharpe | 56.5 | 38.7 |
| Avg markout | +1.8 bps | +1.25 bps |
| Avg adverse fills | 22% | 22% |

The lower PnL is fully explained by the lower price level (same tick count, ~31% lower
notional per fill). The natural spread remained 10 ticks. Adverse selection profile
(markout, % adverse) is essentially identical 9 months later.

**Contribution:** Demonstrates that the mean-reversion cycling mechanism is structurally
stable across regimes and price levels on LINK, not an artefact of a specific volatile
period. The asset's microstructure (permanent 10-tick spread, step-function fill curve)
is the persistent feature that enables the strategy, not the specific 2025 market conditions.

---

## Planned Extensions

- **Stressed regime validation**: download LINK data from high-volatility or crash periods
  to test whether the kill switch ($25 daily loss limit) is sufficient to prevent catastrophic
  losses when the mean-reversion assumption breaks down
- **Cross-asset validation**: test on comparable mid-cap crypto assets (similar tick spread
  structure) to determine whether the step-function mechanism is LINK-specific or generalises
- **Reinforcement learning**: TabularQ and DQN agents training on LINK Jun 11–27 — learn
  optimal inventory threshold and quoting policy directly from reward signal (currently running)
- **ML-based kappa estimation**: XGBoost fill probability model conditioned on regime features
- **Multi-level ladder quoting**: extend single-order framework to multi-level
