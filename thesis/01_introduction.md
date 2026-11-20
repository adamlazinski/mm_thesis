# Introduction

---

## 1. Motivation

Market making — continuously quoting two-sided prices and earning the spread from uninformed
order flow while managing the risk of holding a non-zero position — is one of the oldest
problems in market microstructure. The Avellaneda & Stoikov (2008) framework ("A-S"), and its
ergodic refinement by Guéant, Lehalle & Fernández-Tapia ("GLFT"), is the standard modern
answer: derive a reservation price and an optimal quote width from a stochastic control
problem, and the spread captured from the resulting fills compensates for the inventory risk
of a moving market.

Both models were derived for, and have mostly been validated on, markets with professional
infrastructure: co-located participants with deterministic sub-millisecond latency, maker
rebates that subsidise quoting, and — implicitly — priority in the exchange's limit order queue
that comes from being among the first to post at a price level. Retail participants have none
of these.

Crypto markets offer an unusually clean setting in which to separate the A-S/GLFT *mechanism*
from the professional *infrastructure* normally bundled with it. Tick-level data is freely
available, exchange access requires no special relationship, and fee schedules are public. If
A-S/GLFT profitability survives when the models are implemented faithfully, calibrated to the
empirical microstructure of these markets, and backtested with realistic latency and standard
fees, it should appear in the numbers.

It does appear, and this thesis is largely an account of why that appearance is misleading and
what remains once it is removed. The investigation proceeds in two movements. The first
establishes that liquidity provision at the competitive margin returns a quantity
**indistinguishable from zero** for a retail-accessible participant across every book and
sample tested, that every apparently profitable backtest produced here was traced to an
execution-accounting error, and that four distinct classes of information fail to change it.
That the zero is an *enforced equilibrium* rather than an unlucky sample is the reading this
thesis argues for and does not claim to have proved; Chapter 10 §1 separates the two and
states what the design can and cannot support. The second asks what, if anything, does earn a positive
return once that is accepted, and finds three answers — none of which is a signal.

The work also outgrew its data. It begins with purchased tick history for two Binance pairs and
ends with a purpose-built capture of four venues recorded simultaneously, because the questions
raised by the first results could not be answered from vendor files: a correction to the most
basic parameter of the market (Contribution 54) came only from checking a live feed; the queue
decomposition needed real resting depth rather than a quote-derived proxy; the cross-venue
questions needed venues observed at the same instant; and the sharpest test of flow selection
needed something no centralised exchange discloses — the identity of the counterparty.

---

## 2. Research Questions

**RQ1 — Implementation.** Can A-S and GLFT be implemented faithfully and calibrated
empirically — fill-sensitivity kappa, volatility sigma, order-arrival rate A, and the shape of
the fill curve itself — to crypto tick data, and what do the resulting backtests show?

**RQ2 — Mechanism.** If those backtests show a profit (they do; Contributions 16–24), what is
that profit made of? Is it spread capture from uninformed flow, as the theory assumes, or does
it depend on something the simulation grants for free that a real participant would have to
earn?

**RQ3 — The competitive margin.** If the apparent profit is an artefact, is the honest result
approximately zero *by accident of this sample*, or is it an enforced equilibrium? And does any
class of information open it — being faster, reading the market's observable state, knowing the
counterparty's identity, detecting the prevailing price-process regime, or acting on the
sharpest causal signal the data contains?

**RQ4 — The boundary.** Whatever survives, what is it compensation *for*? Is a positive return
available at all to a participant without professional infrastructure, and if so, does it come
from predicting prices or from occupying a structural position that someone must occupy?

RQ1 and RQ2 are answered in Part I, RQ3 is the subject of its central chapter, and RQ4 is
Part II.

---

## 3. Data and Approach

The empirical work rests on an event-driven backtest engine built for this thesis, and on two
distinct data programmes.

The first is **purchased tick history** (CoinAPI): trade and quote streams for BTC/USDT (May
2025) and LINK/USDT (June–July 2025, April 2026, and 182 further untouched days from October
2025 to March 2026), together with LINK perpetuals — on the order of four million
trade-and-quote events per trading day. The engine merges these streams chronologically,
maintains a rolling microstructure state (volatility, order-flow imbalance, momentum, a
Poisson-MLE kappa estimator), passes it to a pluggable strategy — A-S, GLFT, a two-component
"shifted GLFT", OFI and momentum extensions, regime filters, and tabular-Q / DQN reinforcement
learning — and simulates the resulting limit orders under an explicit latency and fill model.

The second is a **purpose-built live capture** (July–September 2026) of four venues recorded
concurrently: Binance spot and USDT-M perpetuals, Coinbase spot and International perpetuals,
Hyperliquid perpetuals including a screened long tail of thinly-quoted instruments, and Deribit
options. It is raw-first — every websocket message appended verbatim with a local receive
timestamp, reconstruction performed offline under each venue's own synchronisation rules — and
it supplies four things the purchased data cannot: real order-book depth, several venues
observed at the same instant, two clocks per event, and, on Hyperliquid, both counterparty
wallet addresses on every trade.

Two methodological commitments matter more than any strategy parameter. The first is
calibrating kappa, sigma and A directly from the data rather than importing equity-literature
defaults (Contributions 3, 5, 25–28), which is what exposes the step-function fill curve on LINK
and the momentum plateau that strands GLFT's textbook spread on BTC. The second is the
**honest-accounting discipline** of Chapter 3 §7: ten rules, each traceable to a specific error
this thesis made and then found — exchange-valid prices, real queue clearing, taker-on-arrival
treatment, round-trip pricing at executable touches rather than mark-to-mid, inventory-aware
simulation, placebo and anti-signal controls, out-of-sample and pre-registered replication,
depth-capped capacity, common-clock validation, and explicit fee tiers. The discipline is itself
a contribution, and its severest test is that it removed two of this author's own positive
results (Contributions 64 and 66), both reported in full.

---

## 4. Headline Result

Stated early, because it organises everything that follows.

**The profitability that classical and RL-based market making appear to show in a standard
event-driven backtest is not a strategy edge.** Contribution 30 shows it directly, by
sweeping the quote distance and measuring the P&L at each: every profitable setting is one in
which the simulated fill could not have happened, and the settings fail for two different
reasons. *Inside* the spread — where the optimiser places the strategy, and where the sweep
peaks at +$94/day — the orders sit at prices the exchange's $0.01 tick grid does not contain,
and would have been rejected on submission (Contribution 54). *At the touch*, where the price
is real,
the price-only fill model grants the order absolute queue priority it has not earned,
overstating the fill rate by a factor of 41 against an L2 queue-clearing model (Contribution
20). In the one regime where the fill model is physically honest — outside the natural spread,
where a fill genuinely requires the market to trade through the level — the result falls to a
few dollars a day and the average markout *inverts* from positive to negative. Nothing is left
standing, and the decomposition is exact.

Four further accounting errors, each biasing in the same direction, complete the catalogue
(Chapter 5): mark-to-mid valuation, at the level of a single fill and again more severely at the
level of a position; fee tiers a strategy's own volume cannot earn; and the winner's curse in
maker fill selection. Once all five are removed, the honest quoter earns **approximately
zero**, and in fact *negative* before fees at the horizons that matter — −$9.78/day
measured at one second, −$2.87 at ten, and +$1.35 only at thirty — with a negative mean markout
throughout and fewer than half of its fills profitable.

**The reading this thesis offers is that the residue is not noise but an enforced
equilibrium** — an interpretation of the measurement, held to a lower standard than the
measurement itself and argued as such in Chapter 10 §1. The zero-profit condition it appeals to
is Glosten & Milgrom (1985) and Wyart, Bouchaud, Kockelkoren, Potters & Vettorazzo (2008), and
the supporting evidence is Contribution 33's synthetic control, which validates the engine and
the strategies against known ground truth: fed the *true* volatility in a world with no queue
and no informed flow, A-S and GLFT are robustly profitable, exactly as theory demands, and the
breakeven half-spread scales with volatility at a constant ratio across a tenfold range. That
last is a property of the simulated market rather than a measurement of a real one, and
Chapter 5 §7 is explicit about the difference. On a small-tick
asset (BTC) the equilibrium is enforced through the spread; on a large-tick asset (LINK) the
spread is floored at one tick, so the same law is enforced through **queue depth** instead. The
Contribution 30 rent *is* the Wyart-Bouchaud equilibrium, expressed on whichever axis happens to
be free.

**The competitive zero is then measured four independent ways** (Chapter 6), each corresponding
to a class of information a maker might bring:

| instrument | what it knows | result |
|---|---|---|
| model-free markout (C59) | nothing — the tape alone | the half-spread is eaten within 100 ms on every book |
| speed (C60) | the leading venue, 1 ms sooner | 1 ms performs as 10 ms; nothing remains inside an 80 ms lead |
| observable state (C61) | flow, imbalance, volatility, intensity | toxicity is rankable; the cleanest 20% is still negative at a *zero* fee |
| counterparty identity (C62) | exactly who is trading | separation at the 100th percentile against a wallet-shuffle placebo — and the benign pocket is **+0.15 ± 0.20 bps**, against a 1.0 bps fee |

Three of the four detect genuine, placebo-validated structure. All four terminate at zero rather
than below it, which is what an enforced equilibrium looks like from the inside: the predictable
component of adverse selection is already incorporated in the price at which the maker is
permitted to trade. A price-process regime filter fails the same way, and a matched-frequency
placebo accounts for the whole of its apparent improvement.

**What does pay is structural position, not prediction.** Part II establishes three
configurations that survive the full discipline, and each is compensation for bearing a risk or
occupying a seam rather than for knowing something:

- **Renting a slow venue's clock** (Chapter 7). Where a venue's makers reprice on a seconds
  clock rather than a millisecond one, dislocations from the consensus price are large enough to
  clear the toll: +4.8 to +5.8 bps per event across two days and two independent leaders, priced
  at executable touches on both legs, and surviving a clock-artefact check by improving. It is
  bounded on three sides — threshold, fee tier, and a touch holding only a few thousand dollars —
  and the capacity bound is *why* an edge visible in public data has not been competed away.
- **Providing immediacy where nobody else will** (Chapter 8). On books with two or three makers
  at the touch, the spread genuinely exceeds the adverse-selection cost: four of six instruments
  clear base fees on an inventory-aware round trip and the basket is positive on every day of two
  samples, with a pre-registered replication on disjoint instruments. The organising law of
  Part II emerges here — **the adverse-selection horizon is the venue's repricing clock**, from
  about 15 ms on Binance to beyond 10 s in the tail — and a bridge control prices the premium's
  dependence on competition directly: the same instrument decayed from +32.4 bps to approximately
  zero in two months as the tail tightened.
- **Being paid to carry a basis** (Chapter 9). Hyperliquid's perpetual runs persistently rich, so
  shorts are contractually compensated; net of Binance's funding the differential is 5 to 8%
  annualised, and a delta-neutral book returned +8.4%/yr annualised on BTC — though over the
  thirty-six hours actually observed that is 3.45 bps against a 5.6 bps round trip, so what is
  established is that the cash flow is collectible, not that the window paid. The
  basis, not the funding, is the risk, and the cascade tail that ends such books is the one
  quantity a benign sample could not measure.

The through-line is a single sentence: **markets pay for risk-bearing and structural position,
not for prediction a single participant can compute.** Every genuinely predictive effect measured
here — short-horizon momentum, order-book imbalance, the perpetual lead, institutional
meta-order drift, maker withdrawal, wallet-level toxicity — is real, placebo-validated where a
placebo applies, and priced at or just under the cost of acting on it. Meta-order drift, the
best-documented flow effect in the literature, is priced to within **0.06 bps** of the fee wall.
The exceptions are not better forecasts; they are seams that competition has not reached, and
each is as small as the seam permits.

Two corrections to earlier conclusions are recorded here rather than buried. Contribution 36
closed the cross-venue escape on the finding that spot and perpetual are contemporaneously
integrated; Contribution 56 shows that theta = 0 was a resolution artefact of a 100 ms grid, and
that the perpetual in fact leads by 40–100 ms — which reopened the question Chapter 7 eventually
answers. And the "two-gate" formulation of an earlier draft (queue priority for makers, a
sub-1 bps fee tier for takers) is superseded by the stronger statement above: the gate is the
equilibrium itself, and infrastructure is one of several ways to sit outside it.

---

## 5. Summary of Contributions

Four substantive contributions, in the order the thesis establishes them.

1. **A decomposition of apparent market-making profit into five accounting illusions**, each
   identified by a mechanism rather than a correction factor, and each shown to account for a
   specific published-looking result in this project. The decomposition is exhaustive on the
   data tested: nothing survives all five.
2. **A measurement of the competitive zero by four mutually independent instruments** — the
   tape alone, speed, observable state, and counterparty identity resolved to the wallet — which
   agree that the residue is zero rather than negative, together with a derivation of that zero
   from a breakeven ratio that is constant across a tenfold range of volatility.
3. **Three structural positions that survive the decomposition**, with a law relating them: the
   adverse-selection horizon tracks the venue's repricing clock across nearly three orders of
   magnitude, and the surviving returns are compensation for bearing a risk on that clock rather
   than rewards for prediction. A pre-registered replication and a within-instrument bridge
   control establish that the magnitude is priced by competition.
4. **A ten-rule honest-accounting discipline for backtesting**, each rule motivated by the false
   positive its absence produced here, and demonstrated by the results it removed — including
   two of the author's own, in full.

A fifth is methodological and negative: the thesis reports the strategies that *failed*, at the
same level of detail as those that worked, because the asymmetry between the two is the finding.

These rest on **68 numbered contributions** logged in `contributions.md`, which is the
exhaustive record and the source of truth for every number in these chapters. Most of the 68 are
calibrations, controls, retractions and bounding negatives rather than claims in their own
right; the count is a measure of the work, not of the result. The seven groups below summarise
them by theme.

**Empirical microstructure characterisation** (C1, C5, C6, C12, C13, C15, C25–28, C58). BTC
return autocorrelation of about 0.15–0.18 at the 300 ms–1 s horizon decaying to zero by 20 s; a
two-component (liquidity plus momentum) fill curve on BTC and a step-function curve on LINK, both
of which violate the exponential premise of A-S and GLFT; an order-of-magnitude gamma-calibration
error in equity-literature defaults applied to crypto's much smaller sigma-squared; calendar
regime explaining more P&L variation than model choice; and, from the live capture, direct
measurement of the three premises the central verdict rests on — a one-tick modal spread, roughly
half of all touch-level disappearances being cancellations rather than trades, and spread repair
in about 100 ms.

**Classical and machine-learning strategy results** (C16–24). A-S, GLFT, OFI/momentum extensions
and tabular-Q / DQN agents, calibrated as above. A near-degenerate flat-spread configuration is
robustly profitable on LINK with a nine-month zero-shot transfer (C19), RL improves on it by
about 5% (C23), and the identical action space fails completely on BTC (C24) — which establishes
relative tick size as the organising axis of the thesis.

**The queue-priority decomposition and the five mirages** (C29–C32, C46–C54). C29 quantifies the
optimism of a price-only fill model against L2 queue clearing (a 41-fold overstatement of touch
fills); C30 shows the entire LINK profit sits in regimes the fill model misprices, and that RL leans into them harder than
hand-tuned baselines; C32 closes two plausible escapes at the same sub-dollar noise floor; C54
retracts the mechanism itself on tick-grid grounds; C46–C53 establish the fee gate and the
spread-width gate.

**The zero-profit equilibrium and its boundary** (C33–C35, C37). C33 generalises C30 into a
theory-grounded law, validated on synthetic data, and unifies the spread-axis and queue-axis
mechanisms. C34 values ten-second foresight at roughly twelve times the honest causal P&L,
locating the binding constraint in information rather than in execution. C35 frames the maker as
a short-straddle writer, and C37 maps the curable part of the boundary.

**The competitive zero, measured four ways** (C55–C62). Capture validation and the three measured
premises (C55, C58); the perpetual lead and the wall it fails to clear (C56, C57); and the four
instruments — model-free markout (C59), speed and co-location (C60), observable state (C61), and
counterparty identity (C62).

**The three structural positions, and the negatives that bound them** (C63–C68). The cross-venue
dislocation taker (C63); maker withdrawal as a real but sub-toll signal, together with the
defended-maker retraction (C64); the closure of the flow-analysis family, including meta-order
drift priced to 0.06 bps of the wall (C65); the immediacy premium and its regime dependence
(C66); the cointegration null with the funding-carry book that replaces it (C67); and the
extension of the central result to a second asset class, where Deribit options market making
fails at a hypothetical *zero* maker fee (C68).

**Methodological contribution.** The honest-accounting discipline of Chapter 3 §7, its ten rules
each traced to a specific failure, and the two self-retractions (C64, C66) that demonstrate the
discipline can overturn the author's own positive results. Alongside it, a negative result of
independent interest: Deribit options market making fails even at a hypothetical zero maker fee,
and the two modelling traps encountered there — a pooled-series composition artefact and a
forward-versus-spot repricing error — are documented as method.

---

## 6. Thesis Structure

The thesis is in two parts, preceded by foundations.

**Foundations.**

1. **Introduction** (this chapter) — motivation, research questions, headline result,
   contributions. The abstract, notation, data inventory and reproducibility statement precede
   it in `00_front_matter.md`.
2. **Theoretical Background** — the A-S and GLFT derivations; the fill-intensity assumption;
   price-time priority and queue position; the zero-profit equilibria of Glosten-Milgrom and
   Wyart-Bouchaud; Grossman-Miller's immediacy premium, which Part II tests directly; and the
   dealer lineage these models descend from.
3. **Data, Venues and Methodology** — the purchased datasets and the stylized facts that motivate
   calibration; the kappa/sigma/A estimation approaches; the engine architecture and the
   fill-model audit; the 2026 four-venue live capture; the honest-accounting discipline; and the
   inference methods used to put intervals on everything that follows.

**Part I — The Competitive Zero.**

4. **Classical and Machine-Learning Strategy Results** — the apparently profitable results
   (C16–24) that pose the puzzle, and the three findings within them that do not fit.
5. **The Anatomy of Illusory Profit** — the five accounting errors, the residue that survives
   their removal, and the synthetic control establishing that the engine behaves correctly where
   the answer is known, so that the residue is a measurement rather than an artefact of
   implementation.
6. **The Zero, Measured Four Ways** — the central chapter: markout, speed, observable state and
   counterparty identity, all terminating at zero.

**Part II — The Boundary.**

7. **Cross-Venue Dislocation** — renting a slow venue's clock: the one strategy that survives
   every test applied to it.
8. **The Immediacy Premium in Thin Books** — where competition is thin the spread exceeds its
   cost; the venue-clock law; the pre-registered replication and the bridge control.
9. **Carry and the Funding Basis** — the cointegration null and the cross-venue funding book; the
   basis as the actual risk, and the tail this thesis could not measure.

**Synthesis.**

10. **Conclusions** — the evidentiary chain across both parts, what the zero does and does not
    establish, the methodological contribution, limitations and scope, and further work.

The full numbered contribution log is in `contributions.md`, and `hypotheses.md` holds the
hypothesis register that cross-references it.
