# Conclusions

This thesis set out to implement and calibrate the Avellaneda-Stoikov and
Guéant-Lehalle-Fernández-Tapia market-making models on crypto tick data, and to ask whether
they are profitable. They appeared to be. Establishing that they are not, and then finding
what is, took the project through five accounting artefacts, four independent measurements of
the same equilibrium, a purpose-built capture of four venues, two retractions of its own
positive results, and finally to three positions that do pay — none of which is a market-making
strategy in the sense the first chapter meant.

This chapter states the resulting claim, sets out why it is a necessary rather than a
contingent result, explains why the exceptions in Part II confirm it rather than qualify it,
answers the four research questions in order, and closes on what the thesis contributes as
method, what it cannot support, and what should be done next.

---

## 1. The Claim

The thesis makes a two-part claim, and the parts are not independent — the second is the first
read at its boundary.

**Part one — the measurement.** Across the books, samples and configurations tested here,
competitive liquidity provision by a participant without co-location or a negotiated fee
schedule returns a quantity **indistinguishable from zero at the precision these samples
support**, and negative before fees at the horizons on which a maker turns inventory. Every
apparently profitable backtest produced in the course of this project — classical,
signal-overlaid, or reinforcement-learned — was traced to an execution-accounting error, and
no class of information brought to bear on the residue moved it into profit.

**Part one — the interpretation.** The reading this thesis offers is that the residue is an
enforced competitive equilibrium rather than a run of bad luck: it is what Glosten-Milgrom and
Wyart-Bouchaud predict, it reproduces on synthetic data where the breakeven spread is pinned
to volatility by construction, and four differently-constructed measurements land in the same
place rather than scattering. That is an interpretation, and it should be held to a different
standard than the measurement. **It is not established that the true value is literally
zero**, and the design here could not establish it. Two of the gaps that earlier drafts left
open have since been closed: headline quantities now carry dependence-aware bootstrap intervals
with the unit of replication stated (Chapter 3 §8, `thesis/intervals.md`), and the three
arg-max sites disclose their multiplicity. Three remain, and they are the ones that would be
needed for an equivalence claim: the thesis specifies **no equivalence interval** around zero,
carries **no power calculation**, and applies no multiplicity adjustment across the project's
hundred-odd experiments taken together. The four instruments share data, markout definitions,
code paths and a market regime, so they are four *probes* rather than four independent
replications. Failing to find a
positive result is not the same as demonstrating equality to zero, and competitive-equilibrium
reasoning about the marginal efficient provider does not by itself imply that every
technologically disadvantaged participant earns raw P&L of exactly zero. The strong form of
the claim, used in earlier drafts of this chapter, outran its evidence and is withdrawn.

**Part two.** Positive expected returns appear to be available at the boundary of that
equilibrium, and three candidates were found and stress-tested here. All three rest on short
windows — two days, five days, thirty-six hours — and each is qualified in its own chapter by
a specific accounting or sampling limitation that is not yet closed. They are best read as
**exploratory existence evidence that locates the boundary**, not as established strategies. None of them is a forecast. Each is
compensation for bearing a risk or for occupying a structural position that someone must
occupy: trading against a venue whose makers reprice on a slower clock, providing immediacy on
a book where two or three participants are willing to, and being paid to carry a cross-venue
basis. Each is bounded by the thing that makes it available — capacity, competition, or a tail
the sample does not contain — and each is as small as that bound permits.

Stated as one sentence: **markets pay for risk-bearing and structural position, not for
prediction a single participant can compute.**

---

## 2. Part I: Why the Zero Is Necessary Rather Than Contingent

The argument is a chain, and its force comes from the order of the links rather than from any
single measurement. Each step forecloses a different objection to the one before it.

**Step 1 — the machinery is validated before it is doubted.** On synthetic data with known
ground truth, the engine reproduces analytically-derived P&L exactly, and A-S and GLFT,
injected with the *true* volatility on an exponential-fill market matching their own
assumptions, are robustly profitable (Contribution 33). The implementations are therefore
sound and the engine is not rigged toward a negative answer. On a high-volatility martingale
the same quoter loses, which is the correct short-gamma behaviour rather than a defect, and
connects to Contribution 35's reading of the maker as a writer of a short straddle.

**Step 2 — the apparent profit is real, and stable, and none of it comes from the models.**
On LINK the calibrated strategies earn +$154/day, profitable on thirty consecutive days and
transferring nine months forward across a 30% price move (Chapter 4). But the optimum is
degenerate — random search converges on switching the market-making formula *off*, and a
controlled comparison shows the formula is a liability rather than an asset — signal overlays
make it worse, reinforcement learning improves on it by about 5%, and the identical
configuration yields −$2.10/day on BTC with no learning signal at all. A P&L that survives the
deletion of the entire theoretical apparatus is not being produced by that apparatus.

**Step 3 — five accounting errors, all biasing the same way** (Chapter 5). Sweeping the quote
distance shows the P&L concentrated in the settings where the fill model is wrong, and the two
profitable settings are wrong in different ways. *Prices that do not exist*: LINK's exchange
tick was 0.01, not the 0.001 assumed throughout, so the inside-spread placements — where the
optimiser puts the strategy, and where the sweep peaks at +$94/day — were on a grid the venue
would have rejected outright (Contribution 54). *Queue priority*: at the touch, where the price is real, a price-only fill
model grants a resting order absolute priority it has not earned, overstating fill probability
by a factor of 41 against L2 queue clearing and collapsing +$33/day to about a dollar
(Contributions 20, 29, 30). The two are distinct and were conflated in an earlier draft: a
quote strictly inside the spread has price priority and no queue to jump, which is why
Contribution 20 finds the two fill models agreeing exactly there. *Mark-to-mid accounting*, at the level of a single fill and again more severely at the
level of a position. *Fee tiers a strategy's own volume cannot earn.* *The winner's curse in
maker fill selection.* Each was found by looking for it, and each had survived robustness
testing before it was found.

**Step 4 — the residue is measured, and it is small and adversely selected.** With all five
removed, the honest at-touch quoter is not merely unprofitable but **negative before fees** at
short horizons: −$9.78/day measured at one second, −$2.87 at ten, and +$1.35 only at thirty, with
a negative mean markout at every horizon and 35.9%-48.2% of fills profitable (Contribution 34,
corrected engine). Against that, a perfect-foresight oracle keeping only the fills that turn out
well earns **$28.62 to $47.24/day** on the same book. The dispersion in fill quality is real; what is missing is the information to sort it.
The constraint is identified as informational at this point, not assumed.

**Step 5 — the residue has the shape theory predicts.** Sweeping dollar volatility on
synthetic data and solving for the half-spread at which a fixed quoter breaks even gives a
ratio δ_be/σ_$ that is **constant at about 76 across a tenfold range of volatility**
(Contribution 33). This is a simulator exercise, and Chapter 5 §7 is explicit that the scaling
is substantially a property of the construction — fill intensity is held fixed — so it
establishes that the engine reproduces the scaling theory predicts on a world where the answer
is known, not that a real market's spread is pinned by it. The structural reading that survives
is weaker and sufficient: the breakeven spread is not a free parameter a quoter may optimise.
A narrower quote loses and a wider one does not fill, which is the shape Glosten-Milgrom's
zero-expected-profit dealer and Wyart-Bouchaud's empirical spread-volatility relation both
have. This step also dissolves Chapter 4's
asset-specificity without appealing to anything about LINK's character: where the spread is
free to move (BTC, small relative tick) competition compresses it to the breakeven width and
the maker earns zero *on the spread axis*; where the tick floors the spread wider than
breakeven (LINK, large relative tick) the surplus is competed away through **queue depth**
instead, and accrues to whoever is at the front. One zero-profit law, enforced through
whichever variable happens to be free. Chapter 4's numbers were an accurate measurement of the
queue rent on LINK, credited in full to a five-LINK order with no claim on it.

**Step 6 — four independent instruments, all terminating at zero** (Chapter 6). The obvious
remaining objection is that the right information was never brought to bear. Four mutually
independent classes of it were, on books from three venues:

| instrument | what it knows | result |
|---|---|---|
| model-free markout (C59) | nothing — the tape alone | realized half-spread negative within 100 ms on every book |
| speed (C60) | the leading venue, 1 ms sooner | 10 ms to 1 ms: −$2.04 to −$1.94, and +$1.91 to +$0.54 |
| observable state (C61) | flow, imbalance, volatility, intensity | toxicity rankable; cleanest 20% still negative at a *zero* fee |
| counterparty identity (C62) | exactly who is trading | placebo separation at the 100th percentile; benign pocket +0.15 ± 0.20 bps, against a 1.0 bps fee |

Three of the four detect genuine, placebo-validated structure. The decisive feature is not that
each fails but that **each lands at zero rather than well below it**. Contribution 60 is the
sharpest form: a true, placebo-proof, out-of-sample-robust signal — the 40-100 ms perpetual
lead — whose optimal use nets **+$0.13/day** against a spread of about $5. Acting correctly on
real information forfeits exactly the spread revenue it saves, because the market has already
priced the lead into the width at which the maker is permitted to quote. Speed is not the
missing ingredient either: a 15 ms gate already fires inside a 40-100 ms lead, so collapsing
the stack to the co-located 1 ms limit has nothing left to catch, and front-of-queue
positioning is worse.

Four unlucky experiments would be a coincidence. Four instruments landing at zero is what an
enforced equilibrium looks like from the inside: a market where liquidity provision paid
positively would attract quoting until the spread compressed or the queue lengthened, and one
where it paid negatively would lose quoters until the spread widened. Rankable toxicity, real
signals, and a net of zero is the only stable configuration.

---

## 3. Part II: What the Boundary Pays, and Why It Is Not a Counterexample

If the competitive zero is exact, a positive return requires leaving the competitive game. Part
II establishes three ways to do so, and the temptation is to read them as counterexamples to
Part I. They are not. Each is the zero-profit law evaluated where competition has not arrived,
and each is bounded by exactly how far it has not arrived.

**Renting a slow venue's clock** (Chapter 7, Contribution 63). Exactly one venue-level lead
exists in the captured universe: the centralised complex moves as a block ahead of Hyperliquid
by 200-500 ms, and the twenty-five pairs that show it are one relationship multiplied by the
market factor, not twenty-five findings. Trading dislocations above 5 bps as a taker at
executable touches on both legs returns **+4.8 to +5.8 bps per event**, across two days and two
independent leaders, with hit rates of 85-96% and a median approximately equal to the mean. It
survived a clock-artefact check by improving under the common receive clock. It is bounded on
three sides: below 5 bps the population is large and decisively negative, it is negative at
Hyperliquid's 4.5 bps base taker fee and positive only at the 1.4 bps high-volume tier, and the
touch holds **$1.4k to $8k** at event times because Hyperliquid's own makers withdraw on the
same signal. The capacity bound is not a defect of the measurement — it is the answer to why an
edge visible in public data has not been competed away.

**Providing immediacy where nobody else will** (Chapter 8, Contribution 66). On Hyperliquid tail
books with two or three makers at the touch, the maker's realized half-spread never goes
negative within ten seconds. Four of six books clear **base** fees on an inventory-aware round
trip over five days, each day's residual position liquidated across the closing spread rather
than marked at the mid — HMSTR +13.36 bps of notional, USUAL +12.65, ZORA +7.42, CELO +3.33 —
while VINE at +0.63 does not clear and EIGEN at −1.16 is persistently negative. That terminal
treatment matters less than it looks: pooled over the thirty coin-days the liquidated round trip
is +6.04 bps against +6.36 mid-marked and +6.05 on matched volume alone, so the premium is not an
artefact of how the open position is valued. It was the live alternative explanation and it is
excluded. EIGEN is the one book
in the screen whose competition has already arrived. Per-coin P&L is sign-unstable day to day; the equal-weighted **basket** is positive on all
five days of the original sample and on 4 of 4 days of a pre-registered replication on disjoint
coins, with the micro-price anchor beating the mid on 4 of 4.

**Being paid to carry a basis** (Chapter 9, Contribution 67). Hyperliquid's funding ran 72-100%
positive over the captured window at roughly 11% annualised; net of Binance's funding the
delta-neutral differential is **+5.4% to +7.8%** on all four majors — a contractual cash flow
rather than an estimated edge. But the differential is what the book collects, not what it
earns: the two price legs do not cancel, and the basis moves. On BTC the basis happened to help
(+1.7%/yr on top of +6.7% of funding) for a gross **+8.4%/yr annualised** — which over the
thirty-six hours observed is 3.45 bps against a 5.6 bps round trip, so the window does not pay
for itself and the annualisation is the whole of the headline; on LINK an
adverse drift of −8.6%/yr consumed the entire funding leg and the book returned approximately
zero. With basis volatility of 7-12% against a funding signal of about 7%, any short window
measures the basis rather than the carry.

Set side by side, the three have the same shape and differ only in which bound binds:

| | **dislocation taker** (Ch 7) | **immediacy premium** (Ch 8) | **funding carry** (Ch 9) |
|---|---|---|---|
| what is paid for | being fast against a slow venue | warehousing inventory nobody else will | holding a basis someone wants shed |
| size | +4.8 to +5.8 bps / event | +0.96 to +14.4 bps / round trip | +5.4% to +7.8% annualised |
| evidence | 2 days × 2 independent leaders | 5 days + pre-registered 4-day replication | 2 windows, 4 majors |
| what bounds it | **capacity** — $1.4–8k at the touch | **competition** — decays as the tail tightens | **the basis** — 7–12%/yr vol on a ~7% signal |
| fee sensitivity | negative at 4.5 bps, positive at 1.4 | clears base fees on 4 of 6 books | one-time 5.6 bps; 0.68%/yr monthly, 20%/yr daily |
| principal unknown | behaviour at size | whether any tail stays wide | the cascade tail |
| is it a forecast? | no — a measured deviation | no — a quoted spread | no — a contractual cash flow |

**The law that unifies them.** Chapter 8's central measurement is not the P&L but the ordering
of adverse-selection horizons across venues:

| book | adverse-selection horizon |
|---|---|
| Binance BTC spot / perp (small relative tick) | 15 ms |
| Binance / Hyperliquid LINK (large relative tick) | 75-88 ms |
| Coinbase LINK perp | 0.46 s |
| Hyperliquid LINK | 1.3 s and 4.2 s (two days) |
| Hyperliquid EIGEN | 6.2 s |
| Hyperliquid tail (5 of 6 books) | > 10 s, never crosses |

These are measured under a carry-forward quote rule, with retention reported at every horizon.
The original freshness-gated rule kept as little as 26% of the trades at ten seconds on the
thinnest books, and it biased the slow books toward looking *fast*, because the trades it kept
were those in busy periods. Correcting it moved every crossing later and none earlier, widening
the law's span from roughly two orders of magnitude to nearly three.

**The adverse-selection horizon is the venue's repricing clock.** A maker's edge survives for
as long as it takes the rest of the market to notice the price is wrong, and that interval
spans three orders of magnitude across the venues captured here. Chapters 7 and 8 are the same
observation from the two sides of the trade: Chapter 7 profits by being the fast participant
against a slow venue, and Chapter 8 asks whether being the slow venue's maker is itself paid.
It is, by the amount the clock is slow.

**Why these are premia and not edges.** All three share five properties, and the list is what
distinguishes a risk premium from an information edge:

1. *Nothing is predicted.* The dislocation taker trades a measured deviation from consensus;
   the thin-book maker quotes a spread; the carry book collects a contractual payment.
2. *Each is unstable per unit and stable only in aggregate* — per-coin immediacy P&L is close
   to a coin flip, per-window carry is basis-dominated — which is what compensation per unit of
   idiosyncratic risk borne must look like.
3. *Each is priced by the competition it faces, not by the skill applied.* The bridge control
   is the cleanest evidence in the thesis: USUAL, the same coin and the same strategy, fell from
   **+32.4 bps of notional in July to approximately zero in August** while the tail's widest
   spread compressed from 56 bps to 14 bps, a decay reproduced in fifteen of the sixteen
   configurations swept. Nothing about the technique changed; the regime did.
4. *Costs can invert the usual logic.* The carry book's 5.6 bps round trip amortises to
   +0.68%/yr rebalanced monthly and to **20%/yr churned daily** — a position destroyed by being
   traded.
5. *The binding parameter is the one a benign sample cannot show.* Both carry windows had
   maximum drawdown under 20 bps, so the measured basis volatility is the *calm* volatility, and
   what ends such books is the liquidation cascade the capture does not contain.

The zero-profit law is therefore not violated at its boundary. It is **parameterised** there:
the majors sit at zero because competition has arrived and compressed the spread to its cost,
the tail sits above zero by the amount competition has not yet removed, and applying the same
law to the same book two months later predicts the decay the bridge control measures.

---

## 4. The Answers to the Research Questions

**RQ1 — Implementation.** Yes. A-S, GLFT, a two-component shifted GLFT, OFI and momentum
overlays, regime filters and tabular-Q/DQN agents were implemented and calibrated from the data
rather than from equity-literature defaults, and the calibration is where the first substantive
findings are: BTC's fill curve is two-component rather than exponential and LINK's is a step
function, so the exponential premise both models share is violated on every book tested
(Contributions 6, 25-28); the γ implied by crypto's much smaller σ² is orders of magnitude from
the literature's (Contribution 26); and GLFT's textbook spread lands inside BTC's momentum
plateau whatever the calibration (Contribution 27). The backtests are profitable on LINK and
not on BTC.

**RQ2 — Mechanism.** The profit is queue rent, not spread capture. It is confined to the quote
regimes where the fill model grants priority it has not earned, and it disappears in the one
regime where a fill physically requires the market to trade through the level — where the
markout also inverts from positive to negative. Contribution 54 then removes the mechanism
entirely on tick-grid grounds. Four further errors compound in the same direction, and
reinforcement learning leans into the artefact harder than the hand-tuned baselines do, which
is the clearest evidence that what was being optimised was the simulation rather than the
market.

**RQ3 — The competitive margin.** The honest result is zero as an enforced equilibrium, not by
accident of sample: it is derived from a zero-profit condition, validated against synthetic
ground truth, and shown to hold on whichever of the two available axes is free. No class of
information opens it. Speed saturates before co-location; observable state ranks toxicity
without producing a tradeable pocket even at zero fees; counterparty identity — the strongest
sorting instrument that can exist, available only because Hyperliquid discloses wallets —
separates flow at the 100th percentile against a shuffle placebo and finds a benign pocket of
+0.15 ± 0.20 bps against a 1.0 bps fee; a price-process regime filter's entire apparent
improvement is reproduced by a
matched-frequency placebo; and the sharpest causal signal in the project nets +$0.13/day. The
gate is not the quality of the information but the fact that its predictable content is already
in the price at which a maker is permitted to trade.

**RQ4 — The boundary.** Yes, a positive return is available without professional
infrastructure, and it comes from structural position rather than prediction. The three
survivors are compensation for bearing a basis, for warehousing inventory where few others
will, and for being the fast side of a slow venue — each bounded by capacity, competition, or an
unmeasured tail. The corollary is the thesis's answer to its own opening question: the
A-S/GLFT apparatus is not what makes any of them work, and in Chapter 4 it was measurably a
liability — on the corrected closed form more so than on the mis-transcribed one, because
correctly specified it quotes to a markout of +0.055 bps per fill, which is the competitive zero
reached by optimal control instead of by measurement.

---

## 5. What Makes This More Than One Dataset's Result

Two features of the evidence generalise beyond the instruments and the period.

**The recurring configuration.** The same shape appeared seven times, on different signals,
venues and horizons: a genuine, placebo-validated effect priced at or just under the cost of
acting on it. Short-horizon momentum is real and worth +0.8 to +1.9 bps against a 2.8 bps toll.
The perpetual lead is real, out-of-sample robust, and worth +1.72 bps against a 2-10 bps wall.
Institutional meta-order drift — the best-documented flow effect in the literature — is priced
to within **0.06 bps** of the wall. Order-book imbalance, maker withdrawal, wallet-level
toxicity and intraday cointegration between correlated majors all land the same way; the last
loses 6-12 bps per trade because a 45-to-140-minute reversion does not cover an 8.6 bps round
trip, and five of ten pairs passing a significance test is itself a finding about
multiple testing rather than about cointegration. A single effect priced at its access cost is
an observation. Seven, found by looking for reasons to reject them, is a description of how the
market allocates the returns to information.

**One axis, measured twice.** The organising variable of Part I is relative tick size — whether
the equilibrium is enforced on the spread or on the queue — and the organising variable of Part
II is the venue's repricing clock. These are the same quantity seen at two resolutions: how
finely the price can move, and how quickly it does. Both were derived here from the data rather
than imported, and both make predictions that were subsequently tested: the tick axis predicted
that a true one-tick LINK must behave like the one-tick perpetual, and it does; the clock axis
predicted that positive maker returns should be found by conditioning on competition rather than
on strategy, and Chapter 8's screen found them that way.

The axis is not idiosyncratic to this thesis. Kurth et al. (2026) account for the decay of
short-term trend-following by the same variable in volatility-normalised form, finding that where
the tick is large relative to volatility the strategies that survive are the ones the grid
permits. That is the present result read from the taker's side of the same book: the tick decides
which strategies can exist before it decides which are profitable.

---

## 6. Methodological Contribution

Independent of the substantive result, the thesis contributes a set of diagnostics and a
discipline, each traceable to a specific failure it made and then caught.

**Two diagnostics that generalise to any limit-order-book backtest.** First, *decompose realised
profitability by quote regime relative to the natural spread, under the fill model's
queue-priority assumption.* Applied here, this single decomposition explains a +5% RL
"outperformance" as two measurements of the same artefact at different intensities, predicts
from the natural spread alone which assets can produce the artefact at all, and separates "no
edge exists" from "no edge is causally accessible" via the foresight-oracle construction.
Second, *validate the exchange price grid against the venue's live feed and filters before any
tick-denominated calibration.* The signature is unmistakable once looked for — a spread pinned
at a constant number of ticks, with every price on a coarser sub-grid — and the failure it
prevents is severe, because a backtest quoting on a finer grid than the exchange's manufactures
phantom room inside the spread where no real order can rest, reproducing the queue-priority
artefact through a channel no fill-model correction can see. It cost this project a year of
apparently robust results to learn.

**The honest-accounting discipline** (Chapter 3 §7): ten rules — exchange-valid prices, real
queue clearing, taker-on-arrival treatment, round-trip pricing at executable touches rather
than mark-to-mid, inventory-aware simulation, placebo and anti-signal controls, out-of-sample
and pre-registered replication, depth-capped capacity, common-clock validation, and explicit
fee tiers. Each rule exists because its absence produced a false positive here. The fourth rule
is stated at two levels, because it was violated at both: a *fill* priced at the mid and a
terminal *position* valued at the mid are the same error, and the second survived the correction
of the first for three chapters.

**The evidence that the discipline has teeth is that it removed the author's own results.** The
directional-skew arc survived robustness sweeps, a 182-day fresh out-of-sample window at +$80/day,
markout analysis and an RL variant, and fell to a validation channel outside the backtest
entirely (Contribution 54). The defended maker's +1.01 bps per-fill mark-to-mid reversed to
negative under an inventory-aware round trip (Contribution 64). A depth-conditioned anchor rule
that improved in sample failed out of sample and is reported as a negative. The same
mark-to-mid rule was then found to have survived *inside* the corrected simulator, at the level
of the terminal position rather than the fill, and was audited rather than argued away
(Contribution 66): the result held, but a wide-quoting configuration that had reported the
highest margin in its sweep turned out to have closed no position at all, and one book's positive
figure turned out to be terminal mark in its entirety. Contribution 36
closed the cross-venue question on contemporaneous integration, and Contribution 56 showed that
θ = 0 was a resolution artefact of a 100 ms grid — the perpetual leads by 40-100 ms — which
reopened the question Chapter 7 eventually answers. Four further errors of my own analysis are
documented in the log rather than silently corrected: a sign inversion in a placebo comparison,
a one-time cost annualised as recurring, a pooled-series composition artefact that manufactured
autocorrelation where per-instrument series show none, and a forward-versus-spot repricing error
worth 5.21% until Black-76 was inverted on the venue's own marks.

**A fifth, which cut the other way.** The GLFT closed form had been transcribed into the strategy
with γ and κ exchanged. The honest response was not to scope Chapter 4 §3 to "GLFT as
implemented" but to rerun it, and the rerun made the chapter's conclusion stronger rather than
weaker: correctly implemented, the policy earns +$25.44/day against the error's +$88.56 and the
flat control's +$149.45, and its mean markout per fill falls to +0.055 bps. The mistake had been
flattering the model. It is worth recording that a bug can hide a result as easily as
manufacture one, and that scoping a claim around an error is a weaker move than fixing it when
the data to fix it is already on disk.

**A negative result of independent interest.** Options market making on Deribit fails even at a
hypothetical zero maker fee, so no fee schedule rescues it. Reaching that conclusion required
two corrections worth recording as method: the venue's REST trade history silently truncates to
roughly a quarter of the tape, keeping the most recent slice, which is a biased subsample severe
enough to flip a sign; and pooling "at-the-money implied volatility" across strikes and expiries
manufactures large negative autocorrelation that vanishes per instrument.

---

## 7. Limitations and Scope

- **Latency class.** Results are reported at 10 ms order latency, which a standard cloud
  instance in Binance's matching-engine region achieves without co-location infrastructure. True
  sub-millisecond co-location is out of scope as an *infrastructure* claim, though Contribution
  60's collapse to the 1 ms limit is direct evidence that it does not change the maker verdict.
- **Fees.** Most Part I cells assume zero fees, making the negative results upper bounds. Part
  II reports every tier explicitly, and Chapter 7's alpha exists at one tier and not another.
- **Maker rebates.** Not modelled directly. Rebates accrue only on fills, fills require queue
  priority, so a rebate is one more component of the same queue rent rather than an escape from
  it.
- **Assets, venues and period.** Binance spot BTC/USDT and LINK/USDT plus LINK perpetuals (May
  2025 - April 2026, with 182 further days for out-of-sample work), and a four-venue live capture
  (Binance, Coinbase, Hyperliquid, Deribit) from July to September 2026. Crypto only. **Every
  window a headline is taken from is calm** — a scan of all 320 instrument-days puts their worst
  day between 1.6 and 2.5 times the median daily range — and the one cascade in the data
  (10 October 2025, LINK trading a 67.8% range, thirteen times median) falls outside all of them.
  Contribution 71 measures it: it is a ±7 standard-deviation day whose *sign flips with
  configuration*, moving one month's total by 36% and another's by 153%. A cascade is therefore
  not a uniform worsening of a negative result, and **the daily-mean-with-interval framing used
  throughout this thesis cannot represent it** — a 7-sigma day is not a draw from the
  distribution the other thirty days describe. The intervals of Chapter 3 §8 should be read as
  conditional on the absence of such a day.
- **Part II rests on short windows.** Chapter 7's alpha is two days and two leaders; Chapter 8's
  premium is five days plus a four-day replication; Chapter 9's carry is two windows. These are
  adequate to establish existence and to price the bounds, and inadequate to estimate a
  long-run Sharpe. The intervals are reported rather than left implicit
  (`thesis/intervals.md`, method in Chapter 3 §8): clustering on the coin rather than the
  coin-day, Chapter 8's round trip is +6.04 bps with a 95% interval of [+1.68, +10.58] — clear of
  zero and of the 1.5 bps base fee, but only just at the lower end. Chapter 7's 5 bps rows all
  exclude zero; its 2 bps rows do not, on the pairs where the chapter says they should not.
  Chapter 8's bridge-control decay, +23.4 bps [+7.2, +39.0], is the Part II quantity with the
  most room between its interval and zero, which is why the chapter leans on it.
- **The precision of Part I is not the issue, and should not be mistaken for the claim.** The
  thirty-day +$154/day has a 95% interval of [+$129, +$170]. It is a real, tightly estimated,
  reproducible number, and that is precisely why it was worth eighty pages to take apart. The
  argument against it is structural — the price could not have existed, the queue could not have
  been joined — and no amount of additional data would have found it. A wider interval would have
  made the thesis easier and less interesting.
- **The cascade tail is unmeasured.** Both carry windows had drawdown under 20 bps. A
  negative-skew premium's information is concentrated in the rare loss the sample does not
  contain, so the +8.4%/yr on BTC is *conditional on no cascade*, and the
  unconditional figures are unknown and lower. The same caveat applies to the thin-book premium,
  where the frozen tape cannot show a maker being run over during a volume explosion — which is
  exactly when the July-to-August decay of the bridge control originated.
- **Capacity.** Chapter 7's touch holds $1.4k to $8k, and Chapter 8's books trade a few million
  a day. These are real strategies at a scale that will not support a fund, and the small scale
  is causally connected to their existence.
- **Frozen-tape simulation.** No result models the market's reaction to our own orders. This
  biases *toward* the strategy, and every positive result should be read accordingly. Two parts
  of that bias are now sized rather than asserted (Contribution 72): the median maker's fill rate
  falls as 1/M when competitors enter, so joining one of Chapter 8's books dilutes the incumbents
  and would dilute us; and the simulated maker runs at 0.82× the busiest real participant's fill
  rate across the thirty book-days — **but 1.4 to 3.0× on HMSTR**, the largest contributor to the
  premium, which is a queue position no real wallet held.
- **No genuinely wide centralised book.** After Contribution 54, every centralised instrument
  tested has a spread of one true tick or nearly so. Chapter 2 §8's dealer-window prediction is
  confirmed on Hyperliquid's tail, but Hyperliquid is a decentralised venue with a different
  participant mix and fee structure; whether a wide-tick *centralised* book behaves the same way
  is untested.
- **Options.** The Deribit conclusion rests on a capture of limited duration and on a zero-fee
  upper bound, which is the right shape for a negative result but not for any positive claim
  about the asset class.
- **Twenty-two contributions are not machine-verified.** `scripts/verify_contributions.py`
  checks each entry's figures against the experiment JSONs it names; 46 of the 68 entries can
  be reached that way. The other 22 — C1–C14, C16, C18, C19, C21, C24, C26, C27 and C31 — are
  the project's oldest work and predate the `experiments/NN_*` convention, so their source
  material sits in `analysis/` notebooks rather than in a results file a script can pool. They
  are reproducible from those notebooks and no attempt was made to retro-fit pointers that
  would make the screen pass without adding evidence. The exposure is bounded: all 22 are
  microstructure characterisation or early strategy results, every one of which is superseded
  where it matters (C6 and C15's fill curves by C20's L2 measurement, C16's headline by its
  re-derivation in Chapter 4 and dismantling in Chapter 5, C26 and C27's calibration findings
  by Contribution 17's corrected-formula rerun), and **no claim in Part II depends on any of
  them**.

---

## 8. Suggested Further Work

- **Lengthen the windows until the intervals bite.** The inference apparatus is now in place
  (Chapter 3 §8) and it says the same thing about every Part II result: the point estimates are
  clear of zero and the intervals are wide, because the unit of replication is six coins, two
  days or two windows. Nothing analytical is missing here; what is missing is tape. The
  collector already runs, and a three-month capture would narrow Chapter 8's round trip from
  [+1.7, +10.6] bps to something that could support a sizing decision rather than an existence
  claim.
- **Re-run the notebook analyses as numbered experiments.** The twenty-two unverified
  contributions are a bookkeeping debt rather than a doubt: the analyses exist and the data is
  committed, but they were done before the project adopted the convention that every number
  lives in a results JSON a script can check. Porting them would close the verification gap
  listed in §7 and is the cheapest remaining item on this list.
- **Capture a cascade across venues.** Still the single most valuable missing quantity, and
  Contribution 71 now says precisely what is missing. A cascade *is* in this project's data —
  10 October 2025, LINK trading thirteen times its median daily range — and running a maker
  through it is informative. But Chapter 9's exposure is a cross-venue basis, and that cascade
  sits in the purchased single-venue history while the carry lives in the captured cross-venue
  window. The two do not overlap, so the carry's tail is not merely unmeasured but
  **unmeasurable with the data in hand**. What would measure it is the existing collector,
  already running on both venues, present during an episode of that magnitude. The requirement
  is now specific: simultaneous funding and price on both legs, through a day of >5x median
  range, which the scan puts at roughly 0.4% of days.
- **Extend Part II's windows.** Each of the three survivors was established on days, not months.
  The pre-registration apparatus of Chapter 8 should be applied to Chapters 7 and 9 as well —
  register the prediction, then capture the sample — which converts three existence proofs into
  three estimates.
- **The wide *centralised* book test.** Find a liquid centralised instrument whose spread is
  genuinely several true ticks, validated against the venue's live feed and filters rather than
  vendor data, and run the signal-conditioned inside-spread grid there with real L2 depth. This
  is the one prediction of Chapter 2 that remains untested on the venue class it was made about,
  and the tick screen should precede the data purchase.
- **Model the reaction to our own orders — but note that half of it is now measured rather than
  modelled.** Every simulation here is frozen-tape. The standard remedy is a queue-reactive
  simulator, whose output is a monotone function of assumed reaction parameters. Contribution 72
  shows that on a transparent venue the central quantity need not be assumed: with the filled
  `maker_wallet` on every trade, maker entry is a natural experiment, and the median maker's fill
  rate is measured to scale as 1/M. What a reactive simulator would still add is the *dynamic* —
  whether competitors withdraw in response to **our** quote specifically, which entry data cannot
  separate from entry itself. That remains worth building, and it is now a narrower question than
  it was. Lalor and Swishchuk (2024) is the closest existing treatment — a market simulation that
  carries adverse selection explicitly rather than leaving it to the replayed tape — and the
  measurement of Contribution 72 is what such a simulator would need in order to be calibrated
  rather than parameterised.
- **Push the venue-clock law past three orders of magnitude.** The adverse-selection horizon
  spans 15 ms to beyond ten seconds across the venues captured here. Testing it on venue classes
  not represented — other decentralised exchanges, regional centralised venues, tokenised
  equities — would establish whether the clock is the right state variable in general or a
  property of this particular set of four.
- **Measure queue position live.** The queue-position sensitivity underlying Contribution 30 is
  simulated from an L2 depth model. A small live order-placement study would measure realised
  queue position directly and validate the roughly $1/day signal-blind ceiling that the whole of
  Part I rests on.
- **The variance-risk-premium construction** flagged in Contribution 35 — warehouse inventory
  against a cross-venue hedge, and harvest the short-gamma premium deliberately rather than
  incidentally — is a distinct research question outside this thesis's scope and a natural
  follow-on to Chapter 8.

---

The project's arc is worth stating plainly, because it is the strongest thing it has to offer a
reader who wants to do similar work. It began by asking whether a well-known model is
profitable, found that it appeared to be, and spent most of its length discovering that every
apparent profit was something the simulation had given away. The zero it arrived at is not a
failure to find an edge; it is a measurement of how completely competition prices the
information a single participant can compute. What survived the search was found only after
that was accepted — by looking for slow clocks, thin books and contractual cash flows instead of
for better forecasts. The models this thesis set out to implement turned out to answer a
question about a dealer market, and the market answered a different one.

---

*Full contribution log and reference list: `contributions.md`.*
