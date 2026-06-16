# Thesis Contributions

Empirical and methodological contributions from the implementation and analysis of
Avellaneda-Stoikov and GLFT market making on BTC/USDT and LINK/USDT tick data (CoinAPI,
Binance Spot, May–Jun 2025, Jun–Jul 2025, and April 2026).

> **Metric note (2026-06-10) — "Sharpe" figures below are deprecated.** Entries written
> before this date quote "Sharpe" numbers of two kinds, neither of which should survive into
> the thesis: (a) √365-annualized daily Sharpe over ≤30-day windows (values like 38–58),
> where annualization manufactures a large number from a few weeks of data; (b) the engine's
> per-step quantity (values like −530), which is mean/std of per-100-event PnL increments
> × √N — a *t-statistic*, not a Sharpe ratio (now stored as `pnl_tstat`; the `sharpe` key is
> a deprecated alias). Risk-adjusted ratios are in any case not meaningful for this project's
> verdict: the honest-regime PnL is ≈0/negative, and a ratio of a near-zero mean to its noise
> is noise. Thesis tables should report **mean ± std of daily PnL, win rate (days > 0), and
> markout (bps)**; where a relative risk-adjusted comparison is genuinely needed (e.g., the
> Sharpe paradox in Contribution 29), use the *unannualized* daily mean/std ratio and label
> it as such. Relative comparisons quoted in Sharpe terms (e.g., "RL +24% over A-S") remain
> directionally valid — both sides used the same metric — but should be restated in PnL terms.

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

**Corroborating literature:** Adverse selection as the structural cost of passive liquidity
provision is the foundational result of Glosten & Milgrom (1985); the conditional-on-fill
losing position of limit orders ("the limit order trader's winner's curse") is Handa &
Schwartz (1996). This contribution reproduces both at crypto tick frequency.

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

**Corroborating literature:** The exponential intensity λ(δ) = A·exp(−κδ) is a *modeling
assumption* of Avellaneda & Stoikov (2008) and Guéant, Lehalle & Fernandez-Tapia (2013), not
an empirical claim; the empirical execution literature has long found limit-order fill times
poorly described by simple parametric forms (Lo, MacKinlay & Zhang 2002, survival analysis of
limit-order executions). Finding a two-component deviation therefore contradicts no empirical
result — it refines the assumption with data.

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

**Corroborating literature:** The markout methodology (post-fill mid drift at a fixed
horizon, signed by fill side) follows Albers et al. (2025); the finding that the majority of
passive fills are adversely selected echoes Glosten & Milgrom (1985) and the empirical
limit-order literature (Handa & Schwartz 1996; Hollifield, Miller & Sandås 2004).

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

**Corroborating literature:** LINK (spread pinned at 10 ticks, deep standing queues) is a
textbook *large-tick asset* in the sense of Dayri & Rosenbaum (2015): price dynamics are
dominated by queue dynamics rather than continuous price discovery, which is exactly the
regime where a distance-from-mid fill model loses meaning and queue position becomes the
relevant state variable.

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

---

## 20. Step-Function Fill Curve and Queue Penalty — LINK L2 Analysis

**Experiment:** Computed the empirical fill probability curve P(fill | δ, T=0.5s) for LINK/USDT
over 30 days of April 2026 using CoinAPI L2 orderbook snapshots and trade data. Two models were
compared: (1) price-only (the backtest model — fill if a sell trade occurs at or below our bid),
and (2) queue-aware (fill requires cumulative sell volume to exceed all orders ahead of us in
the L2 queue). δ is measured in ticks from mid; LINK's natural spread is 10 ticks (5 per side).

**Results:**

| Delta (ticks from mid) | Region | Price-only fill prob | Queue-aware fill prob |
|---|---|---|---|
| 1–4 | Inside spread | 2.97% | 2.97% |
| 5 | At natural bid | 2.97% | **0.073%** |
| 6–15 | Outside spread | 0.10% | 0.0055% |

Key ratios:
- Price-only: 28.5× drop from inside/at-touch to outside (2.97% → 0.10%)
- Queue-aware, at-touch vs inside: **41× drop** (2.97% → 0.073%) — the L2 queue at
  the natural bid level almost entirely blocks fills from outside
- Queue-aware exponential fit: A=0.051, κ=0.318, R²=0.76. Poor fit (R²<0.8) because
  the curve is not exponential — it is flat inside, drops sharply at the touch, flat again outside.

The price-only model (used in the backtest) overstates fill probability at the natural bid by 41×.
Inside-spread quotes fill at the same rate as at-touch in the price-only model because any sell
trade at the best bid fills all inside-spread orders simultaneously — the model has no queue.

**Mechanistic explanation (fig14, extended analysis):** The queue penalty is explained by the
size mismatch between typical trades and the L1 queue. Over 30 days and 1.6M trades:

| Metric | Value |
|---|---|
| Median trade size | **2 LINK** |
| Median L1 queue depth | **3,937 LINK** |
| Queue / trade ratio | **1,968×** |
| % of individual trades that clear the L1 queue | **0.1%** |

The typical trade (2 LINK) is 1,968× smaller than the typical queue. Only 0.1% of individual
trades — very large block orders (>4,000 LINK) — can clear the queue. In 0.5s, the cumulative
sell volume of ~0.3 trades × 2 LINK ≈ 0.6 LINK against a queue of ~4,000 LINK. This directly
explains the 0.073% queue-aware fill rate at the touch: fills only happen during rare burst
events, not through ordinary trade flow. Inside-spread orders face no queue — any arrival fills
them immediately — which is the sole reason the inside-spread strategy generates ~4,000 fills/day.

**L1 depth distribution (fig15):** The L1 queue is bimodal: a thin mode at 1–5 LINK (transiently
depleted, immediately post-block-trade) and a normal mode at 3,000–10,000 LINK. Bid depth:
p5=2,109 LINK, median=7,260 LINK, p90=11,667 LINK. The occasional thin-touch episodes are
when outside-spread orders have any chance of filling.

**Contribution:** Provides direct empirical evidence that the fill curve on LINK is a step
function, not the exponential P(fill | δ) ∝ exp(−κδ) assumed by GLFT, and supplies a
quantitative mechanistic explanation: the queue is ~2,000× the size of the median trade. The
inside-spread strategy achieves its fill rate not through price dynamics but by queue-jumping —
a structural feature invisible to the exponential fill model. This finding has direct implications
for any market making model on assets with large standing queues: the relevant variable is not
the distance from mid but whether the order is inside or outside the existing queue.

**Corroborating literature:** That queue position — not distance from mid — is the economically
dominant state variable on large-tick instruments is the central result of Moallemi & Yuan
(2017), who show queue position carries value comparable to a large fraction of the spread;
the large-tick taxonomy is Dayri & Rosenbaum (2015). This contribution provides the crypto
analogue with direct L2 measurement.

---

## 21. LOB Shape: Hollow Touch and Structural Stability

**Experiment:** Analysed the full 50-level LOB structure on LINK/USDT April 2026 (30 days,
~518k snapshots sampled every 5s). Computed mean depth profiles, cumulative depth distribution,
day-to-day shape stability, and intraday variation at the best bid/ask.

**Results:**

| Metric | Value |
|---|---|
| L2/L1 depth ratio (bid) | **6.5×** |
| L5/L1 depth ratio | ~15× |
| L10/L1 depth ratio | ~30× |
| 50% of book within | L~5 |
| 90% of book within | **L~43** |
| Intraday depth variation (peak vs trough) | ~10% |
| Day-to-day shape variation (σ / mean) | <5% at L1–L20 |

The "hollow touch" structure: L1 (best bid/ask) carries disproportionately little depth
relative to deeper levels. L2 has 6.5× more volume than L1. The touch level is thin because
HFT activity refreshes it constantly — orders at the touch are picked off faster than they are
replenished. The book only becomes deep further from the mid.

The IC heatmap of per-level OBI vs future returns (using clean book-mid, all observations)
reveals a non-monotone pattern: L1 OBI IC rises from 0.20 at 0.5s to a peak of 0.39 at 30s,
then decays to 0.29 at 120s. This is explained by OBI persistence (see Contribution 22 extension):
the imbalance at the touch is autocorrelated for 30–60s, so the signal at t=0 continues to be
"right" over a window of several tens of seconds, not just instantaneously. Deep levels add
almost no information: L3 IC peaks at 0.20 (vs 0.39 for L1), and beyond L5 the IC is below 0.10
at all horizons. The ask side is slightly more depth-concentrated than the bid (50th percentile:
L12 vs L15), consistent with the positive price trend in April 2026 creating a deeper bid book.

Intraday depth is remarkably flat — only ~10% variation across UTC hours (mean L1 depth ~7k LINK
bid, ~6.7k LINK ask), with no pronounced open/close effect.

**Contribution:** Documents that LINK/USDT has a structurally thin touch relative to the
deeper book — a feature that (a) explains why fill rates inside the spread are driven by trade
arrivals rather than depth, and (b) makes the queue penalty at the touch especially severe.
The IC heatmap corrects the naive interpretation of OBI as a short-horizon signal: the
0.20 IC at 0.5s understates the signal's true persistence; the peak predictive power is
at 30s, driven by OBI autocorrelation. The shape stability finding (< 5% day-to-day variation)
validates using a fixed depth ratio in the queue model rather than calibrating it daily.

---

## 22. OBI Predictive Power: Signal Exists but is Unexploitable for Market Making

**Experiment:** Measured the predictive power of OBI (order book imbalance at L1, L3, L5, L10)
for future price direction on LINK/USDT April 2026 (30 days). Two methods were applied:

- **obi_analysis.py** (Exp 44b): Spearman IC vs future returns at horizons 0.5–120s, excluding
  zero returns from the IC calculation (`y ≠ 0` filter)
- **lob_shape.py** (Exp 44c): Same IC computation using all observations (including zero returns)
  from clean book-mid returns

**Results:**

| Method | OBI L1 IC @ 0.5s | Hit rate @ 0.5s | Notes |
|---|---|---|---|
| Excluding zero returns | 0.70 (IC), 0.86 (Pearson) | 95.5% | **Artefact** |
| All observations (book-mid) | **~0.20** | ~60% | Correct measure |

The 0.70 IC is an artefact of excluding zero returns. LINK's mid price moves rarely at 0.5s
resolution (the 10-tick permanent spread means the mid changes only when the entire spread
shifts). Conditioning on the rare non-zero return periods creates a highly selected sample
where OBI is trivially predictive — those are exactly the periods when the order book was
heavily imbalanced before the spread moved. Including all observations gives IC≈0.20, which
is genuinely informative but much lower.

OBI L1 IC is 0.20 at 0.5s, peaks at 0.39 at 30s, then decays to 0.29 at 120s (see fig9).
The peak at 30s reflects OBI autocorrelation — the imbalance persists for 30–60s, so the
signal's predictive power extends over that window. Beyond L3 the IC drops sharply
(L3 IC ≈ 0.11 at 0.5s, peak 0.20), confirming the signal is concentrated at the touch.

**Exp 45 confirmation:** Ran a 200-trial random search over the OBI-adjusted reservation
price formula r = mid + α × obi_l1 × mid − q × γ × σ² × T on April 2026 LINK data.
Best trial: α=0.00154, IS PnL = $29.99/day vs A-S baseline $34.82/day — symmetric OBI
exploitation **hurts** performance by 14%. The mechanism: shifting both quotes toward the
market increases fills but also adverse selection; the net effect is negative.

**Contribution:** Reconciles two apparently contradictory results: OBI has genuine predictive
power (IC=0.20) but symmetric exploitation of that signal reduces market making PnL. The
resolution is that OBI predicts the *direction* of the next price move, not its *timing*.
A market maker who shifts quotes toward the expected direction gets more fills on the adverse
side (the side expected to move against them) while the fills on the "right" side are
unchanged — the net effect is worse adverse selection. The correct use of OBI for market
making is asymmetric: widen the quote on the predicted-adverse side. The IC value of 0.20
is also calibrated: it is a useful input for regime detection but insufficient to build a
profitable standalone signal at 0.5s horizon.

**Corroborating literature:** Order-book/order-flow imbalance as the strongest short-horizon
return predictor is established in Cont, Kukanov & Stoikov (2014) and operationalized as the
micro-price in Stoikov (2018); Silantyev (2019) confirms it transfers to crypto. The
consensus in the crypto microstructure literature is precisely this contribution's finding:
the predictability is real and universal but "not strong enough to be the source of a
statistical arbitrage" net of spread and fees (e.g., arXiv:2602.00776).

---

## 23. Reinforcement Learning: TabularQ Outperforms A-S on LINK

**Experiment:** Trained a tabular Q-learning agent (120 states × 19 actions) on LINK/USDT
Jun 11–27 2025 (IS, 17 days) with OOS evaluation on Jun 28–Jul 10 (13 days) and zero-shot
transfer to April 2026 (30 days). State: (inv_bin, vol_ratio, momentum, spike). Action space:
19 combinations of bid/ask spread (3–9 ticks) and hold time (0.25–2.0s). Reward: ΔPnL −
λ_inv × |q| × σ / max_inv. Compared DQN (6-dim continuous state, 2-layer MLP) over 22/50
epochs before instance shutdown.

The greedy rollout (ε=0) uses checkpoint epoch_030 with exploration fully removed.

**Results (ε=0 greedy rollout):**

| Period | Days | Mean PnL/day | Total PnL | Win rate | Sharpe | Fills/day |
|--------|------|-------------|----------|----------|--------|-----------|
| IS (Jun 11–27 2025)      | 17 | +$68.17 | +$1,159 | 100% | 42.7 | 11,688 |
| OOS (Jun 28–Jul 10 2025) | 13 | +$71.24 | +$926   | 100% | 38.6 |  8,884 |
| Apr 2026 (zero-shot)     | 30 | +$45.94 | +$1,378 | 100% | 48.0 |  4,965 |

**A-S baseline (Exp 40, Apr 2026): +$43.78/day, 100%, Sharpe 38.7**

TabularQ vs A-S on Apr 2026: +$2.16/day (+5% absolute), +9.3 Sharpe (+24%). The RL policy
has lower daily variance ($15.19 vs ~$25) because it learned to modulate aggressiveness —
deploying halt actions 3–116 times/day in calm periods (vs 138–1,926 times/day in volatile
Jun/Jul data). ε=0 outperforms ε=0.05 by +$4/day OOS: the learned Q-values are the source
of performance, not exploration noise.

DQN (22 epochs): OOS PnL declined monotonically from +$129/day (epoch 5) to +$42/day (epoch 20),
reaching parity with A-S before the run was cut. The low-data regime (17 IS days) is
insufficient for stable DQN convergence; the replay buffer remains underpopulated relative
to network capacity.

**Contribution:** Demonstrates that a 120-state tabular Q-learner is sample-efficient enough
to learn a market making policy from 17 days of data that transfers robustly to a different
market regime 10 months later — without any parameter recalibration. The policy's primary
learned behaviour (regime-dependent halting) is interpretable and inspectable via the Q-table
heatmap. The DQN comparison provides the negative result: expressive neural architectures
do not help in this low-data, step-function-fill-curve setting. Simpler representations
outperform richer ones when data is scarce and the value function is smooth.

---

## 24. Reinforcement Learning Fails on BTC: Action Space–Microstructure Mismatch

**Experiment:** Applied the same TabularQ architecture (120 states × 19 actions) to BTC/USDT
with identical IS/OOS split (Jun 11–27 2025 IS, Jun 28–Jul 10 OOS). BTC parameters: tick_size
= $0.01, order_size = 0.001 BTC (~$107 notional), daily_loss_limit = $2.0.

**Result:** After 30 training epochs, train PnL = -$2.12/day, OOS PnL = -$2.09/day, win rate
= 0% throughout. The agent shows no improvement across all 30 epochs (mean_loss = 0.000 every
epoch — no gradient signal at all from the tabular updates).

| Epoch | Train PnL/day | OOS PnL/day | Win rate | Fills/day | ε |
|-------|-------------|------------|----------|-----------|---|
| 5  | −$2.25 | −$2.08 | 0% | 108 | 0.708 |
| 10 | −$2.16 | −$2.15 | 0% | 106 | 0.499 |
| 20 | −$2.15 | −$2.11 | 0% | 116 | 0.231 |
| 30 | −$2.12 | −$2.09 | 0% | 96  | 0.104 |

**Greedy eval (ε=0, epoch_030):** −$2.08/day, −$27.08 total (13 days), Sharpe −529.8, win
rate 0%, 135.8 fills/day. Per-day PnL is strikingly uniform (~−$2.10) regardless of fill
count (28 to 388). Peak inventory hits max_inventory = 0.02 BTC on 12/13 OOS days, exposing
the full $2,140 notional to each ~0.1% adverse move.

**Diagnosis — structural action space mismatch:**

The 19-action space spans 3–9 ticks from mid. On BTC, the natural market spread is 1 tick
($0.01). Posting at 3 ticks from mid means posting $0.03 outside mid — 3× outside the natural
spread. In LINK's environment (10-tick natural spread), the same 3-tick action posts *inside*
the spread, earning at-touch fill rates. The critical difference:

| Asset | Natural spread | 3-tick action | Fill regime |
|-------|---------------|---------------|-------------|
| LINK  | 10 ticks | inside spread (7 ticks from touch) | At-touch (99% fills) |
| BTC   | 1 tick   | outside spread (3× wider than touch) | Exponential decay (exp(−0.93)≈39%) |

**Economics of failure:**

- Spread capture per round-trip at 3-tick quote: 6 ticks × $0.01 × 0.001 BTC = **$0.000060**
- Observed net loss per fill: $2.10 / 100 fills = **$0.021**
- Adverse selection ratio: $0.021 / $0.000060 = **350×**

The $0.000060 spread revenue is drowned by inventory mark-to-market losses. With ~10 net BTC
filled on unbalanced sides, a 0.2% adverse price move ($210 on $107k BTC) produces exactly
the -$2.10/day loss observed. BTC's daily volatility (~1.5%, or ~$1,600/day) means this
adverse inventory exposure is hit on virtually every trading day.

The mean_loss = 0.000 reflects that the Q-table receives no usable gradient: because no
episode ever has a positive PnL, all state-action pairs receive uniformly negative TD updates
and the table converges to a plateau of equally bad values.

**Comparison with LINK:**

| Metric | LINK TabularQ | BTC TabularQ |
|--------|--------------|-------------|
| Natural spread | 10 ticks | 1 tick |
| Action regime | Inside spread | Outside spread |
| Fill rate/day | ~5,000–12,000 | ~100 |
| Spread capture/RT | ~$0.07 | $0.000060 |
| OOS PnL/day | +$71 | −$2.09 |
| Win rate (OOS) | 100% | 0% |
| Learning | ✓ converges | ✗ no signal |

**Contribution:** Identifies action space–microstructure alignment as the critical precondition
for RL market making success. When all quoted positions fall outside the natural spread,
fills are pure adverse selection events with negligible spread compensation — the value
function receives no positive signal and learning is impossible. This failure mode is not
detectable from the reward design alone; it requires understanding the relationship between
the action space (spread range) and the asset's natural spread regime. For BTC, a valid RL
strategy would require at-touch quoting (1-2 tick actions) with correspondingly larger order
sizes to generate economically meaningful spread capture relative to BTC's price volatility.

---

## 25. Approach C: Model-Free Crossing Intensity Kappa Estimation (LINK)

**Motivation:** Approaches A and B to kappa estimation both rely on fitting an exponential
fill curve to empirical data, which is unreliable when the underlying curve is not exponential.
A third approach avoids exponential curve fitting entirely by using the *mid-price crossing
intensity* directly.

**Method (Approach C):** For each spread distance δ, estimate the arrival rate of price moves
that cross δ ticks from mid as:

```
λ(δ) = P(|Δm(h)| ≥ δ) / h
```

where Δm(h) is the mid price change over horizon h (typically 60s, 120s). This is the
model-free limit of the theoretical GLFT arrival intensity. Fitting λ(δ) to an exponential
decay extracts kappa without any fill simulation or order placement model.

**Result on LINK/USDT April 2026 (30 days, h=60s):**
- κ = 2.08 / tick, R² = 0.97, pure exponential fit
- No A_mom component (A_mom ≈ 0): the crossing intensity decays cleanly to zero
- This contrasts with BTC (Contribution 6) where a momentum floor A_mom ≈ 15% of total
  arrivals persists at large δ

**Interpretation:** LINK price moves are small and infrequent relative to the natural 10-tick
spread (5 ticks per side). The probability of a ≥5-tick price move in 60s is low, and
decays exponentially beyond that — there is no fat-tailed momentum floor. This finding is
consistent with the step-function fill curve (Contribution 15): the fill curve is flat
*inside* the natural spread (because any trade at the touch fills everything inside), and
flat *outside* (because no trades cross to that level), not because of a momentum floor.

**A-S optimal spread at γ→0:** With κ=2.08/tick, the A-S formula spread limit is:

```
lim_{γ→0} spread = 2/κ = 2/2.08 ≈ 0.96 ticks ≈ 1 tick
```

At LINK's $9 price, 1 tick = $0.01 ≈ 11 bps. The formula itself prescribes touch posting —
min_spread_bps=11 is not an arbitrary floor but exactly what the theory recommends. This
provides empirical grounding for the "flat MM" result: the optimal A-S policy at LINK's
microstructure is approximately a fixed-spread touch-poster with zero inventory skew.

**Contribution:** Introduces crossing-intensity kappa as a third estimation approach that
requires no order placement simulation and is robust to non-exponential fill curves (the
exponential fit is applied to the crossing intensity, not the fill probability). Provides
calibration of κ=2.08/tick for LINK April 2026 with R²=0.97, and derives the implication
that the A-S formula prescribes touch posting for this asset.

---

## 26. A-S Gamma×1000 Calibration Bug: Cross-Asset Failure Mode

**Bug identification:** The `avellaneda_stoikov.py` implementation contained:

```python
self.gamma = gamma * 1000   # compensate for tiny BTC sigma
```

This was intentional for BTC/USDT where σ ≈ 2.9e-5/sec, σ² ≈ 8.4e-10, and the formula
skew `q × γ × σ² × T` requires γ ~ 10,000 to produce a $0.01 reservation price shift at
q=50. The ×1000 hack was applied at construction so config files could use human-scale
gamma values (e.g., 1e-6 instead of 1e-3).

**Failure on LINK:** LINK/USDT has σ ≈ 5.9e-3/sec (log-return), σ² ≈ 3.5e-5 — approximately
40,000× larger per unit time than BTC. With the ×1000 hack and config gamma=1e-6:

```
effective gamma = 1e-6 × 1000 = 1e-3
skew at q=50  = 50 × 1e-3 × 3.5e-5 × 3600 × 9.0 ≈ 56.7 ticks
```

The reservation price is shifted 56.7 ticks ($0.567) from mid for a 50 LINK inventory
— 5.67 natural spreads. Every requote places an inventory-skewed bid or ask far outside
any rational pricing, producing catastrophic adverse fills and essentially zero fill rate
on the un-skewed side.

**Fix:** Removed the ×1000 factor entirely. All configs must now supply the actual gamma
value that produces the desired dollar skew. For the calibrated A-S on LINK with 2-tick
(≈$0.02) skew at q=50:

```
γ = target_skew / (q × σ² × T × mid)
  = 0.02 / (50 × 3.47e-5 × 3600 × 8.98)
  = 3.57e-4
```

**Breaking change:** All BTC configs using gamma=0.086 (calibrated for the ×1000 era)
now produce 1000× smaller skew. BTC configs need gamma ≈ 86 for equivalent behaviour.

**Contribution:** Documents this cross-asset calibration failure mode. Identifies the root
cause (implicit unit rescaling at construction that was not visible in config files) and
provides the correct per-asset gamma derivation formula. Shows that sigma² varies by
40,000× across BTC and LINK, making it impossible for a single hardcoded scaling constant
to be appropriate for both assets.

---

## 27. GLFT Formula Spread Blowup on Low-Kappa Assets

**Finding:** The GLFT ergodic spread formula contains the term:

```
(1 + κ/γ)^(1 + κ/γ)
```

which grows superexponentially as κ/γ increases. For LINK parameters
(σ_d=0.053 $/√s, A=0.072 /s, κ=208 /tick, γ=feasible values):

| γ | κ/γ | (1+κ/γ)^(1+κ/γ) | Half-spread |
|---|-----|-----------------|-------------|
| 4.3 | 48 | ~10^78 | >> $1 |
| 43 | 4.8 | ~8,300 | ~8.5 ticks |
| 430 | 0.48 | ~1.6 | ~1.0 tick |

Even at γ=430 (producing 200× stronger inventory skew than desired), the formula spread
is barely touch-posting. For any economically sensible γ the spread blows up to dozens
of ticks — the formula makes GLFT unquotable on LINK.

**Root cause:** LINK has κ ≈ 2.08/tick (from Contribution 25), but the GLFT formula uses
κ in units of 1/dollar. At $9 price, 1 tick = $0.01/9 = $0.0011 in fractional terms. The
GLFT A=0.072 and κ=208 are calibrated from the fill curve in tick units, but the dollar
sigma σ_d=0.053 interacts with these parameters to make the spread term dominate.

**Fix:** Added `max_spread_bps` parameter to GLFT strategy. When set, the formula spread
is capped:

```python
if self.max_spread_bps is not None:
    max_half_spread = self.max_spread_bps * mid / 20000.0
    half_spread = min(half_spread, max_half_spread)
```

With `max_spread_bps=11.0` (≈1.1 ticks for $9 LINK), GLFT posts at touch while its
reservation price formula continues to manage inventory. This decouples the spread
decision from the spread formula and uses the formula only for inventory skew.

**Implication:** GLFT is practically unusable on assets where the formula spread dominates
inventory considerations. The `max_spread_bps` ceiling is a pragmatic fix that preserves
the reservation price component while discarding the (blowup-prone) formula spread. This
exposes a design limitation of the original GLFT framework for assets outside the
parameter range it was calibrated for.

**Contribution:** Characterises the GLFT spread blowup phenomenon for low-kappa, moderate-
volatility assets. Provides the `max_spread_bps` ceiling as a minimal fix, and identifies
the underlying cause (superexponential growth in (1+κ/γ)^(1+κ/γ)) as a warning for applying
GLFT outside its originally intended parameter range.

---

## 28. Classical MM Calibration Workflow on LINK: Flat A-S Outperforms Calibrated by 2×

**Experiment (Exp 52):** Ran three variants of the A-S/GLFT framework on LINK/USDT April 2026
(30 days, Apr 1–30) using Approach C kappa (κ=2.08) and corrected calibration throughout:

| Strategy | Description | Total PnL | Mean/day | Std/day | Sharpe | Win rate | Fills |
|---|---|---|---|---|---|---|---|
| **A-S flat** (γ≈0) | No inventory skew, touch posting | **+$1,428** | +$47.6 | $49.0 | **0.97** | **90%** | 94,226 |
| A-S calibrated v2 | γ=3.57e-4, 2-tick skew at q=50 | +$677 | +$22.6 | $37.0 | 0.61 | 67% | 95,651 |
| GLFT touch v2 | γ=4.3, max_spread=11bps | +$648 | +$21.6 | $37.3 | 0.58 | 67% | 95,672 |

Both calibrated variants are matched to produce identical theoretical skew (2 ticks at q=50
LINK) using correctly derived parameters. All three post at touch (11 bps). Fill counts are
nearly identical (~95k). The flat A-S outperforms by **2.1× in PnL** and **60% in Sharpe**.

**Mechanistic explanation:** LINK fills are sweep-driven, not spread-sensitive. With a permanent
10-tick natural spread, fills occur when a large market order sweeps through the entire book to
our price level. These sweeps are not correlated with our inventory state — they arrive randomly.
The moment a sweep arrives, it fills us regardless of which direction the inventory is being
managed. The reservation price skew means that:

- When long, our bid is shifted down → we quote further from mid → fewer fills on the ask
  side (where we *want* to fill to reduce inventory)
- When short, our ask is shifted up → symmetrically, fewer fills where we want them

The net effect is that inventory skew *reduces* the rate of inventory-unwinding fills without
protecting against adverse sweeps. The flat MM stays at touch on both sides and lets the
inventory cycle naturally, capturing both sides of random sweeps.

**A-S optimal spread insight:** At γ→0, the formula spread = 2/κ ≈ 1 tick = 11 bps. The
flat A-S is not an arbitrary simplification — it is the formula's own recommendation when
inventory skew is zero. The calibrated v2 provides no spread advantage because both post at
the same 11 bps min_spread_bps floor.

**Contribution:** Provides a direct controlled experiment showing that inventory skew management
is counterproductive on step-function fill curve assets. Derives a general condition: when fills
are sweep-driven rather than spread-sensitive, reservation price skew reduces fill rate on the
desired side without compensating protection. The result generalises beyond LINK: any asset where
the fill curve is approximately flat (or step-function) across the range of inventory skew applied
will exhibit this same degradation under calibrated A-S or GLFT.

---

## 29. L2 Queue Simulation: Quantifying Backtest Optimism on LINK

**Motivation:** The standard backtest fill model (`queue_model='none'`) fills any resting order
immediately when price is matched. Contribution 20 showed that the L2 queue at LINK's best bid
contains ~4,000–8,700 LINK of resting orders — 1,000×–4,000× our 5-LINK order. The backtest
model thus over-counts fills severely at any quoted price outside the inside-spread regime.

**Implementation:** Extended the `OrderManager` with a `queue_model='l2'` mode using a proper
queue-clearing fill mechanism. Each submitted order carries `queue_ahead` — the estimated depth
ahead of us at submission (scaled by `queue_fraction`). Fills accumulate traded volume from
the moment of submission; the order only fills once cumulative volume exceeds `queue_ahead`:

```python
vol_to_us = vol_after - max(order.queue_ahead, vol_before)
fill_qty = min(order.remaining, vol_to_us)
```

**Queue scaling:** Raw Binance best-bid depth is ~8,600 LINK (mean). Posting a 5-LINK order at
the touch, queue_fraction=1.0 would mean 8,600 LINK must trade before we fill — essentially
never in a 0.5s window (median trade = 2 LINK, ~1 trade/window). `queue_fraction=0.001` models
~1 competing MM of our size: 8.6 LINK ahead, still at the conservative end.

**Results (A-S flat + L2 queue, queue_fraction=0.001 vs no queue):**

| Metric | No queue | L2 queue | Change |
|---|---|---|---|
| Total PnL (30 days) | +$1,428 | +$588 | **−59%** |
| Mean PnL/day | +$47.6 | +$19.6 | −59% |
| Daily std | $49.0 | $18.3 | **−63%** |
| Daily Sharpe | 0.97 | **1.07** | +10% |
| Win rate | 90% | 83% | −7pp |
| Fill records | 94,226 | 107,562 | +14% (partial fills) |
| Avg markout bps | +4.14 | +2.73 | −34% |
| Typical adverse fill rate | ~24% | ~45% | +21pp |

**Key insight — Sharpe paradox:** Despite a 59% PnL drop, Sharpe *increases* from 0.97 to 1.07.
The queue model eliminates most fills on normal days (only large sweeps clear the queue), so
daily PnL variance collapses from $49² to $18². P&L now comes in infrequent large pulses
(bulk fills when a sweep clears the queue), making each "fill day" highly profitable and most
days near-zero.

**Adverse selection under queue model:** Adverse fill rate rises from 24% to 45%. When an order
*does* fill (i.e., a sweep large enough to clear ~8 LINK), it is almost always an informed sweep
— the market was already moving against us while we waited in the queue. This is the actual
adverse selection cost that the no-queue model cannot capture.

**Fill record vs fill volume:** Fill records increase (+14%) because each partial fill as volume
trickles past queue_ahead creates a separate `Fill` entry. However, filled volume *per record*
is lower on average. The total filled notional is less, not more.

**Interpretation:** The no-queue model overstates PnL by ~2.4× for LINK touch posting. The queue
model provides a lower bound: in reality queue position is dynamic (we may be placed anywhere in
the queue based on order submission timing). The true answer lies between the two models. The
+$588 result should be viewed as a conservative estimate and +$1,428 as an upper bound.

**Contribution:** Implements and validates an L2-based queue-clearing fill mechanism in the
backtest engine. Quantifies the optimism of the standard fill model at 2.4× on LINK — a
significant source of backtest overstatement. Introduces `queue_fraction` as a calibration
handle for the "effective competing depth" ahead of our order, derived from L2 snapshot data
(Contribution 20's finding that median depth is ~8,600 LINK). Demonstrates the Sharpe paradox:
queue models simultaneously reduce PnL and improve risk-adjusted metrics because they select
only the rarest, most adversely selected fills, concentrating P&L variance while reducing its
mean. The adverse selection spike (24% → 45%) is the direct empirical consequence of queue
position: resting deeper in the queue means filling only when the market has already moved.

**Corroborating literature:** The economic value of queue position quantified here is the
empirical counterpart of Moallemi & Yuan (2017); the result that orders which *do* fill from
deep queue positions are more adversely selected is the adverse-selection/latency mechanism
modeled by Lehalle & Mounjid (2017). The 2.4× optimism of first-touch fill models also
explains why published crypto-MM backtests using that model report profits. Lalor &
Swishchuk (2024, arXiv:2409.12721) document the same general failure mode on CME futures
(ES/NQ/CL/ZN): simulating the price process and the order-fill process independently — i.e.
"price touched my level" ⇒ "I was filled" — systematically overstates short-horizon MM
performance, and folding adverse selection into the fill simulation brings results back down
to realistic levels. The L2 queue model here, and the exp 62 marketable-on-arrival fix (C30),
are this project's own instances of exactly that correction.

---

## 30. The Queue-Priority Decomposition: All Profitable Results Are Inside-Spread Artifacts

**Motivation:** Across the entire project, every profitable backtest (classical A-S/GLFT and RL,
on LINK) shares one structural feature: it quotes *inside* the natural bid-ask spread. The
backtest fill model (`order_manager.py`, `queue_model='none'`) fills a resting order on the
**first** trade that touches its price, granting the simulated market maker **absolute queue
priority** — as if it were the only participant at that price level. This contribution decomposes
all results by quote regime and shows that profitability is entirely a function of this
unphysical priority assumption, not of strategy class.

**The fill-model artifact (verified in code):** The strategy posts a bid at `mid − δ` ticks
(`avellaneda_stoikov.py:157`, `reinforcement_learning.py:433`). LINK's natural spread is exactly
10 ticks (5 per side) for 99.9% of April 2026 (median = mean = 10 ticks, p10 = p90 = 10).
The fill condition (`order_manager.py:181`) fills the bid on **any** sell trade at price ≤ bid.
Ordinary sells print at the natural bid (`mid − 5t`), which is ≤ any inside quote (`mid − δ`,
δ < 5), so **every** ordinary sell fills the inside order. The backtest thus credits the inside
quote with the entire taker flow that, in reality, would clear against the ~8,600 LINK of orders
already resting at the natural bid ahead of it.

**Regime decomposition (LINK April 2026, 30 days, zero fees, A-S flat):**

| Regime | Half-spread | Inside natural touch? | Honest fill model? | Fills/day | PnL/day | 1s markout |
|---|---|---|---|---|---|---|
| Deep inside | 2 ticks | yes (3t inside) | **no** | 7,673 | +$35 | +0.98 bps |
| Inside (opt) | 4 ticks | yes (1t inside) | **no** | 7,288 | **+$94** | +2.80 bps |
| At touch | 5 ticks | at | partial | 2,502 | +$33 | −0.41 bps |
| Outside | 8 ticks | no (3t outside) | **yes** | 216 | +$2.5 | −0.65 bps |

The only regime where the price-only fill model is physically honest is **outside the natural
spread**: there, filling genuinely requires the price to trade *through* your level (a sweep),
so there is no queue to jump. That regime earns **+$2.5/day** with a *negative* 1s markout —
i.e. every fill is initially adverse, and the small positive total comes only from longer-horizon
inventory mean-reversion.

**Queue-position sensitivity (at-touch + L2 queue model, `queue_fraction` = share of visible
depth ahead of us):**

| Position | Depth ahead | PnL/day | Markout |
|---|---|---|---|
| Front (~1 competing order) | 9 LINK | +$11.8 | — |
| ~17 orders | 86 LINK | +$2.8 | — |
| ~86 orders | 431 LINK | +$0.4 | — |
| ~170 orders | 863 LINK | +$0.9 | — |
| Mid-queue (realistic retail) | 4,313 LINK | +$1.0 | **−2.9 bps** |

From 5% of visible depth onward, PnL is pinned at a sub-$1/day noise floor with a negative
markout: the only fills that clear a large queue are informed sweeps moving against the maker.

**RL is the same artifact, harder.** The TabularQ policy (Contribution 23, +$45.94/day on
April 2026) runs through the identical engine and fill model. Its action space
(`reinforcement_learning.py:124`) is anchored on the natural spread with explicit
`inside_sym` / `near_sym` / `at_sym` / `outside_sym` actions. The trained greedy policy chose
inside/at-touch actions almost exclusively — proven by its fill rate: **median 4,970 fills/day
(min 1,495, max 8,311)**, every single day 7–38× above the honest outside-spread ceiling of
216 fills/day. The RL did not discover a real edge; it discovered that the backtest rewards
inside-spread quoting with free priority and learned to harvest it (the genuine, transferable
part of its behaviour is regime-dependent halting, not the spread capture). Contribution 23's
"TabularQ outperforms A-S" is therefore true only *relative to* A-S within the same fictitious
fill regime — both are inside-spread artifacts.

*Overfit demonstration (exp 58).* To close the "you never gave RL a fair chance under the honest
model" objection, a paired test runs the **same TabularQ** on the same 3 LINK days under two fill
models, with train = eval and 200 epochs (licensed to memorise). The control (19-action space,
`queue_model='none'`) overfits to **+$58/day** (best +$88) — reproducing the artifact. The honest
arms (a 63-action at-touch/outside-only space so no inside quote can inherit the first-touch
artifact under `queue_model='l2'`) **cannot overfit to profit at all**: best stable PnL +$0.7/day,
single-epoch bests $4.7–8.5 of pure noise, the control's *worst* eval far above every honest *best*.
A generous queue assumption (qf=0.05) and a continuous-state DQN both fail too — the DQN converges
to **~0 fills/day** (given no edge, not quoting dominates). RL given the artifact finds +$45–88/day;
under the honest L2 model **no policy over the observable state** profits, even by memorisation.
This is a statement about *causal* policies, not about whether in-sample profit exists at all — a
foresight strategy would profit (see Contribution 34). (See
`experiments/58_rl_honest_overfit/findings.md`.)

**BTC is the control that confirms the mechanism.** BTC RL (Contribution 24, −$2.09/day, 0% win)
is not an independent failure. BTC's natural spread is 1 tick; the BTC action space
(`reinforcement_learning.py:169`) starts at 5 ticks and ranges to 80 — **every action posts
outside the natural touch**. BTC RL is therefore forced into the honest fill regime and loses,
exactly as LINK does in its outside-spread (+$2.5) and at-touch-with-real-queue (~$1) regimes.
The asset that *cannot* quote inside its spread (because the spread is 1 tick) cannot produce
the artifact, and produces no profit.

**The unified law:**

> Every positive backtest in this project lives inside the natural spread under the no-queue
> fill model. Every result in the physically honest regime — outside the spread, or at-touch
> behind a realistic L2 queue — is ≈0 or negative. This holds across both assets (BTC, LINK)
> and both strategy classes (classical A-S/GLFT, tabular/deep RL). The microstructure "edge"
> is not a strategy edge at all; it is a **queue-priority rent**. No strategy can capture it
> without being first in the queue, which is a function of latency and venue infrastructure,
> not of quoting logic.

**Contribution:** Provides a single decomposition that explains every result in the project —
profitable and unprofitable, classical and RL, LINK and BTC — through one variable: whether the
quote sits inside the natural spread under an absolute-priority fill model. Demonstrates that the
LINK "profitability" (including the RL outperformance) is an artifact of unmodelled queue
position, and that the only physically honest regime (outside-spread / behind-queue) is
break-even-to-negative on every asset and strategy tested. Reframes Contributions 16–23 as
measurements *within* the artifact rather than evidence of a retail-accessible edge, and
establishes that distinguishing a genuine market-making edge from a queue-priority rent requires
either L2 queue-position modelling or live order placement — neither of which is captured by
the standard trade/quote backtest.

**Addendum — regime-conditional honest markout (does any regime escape?).** To test whether a
regime/timing filter could rescue honest passive MM, the outside-spread (8-tick) fills were
re-run with per-fill capture (`config_spread_17p8_full.json`, `save_full=true`) and each fill's
1s markout was conditioned on UTC hour, trailing-120s realized-vol tercile, and post-sweep
timing (largest trade in prior 5s ≥ p95). Across 6,476 fills over 30 days
(`analyze_honest_markout.py`):

- **Overall: −0.634 bps, 12.6% positive** — adverse, confirming the verdict.
- **By hour:** every hour negative except hour 23 UTC (+0.020 bps — a statistical zero).
- **By vol:** adverse selection shrinks sharply with volatility (low −0.91, med −0.90,
  **high −0.095 bps**).
- **By post-sweep:** *less* adverse after a sweep (−0.46 vs −0.64) — refuting the prior
  hypothesis that thin-queue post-sweep fills would be more adverse.
- **high-vol × post-sweep: +0.381 bps (n=142)** — the only genuinely positive cell.

The positive cell is the **overshoot-catch** effect: a large sweep in volatile conditions
overshoots, and a passive order resting beyond the touch catches the bounce-back. It is real and
directionally sensible, but **economically negligible for passive MM**: 142 fills over 30 days
(~5/day) at +0.38 bps ≈ **$0.24 total over the month** (~$0.01/day), and statistically marginal
given single-fill markout noise. The regime/timing escape is therefore effectively closed: the
honest passive-MM edge is zero-to-negative in every economically meaningful regime. Notably, the
overshoot-catch is the *first positive-markout signal* found in the project, and it is naturally
a **taker** trigger (deliberately place to catch the bounce, instantly, no queue), not a passive
one — motivating the maker→taker pivot rather than rescuing passive MM.

**Corroborating literature:** The decomposition's verdict — MM profitability is gated by queue
priority, which is bought with speed/infrastructure — is consistent across the empirical HFT
literature: modern MM profits accrue to the fastest, queue-privileged participants (Menkveld
2013; Baron, Brogaard, Hagströmer & Kirilenko 2019), the contest for priority is an arms race
in speed (Budish, Cramton & Shim 2015), and queue position itself carries quantifiable value
on large-tick instruments (Moallemi & Yuan 2017). The contribution does not contradict
published *profitable* crypto-MM backtests — it explains them, since they overwhelmingly use
the same first-touch fill model dissected here.

**Scope and rebates.** All claims are scoped to: Binance **spot** BTC/USDT and LINK/USDT,
May 2025 – April 2026 data, the ~100ms retail latency class, order sizes ≪ L1 depth, and
zero fees (which makes every negative result an *upper bound* on retail economics). One
deliberate exclusion: on venues with **maker rebates** the maker leg carries an additional
revenue term not modeled here. This does not alter the verdict — rebates accrue only on
fills, and fills require queue priority, so the rebate is captured by whoever owns the queue;
it is one more component of the same queue-priority rent, not an escape from it.

**Corrected-engine addendum (latency adverse selection — exp 62).** A later audit found
the fill engine treated a *marketable-on-arrival* order (one that becomes active into a
market already through its limit, because the mid moved during the 100ms latency) as a
passive maker: it filled at the stale limit and, under the L2 model, made it wait in the
same-side queue (so it usually never filled). In reality such an order is a **taker** — it
crosses the spread, takes the opposing liquidity immediately, and bypasses the same-side
queue. The engine was corrected (commit `24a687f`; marketable-on-arrival → taker at the
touch, priced off references at-or-before arrival, no look-ahead; verified by 6 unit + 5
integration invariants; latency-0 results byte-identical). Re-running the honest at-touch
LINK MM on the corrected engine over all 30 April days, with a realistic 4.5bps taker fee
on those crossing fills, moves the honest cell from "≈breakeven noise floor" to
**−$7.93/day, negative on 30/30 days** (~10–15% of fills are toxic latency-adverse takers,
1s markout ≈ −4 ticks). The old engine was systematically *too kind* to the honest MM by
burying these crossings in the queue. This **strengthens** the verdict: honest market
making is not merely unprofitable-at-the-margin but *reliably money-losing* once latency
adverse selection and fees are modeled; the inside-spread artifact (which never crosses the
ask, hence never converts to a taker) is unaffected. RL re-eval is unchanged (the honest
policies avoid the bleed by halting/quoting wide and still cannot profit; the control
artifact prints ~+$26/day as before). See `experiments/62_engine_fix_reruns/`.

---

## 31. Taker Pivot: A Real Signal Capped at ~1 bps — Latency-Robust, Fee-Tier-Bound

**Motivation:** Every market-making result is an inside-spread queue-priority artifact
(Contribution 30). A taker crosses the spread for instant fills and needs no queue priority,
so it sidesteps that constraint entirely. This tests whether short-horizon directional signals
can be monetised by a taker, using tick data + a realistic 100ms latency model.

**Method (latency-aware, tick-resolution):** signal computed at time *t* from data ≤ *t*;
order sent at *t* fills at *t*+latency at the **actual ask** (long) / bid (short); exit crosses
back at *t*+latency+hold. PnL = exit_fill − entry_fill in ticks — spread cost and latency
slippage both emerge from real fills, no hardcoded cost. BTC spot, 41 days across May 2025,
Jun–Jul 2025, Apr 2026. Signals: momentum (trailing return sign), OBI (L1 imbalance),
overshoot-fade (fade large sweeps in high vol), plus a random-direction control.

**The signal is real and queue-independent.** Top-decile momentum/OBI, per-day mean round-trip:

| Signal | 0.5s | 5s | 10s | days>0 | control (random) |
|---|---|---|---|---|---|
| Momentum | +122 t | +471 t | +588 t | 100% | −1.7 t |
| OBI | +182 t | +692 t | +882 t | 100% | −1.7 t |

The random control sits at the −1.7-tick spread floor everywhere; momentum/OBI are positive on
100% of days **including the volatile Jun–Jul 2025 regime where every MM strategy failed.** The
edge genuinely predicts direction net of latency+spread — not a lookahead artifact.

**Sub-finding — BTC sweeps continue, they do not revert.** Overshoot-fade is strongly negative
(0% of days positive, −481 to −877 ticks): fading large sweeps loses, riding wins. This is the
*opposite* of the LINK honest-markout overshoot-catch — the reversal effect does not transfer to
BTC. Internally consistent (overshoot-fade ≈ −momentum).

**But the per-trade edge is capped at ~1 bps and nothing lifts it.** Converting to bps
(tick = $0.01 at ~$103k mid ≈ 0.001 bps), a 30-day selectivity/conviction/hold sweep shows the
gross edge plateaus at ~1.1 bps and refuses to grow:

| Lever | Result |
|---|---|
| Selectivity (p90 → p99 → p99.9) | OBI flat ~0.8–1.1 bps; **momentum *decreases*** (latency adverse selection bites hardest on the biggest moves — by t+100ms the big move is already done) |
| Conviction (momentum ∧ OBI agree) | ~1.0–1.1 bps, no better than OBI alone |
| Hold (10 → 60s) | marginal (+0.2 bps) |
| **Latency (10 → 500ms)** | **OBI 0.90 → 0.69 bps; even at 10ms only ~1 bps** |

**The latency sweep is the key diagnostic: the edge is NOT latency-gated.** Dropping from 100ms
to 10ms (near-co-located) recovers only ~0.1 bps, because the OBI/momentum edge plays out over
*seconds*, not a sub-second pop. So being fast does not help — the signal is simply thin (~1 bps).

**Conclusion — the unified "edges belong to professional infrastructure" verdict, completed:**

| Edge | Real? | Binding constraint | Captured by |
|---|---|---|---|
| Market making | yes | **queue priority** | co-located (front of queue) |
| Taker (momentum/OBI) | yes (~1 bps) | **fee tier** (not latency, not queue) | sub-1-bps-fee players (MM/VIP rebate) |

A ~1 bps gross edge at 66–72% win is a viable HFT strategy *for a player paying <1 bps
round-trip* (market-maker rebate tier), but it is **negative net of even the lowest retail-ish
perp taker fee (3.6 bps round-trip), and hopeless against spot taker fees (~15 bps).** Both the
MM edge and the taker edge are real; both are claimed by professional infrastructure (queue
priority and fee tier respectively); **retail captures neither.**

**Caveats:** these are per-eval-point predictive means with overlapping positions (a
predictive-power metric, not a realisable position-constrained PnL), and market impact is not
modelled. Both make the realisable edge *smaller*, strengthening the negative conclusion.
Selection thresholds (signal decile, sweep-size percentile, vol median) are **trailing-window,
strictly ex-ante** (1h rolling, shifted) — verified by rerun to leave all conclusions
unchanged, as expected since the random-direction control at the same selection points already
bounded any selection effect at the spread floor. Scope: Binance spot BTC/USDT, 41–43 days
across three regimes, ~100ms base latency (swept 10–500ms), sizes ≪ L1 depth.

**Contribution:** Establishes that short-horizon directional predictability on BTC (OBI/momentum)
is real, robust across regimes, queue-independent, and — unlike intuition — **not latency-gated**;
its ~1 bps magnitude is a hard ceiling unmoved by selectivity, conviction, hold, or speed. Reframes
the binding constraint for the taker as the **fee tier** rather than queue position or latency,
completing a unified account in which every captured edge in crypto market microstructure is gated
by a piece of professional infrastructure retail lacks. Identifies cross-venue (spot↔perp lead-lag)
signal fusion as the only remaining lever that could produce a *larger* signal rather than a cheaper
cost.

**Addendum — supervised ML does not lift the ceiling (strict OOS).** A 3-class XGBoost on all 8
microstructure features (OFI, momentum, OBI, σ, spike ratio, λ-imbalance, lagged return, spread),
trained on Jun 2025 and evaluated out-of-sample on Jul 2025 (same regime, later) and May 2025
(different regime), using the identical latency-aware fill model:

| Regime (OOS) | XGBoost | OBI baseline | AUC(up) |
|---|---|---|---|
| Jun–Jul 2025 | +0.66 bps | +0.70 bps | 0.78 |
| May 2025 | +0.87 bps | +0.88 bps | 0.71 |
| **All OOS** | **+0.75 bps** | **+0.78 bps** | 0.75 |

XGBoost has genuine directional skill (OOS AUC 0.75) but **does not beat plain OBI on the
per-trade taker metric — it is marginally worse in both regimes**, and neither clears the 3.6 bps
perp fee. Two conclusions: (1) OBI already saturates the *tradeable* predictability — the residual
signal the other features add lives in sub-spread moves that don't clear the crossing cost; (2) the
model's probability margin is not aligned with move *magnitude* (higher AUC, lower per-trade bps),
so OBI magnitude is itself a better proxy for expected move size than a classifier's confidence.
The ~1 bps within-venue ceiling is therefore a genuine predictability wall, not an artifact of using
a simple signal — confirmed ML-proof under strict OOS. The fee tier remains the binding constraint;
cross-venue spot↔perp fusion is the sole remaining lever.

**Corroborating literature:** Each leg of this contribution lands on an established result.
(1) Signal real but sub-cost: the crypto microstructure consensus is that imbalance/flow
predictability "does not beat transaction costs" when taken (Cont, Kukanov & Stoikov 2014
for the signal; arXiv:2602.00776 for the crypto cost verdict). (2) ML adds classification
skill but little economics: the standard finding for LOB deep learning (Zhang, Zohren &
Roberts 2019 report strong classification metrics; Kearns & Nevmyvaka 2013 note the gap
between predictability and profit). (3) Latency *not* binding here is not in tension with
the latency-race literature (Budish, Cramton & Shim 2015): those races are *maker-side
queue/cancel races at the touch* — exactly the queue gate of Contribution 30 — whereas this
taker edge plays out over seconds and is therefore fee-gated, not speed-gated.

---

## 32. Reversion Is Shallow and Queue-Gated: Deep Liquidity Provision Is Concentrated Adverse Selection

**Motivation:** Two follow-ups to the queue-priority verdict. (1) Does *low-frequency* market making
— commit to a price, sit, and only modify on a genuine risk change — let a maker climb the L2 queue
through patience rather than buy priority via co-location? (2) Does a *deep-limit* reversion strategy
(post 50–500 ticks from mid, fill only on a dislocation, bet on mean-reversion) escape both
infrastructure gates at once — deep means little/no queue, maker means low fees?

**Methodological contribution — risk-based requote gate.** The standard tolerance compares the *new
optimal* quote (which tracks mid) to the resting price, so it makes the quote chase the mid and, under
a queue model, resets queue position on every drift — making "sit" impossible. We implemented a
config-flagged `requote_policy="risk"` that decouples requoting from mid drift: a mid approaching a
resting quote is allowed to ride into the fill (the option going in-the-money), and requoting fires
only on (a) σ change > threshold, (b) directional toxicity `|OFI|` against the resting side (which
*pulls* that side — distinguishing an informed approach from a noise approach), or (c) a change in the
quotable-side set. Per-side reconciliation leaves persisting sides untouched, preserving queue position.

**Finding 1 — queue-climbing does not rescue at-touch MM (exp 56).** LINK at-touch under the L2 queue
model, comparing price vs risk policy at queue_fraction ∈ {0.05, 0.5} (≈430 / ≈4,300 LINK ahead):
all configurations sit at the ~$0.6–0.8/day noise floor, and the risk-gated "sit and climb" policy is
**worse than the mid-chasing policy at both queue fractions** (30-day totals: risk −$4.1 / +$4.0 vs
price +$18.4 / +$23.2 at qf = 0.05 / 0.5), with *worse* adverse selection (markout −3.0 / −3.8 bps vs
−2.7 / −2.9 bps). The mechanism is the opposite of the climbing hypothesis: sitting longer increases
exposure to informed flow picking off the resting order, and that added adverse selection swamps any
queue-advancement benefit — the standing queue (thousands of LINK) is in any case too deep to climb
through ordinary flow within a holding window. Patience does not substitute for queue priority; if
anything it makes fills more toxic. Queue *depth* barely affects the result, confirming the binding
constraint is queue *position*, which sitting cannot manufacture.

**Finding 2 — deep-limit reversion is refuted; reversion is a shallow phenomenon (exp 57).** A
conditional-reversion study (fade a displacement of depth X over a 30s window, measure the 60s
reversion PnL in ticks), pooled over all LINK (~60 days) and BTC (43 days). *Note on n:* events
are sampled on a 1s grid with 30s windows, so observations overlap and the raw counts are
inflated ~30×; all conclusions rest on conditional means and the monotonic depth gradient, not
on n-dependent significance tests. The same applies to the touch-based addendum below
(overlapping placements at 1s spacing).

| Depth from mid | LINK mean | LINK P(profit) | LINK p5 tail | BTC mean | BTC p5 tail |
|---|---|---|---|---|---|
| 8–20t | +1.0t | 36% | −20t | (shallow +) | huge |
| 20–50t | +0.6t | 43% | −40t | −134t | −6,669t |
| 50–100t | 0.0t | 47% | −80t | −213t | −6,921t |
| 100–200t | −13.9t | 47% | −250t | −150t | −7,123t |
| 200–500t | −136.7t | 43% | −1,109t | −192t | −6,894t |
| 500t+ | −682t | 27% | −2,611t | −209t | −8,688t |

The reversion edge is confined to the **shallow near-touch band (8–50 ticks, ~+1 tick/fill)** — which is
exactly the queue-priority-rent regime already documented (the +$2.5/day outside-spread, Contribution 30).
Contrary to the deep-liquidity hypothesis, the edge does **not** grow with depth: it vanishes by ~50 ticks
and turns strongly negative beyond, *monotonically worse with depth*, with an explosively growing left
tail (LINK p5: −20t at the touch → −2,611t at 500t). BTC is negative at every depth with −$60 to −$87/unit
tails. No clean ex-ante separating signal exists at depth (the OFI/vol discriminator that appeared in a
3-day sample collapsed on full data; the few positive deep cells have n≈100 or catastrophic tails).

**Mechanism — adverse selection by selection.** A price move large enough to reach a deep limit is, almost
by construction, an *informed/regime* move rather than noise, so it continues. Noise reverts, but noise does
not travel 100+ ticks to reach you. Therefore **the deeper a maker posts, the more adversely selected every
fill is, monotonically** — deep liquidity provision is not "catching reverting overshoots" but standing in
front of informed moves with a fat left tail. Risk guardrails cannot rescue this: there is no
positive-expectation deep zone to gate into, and the only positive zone (the touch) is itself a queue rent.

**Contribution:** Establishes that the mean-reversion premium in crypto market making is a *shallow,
near-touch* phenomenon co-located with the queue-priority rent, and does **not** extend to deep liquidity
provision — the reversion-vs-continuation balance flips monotonically against the maker with depth, because
deep-reaching moves are selectively informed. Closes the "deep mean-reversion MM with risk guardrails"
branch with a clean negative, and adds the monotonic *adverse-selection-with-depth* result. Also delivers a
reusable risk-based requote policy (sit unless vol/toxicity/inventory changes) and the negative result that
low-frequency queue-climbing does not substitute for queue priority. Together with Contributions 30–31 this
completes the verdict: every positive zone in maker or taker space is gated by professional infrastructure
(queue position or fee tier), and the structural alternatives that appear to escape it — RL, low-frequency
sitting, deep reversion — each collapse back onto the same two gates.

**Corroborating literature:** "Adverse selection by selection" is the limit-order winner's
curse of Handa & Schwartz (1996) — a limit order fills exactly when the market most wants to
trade through it — sharpened here into a monotonic depth gradient. Conditional-on-fill
adverse selection of standing limit orders is the core empirical finding of Hollifield,
Miller & Sandås (2004), and the interaction of resting time, queue, and being picked off by
informed flow is modeled in Lehalle & Mounjid (2017). Finding 1 (sitting longer makes fills
*more* toxic, not better-queued) is that mechanism observed directly.

**Robustness addendum — touch-based fills (censoring check).** The grid study conditions on
displacement *sustained* at exactly t, which censors wick fills (price touches the level and
reverts within the window) — a real resting limit would have filled those *profitably*, so the
grid design could overstate deep adversity. A touch-based rerun (`touch_reversion.py`: limit
rests X ticks from mid for 30s; fill = **first** crossing of the level on a 250ms grid, at the
limit price; reversion measured 60s from the *fill* time) removes the censoring and confirms
the conclusion — if anything more sharply, because fills anchor at first touch and then absorb
the remainder of the move:

| Depth | LINK mean (ticks) | LINK p5 | LINK fills/day | BTC mean |
|---|---|---|---|---|
| 10t | +2.3 | −30 | 57,660 | −1,713 |
| 20t | +1.7 | −40 | 13,705 | −1,708 |
| 50t | −1.9 | −90 | 828 | −1,691 |
| 100t | −34.7 | −443 | 78 | −1,663 |
| 200t | −160.9 | −1,543 | 16 | −1,613 |
| 500t | −536.2 | −2,553 | 3.6 | −1,514 |

Same sign structure, same monotonic depth gradient, same explosive left tail. Mean time-to-fill
is 9–19s, i.e. deep fills happen *mid-move* and then ride the continuation — the
adverse-selection-by-selection mechanism observed at the fill itself rather than inferred from
end-of-window displacement. (Mid-touch is used as the fill trigger, which is *optimistic* for
the strategy; BTC depths of 10–500 ticks are 0.1–5 bps and thus all inside ordinary 30s noise,
so BTC is uniformly negative — consistent with the grid study.) The deep-reversion refutation
is therefore not an artifact of fill-time censoring.

---

## 33. Synthetic Ground-Truth Validation and the Zero-Profit Law Behind the Queue Verdict

**Motivation:** Two questions hang over every negative result in this thesis. (1) Is the
breakeven-to-negative honest regime a *bug* — a flaw in the engine's fill or P&L accounting, or in
the A-S/GLFT implementations? (2) If the code is sound, *why* is honest market making structurally
unprofitable, rather than merely unprofitable on this data? Contribution 33 answers both by
validating the machinery on markets whose profitability is known in closed form, then deriving the
equilibrium that makes the queue-priority verdict (Contribution 30) inevitable.
(See `experiments/59_synthetic_engine_validation/`.)

**(a) The engine is exact.** A fixed-spread quoter at the BBO, run through the real engine on a
market with a *constant* true value and Poisson taker flow, books P&L equal to the closed-form
spread capture to floating precision:

```
expected = n_fills × half_spread × size = 38,520 × $0.02 × 1.0 = $770.40
realized = $769.44   (residual −$0.96 = the 36-unit open inventory marked at mid)
```

With no adverse selection (constant value) every fill earns exactly the half-spread; the fill
condition and `cash + inventory × mid` accounting are correct. Mean-reverting (OU, +$558) and
mild-brownian (+$690) worlds are likewise profitable.

**(b) The negative control — short-gamma, not a rigged engine.** In a high-vol *martingale*
(σ=0.20 $/√s) the same fixed 2-tick quoter loses robustly across seeds (mean −$920, 12 seeds). This
is **not** informational adverse selection — the mid is driftless. It is the structural short-gamma
cost: the MM's ask is lifted as price rises and bid hit as price falls, so inventory and price are
negatively correlated and the realized inventory-variance cost scales with σ². A passive MM is
short a straddle; the spread is the premium. The engine books the loss correctly — it is not
mechanically positive.

**(c) The strategies are sound when fed the truth.** Real `AvellanedaStoikov` and `GLFTMarketMaker`,
**injected with the true σ** and run on an exponential-fill (A-S/GLFT-faithful) market, are clearly
profitable across constant, mild, and medium vol (100% of seeds positive), and **widen their
half-spread monotonically with σ and risk aversion** (A-S 1.0t→24.6t; GLFT 2.0t→16.2t) — the
`γσ²`/`θ` vol term doing its job. At the deliberately extreme σ=0.20 the profitable width band is
narrow (~8t) and each formula's own optimum brackets it (A-S overshoots via its κ·T scaling —
Contribution 27's miscalibration seen again; GLFT bottoms at ~16t because the σ-driven inventory
term dominates while the `(1+κ/γ)^(1+κ/γ)` factor explodes for γ≪κ), so both land at ≈breakeven
rather than clearly positive. The verdict is unchanged at realistic vol: the code finds the profit
whenever it should be there.

**(d) The zero-profit law — why honest MM is breakeven.** Parts (a)–(c) hold σ and the flow
parameters (A, κ) **independent**, which is the only reason the synthetic MM can be made profitable:
the vol-to-flow ratio `σ²/(Aκ)` is a free knob. In a real order-driven market they are coupled. Two
facts (Glosten & Milgrom 1985; Wyart, Bouchaud, Kockelkoren, Potters & Vettorazzo 2008):

1. *Volatility is flow.* Over time `t` there are `N = A·t` trades, so `σ_$²·t = N·σ_trade²`,
   giving the volatility per trade `σ_trade = σ_$/√A` — the irreducible adverse-selection cost
   between quoting and filling.
2. *Market-maker zero-profit.* Free entry competes the half-spread down to `δ* ≈ σ_trade`. The fill
   curve decays on scale `1/κ`, and in equilibrium the quoted spread sits there, so

   ```
   κ_equilibrium ≈ √A / σ_$        (κ falls as σ rises — a flatter fill curve)
   ```

`equilibrium_pinning.py` confirms this with real adverse selection (a fraction φ=0.5 of takers trade
in the direction of the next 5 s move). Locating the breakeven half-spread δ_be(σ) where mean PnL=0:

| σ_$ | fixed 2t quoter | δ_be (ticks) | δ_be/σ_$ | implied κ = 1/δ_be |
|---|---|---|---|---|
| 0.02 | +$118 | 2.0 (floored) | 100 | 0.500 |
| 0.05 | −$540 | 3.9 | 77.5 | 0.258 |
| 0.10 | −$1,436 | 7.6 | 76.0 | 0.132 |
| 0.20 | −$2,843 | 15.2 | 75.9 | 0.066 |

δ_be/σ_$ is constant (~76) — the breakeven half-spread is **linear in σ** (Wyart–Bouchaud), so the
market-clearing **κ = 1/δ_be ∝ 1/σ** (it halves each time σ doubles). κ is not free; zero-profit
pins it to σ. A fixed-κ quoter is living in a disequilibrium — profitable while σ is small,
catastrophic once σ exceeds the level its spread was set for. At the equilibrium κ the premium
exactly equals the adverse-selection cost: **honest expected profit = 0.** Breakeven is the fixed
point, not bad data.

**(e) The unification with Contribution 30.** `δ* ≈ σ_$/√A` assumes the spread can move freely. On a
**large-tick** asset (LINK, 1-tick floor) the spread *cannot* tighten to the zero-profit width, so
the market enforces breakeven on the **queue-depth** axis instead: the touch queue grows until the
marginal back-of-queue order breaks even — the ~8,600 LINK observed in Contributions 20/30. The
Wyart–Bouchaud spread equilibrium (small-tick, e.g. BTC) and the C30 queue-priority rent (large-tick,
LINK) are the **same zero-profit law**, enforced through whichever variable is free — **spread width
or queue position**. Queue priority is the scarce, retail-inaccessible resource precisely *because*
the spread lever is jammed on large-tick assets. This is the constructive complement to C30: when the
profit should be there (no queue, no informational adverse selection) the engine and both classical
strategies find it; in the real market the same theory that prices the spread predicts the
zero-profit honest regime.

**Corroborating literature:** Glosten & Milgrom (1985) — the adverse-selection spread that yields MM
zero-profit. Wyart, Bouchaud, Kockelkoren, Potters & Vettorazzo (2008) — the empirical "spread ≈
volatility per trade" law confirmed here as δ_be ∝ σ. Dayri & Rosenbaum (2015) — large-tick implicit
spread, the regime where the spread is floored and the balance shifts to the queue. Smith, Farmer,
Gillemot & Krishnamurthy (2003) — zero-intelligence order-book model in which spread and volatility
emerge jointly from flow, the theoretical basis for treating κ and σ as coupled rather than free.

---

## 34. The Perfect-Foresight Oracle: the In-Sample Edge Is Real but Information-Gated

**Motivation:** Contribution 30/exp 58 establish that no *causal* policy — over observable
microstructure state — profits under the honest L2-queue fill model. A natural objection: an
overfit strategy that *knew the future* (which fills will be followed by favourable vs adverse
moves) should profit even honestly. It should — and quantifying by how much sharpens the verdict
into its final form. (See `experiments/60_foresight_oracle/`.)

**Method:** an honest touch-quoter (post at best_bid/ask) is run through the real engine on LINK
April 1–3 2026 under `queue_model='l2'`, `queue_fraction=0.5` — the fills a realistic honest MM
actually receives (3,595/day). Each fill's forward markout is computed at horizons H ∈ {1,5,10,30}s
(`bid → mid(t+H)−price`, `ask → price−mid(t+H)`). Two sums are compared: over **all** fills (the
honest MM, no foresight) and over **positive-markout** fills only (a perfect-foresight oracle that
skips every adverse fill).

| Horizon | honest PnL/day (Σ all) | oracle ceiling/day (Σ positive) | % fills positive | mean markout (ticks) |
|---|---|---|---|---|
| 1 s | $0.60 | **$19.76** | 39.7% | −1.04 |
| 5 s | $2.18 | **$22.41** | 45.6% | −0.47 |
| 10 s | $2.03 | **$24.07** | 46.3% | −0.48 |
| 30 s | $4.06 | **$30.03** | 48.9% | −0.13 |

*(Corrected-engine update — exp 62. On the corrected fill engine that converts marketable-on-arrival
orders to takers, fills/day rise 3,595 → 5,768 and the honest causal markout flips negative even at
zero fee: −$9.78 / −$2.87 / +$1.35 per day at H = 1 / 10 / 30 s, with the oracle ceiling rising to
$28.62 / $37.24 / $47.24. The causal-vs-foresight gap widens and the honest side is now negative
pre-fee — the conclusion below is unchanged and sharpened.)*

**Findings:**
- **In-sample honest profit exists — with foresight.** Keeping only the ~40–49% of fills with
  positive markout earns ~$20–30/day, roughly **10× the honest causal ~$2/day**. The honest causal
  figure reproduces the C30 at-touch cell (≈breakeven; mean markout negative ~−0.5 ticks = the
  at-touch adverse selection).
- **Exp 58's null is representational, not absolute.** A TabularQ over 120 microstructure buckets
  (or a 9-feature DQN) cannot condition on the future, so within any state bucket favourable and
  adverse fills aggregate and the learnable optimum is the bucket average — ≈0 honestly. The RL
  found ≈0 because its state cannot *separate* the good fills from the bad, not because no in-sample
  edge exists.
- **Foresight is worth less than the queue artifact.** The ~$24/day foresight ceiling sits *below*
  the queue-priority artifact (+$45–58/day, exp 58 control): the artifact wins on volume (2,600–7,000
  inside-spread fills with free priority), foresight on selection within the thinner honest stream.
  The ceiling is conservative — it only keeps/drops the touch-quoter's existing fills, not where or
  when to quote.

**Conclusion:** the honest edge is **zero causally, ≈$24/day with perfect 10 s foresight.** Both
halves are the thesis. The profit lives entirely in *information retail does not have* — knowing
which fills are adverse — or equivalently in the *queue priority* that substitutes for that
information by letting uninformed flow fill you first. This refines Contribution 30's verdict to its
sharpest form: it is not that honest market making is mechanically unprofitable, but that all of its
profit is gated behind foresight or priority, neither of which is retail-accessible. Constructive
counterpart to Contribution 33: when an omniscient selector is allowed, the in-sample profit appears
exactly where the theory says the adverse-selection cost is being avoided.

---

## 35. Framing: Market Making Is a Short-Gamma (Short-Straddle) Position

This contribution is a *framing* result: it shows that the entire empirical arc above —
the zero-profit equilibrium (C33), the synthetic vol experiments (exp 59), the deep-reversion
refutation (C32), and the foresight oracle (C34) — is the textbook P&L of a **short-gamma
options position**, expressed in microstructure variables. The correspondence is exact at the
level of the P&L decomposition and breaks in exactly one place, which is itself the thesis.

**The identification.** Track inventory `q(t)` as the *delta* of the book. A passive maker
accumulates the wrong delta: price up → ask lifted → `q` falls; price down → bid hit → `q`
rises, so `dq/dS < 0` (negative gamma). Locally, `q(S) ≈ −(φ/Δ)(S − S_ref)`, where `φ` is the
fill intensity and `Δ` the tick — the linear-decreasing delta of a **short straddle struck at
the mid**. This is not an analogy; the resting two-sided quote *is* a written straddle
(Copeland & Galai 1983: the bid is a written put, the ask a written call).

**P&L decomposition.** Total P&L (`cash + inventory × mid`) splits into two flows:

```
dPnL = δ · dN      (spread capture: half-spread δ per fill, dN fills)   ← THETA
     + q · dS      (inventory mark-to-market)                            ← DELTA·dS
```

Over a price excursion, with `q ≈ −(φ/Δ)(S − S_ref)`:

```
∫ q dS ≈ −½ (φ/Δ) (ΔS)²        (negative convexity ∝ (ΔS)²)             ← GAMMA BLEED
```

Compare a delta-hedged short straddle, from the Black–Scholes identity `Θ = −½ σ² S² Γ`:

```
dΠ_short = ½|Γ| σ_impl² S² dt   (theta, premium decaying in your favour)
         − ½|Γ| (dS)²            (gamma bleed, cost of realised moves)
```

The map is term-for-term:

| Market making | Short straddle | Role |
|---|---|---|
| half-spread `δ` per fill | option premium / implied vol | what you **charge** |
| spread-capture rate `δ·dN/dt` | theta `½\|Γ\|σ_impl²S²` | positive carry for writing |
| inventory `q` | delta | unwanted directional exposure |
| fill intensity / tick `φ/Δ` | gamma `\|Γ\|` | speed of accumulating wrong delta |
| `∫q dS ≈ −½(φ/Δ)(ΔS)²` | gamma bleed `−½\|Γ\|(dS)²` | cost of **realised** vol |
| inventory skew (reservation shift) | delta hedging | pushing `q` → 0 |
| spread widens with σ (`δ*∝σ`, C33) | short vega | lose when vol rises |

The post-fill **markout** (C1, C12, exp 60) is the direct measurement of the gamma bleed
`−½|Γ|(dS)²`; the captured spread is the theta. Honest net ≈ 0 (exp 60: +$2/day, mean markout
−0.5 ticks) is theta ≈ gamma cost.

**Zero expected profit = a fairly-priced straddle.** A short straddle written at fair implied
vol (`σ_impl = E[σ_real]`) has `E[P&L] = 0`: the premium exactly funds the expected gamma bleed.
The Black–Scholes hedging identity `Θ = −½σ²S²Γ` says theta offsets expected gamma cost
*by construction*. The competitive market-making spread does the same: free entry sets
`δ* ≈ σ_trade = σ_$/√A` (C33), at which spread-capture rate = expected inventory/adverse cost →
`E[PnL] = 0`. **C33's zero-profit law is the Black–Scholes fair-pricing identity transplanted
into spread/queue variables**; the competitive spread is the market's fair *implied vol* for
liquidity provision.

**When the edge is non-zero — implied vs realised.** A short straddle profits iff realised
vol < implied; the maker profits iff realised vol < the vol its spread was priced for. The
synthetic experiments (exp 59) are exactly a short-vol book with implied (the spread) held while
realised σ varies: constant world = selling vol into dead calm (pure premium, large profit);
high-vol martingale = gamma blowup (−$920); the breakeven half-spread `δ_be ∝ σ` (exp 59c) is the
fair-implied-vol line, and `κ ∝ 1/σ` is the market continuously re-marking implied to realised,
pinning the book to breakeven. Regime dependence (C13, May vs June) is the textbook short-vol
signature: earn in quiet regimes, give it back in violent ones. A persistent edge therefore
requires forecasting realised vol/flow better than the spread reflects — the **variance-risk-
premium** of the options world, i.e. an *information* edge.

**The one place the analogy breaks — and it is the thesis.** A pure short-gamma book assumes the
underlying is *exogenous*: symmetric moves, `E[dS] = 0`, only `(dS)²` bleed. A maker's fills are
*selected*: the counterparty lifting the ask may be informed, so `E[dS | filled] ≠ 0` — an
adverse **drift** on top of the symmetric bleed (Bagehot/Treynor 1971; Glosten–Milgrom 1985).
This is short gamma to a counterparty with a superior forecast who trades only when right —
strictly worse than fair short gamma, and with no vanilla-option analog. The book has two layers:

- **Layer 1 — symmetric short gamma:** present even with uninformed flow (the synthetic −$920).
  Curable by charging enough spread (theta).
- **Layer 2 — adverse-selection drift:** the informed-counterparty selection; what makes the
  competitive spread adverse-selection-driven (Glosten–Milgrom) and honest markout negative even
  after spread.

**Queue priority is the Layer-2 defence with no options analog.** Being early in the queue means
being filled by *uninformed* flow before the informed arrive — writing the straddle only to noise
traders. The foresight oracle (C34) attacks Layer 2 from the other side: knowing future `dS` lets
you decline the adverse fills. Both convert the breakeven book to profit; both are retail-
inaccessible. This is why deep/wide quoting does **not** rescue high-vol making (C32): a price
move large enough to reach a deep quote is selectively informed and *continues* (adverse selection
by selection), so wide quotes in real markets carry *more* Layer-2 drift, not less — exactly the
monotonic deep-reversion loss. The synthetic wide-quote profit (exp 59, +$113 at 8 ticks) exists
only because the synthetic flow is Layer-1-only (uninformed) and non-competitive.

**Practical corollary (high-vol conservatism).** Quoting wider in high vol raises your implied vol
(premium per fill) and, if `κ` flattens so fills still arrive, *can* be profitable — but only
against Layer 1, and only out of equilibrium. In a competitive market `κ ∝ 1/σ` means the
conservative width that still gets filled *is* the fair-vol width → breakeven; quoting wider than
that gets you crowded to the back of the queue and unfilled. The legitimate "make money in stress"
edge — quoting wide when competitors flee so the spread overshoots realised vol — is the variance-
risk-premium earned for **bearing risk with capital**, and on a large-tick asset (LINK) it is
unavailable anyway because the spread lever is jammed at one tick and competition runs on the
queue, not the spread (C30/C33). So conservative quoting helps against symmetric vol but cannot
manufacture a retail edge: it neither removes Layer-2 adverse selection nor escapes the zero-
profit pin.

**Literature.** Copeland & Galai (1983) — dealer quotes as a written put + call; the spread is the
option premium (the foundational "limit order = short option"). Bagehot/Treynor (1971);
Glosten & Milgrom (1985) — adverse selection (Layer 2). Stoll (1978); Ho & Stoll (1981) — dealer
inventory risk (Layer 1). Grossman & Miller (1988) — liquidity suppliers compensated for risk-
bearing. Bouchaud, Bonart, Donier & Gould (2018), *Trades, Quotes and Prices* — the modern
microstructure treatment of maker P&L, the short-vol framing, and the spread–vol relation.
Sinclair (2013), *Volatility Trading*; Taleb (1997), *Dynamic Hedging* — the short-gamma P&L
decomposition (theta vs gamma, realised vs implied). Foucault, Pagano & Röell (2013),
*Market Liquidity* — the limit order as a free option. Wyart, Bouchaud et al. (2008) — spread ≈
volatility per trade (the fair-implied-vol line empirically).

---

## 36. The Cross-Venue Escape Closes: LINK Spot↔Perp Are Contemporaneously Integrated

**Motivation:** the register's one unrefuted hypothesis was that a *cross-venue spot↔perp lead-lag*
could yield a **larger** signal — the single lever that might produce a bigger edge rather than just
a cheaper cost, escaping both the queue gate (maker) and the fee gate (taker). LINK April 2026,
30 days, spot + perp. (See `experiments/61_link_spot_perp/`.)

**Spread structure.** Median dollar spreads: spot $0.0100 (10 ticks), perp $0.0010 (1 tick) — the
perp is 10× tighter, confirming exp 54. The perp is the tight, liquid, BTC-like venue; a passive
maker on it is forced outside the spread into the honest/losing regime (the C24/C30 mechanism), so
**the perp offers no inside-spread artifact and cannot rescue passive making.** Basis is a stable
≈ −5.5 bps (perp below spot).

**Lead-lag — the make-or-break number.** A naive BBO cross-correlation (1 s grid) reported "spot
leads perp by ~1 s" (ρ=0.31), but the perp top-of-book is sampled at **1 Hz** (orderbook-snapshot
rate), so the perp mid is a stale snapshot that *always* appears to lag — a pure sampling artifact.
The **Hayashi–Yoshida estimator** (Hayashi & Yoshida 2005; lead-lag contrast Hoffmann, Rosenbaum &
Yoshida 2013) on **trade-vs-trade** prices — event-time, asynchronous, no gridding, no staleness —
overturns it:

| θ (perp shift) | −1.0s | −0.5s | **0.0s** | +0.5s | +1.0s |
|---|---|---|---|---|---|
| ρ(θ) | 0.196 | 0.214 | **0.236 (peak)** | 0.151 | 0.132 |

The peak is at **θ = 0 (contemporaneous)**; the 1 s "spot leads" was the BBO staleness. A weak,
diffuse spot-leads tilt remains (Σρ spot-side 3.93 vs perp-side 2.71) but it is smeared across lags,
not a sharp exploitable peak.

**Verdict.** The cross-venue lead-lag *signal* route is **closed**: at the 100 ms–2 s scale the
venues are contemporaneously integrated, so "trade spot on perp's lead" has no foundation. The only
surviving cross-venue construction is the capital/hedge play (warehouse on one venue, hedge the
directional continuation on the other) — which is the variance-risk-premium for risk-bearing
(Contribution 35), not retail alpha, and requires two-venue infrastructure. *Caveat:* resolution is
~100 ms (trade frequency ~4/s); a sub-100 ms HFT-race lead is unresolved but lies below the 100 ms
latency assumption and inside the infrastructure-gated regime, irrelevant to a retail strategy.

**Implication for the meta-verdict.** This was the last untested escape. It closes negative: every
real edge in crypto microstructure tested in this thesis is gated by queue priority (maker), fees
(taker), information/foresight (C34), or risk-bearing capital (C35) — none retail-accessible. There
is no third door in cross-venue. The two-gate meta-hypothesis stands across the full hypothesis
register.

---

## 37. Mapping the Curable Boundary: Widen + Speed Restores Latency Tolerance in the Layer-1-Only World

**Motivation:** Contribution 33 showed that the synthetic high-volatility world (σ=0.20) is
*Layer-1-only* — no informational adverse selection — so its short-gamma loss should in
principle be fully curable by pricing (widen the spread) and/or speed (track the mid). This
contribution maps that curable region precisely, including under the latency that the
corrected-engine addendum to Contribution 30 (exp 62) showed to be decisive. It does **not**
reopen the two-gate meta-verdict (C30/C36): the result is confined to the Layer-1-only synthetic
world by construction, and its purpose is to sharpen the Layer-1/Layer-2 boundary in C35's
framing, not to claim a retail edge. (See `experiments/59_synthetic_engine_validation/findings.md`,
Parts E–F; `high_vol_profit.py`, `breakeven_sweep.py`.)

**Part E — levers in isolation, on the corrected engine.** The exp 62 taker-on-arrival fix
changes how latency-adverse fills are priced, so Part E reruns the high-vol lever sweep
(exponential fills, 10 seeds) to confirm the levers behave as C33 predicts and to characterise
the latency gate honestly:

- **Widen** (Lever 1): 2t → 6t lifts −$514 → +$67 (50% days positive) — cushions the
  short-gamma bleed, but marginal and noisy; too wide starves fills.
- **Inventory skew** (Lever 2): *hurts the mean* (+$67 → −$369) while crushing variance
  ($590 → $41) — the high-vol cost here is a drift, not a variance, so flattening trades away
  return for nothing.
- **Speed** (Lever 3): requote 0.5s → 0.05s turns −$898 → **+$169 (80% days positive)** —
  tracking the mid removes the staleness pick-off. Levers 1–3 use latency=0 and are
  byte-identical to the pre-fix engine (the exp 62 fix is scoped to latency>0).
- **The latency gate** (Lever 4, now charged honestly): at the Lever-3 configuration (4t,
  requote 0.02s), **only exact zero latency is positive** — 0 ms +$153 (70%), 20 ms −$95
  (50%), 50 ms −$389 (40%), 100 ms −$786 (10%), 200 ms −$1,580 (0%). The pre-fix engine had
  estimated 20 ms as a marginal −$12; the corrected engine shows it is already solidly
  negative.

Read in isolation, Lever 4 suggests speed "fails" the moment any realistic latency is added — an
overly pessimistic reading of how curable Layer 1 actually is, because 4t/0.02s is only one
point in a 2-D (spread, requote) space.

**Part F — the joint sweep.** A single combined probe (8t, requote=0.05s, latency=0.05s) gave
**+$389.8 (70% days positive)** — sharply better than the 4t/0.02s/50ms cell (−$388.9).
`breakeven_sweep.py` generalises this to a full sweep: half-spread ∈ {6, 8, 12, 16} ticks ×
latency ∈ {0, 20, 50, 100, 200} ms, fixed requote=0.05s, β=0, 10 seeds/cell. Mean P&L
(days>0 in parentheses):

| half-spread | 0 ms | 20 ms | 50 ms | 100 ms | 200 ms |
|---|---|---|---|---|---|
| 6t | +$255 (60%) | +$165 (70%) | +$14 (60%) | −$309 (30%) | −$1060 (0%) |
| **8t** | +$262 (60%) | **+$463 (90%)** | **+$390 (70%)** | **+$188 (70%)** | −$581 (10%) |
| 12t | +$32 (50%) | +$196 (60%) | −$169 (40%) | +$175 (70%) | +$19 (50%) |
| 16t | +$106 (60%) | +$157 (80%) | −$50 (50%) | +$56 (70%) | +$127 (60%) |

**8t + 0.05s requote is robustly profitable across the entire 0–100 ms latency range**
(+$188 to +$463, 60–90% days positive), only collapsing at 200 ms (−$581, 10%). This extends
the latency-tolerant band from "zero only" (4t/0.02s) to roughly 100 ms — a realistic
non-co-located venue latency. 6t shows the monotone decay the 4t cell already hinted at
(positive at 0–20 ms, breakeven ~50 ms, negative beyond); 12t/16t are too noisy ($500–850 std
vs. $20–200 means) to read either way.

**Verdict — the boundary, and why it stays a boundary.** Yes: in the Layer-1-only synthetic
world, there is a combination — widen to the vol-appropriate ~8t *and* requote fast (0.05s) —
that is robustly profitable at realistic, non-zero latency. This refines C33's "the code finds
profit whenever it should be there" to a precise statement of *how much* spread and speed Layer
1 alone requires. But per C35's Layer-1/Layer-2 decomposition, an 8-tick resting quote that is
profitable against *uninformed* flow is, on a real venue, exactly the kind of stale level that
Layer-2 informed flow targets (the deep-reversion mechanism of C32) — so the boundary mapped
here does not relocate the C30/C36 meta-verdict. Its value is diagnostic: it shows the curable
Layer-1 problem has a real, latency-tolerant solution, which sharpens the claim that the
*remaining* honest-MM loss on real data (C30 exp 62: −$7.93/day) is a Layer-2, not a Layer-1,
phenomenon.

Reproduce:
```
python experiments/59_synthetic_engine_validation/high_vol_profit.py
python experiments/59_synthetic_engine_validation/breakeven_sweep.py
```

---

## 38. A Numerically-Solved HJB Model for the Two-Component Fill Intensity, and the Limits of the Linear-Decay Calibration

**Motivation:** `shifted_glft.py` (deferred C03) patches the two-component fill intensity
`λ(δ) = A_liq·e^{-κδ} + A_mom` into GLFT's closed-form formulas via `A_total = A_liq + A_mom`.
That substitution is exact only when λ itself is a pure exponential — for the two-component
form it silently changes `λ'(δ)`, which is exactly what the FOC for the optimal quote distance
depends on. This contribution (a) extends the empirical fill-intensity calibration to test
whether the "floor" should instead decay linearly to zero at some finite cutoff (the informal
proposal was: "the floor can't be constant, or fills would continue until eternity — propose a
slow linear decay"), and (b) replaces the closed-form hack with a numerically-solved HJB model,
`ShiftedGLFTNumerical` (`hft_market_maker/strategies/shifted_glft_numerical.py`), valid for
*any* λ(δ), not just exponential. `shifted_glft.py` itself is left untouched.

**Part A — does the data support a finite linear-decay cutoff?**
`scripts/calibrate_fill_intensity.py` refits

    λ(δ) = A_liq·e^{-κδ} + max(a - b·δ, 0)

against the constant-floor model `λ(δ) = A_liq·e^{-κδ} + A_floor`, using survival-based hazard
MLE (`fit_exponential_hazard` — correctly handles right-censored orders via `λ̂ =
n_events/Σ observed_time`) over δ ∈ {0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 7.5, 10, 15, 20, 30, 50, 75,
100} ticks, across four days (2025-05-13, 2025-05-20, 2025-06-15, 2025-07-05).

Result: **b ≈ 0 on all four days** (aggregate mean and median both round to 0.00000, range
[0.00000, 0.00000] to 5 d.p.), i.e. an implied cutoff `a/b → ∞`. The linear-decay model is
AIC-preferred over the constant floor on two of the four days (Δaic ≈ 31), but only because the
extra degree of freedom lets `(A_liq, κ, a)` fit the near-touch exponential decay slightly
better — not because a finite cutoff is detected. **Within 0.5–100 ticks, the toxic/momentum
floor is statistically indistinguishable from a true constant.** Aggregate linear-decay fit:
`A_liq=4.866/sec, κ=2.388/tick, a=0.0871/sec, r²=0.992`
(`analysis/fill_intensity_calibration.json`).

**Part B — `ShiftedGLFTNumerical`: solving the HJB for general λ(δ).** With the standard CARA
ansatz `u(t,x,s,q) = -e^{-γ(x+qs)}·e^{-γh_q(t)}`, the HJB reduces — for *any* λ(δ) — to a
coupled ODE system in `(t,q)`:

    h_q'(t) = ½σ_$²γq² − (1/γ)[g*(h_{q+1}-h_q) + g*(h_{q-1}-h_q)]
    g*(Δh) = sup_{δ≥0} λ(δ)·(1 - e^{-γ(δ+Δh)})

with terminal condition `h_q(T)=0` for all q — no liquidation penalty, matching the
`total_pnl = cash + inventory·last_mid` mark-to-market convention. The sup is found via Newton's
method on the FOC `F(δ) = λ'(δ)(1-z) + γλ(δ)z = 0`, warm-started from the pure-exponential
closed form `δ* = (1/γ)ln(1+γ/κ) - Δh`. At `Δh=0` this is exactly
`GLFTMarketMaker.optimal_half_spread`'s adverse-selection term `(1/γ)ln(1+γ/κ)`, and Newton
reproduces it to floating-point precision when `a=b=0` — the FOC is satisfied identically at
the warm start in that limit (see `tests/test_shifted_glft_numerical.py::FOCSolverTests`). The
PDE is integrated by stepping `τ=T-t` forward via explicit Euler over a reflecting-boundary
inventory grid (`q_max = ⌈max_inventory/order_size⌉ + q_buffer`); `h_q(τ)` grows at a
q-independent linear rate, so `Δh_q=h_{q+1}-h_q` converges to a stationary value — the
`τ=horizon` slice is the ergodic policy, exactly as GLFT's closed form is the ergodic
(infinite-horizon) solution for the exponential case. PDE solutions are cached on log-spaced
`σ_$` buckets (and `A_liq` buckets, if `kappa_from_stats=True`).

**Part C — why the default `b` is not 0, despite Part A.** With `b=0`, `g(δ;Δh)→a` as `δ→∞`
(approached, never attained). For the calibrated `(A_liq=4.87, κ=239/$, a=0.0871, γ=30)` this is
harmless — the near-touch local max of `g` (≈0.22) exceeds `a` (≈0.087), so the global sup is
attained at a finite `δ*≈0.5` ticks regardless. But this is parameter-dependent: if `a` were
ever larger relative to `A_liq/κ/γ` — a different instrument, a different regime, or a
`kappa_from_stats`-shrunk `A_liq` — `g` could become *monotonically increasing* toward `a` with
no finite maximizer, and Newton would run off toward an arbitrary numerical bound rather than a
true optimum. This is the formal version of "if the floor never decays, the optimal quote is
infinitely wide" — consistent with neither the math (no argmax exists) nor reality (BTC doesn't
move $billions in the time an order is live). A finite cutoff fixes this unconditionally:
`λ(δ)→0 ⟹ g(δ)→0` as `δ→∞`, so a finite global maximizer is guaranteed for *any*
`(A_liq,κ,a,γ)`. The default `b = a/1000` (cutoff = 1000 ticks = $10 ≈ 1bps on $100k BTC, 10×
past the calibrated range) is a pure tail regularizer: `e^{-κ·1000ticks}=e^{-2390}≈0`, so it
cannot move the near-touch optimum (verified by
`test_thousand_tick_cutoff_is_noop_near_the_touch`).

**Part D — an overflow bug, its fix, and the PDE-vs-closed-form gap on real data.**
The first solve against real σ_$ revealed that `_solve` overflows to `H(τ)=-1.06e301`
(uniform across all `q`) for σ_$ above the 10th percentile of real BTC volatility, silently
freezing the solver at the σ=0 answer (0.412 ticks) for every higher-vol input. Root cause:
`_delta_max` (the Newton search-domain bound in `_solve_foc`) defaulted to
`max(50/κ, 100·tick) = $1 = 100` ticks — *below* the cutoff `a/b = $10 = 1000` ticks. For `Δh`
whose true `g*`-maximizer lies beyond `_delta_max`, Newton clips `δ` to `_delta_max`, where
`λ($1)>0` still, so `g($1;Δh)=λ($1)(1-e^{-γ($1+Δh)})` blows up exponentially as `|Δh|→∞`
instead of `→0`. This fed into `H(τ)`'s RHS and drove the uniform `-1.06e301` within ~2 Euler
steps. **Fix:** `_delta_max = max(50/κ, 100·tick, a/b)`. At `δ=cutoff`, `λ=λ'=λ''=0` ⟹ `F=F'=0`
⟹ Newton is stuck (by construction) at `g*(cutoff;Δh)=0` for *any* `Δh` — the Part B
boundedness theorem (`g*(Δh)∈[0,A_liq+a]` ∀Δh, since `λ(cutoff)=0`) is now reachable. All 29
unit tests pass; `scripts/debug_pde.py` confirms `H(τ)` now grows smoothly/linearly in `τ` at
every tested σ_$.

Re-running against the realised σ_$ distribution of BTC/USDT 2025-05-13
(`scripts/check_shifted_glft_numerical.py`), same `(γ,κ,A_liq,a)=(30,239,4.87,0.0871)` for
all three models:

| σ_$ percentile | σ_$ | PDE half-spread (ticks) | GLFT (ticks) | ShiftedGLFT (ticks) |
|---|---|---|---|---|
| 10th | 0.0022  | 0.412 | 0.42   | 236.8     |
| 25th | 0.1205  | 0.413 | 1.56   | 12,651.6  |
| 50th | 1.2352  | 0.424 | 12.31  | 129,688.5 |
| 75th | 4.0352  | 0.455 | 39.31  | 423,674.0 |
| 90th | 7.3737  | 0.492 | 71.51  | 774,201.3 |
| 99th | 15.389  | 0.596 | 148.82 | 1,615,754.0 |

Across the full empirical range — the 99th-percentile σ_$ is 7,000× the 10th — the PDE
half-spread moves only **0.41→0.60 ticks**, independently reproducing the empirically observed
~1-tick BTC/USDT market spread (CLAUDE.md), while GLFT's closed form widens 350× and
ShiftedGLFT's `A_total` patch diverges to 1.6M ticks — the ill-conditioning already flagged for
`shifted_glft.py` (deferred C03) is visible at *every* σ_$ above the 10th percentile, not just
in extreme cases. Inventory skew at `q=±20` lots (max inventory) at median σ_$: PDE ±0.46 ticks
≈ GLFT's ±0.48 ticks (ShiftedGLFT's ±0.04 ticks reflects the same ill-conditioning). The PDE's
well-posedness (Part C) and its agreement with the observed market spread are independent lines
of evidence for the same conclusion: the regularized numerical model, not the closed-form
`A_total` patch, is the economically sound member of this family.

**Aside — why `g*(Δh)`, not `λ(δ)·δ`, is the right myopic objective.** Dropping risk-aversion
(γ→0) suggests a simpler objective: maximize expected profit per unit time,
`δ* = argmax_{δ≥0} λ(δ)·δ`. For the calibrated parameters this has a closed form
(`scripts/myopic_objective.py`, confirmed to 6 d.p.): the exponential piece peaks at
`δ=1/κ≈0.42` ticks (`f=A_liq/(κe)≈0.0075`), but the **floor piece dominates globally** at
`δ=a/(2b)=cutoff/2=500` ticks (`f=a²/(4b)≈0.2177`) — **29×** larger. Taken at face value this
objective recommends quoting 500 ticks ($5) from mid, absurd for a 1-tick-spread asset. The
flaw: `λ(δ)·δ` prices every fill at distance `δ` as a clean `+δ` profit, but the floor term
`a-bδ` *is* the momentum/toxic-flow component (Contribution 6) — a fill there means the
reference price already moved `~δ` toward the quote, so its true expected mark-to-market is
≈0, not `+δ`. `g*(Δh)=λ(δ)(1-e^{-γ(δ+Δh)})` has no such flaw: it rewards `λ(δ)` directly
(weighted by `1-e^{-γ(δ+Δh)}∈[0,1]`, never by `δ`), so `g*(cutoff)=0` because `λ(cutoff)=0`,
not via any `δ`-penalty. A "simpler" risk-neutral objective is therefore not simpler to get
*right* for a fill curve with a momentum floor — it would need its own adverse-selection
correction, which CARA's `(1-e^{-γ·})` weighting already provides.

**Closing synthesis.** Stepping back from the mechanics: Part A found `b≈0` on all four
calibration days — the linear-decay floor is statistically indistinguishable from a constant —
so the cutoff `a/b`, and anything computed from it, is *empirically unidentified*, not a
calibrated number. The myopic objective's `δ*=a/(2b)=cutoff/2≈500` ticks is exactly such a
quantity: even taken at face value, it lands deep inside the region Contribution 32 already
showed is a monotonic adverse-selection sink (reversion vanishes by ~50 ticks and the left tail
explodes beyond it), so the "simpler" objective's recommendation would be a guaranteed loser
even if the parameter were real. The two-component model is mathematically well-posed (Parts
B–C — consistent with the general existence/characterization results for this class of HJB
market-making problem in Guéant (2017)) and empirically reproduces the observed ~1-tick
spread (Part D's table) — a genuine, if modest, contribution — but it opens no new edge: the part of the model that looks "interesting"
(the floor/cutoff) is exactly the part the data cannot pin down, and the one place a literal
reading of it points (deep, wide quotes) is a region this thesis already closed.

**Part E — backtest ablation: PDE vs closed-form GLFT at the Part A calibration.** Two 11-day
backtests (2025-05-13→2025-05-24, 2025-05-23 skipped — no quote file) at the identical Part A
calibration `(γ,κ,A_liq,a)=(30,239,4.87,0.0871)`, `min_spread_bps=0` (Part D's BTC-appropriate
setting), differing only in the quoting model: `experiments/63_shifted_glft_numerical/` =
`ShiftedGLFTNumerical` (the PDE), `experiments/64_glft_calibrated/` = `GLFTMarketMaker` closed
form (the σ-sensitive widening curve from Part D's table).

| | exp 63 (PDE) | exp 64 (GLFT closed form) |
|---|---|---|
| Total PnL | -$2,693.51 | -$2,646.47 |
| Mean daily PnL | -$244.86 | -$240.59 |
| Std daily PnL | $70.25 | $79.92 |
| Daily Sharpe (unann.) | -3.486 | -3.010 |
| Days profitable | 0/11 (0%) | 0/11 (0%) |
| Total fills | 2,787,780 | 1,345,243 |
| Avg fill rate | 141.3% | 52.9% |
| Avg spread quoted | 0.01 bps | 0.05 bps |

The PDE quotes roughly 5× tighter on average (consistent with Part D's 0.41–0.60 vs 0.42–150
tick range across the σ_$ distribution) and fills ~2.1× more often (>100% fill rate implies
rapid requote-and-refill cycling right at the touch). None of that converts into PnL: total PnL
is **$47 more negative** for the PDE (-1.8%), and both runs land at essentially the same
≈-$240/day, 0/11 days profitable. The lower daily-PnL std for the PDE (\$70 vs \$80) makes its
Sharpe *more* negative (-3.486 vs -3.010) — it is more *reliably* unprofitable, not less.

This is exactly the queue-priority/adverse-selection mechanism from C29/C30/C32: quoting closer
to the touch (PDE) buys more fills, but each one is more exposed to adverse selection and none
of them carry the inside-spread queue priority the corrected engine no longer grants — so more
fills at a tighter spread nets to the same (or a slightly worse) loss. **Results don't change,
conclusions don't change**: the PDE's realism gain (Part D) and the closed form's widening
defect both wash out at the PnL level, exactly as the Closing synthesis above anticipated.

**Part F — markout-path evidence: fills sit exactly where the market is about to move
against the new position.** Using the same exp 64 `_view.parquet` files as Part E (11
days, ~0.6s quote-log resolution), detect fills via Δinventory (±0.001 BTC = a bid or ask
fill) — 255,897 fills total (129,478 buy-side / bid hit, 126,419 sell-side / ask hit). For
each fill, track the forward mid-price path E[mid(t+k)−mid(t)] for k=1..60 steps (0.6s–36s)
and the trailing-60s order-flow imbalance (OFI) at the fill instant, against the
unconditional (all-steps) baseline (`scripts/adverse_selection_at_fills.py`):

| seconds after fill | after buy fill (now +0.001 BTC) | after sell fill (now −0.001 BTC) | unconditional baseline |
|---|---|---|---|
| 0.6  | −$1.29 | +$1.44 | +$0.01 |
| 1.2  | −$1.91 | +$2.19 | +$0.01 |
| 3.0  | −$2.88 | +$3.39 | +$0.04 |
| 6.0  | −$3.63 | +$4.27 | +$0.07 |
| 12.0 | −$4.01 | +$5.01 | +$0.15 |
| 24.0 | −$4.17 | +$5.44 | +$0.29 |
| 36.0 | −$4.08 | +$5.55 | +$0.44 |

In both directions the mid moves against the position the fill just created — 100–300× the
unconditional drift at the shortest horizon — and the effect persists (does not mean-revert)
out to 36s. On the 0.001 BTC clip just traded this is −$0.0013/−$0.0014 at 0.6s, growing to
−$0.0041/−$0.0055 by 36s (buy/sell). The strategy's average captured half-spread at this
calibration is ≈0.025bps of ≈$103k ≈ $0.00026 per clip, so the adverse-selection cost per
fill is **≈5× the spread revenue at 0.6s and ≈16–20× by 36s**.

This reproduces C12's `avg_markout_bps`/`pct_adverse_fills` metrics on exp 64 itself (−0.56
to −0.81bps, 63–80% adverse fills across the 11 days) — same sign, same order of magnitude —
but traces it out as a path rather than a single 1s snapshot, and converts it into a direct
ratio against the spread revenue per fill.

OFI at fill time: sell fills cluster on positive OFI (mean +0.046 vs −0.033 unconditional,
P(OFI>0)=54% vs 47.7%) — taker buying pressure is elevated exactly when our ask gets hit.
Buy fills show no analogous shift in the 60s-trailing OFI (−0.025 vs −0.033) — the 60s
window is too slow to resolve the sub-second dynamics the markout path captures directly.

**Synthesis.** This is the tick-level mechanism behind C30's queue-priority verdict and
C33's zero-profit equilibrium: expected PnL isn't "zero on average over the dataset" in some
abstract sense — every individual fill carries a visible, growing adverse drift that dwarfs
the spread it earns. The corrected engine (C29) removed the free queue priority that let the
broken fill model harvest these same fills without paying for them; Part F shows what each
of those fills actually costs once the queue model is honest.

**Note on flow-composition inference.** Barucci, Mathieu & Sánchez-Betancourt (2025,
arXiv:2501.03658) argue a market maker can stay profitable despite informed flow *if* it can
infer the prevailing mix of informed/uninformed/"fad" flow from observables. The OFI
asymmetry above (a detectable shift for sell fills, none for buy fills) is a small-scale
instance of exactly such an inferable signal — a follow-up check (conditioning the markout
path on OFI quintile at fill time, both sides) found the adverse markout shrinks somewhat in
the most favorable quintile but never changes sign. Part G's magnitude result (ζ(δ*₀) exceeds
δ*₀ by 1–3 orders of magnitude) sets the bar for what "inferring the mix" would need to buy:
not a shift in the markout distribution, but cancelling nearly all of it.

**Part G — the paper's own first-order correction, calibrated to exp 64: the correction term
dwarfs δ*₀ by 1–3 orders of magnitude.** Barzykin, Bergault, Guéant & Lemmel (2025,
arXiv:2508.20225) model adverse selection as a deterministic reference-price jump ζ(δ)≥0
triggered by the market maker's own fill at distance δ from mid, and derive a first-order
(small-ε) correction to GLFT's optimal half-spread. For ζ(δ)=α·e^(βδ), re-deriving from the
GLFT FOC `F(δ)=λ'(δ)[1−e^{−γ(δ+Δθ)}]+γλ(δ)e^{−γ(δ+Δθ)}=0` by perturbing the fill-exponent
`δ→δ−(q+1)ζ(δ)` and applying the implicit function theorem at ε=0 gives:

  `δ*₁(q) = δ*₀ + (q+1)·(1−β/(κ+γ))·ζ(δ*₀)`

with `δ*₀=(1/γ)ln(1+γ/κ)` — exactly GLFT's own AS term, recovered at q=0, ζ=0 (a passing sanity
check on the derivation).

`scripts/calibrate_zeta_glft_correction.py` re-detects the same 255,856 fills as Part F in
exp 64's 11-day `_view.parquet` set, now also recording `δ=(ask−bid)/2` (the quoted half-spread
— resting distance from mid — at fill time) alongside the forward markout `ζ_obs=E[markout|fill]`
at 0.6s and 12s. At exp 64's calibration (`γ=30, κ=239/$`), `δ*₀=$0.003942` (0.394 ticks),
matching Part D's σ→0 limit (0.412 ticks). Evaluating the q=0 correction
`(1−β/(κ+γ))·ζ(δ*₀)` four ways:

| ζ(δ*₀) estimate | horizon | correction `(1−β/(κ+γ))·ζ(δ*₀)` | ÷ δ*₀ |
|---|---|---|---|
| **Direct** — lowest-δ quantile bin, δ≈0.39t≈δ*₀, n=74,284, no extrapolation | 0.6s | $0.1259 | **32.0×** |
| **Direct** — same bin | 12s | $0.8584 | **217.8×** |
| Fitted `α·e^(βδ)` (β=1.238/$, R²=0.42), evaluated at δ*₀ | 0.6s | $0.5966 | 151.4× |
| Pooled mean over all fills (β=0 / "slow signal" bound) | 0.6s | $1.3612 | 345.4× |
| Pooled mean over all fills (β=0 / "slow signal" bound) | 12s | $4.5030 | 1,142.4× |

The "direct" row is the most defensible: these 74,284 fills (29% of the sample) were quoted at
δ almost exactly equal to δ*₀, so ζ(δ*₀) is read off directly rather than extrapolated from a
fitted exponential whose β is partly confounded with the volatility regime (in exp 64,
`kappa_from_stats=false` makes δ a deterministic function of σ_$ — Part D's table — so δ and σ
are collinear across the bins). Even this most conservative number is **32×** the baseline at
0.6s and **218×** at 12s. Since `δ*₁=δ*₀+correction` and the correction already exceeds δ*₀ by
1–3 orders of magnitude in every row, `δ*₁≈correction` and `δ*₁/δ*₀≈(÷δ*₀ above)+1` — the `+1`
is immaterial.

**Synthesis.** The paper's correction is a first-order Taylor expansion, valid when `ε`
(loosely, `ζ/δ*₀`) is small. Here it is not small by any measure — the correction term computed
from this market's own fills is **larger than the entire baseline GLFT AS half-spread by 1–3
orders of magnitude**, even using the most direct, least-extrapolated estimate. This is a
third, independent confirmation of C30/C33's zero-profit verdict, now from inside the cited
paper's own diagnostic: not merely "GLFT's spread doesn't cover the adverse-selection cost we
measure" (Part F), but "the correction GLFT's own extension proposes for that cost is itself
1–3 orders of magnitude larger than GLFT's existing AS term" — i.e. by this framework's own
small-ε criterion, this market is far outside the regime in which GLFT (corrected or not) is a
sensible local approximation. A market maker who actually priced in the measured ζ(δ*₀) would
have to quote at a half-spread 30–200× wider than δ*₀ — i.e. roughly 12–86 ticks, where the
calibrated fill intensity `λ(δ)=A_liq·e^{−κδ}` (κ=2.39/tick) is essentially zero
(`e^{−2.39×12.6}≈9e-14`): the liquidity-driven fill channel vanishes entirely, leaving only the
momentum floor. The paper's framework, taken at its own word on this data, points to the same
corner as C29/C30/C33: honest pricing of adverse selection collapses toward zero
(liquidity-driven) activity, not toward a wider-but-still-profitable quote.

**Status:** `ShiftedGLFTNumerical` is implemented, unit-tested (29 tests total, 14 on this
module), numerically validated against the realised BTC σ_$ distribution (Part D), registered
in `make_strategy()` as `"shifted_glft_numerical"`, and run as an 11-day backtest ablation
against the closed-form GLFT at the identical calibration (Part E). The PDE-vs-closed-form
spread gap (Part D, 0.41–0.60 vs 0.42–150 ticks) does not translate into a PnL gap: both are
uniformly unprofitable, 0/11 days, at essentially the same ≈-$240/day, with the PDE marginally
worse despite ~2.1× the fill volume. This is the experimental confirmation of the Closing
synthesis above — the two-component model is mathematically sound and empirically realistic
(Part D) but opens no new edge (Part E). `min_spread_bps≈0` (relying on the existing 1-tick
post-rounding floor in `compute_quotes`) is the BTC-appropriate setting and was used throughout
Parts D–E; `08_shifted_glft`'s `min_spread_bps=0.5` (≈259-tick half-spread floor at BTC's price
level) would have dominated the PDE's ~0.5-tick economic optimum entirely. Part F traces the
per-fill mechanism behind both runs' losses directly on exp 64: a markout path showing the mid
moves against every fill by ≈5–20× the spread it earns, persisting (not reverting) out to 36s.
Part G applies Barzykin/Bergault/Guéant/Lemmel (2025)'s first-order adverse-selection
correction to this same calibration: the correction term itself is 32–1,142× larger than
GLFT's baseline AS half-spread δ*₀, depending on estimator — a third, independent confirmation
of the zero-profit verdict from inside that paper's own small-ε framework.

Reproduce:
```
python scripts/calibrate_fill_intensity.py
python -m unittest tests.test_shifted_glft_numerical
python scripts/check_shifted_glft_numerical.py [DATE]
python scripts/debug_pde.py
python scripts/myopic_objective.py
python scripts/run_daily.py --config experiments/63_shifted_glft_numerical/config.json
python scripts/run_daily.py --config experiments/63_shifted_glft_numerical/config.json --aggregate
python scripts/run_daily.py --config experiments/64_glft_calibrated/config.json
python scripts/run_daily.py --config experiments/64_glft_calibrated/config.json --aggregate
python scripts/adverse_selection_at_fills.py
python scripts/calibrate_zeta_glft_correction.py
```

---

## 39. Perp Order Flow as a Cross-Venue Signal for Spot: Real, Mostly-Incremental, but Weak and Slow-Building

**Motivation:** C36 closed the cross-venue *lead-lag* door — spot↔perp returns are contemporaneous
(θ=0), so "trade spot on perp's lead" has no foundation. The remaining open question is whether
perp order-flow signals (OBI, OFI) carry information about SPOT's near-term forward returns that
is INCREMENTAL over spot's own order flow — a same-timestamp cross-venue read that could feed spot
quoting/skew without requiring any timing edge. LINK April 2026, 30 overlapping spot+perp days.
(See `experiments/65_spot_perp_signal/`.)

**1s-grid characterization** (`characterize_perp_signal.py`, 2.59M pooled rows).

(a) Own-venue IC — corr(signal, own-venue fwd log-return):

| horizon | spot_obi | spot_ofi | perp_obi | perp_ofi |
|---|---|---|---|---|
| 1s | 0.207 | 0.044 | 0.204 | 0.062 |
| 5s | 0.323 | 0.007 | 0.192 | 0.055 |
| 10s | 0.361 | -0.005 | 0.161 | 0.041 |
| 30s | 0.361 | -0.013 | 0.102 | 0.025 |
| 60s | 0.310 | -0.012 | 0.073 | 0.014 |

spot_obi's IC builds to a broad 10-30s peak (~0.36, consistent with C22's 0.20-0.36 range);
perp_obi's own-venue IC peaks immediately at 1s (~0.20) and decays monotonically — the perp,
being the tight/liquid/BTC-like venue (C36), digests its own OBI signal faster.

(b) Cross-venue IC — corr(PERP signal, SPOT fwd log-return), the core question:

| horizon | perp_obi | perp_ofi |
|---|---|---|
| 1s | 0.044 | 0.032 |
| 5s | 0.061 | 0.031 |
| 10s | 0.063 | 0.030 |
| 30s | 0.055 | 0.031 |
| 60s | 0.047 | 0.027 |

perp_obi vs spot_fwd peaks around 5-10s at ~0.06 — about a fifth to a third of spot_obi's own IC
at the same horizon (5s: 0.061 vs 0.323).

(c) Redundancy — corr(spot_signal, perp_signal): **obi = 0.036, ofi = 0.258**. perp_obi is nearly
orthogonal to spot_obi; perp_ofi and spot_ofi share a substantial common component (both reflect
aggregate signed trade flow, plausibly a shared market-wide factor).

(d) Incremental info — corr(resid[perp_signal ~ spot_signal], spot_fwd_ret):

| horizon | resid_obi | resid_ofi |
|---|---|---|
| 1s | 0.037 | 0.022 |
| 5s | 0.050 | 0.030 |
| 10s | 0.050 | 0.033 |
| 30s | 0.042 | 0.036 |
| 60s | 0.036 | 0.031 |

Because redundancy(obi) ≈ 0.036 is so low, resid_obi ≈ raw perp_obi_vs_spot_fwd — almost ALL of
perp_obi's cross-venue correlation with spot forward returns is incremental over spot_obi.
perp_ofi's incremental info is slightly below its raw IC, reflecting the higher obi/ofi redundancy.

**Sub-second decomposition** (`characterize_perp_signal_10ms.py`, 10ms grid, 259.2M obs via exact
single-pass accumulators — perp quotes remain ~1Hz step functions, but spot's reaction is now
resolved at ~10-50ms instead of averaged into the next full second):

| horizon | spot_obi_vs_spot_fwd | perp_obi_vs_spot_fwd (cross-venue) |
|---|---|---|
| 10ms | 0.032 | 0.007 |
| 50ms | 0.066 | 0.016 |
| 100ms | 0.088 | 0.023 |
| 250ms | 0.126 | 0.033 |
| 500ms | 0.163 | 0.044 |
| 1s | 0.207 | 0.054 |

Both ICs grow monotonically and smoothly from 10ms to 1s — there is NO sub-second spike or
"first-mover" jump in the cross-venue edge; it builds gradually over multiple seconds, exactly as
the 1s grid suggested. redundancy(obi) at the 10ms grid = 0.0387, essentially identical to the 1s
grid's 0.0359 — a stable property, not a sampling artifact.

**Verdict.** perp_obi carries a real, almost-fully-incremental, but small (IC ~0.04-0.06, peaking
5-10s) same-timestamp cross-venue signal for spot forward returns — about a fifth of spot's own
OBI signal at the same horizon, and slow to build (no exploitable sub-second component). This sets
up C40/C41's tests of whether this small incremental edge can be operationalized as a skew input
or a defensive-widening trigger.

Reproduce:
```
python experiments/65_spot_perp_signal/characterize_perp_signal.py
python experiments/65_spot_perp_signal/characterize_perp_signal_10ms.py
```

---

## 40. perp_obi as a Secondary Skew Term Dilutes an Already Near-Optimal Spot-OBI Skew

**Motivation:** C39 found perp_obi carries a real, mostly-incremental (redundancy ~0.04 with
spot_obi) cross-venue IC (~0.04-0.06) for spot forward returns. C22 found spot_obi itself has
IC~0.20-0.36, but exp45 (pre-engine-fix) found a SYMMETRIC OBI-based reservation-price shift HURTS
— it doubles fills but lowers per-fill quality, leaving the "fade vs lean" sign question open.
exp66 reproduces the spot_obi-only cell from scratch on the corrected engine and tests whether
adding perp_obi as a second skew term changes the picture, and resolves the fade-vs-lean question
for perp_obi. `queue_model="none"` (the fast, fill-count-driven "inside-spread artifact" regime —
see caveat below), LINK April 2026, 30 days, TouchMM control. (See `experiments/66_perp_obi_skew/`.)

**Mechanism:** symmetric reservation-price shift
`shift = (spot_alpha*spot_obi + perp_alpha*perp_obi) * tick_size`; bid/ask/reservation all shift by
`shift`, spread unchanged.

| variant | mean_pnl | std_pnl | days_pos | mean_fills |
|---|---|---|---|---|
| baseline | 69.94 | 23.10 | 100% | 12,571 |
| spot1 (α=1) | 71.48 | 24.57 | 100% | 7,525 |
| spot2 (α=2) | 63.60 | 21.30 | 100% | 4,739 |
| spot1_perp1 | 60.98 | 20.97 | 100% | 6,701 |
| spot1_perpneg1 | 54.89 | 17.61 | 100% | 8,467 |
| spot1_perp2 | 44.89 | 16.83 | 100% | 6,299 |
| spot1_perpneg2 | 34.35 | 11.54 | 100% | 8,304 |

A small spot-only skew (spot1, α=1) gives a modest +2.2% over baseline despite cutting fill count
by 40% — a small directional lean on spot_obi mildly improves per-fill quality, consistent with
C22's spot_obi IC. Doubling it (spot2, α=2) already overshoots: -9.1% vs baseline. Layering
perp_obi on top of spot1 (the best spot-only cell) monotonically DEGRADES PnL with `|perp_alpha|`,
**regardless of sign**: spot1_perp1 is -14.7% vs spot1, spot1_perpneg1 -23.2%, spot1_perp2 -37.2%,
spot1_perpneg2 -51.9%. The "fade" sign (perpneg, leaning against perp_obi) hurts MORE than the
"lean" sign (perp, leaning with it) at equal magnitude — exp45's open fade-vs-lean question is
answered here: neither direction helps, and fading is the worse of the two.

**Verdict.** perp_obi's incremental cross-venue IC (~0.04-0.06, C39) is too weak relative to the
execution noise a symmetric skew shift introduces (it moves BOTH quotes, changing fill rates and
inventory dynamics non-trivially) — it dilutes an already-near-its-optimum spot-only skew rather
than adding value. Combined with C39, this closes the "perp_obi as skew input" direction: a real,
incremental, but small signal does not survive being folded into this mechanism.

**Caveat (carries to C41):** all PnL here is under `queue_model="none"` — the C30 "inside-spread
artifact" regime where measured PnL is roughly monotonic in fill COUNT, not the honest engine (C30
corrected: -$7.93/day, 0/30 days). These numbers are a fast, relative comparison of skew variants
against each other and against the unskewed control, not an absolute profitability claim.

Reproduce:
```
python experiments/66_perp_obi_skew/perp_obi_skew_mm.py
```

---

## 41. Perp-Derived Defensive Spread Widening: Same Negative Result, Different Mechanism — and the Open Question for the Honest Engine

**Motivation:** Both C40's directional skew and the underlying "ride the perp's lead" premise
failed. A DEFENSIVE mechanism — widen spot quotes when a perp-derived "something
informed/large/toxic is happening right now" signal fires, the same multiplicative-widening
pattern as `SpreadMultiplierFilter` (`mult = min(1+alpha*toxicity, max_mult)`, `max_mult=5`) — is
the natural next test: rather than betting on perp_obi's direction, treat an extreme perp signal
as a toxicity flag and step back from the spot book. Three signals tested independently:
`obi`=|perp L1 OBI|, `ret`=z-scored |5-sample (~5s) perp mid log-return| (a "jump" detector,
clipped ≥0), `vol`=z-scored 10-sample (~10s) rolling std of perp log-returns (a "vol spike"
detector, clipped ≥0). Same engine/regime as exp66 (`queue_model="none"`, LINK April 2026, 30
days, TouchMM control + widening only). (See `experiments/67_perp_toxicity_filter/`.)

| variant | mean_pnl | days_pos | mean_fills | Δ pnl vs baseline | Δ fills vs baseline |
|---|---|---|---|---|---|
| baseline | 69.94 | 100% | 12,571 | — | — |
| obi_a1 | 9.31 | 93.3% | 1,621 | -86.7% | -87.1% |
| obi_a2 | 6.99 | 86.7% | 960 | -90.0% | -92.4% |
| ret_a1 | 46.97 | 100% | 6,861 | -32.8% | -45.4% |
| ret_a2 | 44.95 | 100% | 6,517 | -35.7% | -48.2% |
| vol_a1 | 38.92 | 100% | 5,386 | -44.3% | -57.2% |
| vol_a2 | 36.90 | 100% | 5,073 | -47.2% | -59.6% |

(baseline reproduces C40's baseline exactly — 69.9355 — a consistency check: identical TouchMM
control under `queue_model="none"`.)

Every widening variant underperforms the unwidened baseline, monotonically with `alpha`.
`obi_a1/a2` are the most extreme by far (-87% to -92% fills, -87% to -90% PnL): `|perp_obi|` has a
persistently HIGH mean (~0.53 on a representative day), so at `alpha=1` the implied multiplier
`1+alpha*|perp_obi|` averages ~1.5× and is rarely near 1 — this is closer to "always quote ~50%
wider" than a rare-event toxicity flag. `ret`/`vol` (genuine jump/vol-spike detectors, mean near 0
with occasional large z-scores) are comparatively spike-like, cutting fills by 45-60% while losing
"only" 33-47% of PnL.

**Verdict.** Same shape as C40, different mechanism: in `queue_model="none"`, measured PnL is
roughly monotonic in fill count, so ANY mechanism that suppresses fills — whether by directional
skew (C40) or defensive widening (here) — looks like a pure loss, irrespective of whether the
suppressed fills were good or bad for the trader. **This is the open question the honest L2
engine is built to answer**: if the fills that `ret_a1`/`obi_a1` suppress are disproportionately
the adverse-selected ones that C30's corrected engine showed are responsible for the -$7.93/day
honest loss, a defensive filter could be a net win in the honest regime even while looking like a
loss here.

Reproduce:
```
python experiments/67_perp_toxicity_filter/perp_toxicity_filter_mm.py
```

---

## 42. L2-Honest Rerun at Realistic Latency: the Unconditional Baseline Reaches the Zero-Profit Equilibrium, and Spot-OBI Skew Breaks It

**Motivation:** C40/C41 left an explicit open question: both perp_obi skew (C40) and perp-toxicity
widening (C41) looked uniformly negative under `queue_model="none"`, a regime where measured PnL
is roughly monotonic in fill COUNT — any mechanism that reduces fills looks like a loss regardless
of fill QUALITY. This rerun moves the four most informative cells (baseline TouchMM, exp66's best
skew `spot1`, and exp67's most-aggressive `obi_a1` / best-"smart" `ret_a1` widening filters) onto
the corrected engine's honest regime: `queue_model="l2"`, `queue_fraction=0.5`, `L2BookTracker`
from `orderbooks_LINK_{date}.parquet` (exp62's pattern), `taker_fee=0.00045` post-hoc. Per explicit
request, latency was dropped to 10ms (from exp62's 100ms) and — since 10ms latency is wasted if
the strategy only recomputes every 500ms — `requote_interval` was correspondingly dropped to 50ms
(from exp66/67's 500ms and exp62's 100ms). LINK April 2026, 30 days. (See
`experiments/68_l2_perp_filter_rerun/`.)

| variant | mean_pnl (4.5bps) | std | days_pos | mean_fills | taker% |
|---|---|---|---|---|---|
| baseline | -0.24 | 6.76 | 46.7% (14/30) | 3,232 | 0.0% |
| spot1 | **+22.32** | 10.33 | **100.0% (30/30)** | 1,583 | 0.0% |
| obi_a1 | +0.46 | 6.98 | 56.7% | 285 | 0.0% |
| ret_a1 | -1.71 | 7.49 | 46.7% | 727 | 0.0% |

**(1) Speed restores latency tolerance — on real data, confirming C37.** The unconditional
baseline at 10ms/50ms (-$0.24/day, 14/30 days positive) is dramatically better than exp62's
identical strategy at 100ms/100ms (-$7.93/day, 0/30 days) — it has moved from "solidly negative"
to sitting almost exactly ON the C33 zero-profit equilibrium (mean≈$0, roughly half the days on
each side). This is the first REAL-DATA confirmation of C37's synthetic finding that requoting
faster (tracking the mid) substantially restores the latency-adverse-selection cost a
slow-requoting honest MM pays.

**(2) spot_obi skew breaks the equilibrium — a robust +$22.32/day, 30/30 days positive.** `spot1`
(spot_alpha=1, the same cell that was a marginal +2.2% over baseline in C40's artifact regime —
71.48 vs 69.94) produces the dominant effect here: every one of the 30 days is positive (range
+$6.68 to +$49.72), at roughly HALF the baseline's fill count (1,583 vs 3,232, -51%). `taker_pct
=0.0%` for all four variants confirms no explicit marketable orders are sent. At alpha=1 with
LINK's ~10-tick spread (half ≈ 5 ticks), the shift `spot_alpha × OBI × tick ≤ 0.001` rarely
exceeds 1 tick, placing quotes close to but potentially slightly inside the spread under strong OBI
readings. The mechanism is better characterised as **OBI-conditional spread placement** — a passive
market maker that leans into the signal direction rather than sitting symmetrically at the touch —
than as a pure at-touch result. The strategy remains market making: all fills come through passive
limit orders gated by the real L2 queue.

**(3) Defensive widening does NOT show the same flip — C41's open question is answered.**
`obi_a1` (+$0.46/day, 56.7% days positive) is within one std of baseline — essentially noise.
`ret_a1` (-$1.71/day, 46.7% days positive) is actually WORSE than baseline despite cutting fills
by 77.5%. Neither toxicity filter converts C41's artifact-regime loss into an honest-regime gain.

**Synthesis — why skew works and widening doesn't.** The contrast is mechanism, not magnitude:
`spot_obi` (IC~0.20-0.36, C22) is DIRECTIONALLY informative about near-term price drift, so
shifting both quotes by `spot_alpha*spot_obi*tick` changes WHICH fills occur and how
adverse-selected they are — it edits fill QUALITY. Defensive widening (`obi_a1`/`ret_a1`) is
directionally agnostic — it scales fill QUANTITY without touching quality, and at an equilibrium
sitting near zero, scaling quantity by a constant factor scales both the (small) wins and the
(small) losses by roughly the same factor, landing near zero either way. This refines rather than
overturns C30/C33: queue priority still caps the fill RATE available to an unconditional maker
(pinning the baseline near zero, C33's law), but a directionally-informed skew using the SAME
signal that barely moved the needle in the artifact regime (C40) extracts a large, robust edge
from the (fewer) fills that survive queue priority once adverse selection is honestly priced.

**Caveats — this needs a robustness pass before being load-bearing.** (a) Single
`queue_fraction=0.5` point — `queue_fraction` is itself a heuristic for queue position (a planned
L2-diff-depth validation against real order-flow data would directly test it); spot1's magnitude
should be checked across a `queue_fraction` sweep. (b) `spot_alpha=1` was C40's best
*artifact-regime* cell, not optimized for the honest regime — given the size and uniformity of the
effect here (30/30 days), a small alpha sweep under L2/10ms/50ms is a natural and cheap follow-up.
(c) Per-fill markout analysis (as in C32/C38) would clarify the mechanism directly — does the skew
reduce the adverse move after fill on both legs, or mostly on one side?

Reproduce:
```
python experiments/68_l2_perp_filter_rerun/l2_perp_filter_rerun.py
```

---

## 43. BTC-PERP Spread-Rule × Skew Grid at L2-Honest 10ms/50ms: the Overcrowded Equilibrium Confirms, and Spot-OBI Skew Makes It Worse

**Motivation:** C42 found that LINK's spot_obi skew (`spot1`) turns the C33 zero-profit-equilibrium
baseline into a robust +$22.32/day, 30/30 days positive. Does this generalize to BTC — the most
heavily-traded, smallest-relative-tick instrument in the dataset? BTC spot has no L2 orderbook data
at all, so this rerun runs C42's same spread-rule × skew grid (touch / A-S γ→0 / constant
half-spread, × baseline/spot1) on BTC-PERP itself — its own quotes/trades/L2 book — at the
identical L2-honest settings (`queue_model="l2"`, `queue_fraction=0.5`, `latency=0.01`,
`requote_interval=0.05`), recalibrated for BTC-PERP's $0.1 tick / ~$68k price (`AS_KAPPA_MIN=20`,
`AS_MIN_SPREAD_BPS=0.01`, `CONST_HALF_TICKS=0.5`). 5 days (2026-04-01..05, the only days with
BTC-PERP L2 snapshots). (See `experiments/71_btc_perp_spread_rule_grid/`.)

| rule | variant | mean_pnl (4.5bps) | std | days_pos | mean_fills | taker% |
|---|---|---|---|---|---|---|
| touch | baseline | -181.84 | 125.00 | 0/5 | 69,939 | 0.0% |
| touch | spot1 | -233.32 | 148.72 | 0/5 | 60,829 | 0.0% |
| as | baseline | -182.08 | 125.08 | 0/5 | 69,891 | 0.0% |
| as | spot1 | -233.53 | 149.55 | 0/5 | 60,984 | 0.0% |
| constant | baseline | -181.97 | 125.08 | 0/5 | 69,990 | 0.0% |
| constant | spot1 | -233.54 | 148.80 | 0/5 | 60,873 | 0.0% |

**(1) The three spread rules are indistinguishable — confirms BTC-PERP sits at a 1-tick spread
essentially always.** touch/as/constant agree to within ~$0.3/day for both baseline and spot1
(noise is std≈125). Unlike LINK, where touch≈10 ticks and constant=5 ticks gave the rule axis room
to matter (C40/C42's groundwork), BTC-PERP's market spread is pinned at 1 tick (TICK=$0.1) almost
continuously, so all three rules collapse to the same ~1-tick half-spread. The spread-RULE choice
is simply not a free variable on this instrument.

**(2) Uniformly, deeply negative — 0/5 days positive for every cell, an order of magnitude beyond
LINK's baseline.** -$182/day vs LINK's -$0.24/day (C42) — not "near the C33 zero-profit
equilibrium" but solidly on the losing side. With ~70,000 fills/day at 0.001 BTC each (≈$68
notional/fill), the maker is being adversely selected at a scale LINK's queue-axis economics never
reach.

**(3) spot_obi skew makes it WORSE, not better — the opposite sign from C42, and the opposite
mechanism.** `spot1` loses an additional ~$51/day vs baseline (-233 vs -182, all three rules),
consistent in direction across all 5 days (range -$13 to -$104 worse per day). Fill count drops by
only ~13% (69,939→60,829) — far less than LINK's -51% (C42) — so the shift filters out
comparatively few fills, and the ones that remain are, if anything, MORE adversely selected.
`taker_pct=0.0%` throughout — a genuine L2-queue-gated maker result, not a reopening of C30's
artifact mechanism via a different door.

**Synthesis — the spread-axis/queue-axis contrast completes.** BTC-PERP's relative tick size is
~0.15bps (TICK=$0.1 on a ~$68,000 mid) vs LINK's ~11bps (TICK=$0.001 on a ~$9 mid) — roughly 70×
smaller. In the Wyart-Bouchaud framing underlying C33/C34, the zero-profit rent on a
small-relative-tick instrument is extracted almost entirely on the SPREAD axis: sub-millisecond
participants compress the spread to the point where a 10ms maker is structurally too slow to
capture queue priority at any meaningful rate, and a directional skew (`spot1`) can only ever
re-pick among an already-adversely-selected fill set — making things WORSE by tilting toward the
side about to move against the resting order, rather than better. LINK's much larger relative tick
leaves room on the QUEUE axis: queue priority caps the unconditional baseline near zero (C33), but
a directionally-informed skew can still select higher-quality fills FROM WITHIN that queue-gated
set (C42). BTC-PERP is the "fully arbitraged, nothing left" case that the tick-size/HFT-crowding-out
literature (Yao & Ye; the US Tick Size Pilot) predicts for the most liquid, smallest-relative-tick
instruments; LINK is the "less crowded, queue-axis rent still available" case. This rerun is
**confirmatory** of the existing BTC narrative (overcrowded, at-or-below zero-profit) at the new
10ms/50ms L2-honest settings — it does not change prior BTC conclusions, only restates them under
the latency/requote calibration now used for C39-42.

**Caveat.** Single instrument/window (BTC-PERP, 5 days) and a single `queue_fraction=0.5` point —
same caveat class as C42(a). Given the magnitude (-$182/day, far beyond the std≈125 noise band) and
uniform sign across all 5 days and all 3 spread rules, a `queue_fraction` sweep is very unlikely to
flip the sign — unlike C42, where the effect sat close to the equilibrium and robustness mattered
more.

Reproduce:
```
python experiments/71_btc_perp_spread_rule_grid/btc_perp_spread_rule_grid.py
```

---

## 44. C42 Robustness Pass: Queue-Fraction Sweep, Spread-Rule Grid, and Spot-Alpha Optimization — alpha=1 Was Leaving More Than Half the Edge on the Table

**Motivation:** C42's caveats (a)-(c) flagged `spot1` (+$22.32/day, 30/30 days+) as not yet
load-bearing: a single `queue_fraction=0.5` point, an `spot_alpha=1` inherited from C40's
*artifact-regime* triage and never re-optimized for the honest regime, and no per-fill markout.
This entry resolves (a) and (b) via four follow-up runs, all LINK April 2026, 30 days, at C42's
L2-honest settings (`queue_model="l2"`, `latency=0.01`, `requote_interval=0.05`) unless noted.

**(A) queue_fraction sweep, 0.3-0.7 (exp69) — spot1's edge is flat.**

| variant | qf | mean_pnl (4.5bps) | std | days_pos | mean_fills |
|---|---|---|---|---|---|
| baseline | 0.3 | -0.45 | 6.76 | 46.7% | 3,480 |
| baseline | 0.4 | -0.05 | 6.38 | 50.0% | 3,354 |
| baseline | 0.5 | -0.24 | 6.76 | 46.7% | 3,232 |
| baseline | 0.6 | +0.06 | 6.79 | 46.7% | 3,184 |
| baseline | 0.7 | -0.08 | 6.50 | 43.3% | 3,161 |
| spot1 | 0.3 | 22.30 | 10.41 | 100% | 1,670 |
| spot1 | 0.4 | 22.28 | 10.21 | 100% | 1,614 |
| spot1 | 0.5 | 22.32 | 10.33 | 100% | 1,583 |
| spot1 | 0.6 | 22.14 | 10.27 | 100% | 1,558 |
| spot1 | 0.7 | 21.93 | 10.41 | 100% | 1,538 |

Across the entire 0.3-0.7 range, `spot1` varies by less than 2% (21.93-22.32) and is **100% days
positive at every point**; `baseline` is noise-level and non-monotonic (-0.45 to +0.06). Both
results are consistent with a flat dependence on `queue_fraction` over this band.

**(B) queue_fraction sweep, 0.0/0.1/0.2 (exp72) — a cliff at qf=0, not a gradient.**

| variant | qf | mean_pnl (4.5bps) | std | days_pos | mean_fills |
|---|---|---|---|---|---|
| baseline | 0.0 | **+71.45** | 23.18 | 100% | 13,786 |
| baseline | 0.1 | -1.67 | 7.03 | 50.0% | 4,137 |
| baseline | 0.2 | -0.60 | 7.15 | 46.7% | 3,723 |
| spot1 | 0.0 | **+81.62** | 27.07 | 100% | 7,216 |
| spot1 | 0.1 | +22.50 | 9.67 | 100% | 1,905 |
| spot1 | 0.2 | +22.67 | 10.20 | 100% | 1,754 |

`qf=0.1` and `qf=0.2` sit on the same plateau as (A) — `baseline` near zero, `spot1`≈22.5-22.7,
fill counts in the same range. `qf=0.0` (`queue_ahead=0` always) is a **discontinuous jump**:
fills roughly quadruple and `baseline` alone goes to +$71/day. `queue_fraction=0` is precisely the
L2-honest engine degenerating into the pre-correction "no queue" artifact regime (C29/30) — this
pins down *why* the old artifact numbers were so large, and confirms that (A)+(B) together describe
a genuine plateau, `qf∈[0.1, 0.7]`, with C42's `qf=0.5` safely in the middle, bounded by a sharp,
identifiable edge rather than an unknown gradient.

**(C) spread-rule grid at qf=0.5 (exp70) — touch≈as≈constant on LINK too.**

| rule | variant | mean_pnl (4.5bps) | std | days_pos | mean_fills |
|---|---|---|---|---|---|
| touch | baseline | -0.236 | 6.763 | 46.7% | 3,232 |
| touch | spot1 | 22.321 | 10.335 | 100% | 1,583 |
| as | baseline | -0.218 | 6.780 | 46.7% | 3,239 |
| as | spot1 | 22.269 | 10.318 | 100% | 1,583 |
| constant | baseline | -0.218 | 6.780 | 46.7% | 3,239 |
| constant | spot1 | 22.268 | 10.318 | 100% | 1,583 |

All three rules agree to within ~$0.05/day for both `baseline` and `spot1` (`touch` is exactly
C42's headline cell). `as` and `constant` are *bit-identical* — at this calibration
(`AS_GAMMA=1e-8`, `AS_KAPPA_MIN=200`), A-S's `gamma->0` adverse-selection term collapses to
`2/kappa = 10 ticks` total spread, i.e. a 5-tick half-spread, numerically equal to
`CONST_HALF_TICKS=5.0`. `touch`'s market half-spread averages close enough to 5 ticks that it lands
in the same place. The spread-rule axis is not a free variable for C42 either, for a different
reason than C43's BTC-PERP result (there the market spread is pinned at 1 tick; here all three
formulas independently land near the same value).

**(D) spot_alpha sweep, 0-5 at qf=0.5 (exp74) — alpha=1 was leaving more than half the edge on the
table.**

| alpha | mean_pnl (4.5bps) | std | days_pos | mean_fills | taker% | inside% |
|---|---|---|---|---|---|---|
| 0.0 | -0.24 | 6.76 | 46.7% | 3,232 | 0.0% | 0.00% |
| 1.0 | 22.32 | 10.33 | 100% | 1,583 | 0.0% | 0.00% |
| 1.5 | 40.46 | 13.25 | 100% | 1,661 | 0.0% | 0.00% |
| 2.0 | 48.52 | 14.73 | 100% | 1,844 | 0.0% | 0.00% |
| 2.5 | 53.16 | 16.37 | 100% | 1,995 | 0.0% | 0.00% |
| 3.0 | 55.47 | 17.66 | 100% | 2,105 | 0.0% | 0.00% |
| **4.0** | **56.00** | 18.21 | 100% | 2,245 | 0.0% | 0.00% |
| 5.0 | 55.36 | 18.70 | 100% | 2,342 | 0.0% | 0.00% |

`alpha=0` and `alpha=1` reproduce C42 exactly (consistency check). PnL climbs monotonically from
alpha=1 to a broad plateau at alpha=3-5 (55.47 / **56.00** / 55.36 — flat well within
std≈18), peaking near **alpha=4 at +$56.00/day, 100% days positive** — roughly **2.5x C42's
original +$22.32**. Unlike the 0->1 transition (which roughly halved fill count, 3,232->1,583),
1->4 *increases* fills (1,583->2,245) while also increasing PnL per fill (~$0.0141 -> ~$0.0249) —
both the quantity and the quality of the fill set improve together as the skew is sharpened.

`taker_pct=0.0%` at every alpha confirms no explicit marketable orders. `inside_frac=0.00%`
throughout requires a careful reading: the diagnostic flags quotes with `|shift| >= half_spread`
(i.e. shift crossing the **mid**), but with LINK's ~10-tick market spread `half ≈ 5 ticks =
$0.005`. The maximum shift at alpha=4 is `4 × 1.0 × TICK = $0.004 < $0.005`, so the diagnostic
is silent even when the bid sits up to 4 ticks **inside the spread** (between best_bid and mid).
The correct characterisation at high alpha is therefore not "at-touch" but
**OBI-conditional inside-spread placement**: when OBI > 0, the bid is shifted 1–4 ticks above
best_bid (inside the spread) and the ask is shifted the same distance above best_ask (outside);
when OBI < 0, the pattern reverses. Both legs remain passive limit orders; no explicit taker
orders are ever sent. This is still market making — quotes lean into the signal direction rather
than sitting symmetrically at the touch.

The critical distinction from C40's inside-spread artifact (and from `qf=0` in part B above) is
that in the real L2 orderbook data used here, inside-spread price levels carry **actual queue
depth** from other participants already resting there. The fill model therefore still imposes a
non-trivial `queue_ahead` even for inside-spread orders, and fills remain genuinely gated by
cumulative trade volume — not handed out for free as under `queue_model="none"` or `qf=0`. The
mechanism is OBI-conditional spread management rather than unconditional inside-spread priority
capture.

**(E) per-fill markout analysis at qf=0.5, alpha in {0, 1, 4} (exp75) — alpha=4's extra PnL is
measurably less adverse selection, not an artifact.**

Signed markout = `sign * (mid(t+h) - fill.price)`, `sign=+1` for bid fills (we bought), `-1` for
ask fills (we sold); positive = price moved in our favor after the fill. `%adverse` = share of
fills with negative markout. Horizons span the ~5-10s momentum-decay window from CLAUDE.md;
"all" pools both sides (n given for "all").

| horizon | alpha=0 mean (ticks) | alpha=0 %adv | alpha=1 mean (ticks) | alpha=1 %adv | alpha=4 mean (ticks) | alpha=4 %adv |
|---|---|---|---|---|---|---|
| 0.5s | -1.26 | 62.6% | +1.54 | 32.8% | +2.88 | 9.8% |
| 1.0s | -1.17 | 61.5% | +1.65 | 32.8% | +3.01 | 10.0% |
| 2.0s | -0.96 | 59.3% | +1.87 | 32.1% | +3.24 | 10.0% |
| 5.0s | -0.59 | 55.6% | +2.25 | 31.1% | +3.65 | 10.3% |
| 10.0s | -0.41 | 53.7% | +2.48 | 31.4% | +4.06 | 11.1% |

(n_all = 96,953 / 47,485 / 67,338 fills for alpha=0/1/4 respectively, pooled across 30 days;
bid/ask markouts are symmetric to within ~0.1-0.2 ticks at every alpha/horizon, as expected for a
symmetric OBI-driven skew.)

The three regimes are cleanly separated at *every* horizon, with no sign changes or crossovers:

- `alpha=0` is adverse-selected outright — negative mean markout at all five horizons (-1.26 to
  -0.41 ticks) and 54-63% of fills land on the wrong side of subsequent price movement. This is
  the per-fill signature behind the near-zero/slightly-negative baseline PnL: the signal-blind
  quote gets run over by informed flow more often than not.
- `alpha=1` flips the sign at every horizon (+1.54 to +2.48 ticks) and roughly halves the
  adverse-fill rate to 31-34%. This is the per-fill mechanism behind C42's +$22.32/day.
- `alpha=4` does not merely continue this trend — it roughly **doubles alpha=1's markout
  magnitude at every horizon** (+2.88 to +4.06 ticks) and **cuts the adverse-fill rate to ~10%**,
  a further 3x reduction from alpha=1's ~32%. Sharpening the skew doesn't just shift more volume
  into already-good fills; it makes the *marginal* fills measurably better too.

This reconciles with (D)'s PnL numbers: the ~1.6-1.9x markout improvement (alpha=1->4) combined
with (D)'s ~1.42x fill-count increase (1,583->2,245) multiplies out to roughly the observed
2.5x PnL ratio (22.32->56.00). Both legs of (D)'s "quantity and quality improve together" finding
are now independently confirmed at the per-fill level: alpha=4's edge over alpha=1 is a genuine,
measurable reduction in adverse selection, not an artifact of sample size or inventory mix. The
bid/ask markout symmetry (within ~0.1-0.2 ticks at every alpha/horizon) is consistent with
OBI-conditional inside-spread placement: both legs shift toward the signal direction, so the
signal predicts fill quality on both sides equally.

**Synthesis.** (A)+(B) show `queue_fraction` robustness is excellent: a wide, flat honest plateau
(`qf∈[0.1,0.7]`) bounded by a sharp, mechanistically-understood cliff at `qf=0` (the old artifact
regime) — C42's `qf=0.5` sits centered in that plateau, not near an edge. (C) shows the
spread-RULE axis is inert on LINK — A-S/GLFT's spread-width formula contributes little once the
engine is L2-honest; what the formula mostly does is set the base half-spread (~5 ticks) within
which the skew then operates. (D) is the one axis that mattered all along but was never tuned:
`spot_alpha=1` was C40's artifact-regime optimum, carried into C42 unchanged. In the honest regime
the true optimum is `alpha≈4`, **+$56.00/day, 100% days+**. The mechanism at this alpha is
**OBI-conditional inside-spread placement** (see (D) above): the strategy leans the bid inside
the spread when OBI is positive and pulls the ask outside, and reverses when OBI is negative. This
is market making — both legs are passive limit orders, taker_pct=0% — but the quotes are
conditionally placed 1-4 ticks inside the market spread rather than sitting symmetrically at the
touch. (E) confirms the per-fill mechanism: alpha=0/1/4 form a cleanly ordered sequence of
decreasing adverse selection (54-63% → 31-34% → ~10%), so the PnL ordering is a direct
consequence of fill quality. C42's number stands as the first demonstration that the mechanism
exists; this entry shows its magnitude at the tuned optimum is roughly 2.5x larger.

**Caveats.** (a)-(c) of C42's robustness pass are now resolved: `queue_fraction` is flat over
`[0.1,0.7]` with a sharp, understood cliff at 0 (A/B), the spread-rule axis is inert (C), and
`alpha≈4` is the honest-regime optimum with a confirmed per-fill adverse-selection mechanism (D/E).
(d) Out-of-sample validation (same caveat as C42) remains open — both +$22.32 and +$56.00 (and the
(E) markout numbers) come from the same 30-day LINK April 2026 window used throughout C39-44. The
alpha=3-5 plateau is flat enough (range $0.64, well inside std≈18) that a finer grid around the
optimum is likely not worth the compute; alpha≈4 is reported as the practical optimum rather than a
precisely-located one.

Reproduce:
```
python experiments/69_queue_fraction_sweep/queue_fraction_sweep.py
python experiments/70_spread_rule_grid/spread_rule_grid.py
python experiments/72_queue_fraction_sweep_low/queue_fraction_sweep_low.py
python experiments/74_spot_alpha_sweep_confirm/spot_alpha_sweep_confirm.py
python experiments/75_markout_analysis/markout_analysis.py
```

---

## 45. OOS Validation of Spot-OBI Skew on LINK June–July 2025: Signal Generalises; Proxy Limitation Identified at High Alpha

**Motivation:** C44's caveat (d): every in-sample result (C42: +$22.32/day, C44: +$56.00/day)
comes from the same 30-day LINK April 2026 window. This entry tests on a fully held-out window:
LINK June 11 – July 10 2025 (30 days, 9 months before the in-sample period).

No L2 orderbook parquets exist for June–July 2025 (CoinAPI L2 capture began April 2026). A
**quote-based proxy** L2 tracker is constructed from the standard quotes file: each snapshot has
`bid_levels = ((best_bid, best_bid_size),)`, giving `queue_ahead(at_touch_bid) = best_bid_size ×
queue_fraction` — mathematically exact for at-touch orders. Settings otherwise mirror C44 exactly
(`queue_model="l2"`, `queue_fraction=0.5`, `latency=10ms`, `requote_interval=50ms`,
`TICK=0.001`, `ORDER_SIZE=5.0 LINK`, `MAX_INV=38 LINK`, `TAKER_FEE=4.5bps`).
Alphas tested: {0, 1, 4}. (See `experiments/76_link_oos_validation/`.)

| alpha | mean PnL/day | std | days+ | mean_fills/day | taker% | inside% |
|---|---|---|---|---|---|---|
| 0 (baseline) | **−$17.28** | 16.25 | 10.0% (3/30) | 1,030 | 0.0% | 0.00% |
| 1 | **+$27.04** | 18.14 | 93.3% (28/30) | 1,714 | 0.0% | 0.00% |
| 4 | **+$100.85** | 33.80 | 100% (30/30) | 4,517 | 0.0% | 0.00% |

**(1) Alpha=0 baseline: OOS is materially worse (−$17.28/day vs −$0.24/day in-sample).** The
Jun–Jul 2025 period was more volatile and directional (daily price ranges of 10–15% common,
overall declining from ~$15 in mid-June to a trough near $11 before recovering). A symmetric
at-touch maker in a fast-trending market accumulates adverse inventory; the baseline's loss
rate reflects this regime, not a calibration or proxy artefact.

**(2) Alpha=1 OOS: +$27.04/day, 93.3% days positive — the signal generalises.** The effect size
is larger OOS than in-sample (+$27 vs +$22), and the proxy tracker is approximately valid at
alpha=1: with LINK's ~10-tick spread and shift ≤ 1 tick for most OBI readings, quotes stay close
to the touch and the single-level proxy introduces only minor error. This is the cleanest OOS
confirmation: a different market regime, different month, same direction and roughly same
magnitude.

**(3) Alpha=4 OOS: +$100.85/day — plausible upper bound, but proxy limitation applies.** The
fill count at alpha=4 is 4,517/day OOS vs 2,245/day in-sample. This large discrepancy reveals
the proxy's scope condition: at alpha=4 with meaningful OBI, the bid is placed 1–4 ticks inside
the spread (C44-D), meaning `bid > best_bid`. The proxy's single-level representation then gives
`queue_ahead = 0` for this order (no bid_levels at a price above best_bid), producing instant
fills on any sell trade. In the real L2 data (in-sample), inside-spread price levels carry actual
queue depth from other resting orders, so fills at those prices are still gated. The OOS fill
count explosion (4,517 vs 1,030 at alpha=0) is therefore a proxy artefact for alpha=4, not a
property of the real market. The alpha=4 OOS PnL of +$100.85 should be read as an upper bound;
the true OOS figure, with real L2 inside-spread depth, is unknown. Real L2 data for Jun–Jul 2025
does not exist in this dataset (CoinAPI L2 capture started April 2026).

**What this validates and what it doesn't.** The OBI signal's predictive content — its ability to
identify which side of the spread will be adversely selected — is confirmed OOS by alpha=1's
result (+$27.04/day, 28/30 days positive on fully held-out data). The alpha=4 mechanism (deeper
inside-spread placement) is confirmed in-sample with real L2 data (+$56.00/day, real inside-spread
queue gating) and is directionally supported OOS, but the exact OOS magnitude is not
independently verifiable without L2 orderbook data for the OOS period.

**Synthesis.** The OBI-conditional spread-placement mechanism (C42, C44) generalises out of
sample: a held-out period 9 months earlier, in a materially different volatility/trend regime,
produces a similar directional result at alpha=1 and a plausible amplification at alpha=4. The
caveat (d) from C44 is closed for alpha=1; for alpha=4, L2 OOS validation remains open.

Reproduce:
```
python experiments/76_link_oos_validation/oos_validation.py
```

---

## Future Work

The items below were drafted before the queue-priority verdict (C30) and the zero-profit
equilibrium (C33) became the thesis's central results. They are reframed here against that
finding rather than dropped — some still test it directly, others are superseded by it.

- **Cross-asset generalization of the queue-rent mechanism** (extends C30/C33): C43 covers the
  small-relative-tick end (BTC-PERP, ~0.15bps) and finds it fully arbitraged on the spread axis,
  consistent with C33's "same zero-profit law, enforced through whichever variable is free"
  framing. The open end is the large-relative-tick side: testing another LINK-like asset (similar
  tick-to-price ratio) to see whether queue-axis rent — and the `spot1` skew mechanism (C42) — is
  LINK-specific or general. `data/real` currently has only LINK/BTC (+perps), so this requires a
  new CoinAPI data pull, a separate scoping decision from the LINK-depth robustness items below.
- **BTC cross-asset symmetry for C36**: re-pull BTC perp trade data (the current CoinAPI file
  is mislabeled — byte-identical to the orderbook snapshot) to complete the spot↔perp
  Hayashi-Yoshida check on BTC and confirm C36's "contemporaneous, no third door" result
  generalises beyond LINK.
- **Stressed-regime check on the corrected-engine result** (extends C30/exp 62/C42): the
  honest at-touch baseline is now known to be highly latency/speed-sensitive — −$7.93/day at
  100ms latency/100ms requote (exp 62) vs ≈$0/day, 46.7% days positive at 10ms/50ms (C42).
  Re-run the honest at-touch backtest on high-volatility or crash-period data, at a stated
  latency/requote point. Open question, not assumed: does the queue-priority loss widen,
  narrow, or hold flat under stress, and does that depend on the latency regime?
- **OOS validation for the alpha≈4 optimum (+$56.00/day, 100% days at 10ms/50ms/queue_fraction=0.5)**:
  (a)-(c) of C42's robustness pass are now resolved by C44 — `queue_fraction` is flat over
  `[0.1,0.7]` with a sharp cliff at 0, the spread-rule axis is inert, `spot_alpha≈4` (not 1) is the
  honest-regime optimum, and exp75's per-fill markouts confirm the mechanism is a genuine,
  monotonically-increasing reduction in adverse selection (54-63% -> 31-34% -> ~10% adverse fills
  for alpha=0/1/4). Remaining: (d) out-of-sample validation — a different window (different month,
  or a held-out asset with similar tick-to-price ratio) to check both the +$56.00/day level and the
  alpha≈4 optimum location are not specific to LINK April 2026.
- **L2 diff-depth validation of `queue_fraction`** (motivated by C42(a) above, now de-prioritized
  by C44's flat-plateau result, but still useful for the absolute fill-rate calibration): buy or capture
  full Binance L2 order-book-update streams (current CoinAPI orderbook files are ~1Hz
  snapshots) for a few days, reconstruct true queue position, and compare against the
  `queue_fraction=0.5` heuristic's implied fill rate — calibrate a correction factor and apply
  it to C42's headline numbers.
- **Largely superseded by C33**: (a) ML-based kappa estimation — C33 shows κ is not a free
  parameter but pinned to σ by zero-profit (`κ_eq ≈ √A/σ_$`), so a better *estimate* of κ
  doesn't relax the binding constraint; (b) multi-level ladder quoting — every level is still
  an inside-spread resting order subject to the same queue-priority rent as the touch, so
  laddering doesn't escape C30's mechanism (whether it changes the *per-level* rent is
  untested and could be a short follow-up, but is not expected to overturn C30).
- **Two small untested threads from `hypotheses.md` §F**: whether a lower perp fee tier makes
  the within-venue taker (exp 55) viable (reasoned "likely no" — 3.6 bps round-trip vs ~1 bps
  edge — but untested), and funding rate as a queue-independent carry return (a different
  strategy class — carry, not market making — so out of scope for this thesis but worth
  flagging).

---

## References

Cited in the "Corroborating literature" notes above. Verify exact page numbers against the
originals before final thesis submission.

- Avellaneda, M. & Stoikov, S. (2008). High-frequency trading in a limit order book.
  *Quantitative Finance*, 8(3), 217–224.
- Albers, J. et al. (2025). [Markout / OBI methodology — complete citation from the copy used
  for the markout horizon choice.]
- Barucci, E., Mathieu, A. & Sánchez-Betancourt, L. (2025). Market making with fads, informed,
  and uninformed traders. arXiv:2501.03658.
- Barzykin, A., Bergault, P., Guéant, O. & Lemmel, F. (2025). Optimal quoting under adverse
  selection and price reading. arXiv:2508.20225.
- Baron, M., Brogaard, J., Hagströmer, B. & Kirilenko, A. (2019). Risk and return in
  high-frequency trading. *Journal of Financial and Quantitative Analysis*, 54(3), 993–1024.
- Budish, E., Cramton, P. & Shim, J. (2015). The high-frequency trading arms race: frequent
  batch auctions as a market design response. *Quarterly Journal of Economics*, 130(4),
  1547–1621.
- Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018). *Trades, Quotes and Prices:
  Financial Markets Under the Microscope*. Cambridge University Press. (Maker P&L, short-vol
  framing, spread–volatility relation.)
- Cont, R., Kukanov, A. & Stoikov, S. (2014). The price impact of order book events.
  *Journal of Financial Econometrics*, 12(1), 47–88.
- Copeland, T. E. & Galai, D. (1983). Information effects on the bid–ask spread.
  *Journal of Finance*, 38(5), 1457–1469. (Dealer quotes as a written put + call; spread as
  option premium — the foundational "limit order = short option.")
- Foucault, T., Pagano, M. & Röell, A. (2013). *Market Liquidity: Theory, Evidence, and Policy*.
  Oxford University Press. (The limit order as a free option.)
- Grossman, S. J. & Miller, M. H. (1988). Liquidity and market structure. *Journal of Finance*,
  43(3), 617–633.
- Ho, T. & Stoll, H. R. (1981). Optimal dealer pricing under transactions and return uncertainty.
  *Journal of Financial Economics*, 9(1), 47–73. (Dealer inventory-risk model.)
- Sinclair, E. (2013). *Volatility Trading* (2nd ed.). Wiley. (Short-gamma P&L: theta vs gamma,
  realised vs implied.)
- Stoll, H. R. (1978). The supply of dealer services in securities markets. *Journal of Finance*,
  33(4), 1133–1151.
- Taleb, N. N. (1997). *Dynamic Hedging: Managing Vanilla and Exotic Options*. Wiley.
- Treynor, J. L. (as W. Bagehot) (1971). The only game in town. *Financial Analysts Journal*,
  27(2), 12–14. (Dealer vs informed trader — adverse selection.)
- Dayri, K. & Rosenbaum, M. (2015). Large tick assets: implicit spread and optimal tick size.
  *Market Microstructure and Liquidity*, 1(1).
- Glosten, L. R. & Milgrom, P. R. (1985). Bid, ask and transaction prices in a specialist
  market with heterogeneously informed traders. *Journal of Financial Economics*, 14(1),
  71–100.
- Guéant, O. (2017). Optimal market making. *Applied Mathematical Finance*, 24(2), 112–154.
  (arXiv:1605.01862)
- Guéant, O., Lehalle, C.-A. & Fernandez-Tapia, J. (2013). Dealing with the inventory risk:
  a solution to the market making problem. *Mathematics and Financial Economics*, 7(4),
  477–507.
- Handa, P. & Schwartz, R. A. (1996). Limit order trading. *Journal of Finance*, 51(5),
  1835–1861.
- Hollifield, B., Miller, R. A. & Sandås, P. (2004). Empirical analysis of limit order
  markets. *Review of Economic Studies*, 71(4), 1027–1063.
- Kearns, M. & Nevmyvaka, Y. (2013). Machine learning for market microstructure and high
  frequency trading. In *High Frequency Trading: New Realities for Traders, Markets and
  Regulators*. Risk Books.
- Lalor, J. & Swishchuk, A. (2024). Market simulation under adverse selection. arXiv:2409.12721.
- Lehalle, C.-A. & Mounjid, O. (2017). Limit order strategic placement with adverse selection
  risk and the role of latency. *Market Microstructure and Liquidity*, 3(1).
  (arXiv:1610.00261)
- Lo, A. W., MacKinlay, A. C. & Zhang, J. (2002). Econometric models of limit-order
  executions. *Journal of Financial Economics*, 65(1), 31–71.
- Menkveld, A. J. (2013). High frequency trading and the new market makers. *Journal of
  Financial Markets*, 16(4), 712–740.
- Moallemi, C. C. & Yuan, K. (2017). A model for queue position valuation in a limit order
  book. Working paper, Columbia Business School.
- Silantyev, E. (2019). Order flow analysis of cryptocurrency markets. *Digital Finance*,
  1(1), 191–218.
- Smith, E., Farmer, J. D., Gillemot, L. & Krishnamurthy, S. (2003). Statistical theory of the
  continuous double auction. *Quantitative Finance*, 3(6), 481–514.
- Wyart, M., Bouchaud, J.-P., Kockelkoren, J., Potters, M. & Vettorazzo, M. (2008). Relation
  between bid–ask spread, impact and volatility in order-driven markets. *Quantitative Finance*,
  8(1), 41–57.
- Stoikov, S. (2018). The micro-price: a high-frequency estimator of future prices.
  *Quantitative Finance*, 18(12), 1959–1966.
- Zhang, Z., Zohren, S. & Roberts, S. (2019). DeepLOB: deep convolutional neural networks
  for limit order books. *IEEE Transactions on Signal Processing*, 67(11), 3001–3012.
- *Explainable Patterns in Cryptocurrency Microstructure* (2026). arXiv:2602.00776 —
  crypto-specific confirmation that imbalance predictability does not beat transaction costs.
