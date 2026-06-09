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

---

## Planned Extensions

- **Stressed regime validation**: download LINK data from high-volatility or crash periods
  to test whether the $25 daily loss limit is sufficient to prevent catastrophic losses
- **Cross-asset validation**: test on comparable mid-cap crypto assets (similar tick spread
  structure) to determine whether the step-function mechanism is LINK-specific or generalises
- **ML-based kappa estimation**: XGBoost fill probability model conditioned on regime features
- **Multi-level ladder quoting**: extend single-order framework to multi-level
