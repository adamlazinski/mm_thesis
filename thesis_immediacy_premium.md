# The Immediacy Premium in Thin Books

---

## 1. Where the Zeros Were Measured

Every zero in Part I was measured on a densely-competed book. LINK and BTC on Binance,
Hyperliquid's majors, Coinbase's majors: all venues where thousands of participants quote and
the spread is compressed, tick by tick, to the cost it must cover. Chapter 6 §2 measured that
compression directly — the median spread is exactly one tick and it repairs itself in about
100 ms, faster than a retail participant can react.

But the compression is performed *by competitors*, and that observation is the opening this
chapter exploits. Grossman-Miller's account of liquidity provision predicts a premium wherever
entry is costly enough that few providers arrive: the immediate counterparty to an impatient
trader must be compensated for warehousing a position nobody else wants. Wyart-Bouchaud says
the spread tracks the adverse-selection cost; it does not say the spread *equals* it on a book
where nobody is competing the surplus away.

So the question is empirical and specific: does a book with two or three makers at the touch
sit *above* the equilibrium the majors sit on? Crypto's long tail is the natural place to look,
and it is the one regime this thesis had not sampled.

## 2. Finding the Thin Books

Contribution 66 begins with a screen rather than a hypothesis. All 232 Hyperliquid perpetuals
are ranked by spread × √volume within a volume band — wide enough to pay, liquid enough to
trade — and six candidates spanning 9 to 56 bps of spread were captured for five days.

The tail is a different world from anything measured so far:

| book | spread | volume/day | orders at touch |
|---|---|---|---|
| HMSTR | **56 bps** | $244k | 22 |
| CELO | 25 bps | $236k | **2** |
| USUAL | 23 bps | $186k | 11 |
| VINE | 19 bps | $394k | **3** |
| ZORA | 16 bps | $645k | **3** |
| EIGEN | 9 bps | $3.3M | 13 |

against HL_BTC's 0.15 bps and 39 orders at the touch. Two or three orders at the touch is thin
competition *observed* rather than inferred, and the processed data makes it quantitative:
**13 to 101 unique makers per day** on these books, against thousands on the majors. A 56 bps
spread against a 1.5 bps maker fee also means that, for the first time in this thesis, the fee
gate of Chapter 5 §4 is not the binding constraint.

## 3. The Adverse-Selection Horizon Is a Property of the Venue

The first test is the Chapter 6 §4 markout, unchanged, applied to the tail. On five of the six
books the maker's realized half-spread **never goes negative within five seconds** — the
adverse-selection horizon runs off the end of the measurement window.

Set against the earlier measurements, a single ordering emerges:

| book | adverse-selection horizon |
|---|---|
| Binance spot / perp (small relative tick) | ≤ 15–20 ms |
| Binance / Hyperliquid LINK (large relative tick) | 75–87 ms |
| Hyperliquid BTC | seconds |
| Hyperliquid LINK | 3.4 s |
| **Hyperliquid tail (5 of 6)** | **> 5 s** |

This is the organising fact of Part II, and it is worth stating as a law rather than a list:
**the adverse-selection horizon is the venue's repricing clock.** A maker's edge survives for
as long as it takes the rest of the market to notice the price is wrong. On Binance that is
tens of milliseconds; on Hyperliquid's majors, seconds; on a book with three makers, longer
than five seconds. Chapter 7's dislocation alpha and this chapter's premium are the same
observation read from the two sides of the trade: Chapter 7 profits by *being* the fast
participant against a slow venue, and this chapter asks whether being the slow venue's maker
is itself paid.

## 4. Why the Round Trip Comes First

Before the numbers, a methodological commitment, and it is there because of a failure.

Contribution 64 tested a "defended maker" on Hyperliquid LINK — quoting both sides of the one
book then known to have seconds of protection, with free defensive gates. Under per-fill
accounting it looked like the project's first positive passive configuration: realized
half-spread of +1.01 and +0.62 bps on two days with the consensus and withdrawal gates active,
net positive at a rebate tier. The **inventory-aware round-trip simulation reversed it**:

| A+W gates, round trip | 15 Jul | 16 Jul | 17 Jul |
|---|---|---|---|
| bps of notional | **−1.60** | +0.12 | **−4.21** |

sign-unstable across queue-fraction assumptions, negative at base fees everywhere, with
inventory pinned at its cap every single day. The mechanism is the one that matters for this
chapter: trend flow is **one-sided**, so the market fills a maker *to* its cap, and the
apparently positive realized half-spread was unrealised mark on a position whose paired exit
never fills at those mids. Chapter 5 §5 catalogues this as the fourth mirage; Contribution 60
found it at the level of a single fill, and Contribution 64 found it again, worse, at the level
of a position.

Two consequences follow. First, every number in the rest of this chapter is produced by the
inventory-aware round trip, and mark-to-mid is not reported as a headline anywhere. Second,
the gates themselves are suspect: they made the round trip *worse* on two of the three days,
which is Chapter 6 §3's pairing-breakage reappearing — suppressing predicted-adverse fills
removes their losses and their exit fills together.

Contribution 64 also contains a clean illustration of why this chapter is about a premium
rather than a signal. On Hyperliquid, maker withdrawal genuinely *leads* price: one-sided touch
collapses, some 7,674 a day on BTC, precede drift of +0.40 bps at one second and +0.91 bps at
fifteen, against a placebo of approximately zero — an effect impossible on Binance, where
withdrawal and repricing are the same event at 50 ms. Taker aggression rises 1.3 to 1.4 times
in the ten seconds after a withdrawal. And acting on it as a taker nets **−2.3 bps**, because
the entry must cross into the side that just thinned. Real information, smaller than the cost
of using it: Chapter 6's pattern on a third venue.

## 5. The Round Trip on Thin Books

With that accounting, the tail books pay. The round trip clears **base fees** — no rebate
assumed — on four of the six:

| book | bps of notional | clears base fees? |
|---|---|---|
| HMSTR | +20.6 | yes |
| USUAL | +16.4 | yes |
| CELO | +8 to +9 | yes |
| VINE | +8 to +9 | yes |
| ZORA | negative | no |
| EIGEN | negative | no |

The two failures are the two tightest and most-competed books, which is the result rather than
an exception to it: EIGEN quotes 9 bps on $3.3M a day, which is the majors' regime in
miniature, and it behaves accordingly.

The important caveat is that **per-coin P&L is sign-unstable from day to day**. A single book's
result is close to a coin flip, because the outcome is dominated by whether that day's flow
happened to be one-sided. What is stable is the **basket**: equal-weighted across the six coins,
P&L is positive on **all five days**, averaging +$243/day with a mid anchor. The premium is a
portfolio property, not a per-instrument one — which is exactly what compensation for bearing
idiosyncratic inventory risk should look like.

## 6. Fair Value and Distance

Two refinements improve it, and both follow from Contribution 64's failure mechanism.

If a mid anchor lags and therefore keeps buying into a downtrend, an anchor that *leads* the mid
should skew away from the trend. Replacing the mid with Stoikov's imbalance-weighted
**micro-price** does exactly that: the micro anchor beats the mid anchor on the basket on four
of five days, +$291/day against +$243/day.

And if the spread genuinely exceeds the adverse-selection cost, quoting further from fair value
should raise the margin on each fill. It does, monotonically. On HMSTR, quoting at fair value
± k × (rolling median half-spread):

| k | bps of notional | fills/day |
|---|---|---|
| 0.5 | 44.9 | 887 |
| 1.0 | 55.2 | 563 |
| 1.5 | **88.1** | 266 |

This is the trade-off in its cleanest form — better price per fill against fewer fills — and it
is available only because the book is wide enough to have somewhere to stand. On a one-tick
book, "wider" means behind the touch, where the order does not fill at all.

One refinement failed and is reported as a negative. A depth-conditioned rule for choosing the
anchor per coin — micro where the touch has depth, mid where it is thin — was fitted on two days
and looked persistent. Out of sample it delivered +$228/day against +$218/day for simply using
the micro anchor everywhere: no meaningful edge over the simpler rule. The mechanism was a
narrative fitted to twelve observations, and thirty coin-days do not support per-coin anchor
selection.

## 7. The Replication, and What the Bridge Control Reveals

The six coins were *selected* by a screen for wide spreads, so the basket's consistency could be
a selection artifact. The only cure is a disjoint sample, and Contribution 66 takes it with the
prediction registered in version control **before the data was examined**: if the effect is real,
the basket is positive and micro ≥ mid on the majority of days.

Six new coins were captured, none in the original set, plus one **bridge control** — USUAL, which
was in the original six and remained wide. Both pre-registered checks pass: the basket is
positive on **4 of 4 days**, including with the single outlier coin removed, and micro ≥ mid on
**4 of 4 days**. The effect is not an artifact of coin selection.

The bridge control, however, carries the more important finding. USUAL — the *same coin*, same
strategy — fell from **+40 bps of notional in July to +0.39 bps in August**, while the tail's
widest available spread compressed from 56 bps to 14 bps. Nothing about the technique changed.
What changed was the regime.

That single comparison converts the chapter's result from a claim about a strategy into a claim
about a price. The immediacy premium is **priced by spread width**: it is large when the tail is
wide and approximately zero when the tail tightens, and a practitioner who measured it in July
and sized against it in August would have been sizing against a number that no longer existed.

It also means the honest magnitude is the ex-ACE basket figure of roughly +$215/day rather than
the headline that one coin's volume explosion produced — and that a frozen tape during such an
explosion is precisely where a real maker is run over and the simulation cannot see it.

## 8. Synthesis

This is the affirmative half of the zero-profit law, and its cleanest confirmation.

Where competition is thin, the spread genuinely exceeds the adverse-selection cost and a maker
is paid: four of six books clear base fees on an inventory-aware round trip, the basket is
positive on every day of two independent samples, and a pre-registered replication on disjoint
coins holds. The adverse-selection horizon on these books runs beyond five seconds, against
tens of milliseconds on Binance — one law, read at four venue clocks.

But what is being paid is a **premium, not an edge**. It is compensation for warehousing
inventory and bearing jump risk in illiquid names; it is sign-unstable per coin and positive
only as a diversified basket; it shrinks with the spread that defines it; and its magnitude is
set by how many competitors have arrived, not by anything the quoter knows. The bridge control
prices that dependence exactly: a forty-fold decay in two months, on an unchanged coin, driven
by a tightening tail.

The zero-profit law is therefore not violated at its boundary. It is **parameterised** there.
The majors sit at zero because competition has arrived and compressed the spread to its cost;
the tail sits above zero by the amount competition has not yet removed; and the same law,
applied to the same books two months apart, predicts the decay that the bridge control measures.
Chapter 9 turns to the third and last structural position — being paid to carry a risk rather
than to quote a price — and finds the same shape a third time.
