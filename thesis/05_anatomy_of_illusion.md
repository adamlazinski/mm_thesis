# The Anatomy of Illusory Profit

---

## 1. The General Problem

Chapter 4 ended with three facts that do not fit together: an optimiser that switches the
model off and still earns +$154/day, an edge that exists on LINK and is destroyed on BTC,
and a direct measurement showing the fill probability used by those backtests is wrong by a
factor of forty-one at the touch while being exactly right inside the spread — which is the
only place the strategy quotes.

The resolution is not a subtle statistical point. It is that a backtest is a claim about
counterfactual executions: it asserts that a particular order, had it been placed, would
have been filled at a particular price and time. Every simplification available to the
person making that claim biases it in the same direction — toward fills that a real order
would not have received, at prices at which it could not have transacted. There is no
symmetric error. A model that is wrong about queue position grants extra fills; it never
withholds deserved ones. A model that is wrong about the price grid places orders at prices
that do not exist; the exchange, which would have rejected them, is not represented in the
simulation. A model that marks positions to the mid credits the quoter with a price no
counterparty offered.

This chapter dissects the errors that produced Chapter 4's results. Three are established
here on the purchased data; two more are established later, on the captured data, and are
stated here with
forward references, because the catalogue is more useful whole than split. Section 7 then
asks what remains once all five are removed, and §8 gives the theoretical account of why the
remainder is what it is.

## 2. The First Mirage: Queue Priority

**The mechanism.** The engine of Chapter 3 §4 fills a resting order on the first trade that
touches its price. On a book where the quoter is the only participant at that level, this is
correct. On a real book it grants **absolute queue priority** — the simulated maker is always
at the front, ahead of everything already resting there.

On LINK the consequence is severe and precisely identifiable. The natural spread is exactly
one tick for 99.9% of April 2026 — $0.01 on a price near $9, so **11.1 bps quote to quote**,
with median, mean, p10 and p90 all identical. (On the $0.001 grid the experiments were
originally parameterised with, the same observation reads as a constant ten ticks;
Contribution 54 is the correction, and this chapter quotes basis points throughout to avoid
inheriting the error.) Ordinary sells print at the natural bid, half a tick — about 5.6 bps —
below the mid.

The artefact bites **at the touch**, where the quoter shares a price with the depth already
resting there. A five-LINK order joining a bid that already holds some 8,600 LINK is, under
the price-only rule, filled on the first trade that reaches that price, as though the queue
ahead of it did not exist. It is being handed fills that belong to a queue 1,700 times its
size, and Contribution 20 measures the resulting overstatement directly: a 41-fold gap in
touch-level fill probability.

**A distinction that matters, and that an earlier draft of this chapter got wrong.** The same
mechanism does *not* explain the inside-spread regimes. A bid strictly better than the natural
bid has **price priority**: an incoming market sell executes against it before reaching the
inferior level, so there is no queue to jump and the price-only rule is, on its own terms,
correct. Contribution 20 says exactly this — inside the spread the price-only and queue-aware
models agree to the digit (2.97% against 2.97%), because an order there has nothing in front
of it. What is wrong with the inside-spread quotes is not their queue treatment but their
**existence**: on the venue's true $0.01 grid there is no price strictly inside a one-tick
spread, so those orders would have been rejected on submission. That is the second mirage
(§3), not the first, and the two should not be conflated. Each regime is destroyed by its own
error, which is why the decomposition below leaves nothing standing.

**The decomposition.** Contribution 30 partitions the results by quote regime (LINK, April
2026, thirty days, zero fees, flat A-S):

| regime | quoted spread | vs. the one-tick touch | why the fill model fails | fills/day | P&L/day | 1s markout |
|---|---|---|---|---|---|---|
| deep inside | 4.5 bps (0.4 ticks) | 0.6 ticks inside | **price does not exist** (§3) | 7,673 | +$35.37 | +0.98 bps |
| inside (optimum) | 8.9 bps (0.8 ticks) | 0.2 ticks inside | **price does not exist** (§3) | 7,288 | **+$94.13** | +2.80 bps |
| at touch | 11.1 bps (1.0 tick) | at the touch | **queue priority** (§2) | 2,502 | +$33.23 | −0.41 bps |
| outside | 17.8 bps (1.6 ticks) | 0.6 ticks outside | — honest | 216 | **+$2.52** | −0.65 bps |

The spread column is the **full quote-to-quote width**, which is how the sweep was
parameterised (`min_spread_bps`, applied as `mid × bps / 20000` per side). LINK traded near $9
against a true $0.01 tick, so one tick is 11.1 bps and the "at touch" row sits at exactly one
tick by construction. Earlier drafts labelled this column "half-spread" and quoted the tick as
22.2 bps, both of which are the same factor-of-two error; the tick multiples, the regime
boundaries and every P&L figure are unaffected, since the regimes are defined by position
relative to the touch. Earlier drafts also labelled these rows 2/4/5/8 ticks, which is the
invalid $0.001 grid of Contribution 54.

The only regime in which the price-only rule is physically honest is *outside* the natural
spread: there a fill genuinely requires the market to trade through the level, so there is no
queue to jump. That regime earns **+$2.5/day** — and its markout is *negative*, meaning every
fill is initially adverse and the small positive total comes only from longer-horizon
inventory mean reversion.

This also explains Chapter 4's most anomalous number. The positive markout of +1.2 to +2.5
bps, which would mean the strategy is systematically filled by counterparties who are wrong,
appears only in the regimes where the fill model is dishonest, and inverts to negative in the
one regime where it is not. It was never a property of the flow; it was a property of the
simulator.

**At the touch, queue position is the whole story.** Re-running at the touch under an L2 queue model,
parameterised by the share of visible depth resting ahead of the order:

| position | depth ahead | P&L/day | markout |
|---|---|---|---|
| front (~1 competing order) | 9 LINK | +$11.8 | — |
| ~17 orders | 86 LINK | +$2.8 | — |
| ~86 orders | 431 LINK | +$0.4 | — |
| ~170 orders | 863 LINK | +$0.9 | — |
| mid-queue (realistic retail) | 4,313 LINK | +$1.0 | **−2.9 bps** |

From about 5% of visible depth onward the P&L is pinned at a sub-dollar noise floor and the
markout is firmly negative. Contribution 29 reaches the same place from the other direction:
imposing an L2 queue on Contribution 28's best configuration cuts thirty-day P&L from +$1,428
to +$588, a 59% reduction — while the daily *Sharpe* rises slightly, from 0.97 to 1.07,
because the queue converts frequent small fills into rare sweep-driven ones, and the adverse
fill rate on those survivors rises from 24% to 45%. Waiting in a queue selects for the fills
that occur *because the market has already moved against you*. That is the adverse-selection
cost the price-only model cannot represent by construction.

**Reinforcement learning is the same artefact, harder.** The tabular Q-learner of Chapter 4
§6 runs through the identical engine, and its action space is anchored on the natural spread
with explicit inside, near, at-touch and outside actions. Its greedy policy achieves a median
of **4,970 fills/day** (range 1,495–8,311) against the honest outside-spread ceiling of **216
fills/day** — between 7× and 38× above it, every single day. The learner did not discover an
edge; it discovered that the simulator pays for inside-spread quoting and learned to harvest
that. What is genuine and transferable in its behaviour is the regime-dependent halting, not
the spread capture, and Contribution 23's "TabularQ outperforms A-S" is true only *within*
the fictitious regime both inhabit.

The obvious objection — that reinforcement learning was never given a fair attempt under the
honest model — is closed by a paired experiment. The same TabularQ is trained on the same
three LINK days under two fill models, with train set equal to evaluation set and 200 epochs,
explicitly licensed to memorise. The control (nineteen actions, no queue model) overfits to
**+$58/day**, best epoch +$88, reproducing the artefact. The honest arms — a sixty-three-action
at-touch/outside-only space under the L2 queue model, so that no inside quote can inherit
first-touch priority — **cannot overfit to profit at all**: best stable P&L +$0.7/day, with
single-epoch bests of $4.70–8.50 that are pure noise, and the control's *worst* evaluation
sitting far above every honest *best*. A generous queue assumption and a continuous-state DQN
both fail as well; the DQN converges to approximately **zero fills per day**, which is the
correct policy when there is no edge.

**BTC is the control that confirms the mechanism.** Chapter 4 §6's flat, featureless
−$2.10/day on BTC with no learning signal is what the same code produces on an asset whose
spread is already at its one-tick minimum: there is no inside-spread region to quote into, so
the artefact is unavailable and the strategy is left with the honest result. The
asset-specificity of Chapter 4 was never about LINK being a better market. It was about LINK
having a spread wide enough for the simulator to be wrong inside it.

## 3. The Second Mirage: Prices That Do Not Exist

The queue decomposition explains the P&L. Contribution 54 then removes the mechanism itself.

Every inside-spread result in this thesis was parameterised with a LINK tick of $0.001. The
exchange tick in the sample period was **$0.01**. Validation against a live feed showed every
price in the dataset sitting on the $0.01 grid; Binance reduced the tick to $0.001 only after
the sample ended. What the backtests called a "10-tick spread" with nine placeable levels
inside it was a **one-tick spread with none**.

The inside-spread mechanism therefore did not merely enjoy optimistic queue treatment. It
placed orders at prices the exchange would have rejected outright. Chapter 4 §7's fill-curve
geometry — a plateau inside the spread, a cliff, a plateau outside — is likewise reinterpreted
rather than invalidated: measuring a $0.01-grid book at $0.001 resolution makes nine of every
ten fine-grid levels structurally empty, so the two plateaus are the two *real* price regions
(at the touch and behind it) and the cliff between them is the tick boundary itself.

This is worth stating flatly because of how long it survived. The mis-specification passed
through parameter searches, out-of-sample tests, a nine-month zero-shot transfer, a
reinforcement-learning arc and a 182-day fresh-sample validation, none of which could detect
it, because every one of them was internally consistent. Only an external check against the
venue's own rules could find it. The methodological rule that follows — validate the price
grid against a live feed, never infer it from a vendor's data — is the first entry in the
discipline of Chapter 3 §7.

## 4. The Third Mirage: Fees That Cannot Be Earned

A strategy alive only at a fee tier its own volume cannot achieve is not alive. Contributions
47 and 53 make this quantitative: the LINK edge is gated at roughly **2 bps of maker fee**,
and above that gate the mechanism is negative regardless of parameterisation. Since the same
work also shows the surviving P&L is a few dollars a day on retail size, the volume required
to reach the tier that would rescue it cannot be generated by the strategy that needs it.

This mirage differs from the others in that it is not a modelling error at all — the
arithmetic is correct — but a scoping one. Reporting a single headline number at a favourable
fee assumption conceals a discontinuity in the result. The corresponding rule is to report
P&L across the realistic fee schedule rather than at one point on it, which is why every
table in Part II carries multiple tiers.

## 5. Two Further Mirages, Established on the Captured Data

For completeness, the remaining two entries in the catalogue, both demonstrated later on the
live multi-venue capture:

**Mark-to-mid accounting** (Contribution 60, and again in Contribution 64). Crediting a
position at the prevailing mid, rather than at a price where it could be transacted,
overstates the result — at the level of a single fill, where the maker's realized half-spread
is measured against a mid no counterparty offered, and again more severely at the level of a
*position*, where an apparently profitable inventory is marked at mids at which its paired
exit never fills. Contribution 64 is the sharper case: a passive strategy that looked
positive under per-fill accounting reversed to negative under an inventory-aware round trip,
because one-sided flow fills a maker *to* its cap and the favourable mark never realises.

**Maker fill-selection, or the winner's curse** (exp 100). A passive order does not receive a
random sample of the flow; it is filled precisely when its price is the wrong one. Quoting
the receiving side of a cross-venue dislocation — a signal independently shown to be real —
produced a 1% fill rate at an 8% hit rate, because the maker was filled only in the cases
where the expected convergence failed.

Both are instances of the same asymmetry as §1: the modelling shortcut always credits the
strategy, never charges it.

## 6. What Survives Removal

Once the artefacts are removed, the honest at-touch quoter does not merely stop earning. On the
corrected engine — the one that converts marketable-on-arrival orders to takers rather than
treating them as patient limits — it **loses** at the horizons on which a maker actually turns
inventory: **−$9.78/day** at a one-second evaluation horizon, **−$2.87** at ten seconds, and only
**+$1.35/day** at thirty, on 5,768 fills/day, with a negative mean markout at every horizon and
35.9%–48.2% of fills profitable (Contribution 34, corrected-engine update). That is the residue
of Chapter 4's +$154/day: approximately zero at the longest horizon measured, and negative before
fees at every shorter one.

Contribution 34 also establishes what the residue is *not*. Running the same honest quoter
with a perfect-foresight oracle — keeping only the fills that turn out profitable — yields a
ceiling of **$28.62/day** at one second rising to **$47.24/day** at thirty. The gap between
−$9.78 and +$28.62 is not a modelling failure; it is information. There is real dispersion in
fill quality, and a quoter that could identify in advance which fills to accept would earn a
meaningful amount. No causal policy over the observable state can do so, which is precisely
what the overfitting experiment of §2 demonstrated by exhaustion. The edge exists and is
information-gated, and Chapter 6 applies four independent instruments to that gate: it opens for
none of them — not for speed, not for observable state, not for counterparty identity, not for
regime.

Contribution 32 supplies the complementary result on the other side of the book: reversion
after a fill is shallow and queue-gated, so deep liquidity provision is not a diversified
harvest of the spread but a concentrated exposure to the sweeps that clear the queue.

## 7. Why the Residue Is Zero: the Synthetic Control

A negative result invites two objections: that the engine is broken, and that the strategies
are badly implemented. Contribution 33 answers both on synthetic data with known ground
truth.

The engine reproduces analytically-derived P&L exactly on a controlled process. A-S and GLFT,
injected with the *true* volatility and run on an exponential-fill market matching their own
assumptions, are clearly profitable — so the implementations are sound and the machinery is
not rigged. On a high-volatility martingale the same quoter loses, which is the correct
short-gamma behaviour rather than an engine defect, and connects to Contribution 35's framing
of market making as a short-straddle position: the maker is paid a premium and is short
realized variance.

The decisive part is the breakeven analysis. Sweeping dollar volatility and solving for the
half-spread at which a fixed quoter breaks even gives:

| σ_$ | fixed 2-tick quoter | breakeven δ (ticks) | δ_be / σ_$ | implied κ = 1/δ_be |
|---|---|---|---|---|
| 0.02 | +$118 | 2.0 (floored) | 100 | 0.500 |
| 0.05 | −$540 | 3.9 | 77.5 | 0.258 |
| 0.10 | −$1,436 | 7.6 | 76.0 | 0.132 |
| 0.20 | −$2,843 | 15.2 | 75.9 | 0.066 |

The ratio δ_be/σ_$ is constant at about 76 across a tenfold range of volatility. The breakeven
spread is not a free parameter to be optimised; it is pinned to volatility by the market's own
structure, exactly as Wyart-Bouchaud requires. A quoter narrower than δ_be loses, one wider
does not fill, and the equality is the zero-profit condition.

**The unification.** This closes the asset-specificity of Chapter 4 §7 without appealing to
anything about LINK's character. The relation `δ* ≈ σ_$/√A` presumes the spread can move
freely. On a **small-tick** asset such as BTC the spread does move, competition compresses it
to δ*, and the maker earns zero on the spread axis — which is why BTC yields −$2.10/day and no
learning signal. On a **large-tick** asset such as LINK the spread *cannot* tighten to δ*,
because the tick floor holds it wider; the surplus that competition cannot remove through the
spread is instead competed away through **queue position**, and the rent accrues to whoever is
at the front. One zero-profit law, enforced through whichever variable happens to be free.

Chapter 4's results were, in this light, an accurate measurement of the queue rent on LINK —
credited in full to a five-LINK order that had no claim on it.

## 8. Synthesis

Five distinct errors, each biasing the same way:

| # | mirage | what the simulator grants | how it was caught | what it was worth |
|---|---|---|---|---|
| 1 | **queue priority** | front-of-queue on every fill, regardless of arrival time | L2 queue-clearing model against the price-only rule | 41× the touch fill rate; +$33/day at the touch → ~$1 |
| 2 | **prices that do not exist** | a $0.001 grid where the exchange runs $0.01 | live-feed validation of the tick against `exchangeInfo` | the inside regimes outright, +$129/day |
| 3 | **mark-to-mid** | exit at a mid no counterparty offered | inventory-aware round trip at executable touches | +1.01 bps/fill → negative |
| 4 | **unearnable fee tiers** | a tier the strategy's own volume cannot reach | reporting every tier rather than the favourable one | sign flip between 4.5 and 1.4 bps |
| 5 | **fill selection** | fill quality measured on realised fills alone | markout conditioned on the flow that selected them | the winner's curse, unquantified |

Each was found by looking for it, and each had survived robustness testing before it was found.
Removing them takes Chapter 4's +$154/day to approximately zero — negative before fees at short
horizons, +$1.35/day at thirty seconds — with a negative markout throughout, and the
synthetic control shows this is the correct answer rather than a broken one — the breakeven
spread is pinned to volatility, and the zero-profit condition is enforced on the spread axis
where the spread is free and on the queue axis where it is not.

What remains is not nothing. The foresight oracle values perfect fill selection at $29–47/day
on the same book, so the dispersion is real and the constraint is informational. The rest of
this thesis is an attempt to open that gate: Chapter 6 tests speed, observable state,
counterparty identity and price-process regime against it, and Part II asks what — if anything —
is left once all four have failed.
