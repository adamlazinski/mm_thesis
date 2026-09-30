# Hypothesis Register

The full space of hypotheses tested (and pending) across the project, organized by theme.
This is the thesis's organizing skeleton — update the status markers as results land.

**Status:** `✓` confirmed · `✗` refuted · `◐` true-but-nuanced · `⧖` pending data ·
`⊘` **retracted or superseded by a later contribution**

Cross-references point to numbered entries in [thesis_contributions.md](thesis_contributions.md)
(C1–C67) and to experiment folders. The `→` marker on each section head gives the chapter that
now carries it.

**Reading the `⊘` entries.** Four entries below — plus the meta-hypothesis itself — were
positions this project held and later work removed. They are kept rather than deleted, because
the register's value as evidence depends on showing what was believed and when. The two largest
are the directional-skew arc (§H) and the cross-venue null (§F), and both were overturned by
measurement rather than by argument. Two further retractions are recorded inside entries rather
than as entries: the defended maker (§K, C64) and a depth-conditioned anchor rule that improved
in sample and failed out of sample (C66).

---

## A. Classical market-making models (Avellaneda-Stoikov & GLFT) → Ch2, Ch4

- `✗` **A-S inventory skew is meaningful on crypto at standard γ.** No — σ² is so small that γ must be
  ~1000× larger than the equity-literature value; the hardcoded ×1000 factor was a cross-asset
  calibration bug (catastrophic on LINK, whose σ² is ~40,000× BTC's). *(C3, C26)*
- `✗` **The fill curve is exponential (the GLFT premise).** No — BTC has a two-component structure with a
  momentum floor `A_mom`; LINK is a step function (flat inside the spread, flat outside). *(C6, C15)*
- `✗` **GLFT's ergodic inventory management beats A-S.** No — on LINK, flat A-S beats GLFT ~2×, and the
  GLFT spread formula `(1+κ/γ)^(1+κ/γ)` blows up at LINK's low κ. *(C17, C27, C28)*
- `◐` **The A-S optimal spread is derivable from κ.** Yes — and for LINK it collapses to touch-posting
  (`2/κ ≈ 1 tick`); the "flat MM" is the formula's own recommendation, not a simplification. *(C25, C28)*
- `✗` **Inventory skew adds value.** No on LINK — fills are sweep-driven, uncorrelated with inventory
  state, so skew only reduces inventory-unwinding fills without protecting against adverse sweeps. *(C28)*
- `✗` **Solving the HJB numerically for the true (two-component) intensity rescues the models.** No — the
  numerical solution confirms the linear-decay calibration's limits rather than escaping them. *(C38)*
- `✗` **Multi-asset closed forms matter on correlated crypto pairs.** No — correct for the setting
  (LINK spot/perp, ρ = 0.76, net-inventory weight 0.85) and empirically inert: the cross-asset skew is
  ~0.04 ticks at calibrated γ and quantizes to zero on a one-tick grid. *(Ch2 §3)*

## B. The queue-priority verdict (the MM unifier) → Ch5 §2

- `✗` **Low-frequency MM (sit, modify only on risk change) climbs the queue and escapes the priority
  problem.** No — at-touch under the L2 queue model, risk-gated sitting does not beat mid-chasing; all
  configs sit at the ~$0.6–0.8/day noise floor. The standing queue is too deep to climb through ordinary
  flow; patience does not substitute for priority. *(C32, exp 56)*
- `✗` **Deep-limit reversion MM (post 50–500t out, bet on reversion) escapes both gates.** No — reversion is
  a shallow near-touch phenomenon (8–50t, ~+1 tick); it vanishes by ~50t and turns strongly negative beyond,
  monotonically worse with depth, with an explosive left tail (LINK p5: −20t→−2,611t). BTC negative at all
  depths. Mechanism: *adverse selection by selection* — a move large enough to reach a deep limit is
  selectively informed, so it continues. Robust to fill-time censoring. *(C32, exp 57)*
- `✗` **Backtested MM profit is retail-accessible.** No — every profitable MM run is an inside-spread
  artifact of the no-queue fill model, which grants absolute queue priority over the ~8,600-LINK
  natural-bid queue. *(C30)*
- `✗` **Some regime/parameter makes honest MM positive.** No — regime-conditional honest markout found
  only one positive cell (high-vol overshoot-catch, +0.38 bps, ~$0.01/day), economically negligible. *(C30 addendum)*
- `◐` **Honest MM (outside-spread / L2-queue-modeled) is viable.** Breakeven — the price-only model
  overstates touch fills 41× and total PnL ~2.4×; realistic queue position pins PnL at a sub-$1/day noise
  floor with negative markout. The best current estimate of the honest number is **+$0.60/day (1 s) to
  +$4.06/day (30 s)** against a foresight ceiling of $19.76–$30.03. *(C20, C29, C30, C34)*

## C. Asset structure — the organizing axis is relative tick size → Ch4 §7, Ch5 §7

- `✓` **Relative tick size, not the asset name, is the organizing axis.** Where the spread is free to move
  (BTC) competition compresses it to breakeven and the equilibrium is enforced on the *spread axis*; where
  the tick floors the spread wider than breakeven (LINK) it is enforced on the *queue axis*. One law, two
  axes. Confirmed independently from markouts alone. *(C30, C33, C52, C59)*
- `⊘` **LINK's "10-tick" spread supports the cycling edge; BTC's 1-tick cannot.** Retracted in its stated
  form: LINK's exchange tick was $0.01, so its spread was **one** true tick, not ten. The axis above
  survives; this instance of it does not. *(C16, C24 → superseded by C54)*
- `⊘` **The LINK edge is structurally stable (9-month zero-shot transfer).** The transfer is real and
  reproducible, but what transferred was the queue rent at prices the exchange would have rejected. The
  surviving at-touch baseline is the equilibrium (−$0.24/day at 10 ms). *(C19, C30 → superseded by C54, C42)*
- `✓` **The spread-width gate is real** — identical strategy, notional-matched: LINK +$99/day vs
  BTC −$133/day. Read post-C54, this is a statement about where the *artifact* can form, and its honest
  counterpart is §K's competition gate. *(C52)*

## D. Reinforcement learning → Ch4 §6

- `◐` **RL beats A-S on LINK.** Yes by ~5% in PnL/day (+$2.16), but it's the same inside-spread artifact plus a
  genuine learned regime-dependent halting behavior. *(C23, C30)*
- `✓` **RL transfers across regimes.** LINK zero-shot to Apr 2026, no recalibration. *(C23)*
- `✗` **DQN beats TabularQ.** No — low-data regime (17 IS days); the simpler tabular representation wins. *(C23)*
- `✗` **RL works on BTC.** No — the 19-action space (3–9 ticks) all lands outside BTC's 1-tick spread, so
  every fill is pure adverse selection and the value function gets no positive signal. *(C24)*
- `✗` **RL discovers a genuine (non-artifact) edge.** No — it leans into the queue artifact *harder* than the
  hand-tuned configs, which is the clearest single sign that what was being optimised was the simulation.
  *(C30)*
- `✗` **A causal RL policy over observable state profits under the honest fill model.** No — paired
  demonstration: the same TabularQ overfits to +$58/day under the no-queue artifact model but cannot beat the
  ±$1/day noise floor under L2-queue even memorizing 3 days × 200 epochs; a continuous-state DQN learns to
  halt. *(C30, C33, exp 58)*
- `◐` **In-sample honest profit exists at all.** Yes, but only with FORESIGHT — a perfect-foresight oracle
  keeping only positive-markout fills earns ~$20–30/day vs ~$1–4/day causal. The edge is real, and
  information-gated. *(C34, exp 60)*
- `◐` **RL can win on the honest engine.** Once: a DQN cancel-controller degrades more gracefully than the
  hand-written rule under regime shift — the first honest-engine RL win in the project, but on the
  mechanism C54 then retracted. *(C53)*

## E. Trend-following / taker → Ch6 §3, Ch7 §6

- `◐` **Momentum (return autocorrelation) is taker-exploitable.** Signal real, ~1 bps, below fees. *(C1, C31)*
- `◐` **OBI predicts direction exploitably.** Real (~1 bps), the single best own-book signal, but below
  fees. *(C22, C31)*
- `✗` **Overshoot-catch (fade large sweeps) works.** No on BTC — sweeps *continue* (informed), fading loses;
  only a negligible positive cell on LINK. *(C30 addendum, C31)*
- `✗` **Selectivity / conviction / hold raise the per-trade edge.** No — capped ~1 bps; the momentum edge
  actually *decreases* with selectivity (latency adverse selection on the biggest moves). *(C31)*
- `✗` **Latency is the binding constraint for the taker.** No — ~1 bps even at 10 ms; the edge plays out over
  seconds, not a sub-second pop. *(C31)*
- `✗` **ML (XGBoost on 8 features, strict OOS) beats simple signals.** No — marginally worse than plain OBI
  despite genuine directional skill (AUC 0.75); OBI saturates the tradeable predictability. *(C31 addendum)*
- `✗` **Own-venue momentum clears the toll on a fast venue.** No — it beats random entry on every tight book
  (so the signal is real) at +0.8 to +1.9 bps against a 2.8 bps toll, and is negative in every cell. This is
  the control that isolates §K's cross-venue mechanism. *(exp 116)*
- `◐` **The fee tier is the binding constraint for the taker.** Binding, but *crossable* when the signal is
  large enough: the same venue and fee schedule that kills own-venue momentum admits the cross-venue
  dislocation taker at the 1.4 bps tier and refuses it at 4.5 bps. A gate, not a wall. *(C31, C63)*

## F. Spot vs perpetual, and the cross-venue question → Ch6 §3, Ch7

- `✓` **Perp spread is tighter than spot.** Confirmed LINK April (30d): perp $0.001 (1 tick) vs spot $0.01
  (1 true tick, at 10× the dollar width). *(exp 54, exp 61)*
- `✓` **Perp passive MM behaves like BTC (tight → loses).** Confirmed directly, not only mechanistically:
  the LINK PERP honest baseline is **−$74.94/day**, and OBI skew acts there as post-only gating rather than
  as inside-spread placement, because a 1-tick spread leaves no room. *(C47)*
- `⊘` **Cross-venue spot↔perp lead-lag yields no exploitable signal (θ = 0, contemporaneous).**
  **Superseded.** The θ = 0 finding was a resolution artifact of a 100 ms correlation grid; on captured data
  the perpetual **leads spot by 40–100 ms**, event-level and placebo-proof. The escape still closes, but for
  the opposite reason: the signal is real, out-of-sample robust, and its optimal use nets **+$0.13/day** —
  the market has priced the lead into the spread exactly. *(C36 → superseded by C56, C57, C60)*
- `✓` **A venue-level lead exists somewhere in the captured universe.** Exactly one: the centralised complex
  leads Hyperliquid by 200–500 ms. The 25 pairs showing it are one relationship times the market factor;
  Hyperliquid's own assets are contemporaneous with each other, and Binance↔Coinbase self-validates at 0 ms.
  *(C63, exp 110)*
- `✓` **Funding rate is a queue-independent carry return.** Confirmed — and it is the purest form of being
  paid to bear a risk rather than to predict: a contractual cash flow, +5.4% to +7.8%/yr net of Binance on
  all four majors. *(C67)*
- `◐` **Lower perp fees make the taker viable.** Not for own-venue signals (exp 116, negative at every
  tier); yes for cross-venue dislocation, at the high-volume tier only. *(C63, exp 116)*
- `✗` **Perp order flow is a usefully incremental signal for spot quoting.** Real but mostly redundant with
  spot OBI, weak and slow-building; as a secondary skew term it *dilutes* an already near-optimal spot-OBI
  skew, and as defensive widening it reproduces the same negative. *(C39, C40, C41)*

## G. Methodology / cross-cutting → Ch3 §7

- `✓` **Kappa estimation:** execution-aware (Approach B) and crossing-intensity (Approach C) beat the
  unconditional market-distance estimate (Approach A). *(C5, C25)*
- `✓` **Backtest fill-model optimism is quantifiable** via an L2 queue-clearing model. *(C29)*
- `✓` **The engine under-modeled latency adverse selection (fixed).** Marketable-on-arrival orders are
  takers that cross and bypass the same-side queue, not patient makers at a stale limit. Correcting this
  turns the honest at-touch LINK MM from ≈breakeven to −$7.93/day at 100 ms, 0/30 days positive.
  *(C30 corrected-engine addendum, exp 62)* — **note:** −$7.93/day is superseded as *the* honest number by
  C42's **−$0.24/day at 10 ms**; speed restores latency tolerance, so the 100 ms figure measures the
  latency penalty rather than the equilibrium. *(C37, C42)*
- `✓` **Adverse selection is structural at the requote frequency** (post-fill markout analysis). *(C1, C12)*
- `✓` **The engine + A-S/GLFT are sound (synthetic ground truth).** Constant-value world books closed-form
  spread capture to floating precision; fed true σ both strategies profit and widen ∝σ; they lose only to
  the σ² short-gamma cost a too-tight spread cannot cover. Honest-regime breakeven is not an engine bug.
  *(C33, exp 59)*
- `✓` **Honest MM breakeven is a zero-profit equilibrium, not bad data.** Breakeven half-spread δ_be ∝ σ
  (Wyart–Bouchaud) ⟹ market-clearing κ ∝ 1/σ, with δ_be/σ_$ constant at ≈76 across a tenfold volatility
  range; on large-tick LINK the same law is enforced via queue depth (= the C30 rent). *(C33, exp 59)*
- `✓` **Regime determines profitability more than model or parameters** (May vs June 2025). *(C13)*
- `✓` **Vendor tick metadata must be validated against the venue's live feed.** The single most expensive
  methodological lesson in the project: a backtest quoting on a finer grid than the exchange's manufactures
  phantom room inside the spread where no real order can rest. Signature: a spread pinned at a constant "N
  ticks" with every price on a coarser sub-grid. *(C54)*
- `✓` **Correlation-based lead-lag is not robust to the choice of clock; large-event studies are.** Exchange
  stamps and a common local receive clock disagree by hundreds of milliseconds on cross-venue pairs. The
  correlation measure attenuates (errors-in-variables); the ≥5 bps event study is indifferent, and survived
  the recomputation by *improving*. Every cross-venue claim is validated on the common clock. *(C63)*
- `✓` **Per-fill mark-to-mid can invert under an inventory-aware round trip.** +1.01 bps per fill became
  negative once the paired exit had to clear at an executable touch against a maker filled *to* its cap.
  *(C64)*
- `✓` **Pre-registration and placebo controls change conclusions.** A wallet-shuffle placebo, an anti-signal
  control, a matched-frequency regime placebo, and a prediction registered in version control before the
  data was examined each either validated or killed a result that raw comparison would have passed.
  *(C60, C62, C66, exps 114–115)*

## H. The directional-skew arc, and its retraction → Ch5 §3

The project's one sustained apparent exception, built over C39–C53 and removed by C54. Retained in full
because the seduction and the retraction are both evidence.

- `⊘` **OBI-conditional inside-spread placement breaks the equilibrium on LINK.** Appeared confirmed across
  an unusually thorough campaign: asymmetric alpha grids with superadditive sides (C48), a one-sided-quoting
  null showing the continuous skew already implements adverse-side avoidance (C49), a recompute/requote
  decoupling at 10 ms (C50), a **fresh 182-day out-of-sample window** on untouched data at +$80/day (C51),
  a spread-width gate (C52) and a fee gate (C53). **Retracted:** every placement was at a price off the
  exchange's $0.01 grid. Rerun at the true tick, +$0.36/day. *(C42, C44–C46, C48–C53 → C54)*
- `✓` **What survived the retraction.** The at-touch baselines quote real book prices, so C42's
  −$0.24/day equilibrium at 10 ms stands, as do the queue verdict (C29/C30), the zero-profit law (C33), all
  BTC results, BTC-PERP (C43) and LINK-PERP (C47). *(C54)*
- `✓` **The framework predicted the corrected outcome before it was measured.** A true one-tick LINK must
  behave like the one-tick perpetual (C47) — and it does (exp 85). *(C54)*
- `✓` **Fill realism is regime-dependent in a way that explains the whole arc.** Inside-spread, at-touch and
  outside-spread placements are three different physical situations, and the price-only model is exactly
  correct in the first, wrong by 41× in the second, and wrong by ~18× in the third. *(C46, C20)*

## I. Accounting: the five mirages → Ch5

- `✓` **Mirage 1 — queue priority.** A price-only fill model grants absolute priority; profit is confined to
  the regime where that is accidentally true. *(C20, C29, C30)*
- `✓` **Mirage 2 — prices that do not exist.** A mis-specified tick grid manufactures room inside the
  spread. *(C54)*
- `✓` **Mirage 3 — mark-to-mid.** Overstates at the level of a single fill, and more severely at the level
  of a position. *(C60, C64)*
- `✓` **Mirage 4 — fee tiers a strategy's own volume cannot earn.** *(C53, C63)*
- `✓` **Mirage 5 — the winner's curse in maker fill selection.** The fills a maker gets are selected against
  it, so measuring fill quality on realised fills alone is not neutral. *(C59, C61)*
- `✓` **All five bias the same direction, and the residue after removing them is the equilibrium.** Ch4's
  +$154/day becomes ~+$1/day with a negative mean markout and 39.7–48.9% of fills profitable. *(C33, C34)*

## J. Information: the four instruments → Ch6

Each instrument asks whether a different *class* of information opens the gate. All four terminate at zero
rather than below it, which is the register's single most important pattern.

- `✓` **Adverse selection is measurable model-free from the tape alone.** The maker's realised half-spread
  is negative within 100 ms on all four books; the protective window is 75–87 ms on large-relative-tick
  books and ≤15–20 ms on small-tick ones, and it coincides with the perp-lead clock. *(C59)*
- `✗` **Instrument 1 — being faster opens the gate.** Collapsing the whole latency stack from 10 ms to the
  co-located 1 ms limit changes essentially nothing (−$2.04→−$1.94; +$1.91→+$0.54, slightly *worse* from
  quote churn), and front-of-queue positioning is worse still. A 15 ms gate already fires inside a 40–100 ms
  lead. *(C60 colo addendum)*
- `✗` **Instrument 2 — observable state isolates benign flow.** Toxicity is genuinely rankable by flow,
  imbalance, volatility and intensity, and the cleanest quintile is still negative at a **zero** fee. *(C61)*
- `✗` **Instrument 3 — counterparty identity isolates benign flow.** The strongest sorting instrument that
  can exist, available only because Hyperliquid discloses both wallets: it separates flow at the **100th
  percentile** against a wallet-shuffle placebo, and the benign pocket is **+0.0 ± 0.3 bps**. *(C62)*
- `✗` **Instrument 4 — a price-process regime filter works.** No — a matched-frequency placebo reproduces
  the entire apparent improvement. *(exps 114–115)*
- `◐` **A real, placebo-proof, OOS-robust signal nets a positive return.** No: the sharpest signal in the
  project, used optimally, nets **+$0.13/day** against a ~$5 spread. Avoiding the adverse fills forfeits
  exactly their spread revenue. This is the strongest form of the zero-profit statement the thesis makes.
  *(C60)*
- `✓` **The three premises the verdict rests on are measured, not assumed.** One-tick modal spread,
  cancellation as roughly half of all touch deaths, spread self-repair in ~100 ms, hollow touch as a
  small-tick phenomenon, and `queue_fraction = 0.5` inside the identifiable band. *(C55, C58)*

## K. Structural positions: what the boundary pays → Ch7–Ch9

- `✓` **Renting a slow venue's clock pays.** +4.8 to +5.8 bps per event, two days, two independent leaders,
  priced at executable touches on both legs, 85–96% hit rate, median ≈ mean, and it survived the
  common-clock recomputation by improving. *(C63)*
- `✓` **…and it is bounded on exactly three sides.** Below a 5 bps threshold the large population is
  decisively negative; it is negative at the 4.5 bps base taker fee; and the touch holds only $1.4k–$8k at
  event times because Hyperliquid's own makers withdraw on the same signal. The capacity bound is the
  *answer* to why a public-data edge persists. *(C63)*
- `✓` **The immediacy premium exists where competition is thin.** Four of six tail books clear **base** fees
  on an inventory-aware round trip (HMSTR +20.6 bps, USUAL +16.4, CELO/VINE +8–9); the two failures are the
  two tightest books. *(C66)*
- `◐` **…but it is a portfolio property, not a per-instrument one.** Per-coin P&L is sign-unstable day to
  day; the equal-weighted basket is positive on 5/5 days of the original sample and 4/4 of a
  **pre-registered** replication on disjoint coins, with micro-price ≥ mid on 4/4. *(C66)*
- `✓` **…and its magnitude is priced by competition, not by technique.** The bridge control is the cleanest
  evidence in the thesis: USUAL, same coin and same strategy, fell from **+40 bps in July to +0.39 bps in
  August** as the tail's widest spread compressed from 56 to 14 bps. *(C66)*
- `✓` **The adverse-selection horizon is the venue's repricing clock.** ≤15–20 ms (Binance small-tick) →
  75–87 ms (large-tick) → seconds (HL majors) → 3.4 s (HL LINK) → >5 s (HL tail). Part II's organising law,
  and the reason Ch7 and Ch8 are one observation from two sides. *(C59, C66)*
- `✓` **Cross-venue funding carry pays, and the basis is the actual risk.** +8.4%/yr at a gross Sharpe ≈1.26
  on BTC where the basis happened to help, ≈0 on LINK where it did not; basis volatility 7–12%/yr against a
  ~7% funding signal, so any short window measures the basis. Costs invert: 5.6 bps round trip amortises to
  +0.68%/yr monthly and **20%/yr churned daily**. *(C67)*
- `✗` **Intraday cointegration between correlated majors is tradeable.** No — five of ten pairs pass a
  significance test (itself a finding about multiple testing), and the trade loses 6–12 bps because a
  45–140 minute reversion does not cover an 8.6 bps round trip. *(C67)*
- `✗` **Maker withdrawal is tradeable.** The lead is real on a slow venue, and sub-toll. The defended maker
  built on it is retracted under inventory-aware accounting. *(C64)*
- `✗` **The flow-analysis family yields anything tradeable.** Closed: institutional meta-order drift — the
  best-documented flow effect in the literature — is priced to within **0.06 bps** of the fee wall.
  *(C65)*
- `✗` **Premium-gating stacks with the dislocation trade.** Clean null — Hyperliquid's premium is ≈ −dev, a
  slower read of the same quantity, because the oracle is built from centralised prices. The dislocation
  taker and the funding carry are one object at two timescales. *(C63, C67)*
- `⧖` **The cascade tail.** The principal unmeasured quantity in the thesis. Both carry windows were benign
  (drawdown <20 bps), so the measured basis volatility is the *calm* volatility and the BTC Sharpe is
  conditional on no cascade. Requires a stressed window. *(C67)*

## L. Other asset classes and remaining gaps

- `✗` **Options market making (take gamma/vega inventory, hedge delta) works.** No — it fails on Deribit
  even at a hypothetical **zero** maker fee, so no fee schedule rescues it. *(exp 112)*
- `✗` **Implied volatility exhibits exploitable autocorrelation.** No — the large negative lag-1
  autocorrelation (−0.26 to −0.37) in a pooled ATM-IV series is a **composition artifact** of mixing
  strikes and expiries; per-instrument it is +0.012/+0.036, i.e. zero. *(exp 113)*
- `⧖` **A genuinely wide-spread *centralised* book behaves like the Hyperliquid tail.** The one outstanding
  empirical gap. Ch2 §8's dealer-window prediction is confirmed affirmatively on Hyperliquid's tail (C66),
  but Hyperliquid is a decentralised venue with a different participant mix and fee structure. The tick
  screen should precede the data purchase.
- `⧖` **Ladder / multi-level quoting changes the verdict.** Never tested; single-order throughout. The
  queue-priority argument applies per level, so the prior is that it does not.
- `⧖` **The market reacts to our own orders.** Every result is frozen-tape, which biases *toward* the
  strategy. Ch7's disappearing touch is direct evidence the channel is active and unmodelled.

---

## Meta-hypothesis (the thesis's central claim)

The original formulation was a two-gate access claim:

> ~~Every real edge in crypto market microstructure is gated by a piece of professional infrastructure that
> retail lacks — queue priority for the maker, sub-1-bps fees for the taker. The signals are real; the
> access is not.~~

`⊘` **Superseded** — not refuted, but subsumed by something stronger. Infrastructure turned out to be one of
several ways to sit outside the equilibrium rather than the thing that defines it, and the claim's
"signal-blind" framing could not accommodate §J's result that a *real* signal, used optimally, also nets
zero. The current claim is in two parts:

> **1.** For a participant without co-location or a negotiated fee schedule, competitive liquidity provision
> on a lit crypto book earns **exactly zero** — as the enforced outcome of a zero-profit equilibrium, not as
> an accident of sample. Every apparently profitable backtest decomposes into one of five accounting errors
> (§I), and no class of information opens the gate: not speed, not observable state, not counterparty
> identity, not regime, and not the sharpest causal signal in the data (§J).
>
> **2.** Positive expected returns *are* available at the boundary of that equilibrium, and all of them are
> compensation for bearing a risk or occupying a structural position rather than for prediction (§K). Each
> is bounded by the thing that makes it available — capacity, competition, or an unmeasured tail — and each
> is as small as that bound permits.
>
> **In one sentence:** markets pay for risk-bearing and structural position, not for prediction a single
> participant can compute.

The supporting regularity, which is what makes this more than one dataset's result: **seven** genuine,
placebo-validated effects were measured at or just under the cost of acting on them — momentum (+0.8–1.9 bps
vs a 2.8 bps toll), OBI, the perpetual lead (+1.72 bps vs a 2–10 bps wall), meta-order drift (**within
0.06 bps** of the wall), maker withdrawal, wallet-level toxicity, and intraday cointegration. One such
coincidence is an observation; seven is a description of how the market allocates the returns to
information.

## Narrative arc

**Part I — the competitive zero.** Classical models fail on their own terms (§A) → but a degenerate flat MM
looks robustly profitable, and neither the formula nor a directional overlay nor RL improves on it (§C, §D)
→ which turns out to be a queue-priority artifact, one of five accounting mirages all biasing the same way
(§B, §I) → the residue is derived rather than merely observed, and is the zero-profit equilibrium enforced
on the spread axis where the spread is free and the queue axis where the tick floors it (§G) → the taker
pivot needs no queue but is capped ~1 bps, sub-fee even with ML and even when fast (§E) → the cross-venue
lever looked closed on a contemporaneity finding that later proved to be a grid artifact; on captured data
the perpetual genuinely leads by 40–100 ms, and acting on it optimally nets +$0.13/day (§F) → four
independent instruments — markout, speed, observable state, counterparty identity — all terminate at exactly
zero (§J). Along the way the project's one celebrated exception, the OBI inside-spread arc, survived a
182-day fresh out-of-sample window and fell to a live-feed check of the price grid (§H).

**Part II — the boundary.** If the zero is exact, a positive return requires leaving the competitive game.
Three ways exist, and each is bounded by what makes it available: trading against a venue whose makers
reprice on a seconds clock (capacity-gated at a few thousand dollars of touch depth), providing immediacy on
a book with two or three makers (priced by spread width, and decaying forty-fold in two months as
competition arrived), and being paid to carry a cross-venue basis (where the basis, not the funding, is the
risk, and the cascade tail is unmeasured) (§K). Options market making fails even at zero fees (§L). The
organising law of the second half is that **the adverse-selection horizon is the venue's repricing clock** —
the same quantity as Part I's relative-tick axis, seen at a different resolution.
