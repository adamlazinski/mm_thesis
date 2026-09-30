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
establishes that liquidity provision at the competitive margin earns **exactly zero** for a
retail-accessible participant, that every apparently profitable backtest produced here
decomposes into one of five accounting errors, and that four mutually independent classes of
information fail to change this. The second asks what, if anything, does earn a positive
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
event-driven backtest is not a strategy edge.** Contribution 30 shows it directly: the entire
LINK profit of Contributions 16–24 is a consequence of one unmodelled assumption — that a
resting limit order has absolute priority in the queue regardless of when it was placed. The
decomposition is exact. Profitability is confined to the quote regimes where that assumption is
false, and in the one regime where the price-only fill model is physically honest — outside the
natural spread, where a fill genuinely requires the market to trade through the level — the
result falls to a few dollars a day and the average markout *inverts* from positive to negative.
Contribution 54 then removes the mechanism entirely: the inside-spread quotes that generated the
profit were placed at prices the exchange's tick grid would have rejected.

Four further accounting errors, each biasing in the same direction, complete the catalogue
(Chapter 5): mark-to-mid valuation, at the level of a single fill and again more severely at the
level of a position; fee tiers a strategy's own volume cannot earn; and the winner's curse in
maker fill selection. Once all five are removed, the honest quoter earns roughly **a dollar a
day** — between +$0.60 and +$4.06 depending on the evaluation horizon — with a negative mean
markout and fewer than half of its fills profitable.

**That residue is not noise; it is an enforced equilibrium.** Contribution 33 derives the same
result from a zero-profit condition (Glosten & Milgrom, 1985; Wyart, Bouchaud, Kockelkoren,
Potters & Vettorazzo, 2008) and validates the engine and strategies on synthetic data with known
ground truth: fed the *true* volatility in a world with no queue and no informed flow, A-S and
GLFT are robustly profitable, exactly as theory demands. On synthetic data the breakeven
half-spread is pinned to volatility at a constant ratio across a tenfold range. On a small-tick
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
| counterparty identity (C62) | exactly who is trading | separation at the 100th percentile against a wallet-shuffle placebo — and the benign pocket is **+0.0 ± 0.3 bps** |

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
  about 15 ms on Binance to beyond 5 s in the tail — and a bridge control prices the premium's
  dependence on competition exactly: the same instrument decayed from +40 bps to +0.39 bps in two
  months as the tail tightened.
- **Being paid to carry a basis** (Chapter 9). Hyperliquid's perpetual runs persistently rich, so
  shorts are contractually compensated; net of Binance's funding the differential is 5 to 8%
  annualised, and a delta-neutral book returned +8.4%/yr at a gross Sharpe near 1.26 on BTC. The
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

The thesis makes 67 numbered contributions, logged in full in `thesis_contributions.md`. The
seven groups below summarise them by theme rather than enumerate them; the log is the exhaustive
record.

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
fills); C30 shows the entire LINK profit is that artefact, and that RL leans into it harder than
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

**The three structural positions, and the negatives that bound them** (C63–C67). The cross-venue
dislocation taker (C63); maker withdrawal as a real but sub-toll signal, together with the
defended-maker retraction (C64); the closure of the flow-analysis family, including meta-order
drift priced to 0.06 bps of the wall (C65); the immediacy premium and its regime dependence
(C66); and the cointegration null with the funding-carry book that replaces it (C67).

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
   contributions.
2. **Theoretical Background** — the A-S and GLFT derivations; the fill-intensity assumption;
   price-time priority and queue position; the zero-profit equilibria of Glosten-Milgrom and
   Wyart-Bouchaud; Grossman-Miller's immediacy premium, which Part II tests directly; and the
   dealer lineage these models descend from.
3. **Data, Venues and Methodology** — the purchased datasets and the stylized facts that motivate
   calibration; the kappa/sigma/A estimation approaches; the engine architecture and the
   fill-model audit; the 2026 four-venue live capture; and the honest-accounting discipline.

**Part I — The Competitive Zero.**

4. **Classical and Machine-Learning Strategy Results** — the apparently profitable results
   (C16–24) that pose the puzzle, and the three findings within them that do not fit.
5. **The Anatomy of Illusory Profit** — the five accounting errors, the residue that survives
   their removal, and the synthetic control showing that residue is an equilibrium rather than a
   failure of implementation.
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

10. **Conclusions** — the evidentiary chain across both parts, why the zero is necessary rather
    than contingent, the methodological contribution, limitations and scope, and further work.

The full numbered contribution log is in `thesis_contributions.md`, and `hypotheses.md` holds the
hypothesis register that cross-references it.
