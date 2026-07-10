# Introduction

---

## 1. Motivation

Market making — continuously quoting two-sided prices and earning the spread from
uninformed order flow while managing the risk of holding a non-zero position — is one of
the oldest problems in market microstructure. The Avellaneda & Stoikov (2008) framework
("A-S"), and its ergodic refinement by Guéant, Lehalle & Fernández-Tapia ("GLFT"), is the
standard modern answer: derive a reservation price and an optimal quote width from a
stochastic control problem, and the spread captured from the resulting fills compensates
for the inventory risk of a moving market.

Both models were derived for, and have mostly been validated on, markets with professional
infrastructure: co-located participants with deterministic sub-millisecond latency, maker
rebates that subsidize quoting, and — implicitly — priority in the exchange's limit order
queue that comes from being among the first to post at a price level. Retail participants
have none of these.

Crypto spot and perpetual markets offer an unusually clean setting in which to separate the
A-S/GLFT *mechanism* from the professional *infrastructure* that is normally bundled with
it. Tick-level trade and quote data is freely downloadable (this thesis uses CoinAPI feeds
for Binance BTC/USDT and LINK/USDT), exchange access requires no special relationship, and
fee schedules are public. If A-S/GLFT profitability survives when the models are implemented
faithfully, calibrated to the empirical microstructure of these markets, and backtested with
realistic (~100ms) latency and standard fees, it should appear in the numbers.

This thesis builds that backtest, runs it, and follows the result wherever it leads.

---

## 2. Research Questions

**RQ1 — Implementation.** Can A-S and GLFT be implemented faithfully and calibrated
empirically — fill-sensitivity κ, volatility σ, order-arrival rate A, and the shape of the
fill curve itself — to BTC/USDT and LINK/USDT tick data, and what do the resulting backtests
show?

**RQ2 — Mechanism.** If these backtests show a profit (they do — Contributions 16–23), what
is that profit made of? Is it spread capture from uninformed flow, as the theory assumes, or
does it depend on something the backtest grants for free that a real participant would have
to earn?

**RQ3 — Escape routes.** If the classical-MM profit is not retail-accessible, do the
alternatives the literature offers — a learned (RL) policy, taking liquidity instead of
providing it, trading across a second venue — fare any better?

**RQ4 — Generality.** Whatever the answer to RQ2/RQ3, is it specific to this dataset and
period, or does it follow from a structural property of the market that a synthetic market
with known ground truth, or a theoretical equilibrium condition, would also predict?

---

## 3. Data and Approach

The empirical work rests on an event-driven backtest engine built for this thesis, processing
CoinAPI tick-level trade and quote streams for BTC/USDT (May 2025) and LINK/USDT (June–July
2025 and April 2026, including LINK perpetuals) — on the order of four million trade-and-quote
events per trading day. The engine merges the two streams chronologically, maintains a rolling
microstructure state (volatility, order-flow imbalance, momentum, a Poisson-MLE κ estimator),
passes this state to a pluggable strategy — A-S, GLFT, a two-component "shifted GLFT", OFI and
momentum extensions, regime filters, and tabular-Q / DQN reinforcement learning — and simulates
the resulting limit orders under an explicit latency and fill model.

Two methodological choices turn out to matter more than any single strategy parameter, and
both are contributions in their own right (§5 below). First, calibrating κ, σ, and the
order-arrival rate A directly from BTC and LINK data rather than importing equity-literature
defaults (Contributions 3, 5, 25–28) — this is what first exposes the step-function fill
curve on LINK and the "momentum plateau" that strands GLFT's textbook spread on BTC. Second,
auditing the fill model itself, culminating in a correction (Contribution 30's
corrected-engine addendum) to how marketable-on-arrival orders are treated — which turns out
to be the single change that separates an apparently profitable backtest from an honest one.

---

## 4. Headline Result

Stated early, because it is the organizing fact of everything that follows: **the
profitability that classical (A-S/GLFT) and RL-based market making appear to show in a
standard event-driven backtest (Contributions 16–23) is not a strategy edge.** It is an
artifact of one unmodelled assumption — that a resting limit order has absolute priority in
the exchange's order queue regardless of when it was placed. Contribution 30 shows this
directly: re-running the identical strategies under a fill model that respects the real LINK
order-book queue (price-only fills replaced with queue-position-aware fills, and
marketable-on-arrival orders correctly treated as takers) collapses the result from a clearly
positive backtest to **−$7.93/day, 0 of 30 days positive** — a sign flip, not a shrinkage.

This is not an accident of the May 2025 – April 2026 sample. Contribution 33 derives the same
result from a zero-profit equilibrium condition (Glosten & Milgrom, 1985; Wyart, Bouchaud,
Kockelkoren, Potters & Vettorazzo, 2008): the breakeven half-spread is proportional to
volatility per trade, which pins the market-clearing fill-decay parameter κ to a level no
fixed-κ quoter can beat. On a small-tick asset (BTC) the equilibrium is enforced through the
spread; on a large-tick asset (LINK) the spread is floored at one tick, so the same law is
enforced through queue depth instead — the Contribution 30 rent *is* the Wyart–Bouchaud
equilibrium, expressed on a different axis. A synthetic-market validation (Contribution 33)
confirms the engine and the strategies are sound: fed the *true* volatility in a martingale
world with no queue and no informed flow, A-S and GLFT are robustly profitable, exactly as
theory demands. The honest-regime loss on real data is therefore the market working
correctly, not the code failing.

Three further escape routes were tested, and each closes for a distinct reason. A
reinforcement-learning policy, given the same honest fill model, cannot find a profitable
causal strategy either — it leans into the queue-priority artifact harder than the
hand-tuned baselines when the artifact is present, and cannot clear the noise floor when it
is not, even with perfect in-sample memorization (Contribution 30). An oracle with ten
seconds of perfect foresight recovers roughly twelve times the honest causal PnL (~$24/day
vs. ~$2/day), showing the edge exists but is gated behind information no causal policy has
(Contribution 34). Pivoting from making to taking liquidity removes the queue-priority
dependency entirely and finds a real, queue-independent momentum signal (~1 bps, present on
100% of tested days) — but it is capped below the perpetual taker fee (3.6 bps round-trip)
at every tested horizon, selectivity level, and even with an XGBoost model that has genuine
directional skill (Contribution 31). A cross-venue spot↔perpetual fusion strategy, the last
untested lever, finds the two venues are contemporaneously integrated with no exploitable
lead-lag (Hayashi–Yoshida cross-correlation peaks at θ=0), closing the final door
(Contribution 36).

The result is a two-gate meta-finding: every tested route to a crypto market-microstructure
edge is gated by either **queue priority** (for makers) or a **sub-1-bps fee tier** (for
takers) — both pieces of professional infrastructure that retail participants do not have.
The signals these strategies chase are real; access to them is not.

---

## 5. Summary of Contributions

The thesis makes 37 numbered contributions (`thesis_contributions.md`), which fall into five
groups.

**Empirical microstructure characterization** (C1, C5, C6, C12, C13, C15, C25–28). BTC return
autocorrelation at the 300ms–1s horizon (≈0.15–0.18), decaying to zero by 20s; a
two-component (liquidity + momentum) fill curve on BTC and a step-function fill curve on
LINK that violates the exponential premise of both A-S and GLFT; an order-of-magnitude
γ-calibration error in equity-literature defaults when applied to crypto's much smaller σ²;
and a finding that calendar regime (May vs. June 2025) explains more PnL variation than model
choice or parameters.

**Classical and RL strategy results** (C16–24). A-S, GLFT, OFI/momentum extensions, and a
tabular-Q / DQN RL agent, calibrated to the above and backtested on LINK and BTC. The
headline early result: a near-degenerate, GLFT-recommended flat-spread A-S configuration is
robustly profitable on LINK (nine-month zero-shot transfer, Contribution 19), and RL improves
on it by roughly 5% (Contribution 23) — while the identical action space fails completely on
BTC (Contribution 24), establishing relative tick size — BTC's spread-free book against
LINK's spread-floored one — as the organizing axis for everything that follows. (The early
chapters describe LINK's spread as "10 ticks"; Contribution 54 later shows the exchange tick
was ten times coarser than assumed, making it one *true* tick — a correction that reshapes
the positive results of Chapter 6 but leaves this axis, and the negative results organized
along it, intact.)

**The queue-priority decomposition** (C29, C30, C32) — the central result. C29 quantifies how
optimistic a price-only fill model is relative to an L2 queue-clearing model (a 41× overstatement
of touch fills); C30 shows the entire LINK profit (C16–24) is this artifact, and its
corrected-engine addendum shows the honest result is not breakeven but clearly negative
(−$7.93/day) once marketable-on-arrival orders are correctly charged as takers. C32 closes two
plausible escapes — low-frequency "climb the queue" MM, and deep-limit reversion MM — both of
which land at the same sub-$1/day noise floor.

**The zero-profit equilibrium and its boundary** (C33–C35, C37). C33 generalizes C30 into a
theory-grounded equilibrium law (validated on synthetic data with known ground truth) and
unifies the BTC (spread-axis) and LINK (queue-axis) mechanisms as one law. C34 shows the gap
between honest and artifact PnL is exactly the value of ten-second foresight. C35 frames the
market maker as a short-straddle writer — theta (spread capture) vs. gamma (inventory
mark-to-market) — to organize C30–C34 into a single picture, and C37 maps the boundary of the
*curable* part of that picture: a wider spread plus a faster requote restores latency
tolerance up to ~100ms in the Layer-1-only synthetic world, sharpening (without overturning)
the claim that the remaining real-data loss is a Layer-2, informational phenomenon.

**Beyond market making** (C31, C36). C31 pivots to a momentum/OBI-driven taker strategy that
needs no queue position, finds a real ~1 bps signal robust across selectivity, hold time,
latency, and an XGBoost model — but caps below the perpetual taker fee. C36 closes the last
untested escape, cross-venue spot/perpetual fusion, on contemporaneous-integration grounds.

---

## 6. Thesis Structure

1. **Introduction** (this chapter) — motivation, research questions, headline result, and a
   roadmap of contributions.
2. **Theoretical Background** — the A-S and GLFT stochastic-control derivations, and the
   market-microstructure literature on queue position and zero-profit equilibria (Glosten &
   Milgrom, 1985; Wyart, Bouchaud, Kockelkoren, Potters & Vettorazzo, 2008) that Chapter 5
   relies on.
3. **Data, Microstructure & Methodology** — the CoinAPI datasets, the empirical stylized
   facts that motivate calibration (autocorrelation, fill curves, the κ/σ/A estimation
   approaches), the backtest engine architecture, and the fill-model audit that culminates in
   the taker-on-arrival correction.
4. **Classical and Machine-Learning Strategy Results** — A-S, GLFT, OFI/momentum extensions,
   and tabular-Q/DQN RL as first backtested: the apparently profitable results (Contributions
   16–24) that pose the puzzle the rest of the thesis resolves.
5. **The Queue-Priority Decomposition** — the central contribution: the honest re-fill of the
   Chapter 4 results (C29, C30, C32), the zero-profit equilibrium that generalizes it (C33),
   the foresight oracle (C34), the short-straddle framing (C35), and the curable-boundary
   sweep (C37).
6. **Beyond Market Making: Taker and Cross-Venue Tests** — the momentum/OBI taker pivot (C31)
   and the cross-venue spot/perpetual closure (C36); the exhaustion of the "third door" search.
7. **Conclusions** — synthesis, methodological contribution, limitations and scope, and
   suggested further work (`thesis_conclusions.md`).

*(Chapter boundaries 4–6 are provisional and may be adjusted once drafting is underway —
see `thesis_contributions.md` for the full numbered contribution log and `hypotheses.md` for
the hypothesis register that cross-references it.)*
