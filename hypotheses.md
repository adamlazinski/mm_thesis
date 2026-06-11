# Hypothesis Register

The full space of hypotheses tested (and pending) across the project, organized by theme.
This is the thesis's organizing skeleton — update the status markers as results land.

**Status:** `✓` confirmed · `✗` refuted · `◐` true-but-nuanced · `⧖` pending data

Cross-references point to numbered entries in [thesis_contributions.md](thesis_contributions.md).

---

## A. Classical market-making models (Avellaneda-Stoikov & GLFT)

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

## B. The queue-priority verdict (the MM unifier)

- `✗` **Low-frequency MM (sit, modify only on risk change) climbs the queue and escapes the priority
  problem.** No — at-touch under the L2 queue model, risk-gated sitting does not beat mid-chasing; all
  configs sit at the ~$0.6–0.8/day noise floor. The standing queue is too deep to climb through ordinary
  flow; patience does not substitute for priority. *(C32, exp 56)*
- `✗` **Deep-limit reversion MM (post 50–500t out, bet on reversion) escapes both gates.** No — reversion is
  a shallow near-touch phenomenon (8–50t, ~+1 tick); it vanishes by ~50t and turns strongly negative beyond,
  monotonically worse with depth, with an explosive left tail (LINK p5: −20t→−2,611t). BTC negative at all
  depths. Mechanism: *adverse selection by selection* — a move large enough to reach a deep limit is
  selectively informed, so it continues. Risk guardrails cannot rescue it (no positive deep zone exists).
  Robust to fill-time censoring: a touch-based rerun (wicks fill at the level, reversion from fill time)
  reproduces the same monotonic gradient on both assets. *(C32, exp 57)*


- `✗` **Backtested MM profit is retail-accessible.** No — every profitable MM run is an inside-spread
  artifact of the no-queue fill model, which grants absolute queue priority over the ~8,600-LINK
  natural-bid queue. *(C30)*
- `✗` **Some regime/parameter makes honest MM positive.** No — regime-conditional honest markout found
  only one positive cell (high-vol overshoot-catch, +0.38 bps, ~$0.01/day), economically negligible. *(C30 addendum)*
- `◐` **Honest MM (outside-spread / L2-queue-modeled) is viable.** Breakeven-to-negative — the price-only
  model overstates touch fills 41× and total PnL ~2.4×; realistic queue position pins PnL at a sub-$1/day
  noise floor with negative markout. *(C20, C29, C30)*

## C. Asset structure — BTC vs LINK = tight vs wide spread

- `✓` **Spread width is the organizing axis (not the asset name).** Wide spread enables the inside-spread
  artifact; tight spread forbids it. *(C24, C30)*
- `✓` **LINK (10-tick) supports the cycling "edge"; BTC (1-tick) cannot.** *(C16, C24)*
- `◐` **The LINK edge is structurally stable (9-month zero-shot transfer).** Yes (Apr 2026 holds) — but it
  is a queue rent, not retail-capturable. *(C19, C30)*

## D. Reinforcement learning

- `◐` **RL beats A-S on LINK.** Yes by ~5% in PnL/day (+$2.16), but it's the same inside-spread artifact plus a
  genuine learned regime-dependent halting behavior. *(C23, C30)*
- `✓` **RL transfers across regimes.** LINK zero-shot to Apr 2026, no recalibration. *(C23)*
- `✗` **DQN beats TabularQ.** No — low-data regime (17 IS days); the simpler tabular representation wins. *(C23)*
- `✗` **RL works on BTC.** No — the 19-action space (3–9 ticks) all lands outside BTC's 1-tick spread, so
  every fill is pure adverse selection and the value function gets no positive signal. *(C24)*
- `✗` **RL discovers a genuine (non-artifact) edge.** No — it leans into the queue artifact harder than the
  hand-tuned configs. *(C30)*
- `✗` **A causal RL policy over observable state profits under the honest fill model.** No — paired
  demonstration: same TabularQ overfits to +$58/day under the no-queue artifact model, but under L2-queue
  with an at-touch/outside-only 63-action space it cannot beat the ±$1/day noise floor even memorizing
  3 days × 200 epochs; generous qf=0.05 and a continuous-state DQN (→0 fills, learns to halt) both fail.
  The C23 "edge" was the queue rent, not a learnable strategy. *(C30, C33, exp 58)*
- `◐` **In-sample honest profit exists at all.** Yes, but only with FORESIGHT — a perfect-foresight oracle
  that keeps only positive-markout fills earns ~$24/day (10s) vs ~$2/day causal honest; ~10×. RL's null is
  representational (no future-conditioning in its state), not proof the edge is absent. The edge is gated
  behind foresight or the queue priority that substitutes for it — neither retail-accessible. *(C34, exp 60)*

## E. Trend-following / taker

- `◐` **Momentum (return autocorrelation) is taker-exploitable.** Signal real, ~1 bps, below fees. *(C1, C31)*
- `◐` **OBI predicts direction exploitably.** Real (~1 bps), the single best signal, but below fees. *(C22, C31)*
- `✗` **Overshoot-catch (fade large sweeps) works.** No on BTC — sweeps *continue* (informed), fading loses;
  only a negligible positive cell on LINK. *(C30 addendum, C31)*
- `✗` **Selectivity / conviction / hold raise the per-trade edge.** No — capped ~1 bps; momentum edge
  actually *decreases* with selectivity (latency adverse selection on the biggest moves). *(C31)*
- `✗` **Latency is the binding constraint for the taker.** No — ~1 bps even at 10ms; the edge plays out over
  seconds, not a sub-second pop, so speed barely helps. *(C31)*
- `✗` **ML (XGBoost on 8 features, strict OOS) beats simple signals.** No — marginally worse than plain OBI
  despite genuine directional skill (AUC 0.75); OBI saturates the tradeable predictability. *(C31 addendum)*
- `✓` **The fee tier is the binding constraint for the taker.** *(C31)*

## F. Spot vs perpetual

- `✓` **Perp spread is tighter than spot.** Confirmed LINK April (30d): perp $0.001 (1-tick) vs spot $0.01
  (10-tick) — perp is 10× tighter in dollars. *(exp 54, exp 61)*
- `◐` **Perp passive MM behaves like BTC (tight → loses).** Supported by structure — the perp's 1-tick spread
  forces any maker outside the spread (the honest/losing regime, no inside-spread artifact), exactly the BTC
  mechanism. Direct backtest pending but mechanistically determined. *(exp 61, C24, C30)*
- `⧖` **Lower perp fees make the taker viable.** Likely no (3.6 bps round-trip still > ~1 bps edge), untested.
- `✗` **Cross-venue spot↔perp lead-lag yields a *larger* signal.** No — Hayashi–Yoshida trade-vs-trade (30d)
  puts the peak at θ=0 (contemporaneous, ρ=0.24); the strong "spot leads 1s" from BBO was a 1 Hz perp-staleness
  artifact. Only a weak diffuse spot-leads tilt, not exploitable. The lever that could have produced a *bigger*
  signal is empirically absent at the 100ms–2s scale (sub-100ms HFT-race lead unresolved but infra-gated).
  The last open escape closes negative. *(C36, exp 61)*
- `⧖` **Funding rate is a queue-independent carry return.** Untested (a carry, not market making).

## G. Methodology / cross-cutting

- `✓` **Kappa estimation:** execution-aware (Approach B) and crossing-intensity (Approach C) beat the
  unconditional market-distance estimate (Approach A). *(C5, C25)*
- `✓` **Backtest fill-model optimism is quantifiable** via an L2 queue-clearing model. *(C29)*
- `✓` **Adverse selection is structural at the requote frequency** (post-fill markout analysis). *(C1, C12)*
- `✓` **The engine + A-S/GLFT are sound (synthetic ground truth).** Constant-value world books closed-form
  spread capture to floating precision; fed true σ both strategies profit and widen ∝σ through medium vol;
  they lose only to the σ² short-gamma cost a too-tight spread can't cover. So honest-regime breakeven is
  not an engine/strategy bug. *(C33, exp 59)*
- `✓` **Honest MM breakeven is a zero-profit equilibrium, not bad data.** Breakeven half-spread δ_be ∝ σ
  (Wyart–Bouchaud) ⟹ market-clearing κ ∝ 1/σ; on large-tick LINK the same law is enforced via queue depth
  (= the C30 rent). Spread-axis (BTC) and queue-axis (LINK) are one law. *(C33, exp 59)*
- `✓` **Regime determines profitability more than model or parameters** (May vs June 2025). *(C13)*

---

## Meta-hypothesis (the thesis's central claim)

> **Every real edge in crypto market microstructure is gated by a piece of professional infrastructure that
> retail lacks** — *queue priority* for the maker, *sub-1-bps fees* for the taker. The signals are real; the
> access is not.

`✓` for everything tested so far. The cross-venue lever (F) — the last chance to find an edge that escapes
both gates — **also closes**: spot↔perp are contemporaneously integrated (no exploitable lead-lag, exp 61),
so there is no third door. Every tested route is gated by queue priority, fees, information (foresight), or
risk-bearing capital — none retail-accessible.

## Narrative arc

Classical models fail on their own terms (A) → but a "degenerate" flat MM looks profitable (C) → which turns
out to be a queue-priority artifact (B) → RL confirms the artifact rather than escaping it (D) → so pivot to
the taker, which needs no queue (E) → but the taker edge, though real, is sub-fee even with ML and even when
fast (E) → cross-venue spot↔perp fusion was the only untested escape (F), but spot and perp are
contemporaneously integrated with no exploitable lead-lag, so that door closes too (F, exp 61). Two
infrastructure gates, one unifying verdict (meta).
