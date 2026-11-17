# Carry and the Funding Basis

---

## 1. The Third Structural Position

Chapter 6 established that the competitive margin pays nothing, and Part II has since examined
two ways of leaving it. Chapter 7 traded against a venue that could not keep up. Chapter 8 was
paid to provide immediacy where nobody else would. This chapter takes the third and last: being
paid to **carry a risk** rather than to quote a price or predict one.

The distinction matters because it changes what a positive result would mean. A market maker
who earns money is, in the framing of Chapter 2, being compensated for adverse selection and
inventory risk within a competitive auction. A carry trade earns money for holding an exposure
that someone else wants to be rid of, and the compensation is a **risk premium** in the asset-pricing
sense — durable, documented, and paid precisely because it can hurt. Whether such a premium
survives this thesis's accounting is a different question from whether a quoting strategy does.

Two families are tested, chosen because both are standard answers to how market-neutral desks
earn and neither provides liquidity: statistical arbitrage between correlated assets, and carry
on the perpetual funding basis.

## 2. Intraday Cointegration Does Not Survive

Cointegration is the canonical statistical arbitrage: if two non-stationary prices admit a
stationary linear combination, the spread mean-reverts and is tradeable. Contribution 67 tests
it on the five Hyperliquid majors — Engle-Granger on log-mids (the implementation uses
`statsmodels`' `coint` and `adfuller`; Johansen was planned and not run), 2,164 aligned
sixty-second bars, Ornstein-Uhlenbeck half-lives from an AR(1) fit, and an in-sample /
out-of-sample z-score backtest carrying real per-leg costs.

The econometrics cooperate and the economics do not. **Five of ten pairs "pass" cointegration at
p < 0.05** — ETH/LINK at 0.006, LINK/HYPE at 0.004. Under ten *independent* nulls the expected
number of passes at a 5% threshold is 0.5, so five is an order of magnitude more than chance,
and these p-values are not evidence against the relationships being real. The reason to
discount them is different and has to be argued rather than asserted: the ten pairs are drawn
from five assets that share a dominant market factor, so the tests are strongly dependent
rather than independent; the sample is a short intraday window, where Engle-Granger is known to
over-reject on persistent series; and no multiplicity adjustment was applied. The honest
statement is that this design cannot distinguish genuine intraday cointegration from size
distortion under dependence — which is why §2's verdict rests on the *trading* result below
rather than on the test statistics. Half-lives run 45 to 140 minutes, so the reversion is slow
relative to the horizon on which costs accrue.

Net P&L per trade is negative essentially everywhere, at −6 to −12 bps in sample. The reversion
does not cover the roughly 8.6 bps round trip a two-legged position pays. The marginally positive
out-of-sample pairs had negative in-sample results, which is sign-flip noise on small samples
rather than an edge that generalised.

This is sound econometrics priced out by transaction costs at this frequency, and the honest
scope note is that a genuine cointegration edge would need months to years of daily data,
breadth across many pairs, and a dynamically re-estimated hedge ratio — a different thesis on
public bar data, not a microstructure result. What the experiment establishes for present
purposes is narrower and still useful: the mean reversion visible at minute scale in these
markets is real and is not worth its round trip, which is the same wall that Chapter 6 §3 found
for the perpetual lead and Chapter 7 §5 found for shallow dislocations.

## 3. The Funding Basis: What Is Actually Being Measured

A perpetual future has no expiry, so its price is tethered to spot by a periodic funding payment
from longs to shorts (or the reverse). When a venue's perpetual trades rich, its funding is
positive and shorts are paid to hold the position that pulls it back. This is not a forecast; it
is a contractual cash flow, and collecting it is the purest available form of being paid to bear
a risk.

Over the captured window Hyperliquid's funding was positive on **72 to 100%** of settlements
depending on the asset — 99.9–100% on BTC, ETH and LINK at roughly 11% annualised, but only
71.9% on SOL at 3.7% — so the "persistently rich" description fits three of the four majors
and not the fourth. Taken alone that number is not a strategy, because a short perpetual
position is directionally exposed. The delta-neutral expression is to short the high-funding venue's
perpetual and go long the low-funding venue's, leaving the price legs to cancel and the funding
differential to accrue. Against Binance the net differential is:

| coin | net funding differential, annualised |
|---|---|
| BTC | +6.4% |
| ETH | +7.8% |
| LINK | +6.8% |
| SOL | +5.4% |

Positive on all four, and — unlike anything in Part I — positive before any modelling
assumption, since funding is a settled cash flow rather than an estimated edge.

## 4. The Basis Is the Risk

The differential is what the book *collects*. It is not what the book *earns*, and the gap
between those two is the substance of this chapter.

The two price legs do not fully cancel. Their difference is the basis between the two venues,
and the basis moves. A delta-neutral funding book therefore has two P&L streams — the funding
accrued, and the continuous mark-to-market of the basis — and Contribution 67 simulates both
rather than reporting the first:

| short HL / long Binance | funding leg | basis drift | gross carry | basis vol | Sharpe |
|---|---|---|---|---|---|
| BTC, 36 h | +6.7%/yr | **+1.7%/yr** (aligned) | **+8.4%/yr** (= 3.45 bps over the window, vs a 5.6 bps round trip) | 6.6%/yr | 1.26 — see below |
| LINK, 12 h | +8.3%/yr | **−8.6%/yr** (adverse) | ~0 | 11.9%/yr | ~0 |

On BTC the basis *helped*: the short leg profited as the rich perpetual converged, partly
self-hedging the funding it was collecting, and the combination returned +8.4%/yr against 6.6%
of basis volatility. The ratio of those two is 1.26, which the simulation labels a gross
Sharpe; it is reported here only because it is what the experiment emits, and it should not be
read as one. A Sharpe estimated from thirty-six hours has on the order of one independent
observation of the quantity that actually drives it — the basis — and its sampling error
dwarfs its value. On LINK an adverse basis drift consumed the entire funding leg and the book
returned approximately zero.

**And neither window clears its own round trip.** This is the sharpest limitation of the
chapter and it is arithmetic, not interpretation. The annualised figures above are annualised
from 36 hours and 12 hours respectively. Expressed as what the book actually earned over the
window it was measured on, BTC's +8.4%/yr is **3.45 bps** of notional (the net funding
collected was 2.8 bps: 0.047% from Hyperliquid against 0.019% paid to Binance), and LINK's is
approximately zero. Against the 5.6 bps round trip required to put the two-legged position on
and take it off, **both windows are net negative**. A carry book becomes profitable only by
holding far longer than anything observed here — which is the same point the cost table makes
from the other side, and it means the figures in this section establish that the cash flow
exists and is collectible, not that a tradeable strategy has been demonstrated.

The generalisation is the important part. Basis volatility runs 7 to 12% annualised against a
funding signal of roughly 7%, so over any short window **the realized P&L is basis-dominated,
not funding-dominated**. The funding expectation is only harvestable by holding long enough for
the mean-reverting basis to average toward zero — which means bearing that volatility throughout,
and accepting that a two-day measurement of this strategy is measuring the basis rather than the
carry. The per-coin instability is the same phenomenon Chapter 8 §5 found in the immediacy
premium, arising for the same reason: a risk premium paid per unit of risk borne is unstable per
unit and stable only in aggregate.

Costs determine whether any of it survives, and the direction is counter-intuitive. The one-time
round trip of 5.6 bps amortises to +0.68%/yr if the book is rebalanced monthly and to **20%/yr
if it is churned daily**. This is a hold-and-collect position that is destroyed by being traded,
which inverts the usual relationship between activity and edge and is worth stating plainly for
a reader whose instinct is that more rebalancing means tighter hedging.

## 5. The Tail This Thesis Could Not Measure

One quantity is missing, and its absence is the chapter's principal limitation rather than a
detail.

Both captured windows were benign — maximum drawdown under 20 bps — so the measured 6.6 to 11.9%
basis volatility is the **calm** volatility. What actually ends carry books is the fat left tail:
a liquidation cascade in which the perpetual spikes against the short leg, the basis blows out
rather than reverting, and a position sized against calm volatility is liquidated on one leg
before the convergence it was correct about arrives. Chapter 7 §5 measured the same venue's
touch emptying during dislocations, which is the microstructural signature of exactly that event.

No such episode occurred in the capture. The honest statement is therefore that carry returned a
ratio of 1.26 on BTC *conditional on no cascade*, and that the unconditional number is unknown
and lower — on top of the window being too short for that ratio to be an estimate of anything. This is the standard shape of a negative-skew risk premium: many small
gains, and the distribution's information concentrated in the rare loss that the sample does not
contain. It is also why the funding differential being a contractual cash flow does not make the
strategy safe — the cash flow is certain and the basis is not.

The same caveat has a constructive form. A carry book's sizing should be governed by the cascade
tail rather than the observed volatility, which means the quantity a practitioner most needs is
the one this capture could not supply. Measuring it requires a stressed window, and that is a
data-collection problem rather than an analytical one.

## 6. Synthesis

Carry is the third survivor and the most explicit about what it is.

The negative half is clean: intraday cointegration between correlated majors is real
econometrics — half the pairs pass a significance test — and it loses 6 to 12 bps per trade
because a 45-to-140-minute reversion does not cover an 8.6 bps round trip. Another genuine
effect priced just under its access cost, which is now the fifth time this thesis has measured
that configuration.

The positive half pays, and pays for a reason that can be stated in a sentence: Hyperliquid's
perpetual runs persistently rich, shorts are contractually compensated for holding the position
that corrects it, and the compensation net of Binance's funding is 5 to 8% annualised. The book
returned +8.4%/yr annualised on BTC and approximately zero on LINK, the difference being which
way the basis happened to drift over a short window. Annualised is the operative word: over the
thirty-six hours actually observed, the BTC book earned 3.45 bps against the 5.6 bps it costs
to open and close, so what this chapter establishes is that the cash flow is real and
collectible, not that the strategy was profitable as run.

And its shape is by now familiar. It is not a signal — nothing is being predicted. It is
compensation for bearing a specific risk, the cross-venue basis; it is unstable per unit and per
window and requires holding and diversification to realise; its costs invert the usual logic, so
that trading it destroys it; and its most important parameter, the cascade tail, is precisely the
one a benign sample cannot show.

Three chapters, three structural positions — the fast side of a slow venue, the provider of
immediacy where nobody else will, and the bearer of a basis someone else wants shed — and in
every case what is paid is compensation for occupying a position rather than payment for knowing
something. Chapter 10 takes up what that implies for the thesis as a whole.
