# The Zero, Measured Four Ways

---

## 1. The Question This Chapter Answers

Chapter 5 left the thesis with a specific, well-posed problem. Once the five accounting
mirages are removed, an honest quoter earns about a dollar a day with a negative markout —
but a perfect-foresight oracle on the same book earns $20–30/day, so the dispersion in fill
quality is real and large. The constraint is therefore informational: the maker's problem is
not that good fills do not exist, but that they cannot be identified in advance.

That framing makes the remaining question sharp. There are only so many kinds of information
a market maker could bring to bear on it, and each corresponds to a class of strategy the
literature takes seriously:

- be **faster**, and cancel before the adverse fill arrives;
- read the **state** of the market — order flow, book imbalance, volatility — and quote only
  when it is benign;
- know **who** the counterparty is, and avoid the toxic ones;
- and, tested separately in Chapter 5's terms, act on the sharpest **causal signal** available.

This chapter tests all of them, on data purpose-built for the task, and reports the same
answer four times. Section 2 first establishes that the measurements can be trusted, because
three premises of the Chapter 5 verdict had until now been inferred rather than observed.

## 2. The Premises, Measured

The queue-rent verdict rests on three empirical claims: that these are one-tick books, that
the touch is frequently abandoned rather than traded through (the queue_fraction of Chapter 3
§5), and that the tick binds the spread on a timescale shorter than a maker's reaction. The
live capture of Chapter 3 §6 measures all three directly (Contribution 58, four books,
event-level):

- **The one-tick premise is the modal state, not an approximation.** Median spread is exactly
  1.00 tick on every book measured.
- **Roughly half of all touch-level disappearances are cancellations, not trades** — a
  cancel-to-trade volume ratio of 9:1 to 20:1, with 51–60% of touch deaths cancel-driven.
  This reproduces `queue_fraction ≈ 0.5` from the *book* side, independently of the fill-side
  bracket, which is the first time the parameter has been pinned by two unrelated methods.
- **The spread repairs itself in about 100 ms** (median 97–102 ms, with 42–286 widenings per
  day). Wyart-Bouchaud enforcement is therefore *sub-latency*: the spread is restored faster
  than a retail participant can react to its widening.

Contribution 58 also corrects an earlier observation. The "hollow touch" of Contribution 21 is
not a LINK peculiarity but a **small-relative-tick effect**: BTC concentrates 89–97% of its
near depth on the single touch level, while LINK maintains a full ladder across all ten levels.

Contribution 55 validates the instruments themselves. Running the same strategy on the same
day against the reconstructed full order book and against the quote-derived proxy tracker
gives results that are **identical at the touch** and within pennies elsewhere — so the proxy
used throughout Part I was never a source of error; the tick was. The same work brackets the
effective queue_fraction at [0.07, 1.01] for LINK and [0.32, 1.02] for BTC, placing the
engine's 0.5 inside both bands, and finds that **81–91% of at-touch episodes end by repricing
rather than by the queue clearing** — the maker's order usually does not get to the front; the
price simply leaves.

Nothing in this chapter therefore depends on a modelling convenience that has not been checked
against the venue's own behaviour.

## 3. The Sharpest Signal, and Its Wall

Before testing the four classes of information, it is worth establishing the best case. The
strongest signal this thesis produced is not a forecast at all but a *realized* price move on
a leading venue.

At a 10 ms event grid on mid-changes, **the perpetual leads spot by 40–100 ms** on both pairs
(Contribution 56). Earlier work had found the two contemporaneous; that was a resolution
artefact of a 100 ms grid, and the finer measurement resolves it. Divergence episodes are
frequent — 503/day on LINK, 6,547/day on BTC — they open on a perp move 72–80% of the time,
and they close by the laggard repricing, about 80% of them within 0.1–1.2 s. The same
contribution shows that liquidity withdrawal manifests as *repricing* rather than depth
fading, with a 10–20× hazard increase within 50 ms.

This is a causal, fresh, frequently-firing signal, and Contribution 57 prices both ways of
trading it:

- **As a taker**, the gross mid-to-mid edge is +1.72 bps at 100 ms rising to +2.38 bps at 5 s
  on LINK. Crossing the one-tick spread consumes about 1.3 bps, leaving roughly 1 bps against
  spot taker fees of 2–10 bps depending on tier. Negative at every tier. This re-measures
  Contribution 31's ~1 bps predictability wall with a sharper instrument: the gross roughly
  doubles and the wall still stands.
- **As a maker**, gating the side the signal marks as about to be adverse recovers a large
  share of the below-equilibrium loss on the captured day — LINK −$23.54 → −$16.95, BTC
  −$72.30 → −$19.68 — which proves the signal has causal value. But the decisive test is the
  same gate applied where the baseline already sits *at* the equilibrium (LINK April, true
  tick): **+$0.31/day, t ≈ 0.2**, statistically indistinguishable from zero, and matching an
  independent OBI-gate null of +$0.36/day.

The mechanism of that null recurs throughout this chapter and is worth naming once: **from the
equilibrium, gating is P&L-invariant.** Suppressing predicted-adverse fills removes their
losses and their spread revenue together, and breaks the round-trip pairing that monetises the
favourable leg. Avoidance is worth exactly the excess loss, and never more.

## 4. Instrument One: the Model-Free Markout

The first of the four measurements uses no engine, no strategy and no fitted parameter.

For every market trade, taken from the perspective of the resting maker it executed against,
Contribution 59 decomposes the maker's economics into

```
effective_half(t)   = D * (price - mid_t)              gross edge banked at the fill
impact_half(t,h)    = D * (mid_{t+h} - mid_t)          adverse drift over horizon h
realized_half(t,h)  = effective - impact               what the maker keeps
```

with D = +1 when a taker-buy lifted the ask (so the maker sold) and D = −1 when a taker-sell
hit the bid. This is Glosten-Milgrom arithmetic applied to the tape itself.

**On all four books the realized half-spread is negative within 100 ms.** The gross edge is
consumed almost immediately. Below 100 ms the picture splits cleanly by relative tick:

| book | effective half | realized @15 ms | realized @50 ms | adverse-selection horizon |
|---|---|---|---|---|
| LINK (0.001, ~1.25 bps/tick) | 0.87 t | **+0.69 t** | +0.30 t | **75 / 78 / 79 ms** |
| LINK perp | 0.73 t | +0.63 t | +0.37 t | **87 / 87 / 82 ms** |
| BTC (0.01, ~0.0006 bps/tick) | 0.70 t | −22 t (−0.1 bps) | −80 t | ≤ 20 / ≤ 15 / ≤ 15 ms |
| BTC perp | 0.72 t | −1.5 t | −6.2 t | ≤ 20 / ≤ 15 / ≤ 15 ms |

(three columns of horizons are three consecutive days). On the large-relative-tick books the
maker holds a genuine ~1 bps edge that survives about **80 ms** — stable to the millisecond
across three days, and landing squarely on the 40–100 ms perp-lead clock of §3, which is to
say the informed flow that eats the maker's edge is the same flow that moves the perpetual
first. On the small-tick books the crossing happens before the measurement grid resolves it,
and the gross half-spread is *sub-basis-point* to begin with.

This re-derives Chapter 5 §7's unification from markouts alone: a large-tick book gives the
maker a real spread to defend for a measurable window (the queue-priority regime), while a
small-tick book gives essentially no gross spread at all (the spread-equilibrium regime).

## 5. Instrument Two: Speed

If the maker's edge expires in 80 ms, the natural response is to be faster.

Contribution 60 collapses the entire latency stack — order and cancel wire time, signal lag,
and the requote cadence — from 10 ms to **1 ms**, the co-located limit. This is deliberately
generous: on a frozen tape the strategy dodges fills while every competitor stays still, so a
failure here is decisive in one direction only.

It fails. On a losing day the result moves from −$2.04 to −$1.94; on a winning day it moves
from +$1.91 to **+$0.54** — slightly *worse*, because at a 1 ms requote cadence the quotes
churn and shed queue position while toxic-avoidance was already saturated. Front-of-queue
positioning (queue_fraction = 1.0), the actual prize of co-location, is worse still on one day
and high-variance on the other.

The reason is Contribution 59. The perp leads by 40–100 ms; a 15 ms gate already fires *inside*
that window, so there is nothing left for 1 ms to catch. Speed saturated long before the
co-located limit, and the binding constraint was never latency.

## 6. Instrument Three: Observable State

The second class of information is the market's own state at the moment of quoting.

Contribution 61 conditions the Contribution 59 markout on six variables, all computed strictly
*before* the fill and signed toward the maker's side: perpetual-basis pressure, recent signed
order flow, book imbalance, recent realized volatility, trade intensity, and spread. If
adverse selection is predictable from observable state, the benign tail of that distribution
should be profitable.

Adverse selection is indeed **rankable**: the gap in realized half-spread between the benign
and toxic quintiles is +0.5 to +1.3 bps on every day and every book, with order-flow sweeps
and trade intensity the sharpest separators. But the cleanest 20% of flow, selected purely
from pre-quote state, still keeps a **negative** realized half-spread at every bankable
horizon, net of a **zero** fee. The only positive readings are LINK at 100 ms (+0.02 to +0.12
bps) — a mark-to-mid diagnostic, inside the noise, and gone by one second — and BTC is
negative at every horizon.

Chapter 5's fifth mirage appears here in miniature. Because a fitted classifier cannot beat
the most-benign *observable* bucket, and those buckets are negative, the result is robust to
model sophistication rather than being a statement about the particular six features chosen.

## 7. Instrument Four: Counterparty Identity

The strongest sorting instrument that can exist is knowing exactly who is on the other side.
On a central limit order book that information does not exist; on Hyperliquid it does, because
every trade on the public feed carries both counterparty wallet addresses.

Contribution 62 conditions the same markout on the *taker's identity*. Three findings, over
five assets and two full days:

- **Toxicity is extremely concentrated**: the worst 5% of taker wallets carry **84–91%** of all
  adverse selection.
- **It is persistent and therefore learnable**: a wallet's toxicity in the first half of the
  day predicts the second half with Spearman ρ of 0.20–0.68.
- **The identity split is causal, not survivorship**: against a wallet-label placebo — identities
  shuffled, class sizes and trade counts preserved — the real split lands at the **100th
  percentile on all five assets, on both days**.

And the benign pocket that all of this buys is **+0.0 ± 0.3 bps**. Perfect sorting lifts the
maker from the pooled −0.4 bps to *zero*, and no further.

That is the sharpest statement in the thesis, because the instrument is maximal. There is no
better sorting variable than the counterparty's identity, and it does not cross the line. The
pooling in Glosten-Milgrom is not an artefact of anonymity: the toxicity that is *predictable*
is already priced into who trades, when, and at what spread, so perfect sorting recovers the
maker to the equilibrium and stops there.

## 8. Four Instruments, One Number

| instrument | what it knows | result |
|---|---|---|
| model-free markout (C59) | nothing — the tape alone | half-spread eaten within 100 ms on every book |
| speed (C60) | the leader venue, 1 ms sooner | 1 ms ≈ 10 ms; nothing left to catch inside an 80 ms lead |
| observable state (C61) | flow, imbalance, volatility, intensity | toxicity rankable; cleanest 20% still negative at zero fee |
| counterparty identity (C62) | exactly who is trading | 100th-percentile placebo separation; pocket = +0.0 ± 0.3 bps |

Four mutually independent instruments, applied to books on three venues, all terminate at the
same place. The striking feature is not that each fails but that each fails *at exactly zero*
rather than below it. That is not a coincidence of four unlucky experiments; it is what an
enforced equilibrium looks like from the inside. A market in which liquidity provision paid a
positive risk-adjusted return would attract quoting until the spread compressed or the queue
lengthened; a market in which it paid a negative one would lose quoters until the spread
widened. The observed configuration — rankable toxicity, real signals, and a net of zero — is
the only stable one.

Two further consequences are worth recording. First, the reason the gate does not open is now
identified rather than assumed: it is not that these signals are weak, since three of the four
instruments detect genuine, placebo-validated structure. It is that the predictable component
of adverse selection is already incorporated in the price at which the maker is permitted to
trade. Second, the foresight oracle of Chapter 5 §6 is not contradicted. Perfect *ex post*
fill selection is worth $20–30/day; every *ex ante* proxy for it tested here is worth nothing.
The gap between those two numbers is the price of information, and this chapter measures it as
the whole of the available edge.

What remains for Part II is therefore not another attempt at the same door. If the competitive
zero is exact, then whatever earns a positive return must do so by leaving the competitive
game — by trading against a venue that cannot keep up, by providing immediacy where nobody
else will, or by being paid to bear a risk rather than to predict a price. Those are the three
chapters that follow.
