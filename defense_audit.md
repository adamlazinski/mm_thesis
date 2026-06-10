# Defense Audit — Logic, Results, Conclusions, Literature

A line-by-line adversarial review of the codebase and conclusions, written to answer one
question: *can any result be contested as "nonsense / you messed it up"?* Each item is graded:

- **SOUND** — verified correct, no plausible attack
- **BIASED-SAFE** — simplification exists, but its bias direction *strengthens* the thesis verdict
- **DEFENDED** — attackable, but an explicit robustness check already covers it
- **FIX** — genuine vulnerability; concrete remedy listed in §6

The structural defense that protects almost everything: **the thesis conclusion is negative**
(no retail-capturable edge). Any *optimistic* simulation bias therefore strengthens the
conclusion — if the strategy loses even with favorable assumptions, the verdict holds a
fortiori. Only *pessimistic* biases in the honest regime can be attacked, and there are
exactly two (§3.5, §3.6).

---

## 1. Engine-level audit (`backtest.py`, `order_manager.py`)

### 1.1 P&L accounting — SOUND
`total_pnl = cash + inventory × last_mid`; cash debited at fill price on buys, credited on
sells (`order_manager.py:219-223`). This is the standard mark-to-market identity; cost basis
is encoded in cash, no averaging needed. Verified algebraically correct including partial fills.

### 1.2 Latency model — SOUND
`active_from = t + latency` on submission; cancels keep the order matchable until
`cancel_from = t + latency` (`order_manager.py:135,146`). This correctly models the
cancel race — the order can be picked off during the cancel window. Symmetric latency means
the exposure window equals the quote interval exactly. No lookahead: a quote decision at t
cannot fill before t + latency.

### 1.3 Event ordering — SOUND
Same-timestamp events sort trades (priority 0) before quotes (priority 1)
(`backtest.py:218-221`). Fills are matched against the *pre-update* book state — the
conservative order (the strategy cannot react to a quote and fill on the simultaneous trade).

### 1.4 Price-only fill condition — BIASED-SAFE (and deliberately so)
A trade at P fills a resting bid at ≥ P regardless of aggressor side
(`order_manager.py:184-187`). This is **optimistic** (more fills credited). It is also the
*subject of study*: Contribution 30 explicitly decomposes how much of backtest PnL this
optimism manufactures. The naive model is not a hidden flaw — it is the exhibit.

### 1.5 `queue_model='none'` — the artifact is the finding, not a bug
First-touch-fills = absolute queue priority. The thesis's central claim (C30) is that this
single line is where all positive MM backtests come from. The audit point: this is the
*standard* fill model in published MM backtests (including RL-MM papers, e.g.
[arXiv 2306.17179](https://arxiv.org/pdf/2306.17179)), so the thesis *explains* the
literature's positive results rather than contradicting them. Strong position.

### 1.6 L2 queue-clearing model — DEFENDED (conservative, spanned by sweep)
`vol_to_us = vol_after − max(queue_ahead, vol_before)` (`order_manager.py:195-205`) is
correct partial-clearing arithmetic. Two known simplifications, both **pessimistic**:
- Trades printing *through* our price (P < our bid) only count as queue volume, whereas in
  reality a print below our bid implies our level was exhausted → we'd be fully filled.
- Cancellations ahead of us are not modeled (real queues also drain via cancels), so
  effective queue is overstated.

Defense: the `queue_fraction` sweep spans 0 → 1. At fraction → 0 the model converges to the
optimistic no-queue model; the result (PnL pinned at a sub-$1/day noise floor from 5%
onward) is therefore robust to *any* calibration of these simplifications. A critic must
argue the true competing queue is < 5% of visible depth — implausible on Binance.

### 1.7 Gap closure at last mid — BIASED-SAFE
Closing inventory at mid with no spread cost (`backtest.py:271-277`) is optimistic by
half-spread × |inventory| per closure. Favors the strategy; verdict still negative.

### 1.8 Risk-based requote (`_requote_risk`) — SOUND
Per-side reconciliation verified: persisting sides are left untouched (queue position and
`vol_since_submit` preserved), toxicity pulls suppress one side, vol change triggers reprice
of only the stale side. The exp 56 comparison (risk vs price policy) is apples-to-apples —
same strategy, same fill model, same data, one flag.

### 1.9 Markout measurement — SOUND (minor note)
Signed by fill side, resolved at the first quote ≥ horizon cutoff (`backtest.py:378-383`).
The horizon therefore overshoots by up to one quote inter-arrival (~ms at this data rate) —
negligible. The 1s horizon choice follows Albers et al. (2025); exp 53's regime-conditional
analysis also reports longer horizons, so the conclusion is not horizon-cherry-picked.

### 1.10 "Sharpe" metric — ~~FIX~~ RESOLVED
`metrics["sharpe"] = mean/std × sqrt(len(rets))` over per-100-event PnL increments was a
**t-statistic of per-step PnL**, not an annualized Sharpe ratio. Fixed 2026-06-10: renamed
`pnl_tstat` (legacy `sharpe` key kept as deprecated alias), summary label corrected,
deprecation note added at the top of thesis_contributions.md. Deeper point, agreed with the
author: risk-adjusted ratios are not meaningful here at all — the verdict is that the
honest-regime mean is ≈0/negative, and a ratio of a near-zero mean to its own noise carries
no information. Thesis tables report mean ± std daily PnL, win rate, and markout.

---

## 2. The queue-priority decomposition (C30) — the central argument

The logic chain, audited link by link:

1. *LINK's natural spread is 10 ticks 99.9% of the time* — measured directly from quotes. SOUND.
2. *Inside-spread quotes under `queue_model='none'` capture flow that would clear against
   ~8,600 LINK resting at the touch* — depth measured from L2 snapshots. SOUND.
3. *Only outside-spread fills are physically honest* — a fill requires the price to sweep
   through the level, which no queue can prevent. This is the **key inferential step** and it
   is airtight: price-time priority means a market order *must* exhaust all volume at better
   prices before reaching yours. No assumption about queue share needed.
4. *Regime decomposition*: inside +$94/day, touch +$33, outside +$2.5 (markout −0.65 bps).
   The profit is monotone in queue-priority dependence. SOUND.
5. *RL is the same artifact*: identical engine and fill model; 4,970 fills/day vs the 216/day
   honest ceiling. The 23× fill-rate excess is arithmetic, not interpretation. SOUND.
6. *BTC as control*: 1-tick spread makes inside-quoting impossible; the same RL machinery
   loses. A natural experiment supporting causality, not just correlation. SOUND.

Attack surface: "your queue_fraction for 'realistic retail' is subjective." Defense: the
claim never rests on a point estimate — the sweep shows *every* fraction ≥ 5% lands at the
noise floor, and step 3 needs no queue model at all.

---

## 3. Per-experiment methodology

### 3.1 Exp 53 spread sweep — SOUND, with one scoping note
Fixed-tick-offset parameterization (not bps) is correct for a large-tick asset. Note for the
write-up: exp 52's absolute numbers used `queue_model='partial'` (predates
`_make_order_manager`); only *relative* comparisons from exp 52 are citable. Already
documented — keep it documented.

### 3.2 Exp 55 taker methodology — SOUND, three flags
The fill mechanics are the strongest part: entry at t+latency at the *actual* prevailing
ask/bid, exit crossing back at t+latency+hold; spread cost and latency slippage *emerge*
from real quotes rather than being assumed (`btc_taker_latency.py:76-92`). `px_at` uses
last-quote-≤-t — no lookahead. The random-direction control at the same selection points
(recovering the ~−1.7 tick spread floor) is exactly the falsification test a referee would
demand, and it passed.

- **Flag A (overlapping positions) — DEFENDED.** 250ms grid × multi-second holds ⇒
  overlapping round trips; raw n is inflated. Defense already in place: per-day means as the
  unit of observation, and no daily-PnL extrapolation from n was ever made. State this
  explicitly in the thesis.
- **Flag B (in-day decile threshold) — ~~FIX~~ RESOLVED.** The selection threshold was a
  full-day quantile (end-of-day information in selection, though not in direction — the
  random control bounded its effect at the spread floor). Fixed 2026-06-10: trailing-1h
  rolling quantile, shifted to use strictly past data, for the signal decile, sweep-size
  percentile, and vol median; 43-day rerun confirms all conclusions unchanged. Original
  results preserved as `btc_taker_perday_fulldaythr.csv` for comparison.
- **Flag C (no market impact / full fill at L1) — BIASED-SAFE with scoping.** Optimistic for
  size; fine for the retail-size claim. Add one sentence scoping the result to sizes ≪ L1 depth.

### 3.3 Exp 55 XGBoost — SOUND
Strict temporal OOS (train Jun 2025, test Jul 2025 + May 2025), identical fill model as the
simple signals, identical evaluation. AUC 0.75 with no economic improvement over plain OBI is
the *expected* result in the literature (see §5) — predictability without profitability.

### 3.4 Exp 56 low-frequency MM — SOUND
Same engine, same data, single-flag policy switch; at-touch under the L2 queue model. The
negative result (risk-gated sitting ≤ mid-chasing) is internally consistent with C30: queue
advancement is worthless when the queue never clears honestly.

### 3.5 Exp 57 deep reversion — ~~FIX~~ RESOLVED (touch-based rerun confirms)
The grid proxy conditions on **displacement sustained at exactly t** (`disp = mid(t) −
mid(t−30s)`). A *wick* — price touches 100t down and reverts within the window — would have
filled a real resting limit *profitably*, but the grid at t sees a small displacement and
files the event in the shallow bin. Deep bins therefore contain only *sustained* moves, and
adversity at depth is **overstated by construction** (fill-time censoring). This is the only
place in the codebase where a pessimistic bias is not yet spanned by a robustness check.

**Resolved (2026-06-10):** `touch_reversion.py` reruns the study with touch-based fills —
limit rests X ticks from mid for 30s, fill = first crossing of the level on a 250ms grid at
the limit price, reversion measured 60s from the *fill* time. Wicks now fill profitably, no
censoring. Result: same sign structure, same monotonic depth gradient (LINK: +2.3t at 10t →
−536t at 500t; BTC negative at all depths), same explosive left tail. Mean time-to-fill
9–19s shows deep fills land mid-move and ride the continuation — the
adverse-selection-by-selection mechanism observed at the fill itself. Addendum recorded in
C32. The deep-reversion refutation is not a censoring artifact.

Also note: exp 57's n (8.3M grid obs) is overlap-inflated ~30× (1s grid, 30s window).
Conclusions correctly rest on means and monotonicity, not t-stats — say so in the text.

### 3.6 Honest-regime conservatism — DEFENDED
The two pessimistic biases in the honest regime are §1.6 (queue model, spanned by the
fraction sweep) and §3.5 (exp 57 censoring, now resolved by the touch-based rerun).
Everything else tilts optimistic.

---

## 4. Statistical robustness

| Concern | Status |
|---|---|
| Overlapping observations (exps 55, 57) | Per-day reduction in 55; means-only claims in 57; state explicitly |
| Multiple comparisons (many sweeps) | Verdict claims are *negative* (nothing survives), which multiple testing makes *harder*, not easier — the one positive cell (overshoot-catch +0.38 bps, n=142) was correctly dismissed as negligible rather than promoted |
| Small-sample traps | Already caught twice (exp 57 3-day smoke reversal; conf-sweep p99.9 n=5–7) and excluded from conclusions |
| OOS discipline | XGBoost strictly temporal OOS; RL zero-shot Apr 2026 transfer; A-S/GLFT params from May 2025 applied to Apr 2026 |
| Sample scope | LINK: 30d Apr 2026 + May 2025; BTC: 43d across 3 regimes. Adequate for microstructure (millions of events/day), but **scope all claims to: Binance spot, BTC+LINK, 2025–2026, ~100ms latency class** — see §6 |
| Zero-fee assumption | Makes every negative result an *upper bound* on retail economics — strengthens the verdict. The one place fees were decisive (taker) is the one place they were reinstated. Consistent |

---

## 5. Literature positioning — does anything contradict established research?

**No result contradicts the literature; the thesis's strongest results *reproduce* it in
crypto, and its central claim *explains* the published positive backtests.** Mapping:

| Thesis finding | Literature | Relation |
|---|---|---|
| Queue priority is the maker's economic gate (C30) | Moallemi & Yuan (2017), queue-position valuation; large-tick literature (Dayri & Rosenbaum) — LINK is a textbook large-tick asset | **Agrees** — queue value is a large share of the spread precisely in large-tick names |
| MM profits concentrate with speed/queue-privileged firms | Menkveld (2013); Baron, Brogaard & Kirilenko (2019); Budish, Cramton & Shim (2015) | **Agrees** |
| OBI/OFI predicts short-horizon returns but below costs (C31) | Cont, Kukanov & Stoikov (2014); crypto-specific: imbalance predictability "does not beat transaction costs (bid-ask spread and fees)" — e.g. [Explainable Patterns in Cryptocurrency Microstructure](https://arxiv.org/pdf/2602.00776), [order-book imbalance studies](https://towardsdatascience.com/price-impact-of-order-book-imbalance-in-cryptocurrency-markets-bf39695246f6/) | **Agrees** — this is the consensus finding |
| ML (XGB, AUC 0.75) adds no economic edge over OBI | Kearns & Nevmyvaka (2013); DeepLOB-type results: strong classification, modest economics | **Agrees** |
| Deep/passive limit fills are adversely selected conditional on fill (exp 56/57) | Handa & Schwartz (1996) "winner's curse" of limit orders; Hollifield, Miller & Sandås; [Lehalle et al., adverse selection & latency in limit placement](https://arxiv.org/pdf/1610.00261) | **Agrees** (pending the §3.5 robustness fix) |
| Empirical fill intensity is not exponential (two-component / step) | Contradicts the A-S/GLFT *modeling assumption*, not any empirical study; survival-analysis literature (Lo, MacKinlay & Zhang 2002) supports non-exponential fill times | **Safe** — assumptions vs. data, clearly framed |
| A-S γ requires ~1000× equity-calibrated values on crypto | Pure unit analysis (σ² scale); not contested territory | Safe |
| Published positive crypto-MM backtests (incl. RL) | Use the same first-touch fill model the thesis dissects | **Explains them** — frame this as a contribution, not a conflict |
| Latency is *not* the taker's binding constraint | Superficially tension with Budish et al.'s latency races — but those races are *maker-side queue races at the touch*, which is exactly the thesis's maker gate. The taker edge here plays out over seconds | **No conflict** — spell out this distinction in the thesis to pre-empt the question |

One genuine scope limitation to state rather than defend: **maker rebates**. On venues with
negative maker fees, MM economics include a rebate leg the zero-fee assumption excludes. This
doesn't threaten the verdict (rebate capture *also* requires queue priority — fills are the
prerequisite), but a sentence acknowledging it closes the hole.

---

## 6. Pre-submission action list

1. ~~**Exp 57 touch-based robustness run**~~ **DONE** (`touch_reversion.py`, addendum in C32):
   conclusion confirmed, not softened — deep adversity survives the censoring fix.
2. ~~**Rename/recompute the Sharpe metric**~~ **DONE**: engine metric renamed `pnl_tstat`
   (`sharpe` kept as deprecated alias for old _metrics.json readers); aggregate label marked
   unannualized; deprecation note added at the top of thesis_contributions.md instructing
   thesis tables to use mean ± std daily PnL / win rate / markout instead. Rationale: with a
   ≈0/negative honest-regime mean, a risk-adjusted ratio is a ratio of noise to noise.
3. ~~**Trailing decile threshold in exp 55**~~ **DONE**: `btc_taker_latency.py` now uses
   trailing-1h rolling quantiles (shifted — strictly past data) for the signal decile,
   sweep-size percentile, and vol median; original full-day-threshold results preserved as
   `btc_taker_perday_fulldaythr.csv`; 43-day rerun confirms conclusions unchanged.
4. ~~**Scoping sentence**~~ **DONE**: added to C30 (Scope and rebates) and C31 (Caveats).
5. ~~**Overlap-inflation of n**~~ **DONE**: stated in C31 (already present) and C32 (added
   for both the grid study and the touch-based addendum).
6. ~~**Maker-rebate acknowledgment**~~ **DONE**: C30 "Scope and rebates" — rebates accrue
   only on fills, fills require queue priority; one more component of the queue rent.
7. Keep the exp 52 `queue_model='partial'` provenance note attached to any exp 52 number.

Items 2–7 are wording/metric hygiene. Item 1 is the only one that could move a result, and
its blast radius is confined to the *strength* of C32's deep-reversion refutation — the
queue-priority verdict (C30) and the taker ceiling (C31) are unaffected.
