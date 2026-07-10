# Theoretical Background

---

## 1. The Market-Making Problem

A market maker (MM) continuously posts a bid price and an ask price around a reference
("mid") price, earning the spread when both sides are eventually filled while bearing the
risk that, between fills, the mid moves against an open inventory position. The
Avellaneda–Stoikov (2008) framework ("A-S") and its ergodic refinement by Guéant, Lehalle &
Fernández-Tapia (2013) ("GLFT") cast this as a stochastic optimal control problem: choose a
quoting policy that maximizes expected utility of terminal wealth, trading off expected
spread capture against inventory risk. Both models, and the broader literature on
order-driven markets they sit inside, supply the vocabulary and the formulas that Chapters
4–6 implement, calibrate, and ultimately stress-test against an honest fill model. This
chapter develops that vocabulary: the A-S and GLFT closed forms (§2–3), the fill-intensity
primitive both models share (§4), and the two pieces of microstructure theory — price-time
priority (§5) and zero-profit equilibrium (§6) — that Chapter 5 shows are the actual
determinants of the honest result. It closes (§7) by asking what kind of market the
A-S/GLFT lineage was built to describe in the first place — a dealer market, not an order
book — a distinction that turns out to organize the thesis's negative and positive results
alike.

---

## 2. The Avellaneda–Stoikov Model

**Setup.** The mid-price follows an arithmetic Brownian motion, `dS_t = σ dW_t`. The MM
chooses a bid distance `δ^b_t` and an ask distance `δ^a_t` from the mid, posting
`p^b_t = S_t − δ^b_t` and `p^a_t = S_t + δ^a_t`. Fills arrive as Poisson processes whose
intensities depend on how far the quote sits from the mid:

```
λ(δ) = A · exp(−κδ)
```

— closer-to-mid quotes fill faster, at a rate that decays exponentially in distance with
sensitivity κ and a level set by the overall order-arrival rate A (§4). Cash `X_t` and
inventory `q_t` evolve with these fills; the MM maximizes `E[−exp(−γ(X_T + q_T S_T))]`, i.e.
CARA utility of terminal wealth (cash plus inventory marked at the terminal mid), with risk
aversion γ.

**Reservation price and optimal spread.** Solving the associated Hamilton–Jacobi–Bellman
equation (Avellaneda & Stoikov, 2008; exposition in Cartea, Jaimungal & Penalva, 2015) gives
a closed-form approximation in terms of an *indifference* or *reservation* price `r(s,q,t)`
— the mid-price at which the MM is indifferent to a marginal change in inventory — and a
symmetric half-spread δ around it:

```
r(s, q, t) = s − q · γ · σ² · (T − t)

δ = γ·σ²·(T−t) / 2  +  (1/γ) · ln(1 + γ/κ)

bid = r(s,q,t) − δ          ask = r(s,q,t) + δ
```

Two terms do two different jobs. The **inventory-skew term**, `−q·γ·σ²·(T−t)` in `r`, shifts
both quotes in the direction that reduces `|q|`: a long MM (q>0) lowers both quotes,
discouraging further buying and encouraging selling. The **spread term**, `γσ²(T−t) +
(2/γ)ln(1+γ/κ)`, has an inventory-risk component (`γσ²(T−t)`, growing with remaining
variance to liquidate) and a pure market-making component (`(2/γ)ln(1+γ/κ)`, present even at
q=0 and T=t — set entirely by risk aversion and fill sensitivity).

**What the model assumes.** Three primitives carry the whole result: (i) the mid is a
driftless martingale with constant σ — no informed flow, no momentum; (ii) fills arrive with
exponential intensity `Ae^{−κδ}` — a single, time-invariant (κ,A) pair describes the entire
limit order book's responsiveness; (iii) the optimizing MM's own resting orders are filled
according to this same intensity, with no reference to queue position, competing orders, or
who else is resting at the same price. Chapter 3 tests (i) and (ii) empirically against
BTC/USDT and LINK/USDT; Chapter 5 shows (iii) is the assumption that matters most.

---

## 3. The GLFT Ergodic Refinement

The A-S spread term `γσ²(T−t)` grows linearly as `t→T`: an MM with a fixed terminal time
becomes increasingly risk-averse about inventory as liquidation approaches. This is the
right model for a single trading session with a hard close, but an MM that runs
indefinitely — quoting continuously, day after day — has no terminal time to liquidate
into. Guéant, Lehalle & Fernández-Tapia (2013) take the `T→∞` ("ergodic") limit of the same
control problem, yielding a *stationary* policy: the optimal quotes depend on the current
inventory `q` but not on calendar time. The closed-form asymptotic approximation, expressed
in *dollar* volatility `σ_$ = σ · mid` (so that γ has natural units of risk aversion per
dollar of inventory, not per unit of the underlying):

```
r = mid − q · γ · σ_$² / (2 · A · κ)

δ = (1/κ) · ln(1 + κ/γ)  +  (1/2) · √( σ_$²·γ/(2Aκ) · (1 + κ/γ)^(1+κ/γ) )

bid = r − δ          ask = r + δ
```

The reservation-price term has the same qualitative role as in A-S — it skews quotes against
inventory — but is now scaled by `1/(Aκ)` rather than `(T−t)`: a more liquid market (higher
A) or a more locally competitive one (higher κ) requires *less* skew to manage a given
inventory, because positions can be unwound faster. The spread term's second piece — the
`(1+κ/γ)^{(1+κ/γ)}` factor — is the model's central nonlinearity: it is well-behaved near
`κ/γ ≈ 1` but explodes as κ and γ diverge from each other, a property that becomes diagnostic
once §4's exponential-intensity assumption is tested against LINK's actual fill curve
(Chapter 3; Contributions 17, 27–28).

GLFT and A-S therefore make the *same* three assumptions listed at the end of §2 — they
differ only in how the inventory-risk horizon is parameterized (`T−t` vs. `1/(Aκ)`).
Anything that breaks one of those three assumptions breaks both models in the same way; this
is why Chapters 4–5 treat A-S and GLFT as a single object ("classical MM") rather than as
competing hypotheses.

---

## 4. The Fill-Intensity Assumption and Its Empirical Status

The exponential-intensity form `λ(δ) = A·exp(−κδ)` is not derived from first principles
within A-S or GLFT — it is imported as a stylized fact about limit order books, motivated by
empirical studies of order placement and execution in equity markets (the tradition
summarized in Cartea, Jaimungal & Penalva, 2015, ch. 10). Its appeal is mathematical: it is
the unique intensity function for which the HJB equation above admits the closed forms in
§2–3. Its empirical content is an assumption that **the probability a resting order at depth
δ is filled within a given horizon decays smoothly and monotonically with δ**, with no
structural breaks.

This assumption does two things for the models above. First, it is what makes κ a *single
number* that fully describes "how far from the mid you need to be to expect a fill" — every
other quantity in §2–3 (the spread, the inventory-skew scale) is expressed in units of κ.
Second, via the equilibrium argument in §6, it implicitly assumes κ and σ are independent —
that the market's fill-decay rate is a free parameter the MM observes, not one that the
MM's own quoting (and everyone else's) determines jointly with volatility.

Chapter 3 estimates `λ(δ)` directly from BTC and LINK trade-and-quote data using several
approaches (unconditional market-distance, execution-aware simulation, survival/hazard
analysis) and finds, in both cases, a fill curve that is not a clean exponential: BTC shows a
two-component structure (a fast-decaying "liquidity" component plus a roughly
distance-invariant "momentum" floor), and LINK's curve is closer to a step function (flat
inside the spread, flat — at a different level — outside it). Both findings are read in
Chapter 5 not as failures of A-S/GLFT *per se*, but as symptoms of the independence
assumption above breaking down (§6; Contribution 33).

---

## 5. Price-Time Priority and Queue Position

Modern electronic limit order books match orders at each price level on a first-in,
first-out basis — **price-time priority**. When a marketable order arrives and trades through
a price level, the resting orders at that level are filled in the order they were placed,
until either the marketable order or the resting queue is exhausted. An order's *queue
position* — how much resting volume sits ahead of it at its price — therefore determines
whether, and how quickly, it fills: an order at the front of a deep queue fills on
essentially any trade that reaches its price; an order at the back may need the entire queue
ahead of it consumed first, which can require many such trades or may never happen before
the order is cancelled or the price moves away.

This matters for two distinct reasons that the literature on queue-position valuation
(e.g. models in the spirit of Cont, Kukanov & Stoikov, 2014, on optimal order placement
across price levels) treats jointly. **Fill rate**: front-of-queue orders fill far more
often than back-of-queue orders at the same price, for purely mechanical reasons unrelated to
the order's own quoting decision. **Adverse selection**: the trades that *do* reach a
back-of-queue order's price level are disproportionately the ones large or persistent enough
to clear the queue ahead of it — i.e., conditional on a back-of-queue fill, the triggering
flow was more likely informed/directional than the flow that fills a front-of-queue order on
the very first trade at that price.

A backtest that determines fills by **price alone** — "this order's price was crossed by a
trade, therefore it is filled" — implicitly grants every resting order *front-of-queue*
status, regardless of when it was placed relative to the rest of the book. This is the
"price-only" fill condition documented as a deliberate simplification in this project's early
methodology (CLAUDE.md, *Key Architecture Decisions*; appropriate, as also noted there, for a
discontinuous trade series where a literal queue cannot be reconstructed without L2 depth
data). Chapter 3 describes how an L2-depth-aware queue model is constructed once that data
becomes available; Chapter 5 (Contribution 30) is the result of comparing the two.

**A formal counterpart: Guilbaud & Pham (2013).** The discussion above is qualitative;
Guilbaud & Pham give it a precise optimal-control formulation for exactly the order-driven
setting that A-S/GLFT set aside. The spread is modelled as a finite-state Markov chain on
tick multiples, `S_t ∈ {δ, 2δ, ..., mδ}`, time-changed by a Poisson "tick clock". Rather than
choosing a continuous distance `δ^b`/`δ^a` as in §2–3, the MM at each side chooses between
quoting *at* the best price or *one tick better* (price improvement), `Q ∈ {B, B+}`, with
fill intensities satisfying

```
λ(B+, s) > λ(B, s)    for every spread state s
```

— quoting one tick closer to (or inside) the touch buys queue priority and a strictly higher
fill rate. This single inequality is the formal counterpart of this section's "front-of-queue
orders fill far more often" observation, expressed as a *control variable* rather than an
empirical regularity.

The resulting dynamic-programming equation is a quasi-variational inequality: a regular
Hamilton–Jacobi–Bellman term, with a supremum over the `{B,B+}` choice on each side, combined
with a free-boundary ("impulse control") condition for an additional market-order control
used to manage inventory actively. Even after applying the same kind of
dimensionality-reducing ansatz that produces the closed forms in §2–3, the problem collapses
only to a *finite system* of coupled one-dimensional integro-differential equations — one per
spread state, linked through the spread's own transition rates — which Guilbaud & Pham solve
numerically by finite differences. **Unlike §2–3, there is no closed form**: the two
features that A-S/GLFT's third assumption (§2) sets aside — discreteness of price, and an
intensity that depends on queue priority rather than distance alone — are exactly the two
features that block the closed-form reduction, even though the underlying CARA/mean-variance
objective is otherwise unchanged.

Two aspects of this model anticipate results developed later in this thesis. First, the
binary `{B, B+}` priority choice is the discrete ancestor of the continuous,
signal-conditioned price improvement studied empirically as the directional-skew mechanism
(Contributions 42, 44): the gain comes not from unconditionally claiming the
`λ(B+,s)>λ(B,s)` premium, but from claiming it *selectively*, conditional on a directional
signal. Second, Guilbaud & Pham's exponential-utility reduction retains an explicit drift
term for the underlying price process — a term that §2–3's driftless-martingale assumption
sets to zero, but which is exactly where a directional signal enters the control problem. The
empirical skew mechanism can therefore be read as a tractable, myopic approximation to this
drift term, rather than as an ad hoc addition bolted onto A-S/GLFT.

---

## 6. Zero-Profit Equilibrium: Glosten–Milgrom and Wyart–Bouchaud

The two results below are not about queue position directly — they are about what
*determines the spread* in a competitive market, and they supply the theoretical reason
Chapter 5's honest result is not merely "the queue model found a smaller edge" but "the
honest edge is, in expectation, zero or negative by construction."

**Glosten & Milgrom (1985).** In a market with a competitive (zero-expected-profit) dealer
and a mix of informed and uninformed order flow, the bid-ask spread is set exactly wide
enough that the dealer's expected loss to informed traders is offset by the spread captured
from uninformed traders. The spread is therefore not a source of dealer profit; it is a
transfer from uninformed to informed traders that *passes through* the dealer, sized by the
market's information asymmetry. A dealer who is too aggressive on the size of this transfer
attracts more uninformed flow but loses more to informed flow, and competition drives the
spread to the level at which these exactly cancel.

**Wyart, Bouchaud, Kockelkoren, Potters & Vettorazzo (2008).** This result translates the
same competitive logic to order-driven (limit order book) markets and connects it to
*volatility per trade*. If the quoted spread is wider than the typical price change between
consecutive trades, new limit orders can profitably queue in front of the existing best quote
and tighten the spread; if it is narrower, existing limit orders are picked off by the price
moves between trades faster than they are compensated by spread capture, and the spread
widens. The equilibrium spread is therefore pinned to the *volatility realized over the
timescale of one trade* — equivalently, for a market with trade arrival rate A and price
volatility σ, to `σ/√A`. This is a spread-level restatement of the same zero-profit logic:
competitive liquidity provision earns the volatility it bears, not more.

**The combined prediction.** Read together, these results say that in a competitive market
the spread (Wyart–Bouchaud) and the fill-decay rate κ that A-S/GLFT take as a free input are
*the same equilibrium object viewed from two sides* — a market that has reached this
equilibrium has `κ ≈ 1/δ_be` where `δ_be ∝ σ/√A` is the breakeven half-spread. **κ is not
independent of σ**, as §2–4's models assume; it is pinned to σ by competition. A fixed-κ
quoter is calibrated to whichever σ prevailed when κ was estimated, and is *structurally*
miscalibrated — too aggressive, in the zero-profit sense — whenever σ has since moved.

One further wrinkle, specific to markets with a non-negligible tick size, is what happens
when this equilibrium spread is *narrower than one tick* — the smallest the exchange allows.
The spread cannot tighten further, so (as Chapter 5 develops at length, Contribution 33) the
zero-profit condition is instead enforced on a different axis: the depth of the queue at the
one-tick spread grows until the marginal (back-of-queue) order is the one that breaks even.
On such an asset, §5's queue-position rent and this section's spread-equilibrium condition
are not two separate phenomena — they are the same zero-profit law, enforced through whichever
variable (spread width, or queue depth) is free to adjust.

---

## 7. What Market Were These Models Built For? The Dealer Lineage

The preceding two sections catalogued, one assumption at a time, where the A-S/GLFT
formalism and the order-driven market part ways: fills gated by queue position rather than
by distance alone (§5), and a fill-decay rate κ that competition pins to σ rather than
leaving free (§6). This section makes the case that these are not two independent oversights
but a single one, visible in the models' ancestry: **A-S is a dealer model, and the limit
order book is not a dealer market.**

**The lineage.** Avellaneda & Stoikov (2008) do not derive their framework from order-book
first principles; they explicitly adapt Ho & Stoll (1981), a model of a *dealer* — a single
intermediary who observes a reference price and quotes a bid and an ask around it, facing a
stochastic arrival of client demand. In Ho & Stoll's world there is no order book at all.
The intensity `λ(δ)` is the dealer's *private demand curve*: quote further from the
reference price and clients trade with you less often, but every client who trades does so
at your quote, because you are the counterparty they came to. Three structural features
follow, and all three survive intact into A-S and GLFT: **(i)** there are no competing
quotes in the model — the trade-off is only between the dealer's spread and the client's
patience, never between the dealer's quote and a better one displayed next to it;
**(ii)** there is no queue — a client's order cannot be intercepted by someone else's
resting order at the same price, so `λ(δ)` alone determines fills; **(iii)** price is
continuous — δ is a real number, not a multiple of a tick. The familiar picture is a
commodity or FX dealer quoted on request: the client calls to buy, the dealer looks at the
screen price and decides whether to quote one tick or ten above it. Everything the dealer
needs to know is the reference price and their own demand curve — which is exactly, and
only, what A-S's state and primitives encode.

**What the order book adds is precisely what §5–6 documented.** Transplant this dealer into
a lit order book and each of the three features above fails in a specific, by-now-familiar
way. Competition (i) is §6: the spread the dealer's formula wants to capture is an
equilibrium object that other liquidity providers have already bid down to the zero-profit
level, and κ — far from being a private demand curve — is the public residue of that
competition, pinned to σ. Priority (ii) is §5: at a shared price level the dealer is not
"the counterparty the client came to" but one order in a FIFO queue, and the fills that do
reach the back of the queue are adversely selected. Discreteness (iii) is the tick-size
wrinkle of §6 and the reason Guilbaud & Pham's formulation (§5) loses the closed form. Read
this way, the empirical failures documented in Chapters 4–5 — the GLFT spread that lands in
the momentum plateau whatever the calibration (Contribution 27), the γ that must be
inflated by orders of magnitude to move at all (Contribution 26), the honest-engine
zero-profit verdict itself (Contributions 30, 33) — are not defects being discovered
*inside* the model so much as a category error about its habitat: the model answers "how
should a monopolistic dealer quote?", and the backtest asks "what does a marginal,
queue-anonymous order in a competitive book earn?". Those are different questions, and the
zero-profit theory of §6 says the second has a known answer that no quoting formula can
improve.

**The literature's own trajectory corroborates the reading.** The most direct descendants
of the A-S/GLFT framework found their least-qualified applications not in lit order books
but back in dealer markets: optimal market making for corporate bond dealers and multi-asset
OTC desks (Bergault & Guéant, 2021; Guéant, 2016, pt. III) and for FX dealers internalizing
client flow (Barzykin, Bergault & Guéant, 2022, 2023). In an RFQ or streaming-quote market
the model's primitives are literally true: each dealer faces their own arrival process,
`λ(δ)` is estimable from that dealer's request-and-hit history, there is no queue, and
quotes are private. The framework did not fail and get replaced; it migrated home.

**The exception that proves the rule.** This reading also reorganizes the thesis's one
robust *positive* result. The OBI-conditional inside-spread placement of Contributions
42–46 is, mechanically, the act of posting at a price level where no other order rests: for
the life of that quote the strategy is alone at its price, faces the arrival flow directly,
and is subject to no queue — a momentary, self-constructed reconstruction of the dealer's
situation inside the order book, held open until competing liquidity joins the level. It is
profitable only when conditioned on a directional signal (the unconditional version is the
`{B+}` choice of §5, which buys fills but not favorable ones), and it is *possible* only
where the book leaves room to stand alone: on wide-spread, large-relative-tick assets
(Contribution 52's LINK) and not on one-tick books (BTC, and both perpetuals), where there
exists no price at which an order can be alone and passive at once (Contributions 43, 47).
The dealer model, in other words, stops describing the market maker's problem *except* at
the times and places where the market maker can locally re-create the dealer's market — and
the empirical results select exactly those times and places.

---

## 8. Synthesis: What This Chapter Predicts for Chapters 4–6

Three things follow from §2–6 that the rest of the thesis tests directly.

1. **A-S and GLFT, calibrated to a fixed (κ, σ, A) and run against a price-only fill model,
   should be profitable** — they are explicitly the solution to the profit-maximization
   problem under exactly that fill model (§2–3). Chapter 4's "apparently profitable" results
   are therefore the *expected* output of this theory, not a surprise — the open question is
   what the price-only fill model is silently assuming away (§5).

2. **If §5's price-time-priority point is what the price-only model assumes away, then
   re-fitting the same strategies against a queue-position-aware fill model should remove
   the profit** — not necessarily to exactly zero (real markets are not in perfect
   equilibrium at every instant), but toward the zero-profit benchmark of §6. Chapter 5
   tests this directly.

3. **§6 predicts *why* the result of (2) should be zero/negative rather than merely smaller**:
   a fixed-κ quoter calibrated from historical data is, by the Wyart–Bouchaud argument,
   calibrated to a stale σ the moment volatility changes — and §4 already found that BTC and
   LINK's fill curves are *not* the clean, σ-independent exponentials §2–3 assume. Chapter 5
   (Contribution 33) closes the loop: it derives the breakeven spread `δ_be ∝ σ` directly from
   data and synthetic ground truth, and shows the honest-regime result is this equilibrium
   condition being satisfied, not violated.

To these, §7 adds a fourth, about where any *positive* result should be found:

4. **If the dealer-lineage reading of §7 is right, surviving positive performance should be
   confined to the times and places where the order book locally reproduces the dealer
   setting** — assets whose spread leaves room to stand alone at a price level, and quoting
   policies that claim that position selectively, on a directional signal, rather than
   unconditionally. Chapter 6 finds exactly this pattern: the signal-conditioned
   inside-spread mechanism works on wide-spread LINK and fails structurally on every
   one-tick book tested (Contributions 42–52).

The theory in this chapter is therefore used twice in the thesis: first, conventionally, as
the source of the strategies under test (Chapters 4); second, as the explanation for why
those strategies' honest performance comes out the way it does (Chapter 5) — the same
formulas, read for what they assume rather than what they prescribe.
