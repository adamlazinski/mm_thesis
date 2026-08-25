# Classical and Machine-Learning Strategy Results

---

## 1. What This Chapter Does

Chapter 3 ended with a calibrated engine and a set of parameters derived from the data
rather than from the literature: κ and A separated (§3), dollar volatility in the GLFT
formulas, γ in the range those formulas actually require, and a fill condition chosen to
suit a discontinuous trade series. This chapter runs strategies against that engine and
reports what they earn.

The results are, on their face, good. On LINK/USDT a constrained market maker earns
+$154/day over thirty consecutive days with a 100% win rate and a daily Sharpe of 56.5;
the same parameters, applied nine months later with no recalibration, earn +$43.78/day
with a 100% win rate; a tabular reinforcement learner trained on seventeen days beats the
classical baseline and transfers ten months forward. Reported at this level of detail —
which is the level at which such results are usually reported — this is a working strategy.

The chapter is written to be read twice. On a first pass it is a straightforward account
of strategy performance. On a second pass, after Chapter 5, it is a catalogue of the
symptoms of a single measurement error. Three findings in particular will not fit the
surface story, and §7 states them plainly rather than resolving them: the optimiser
converges on a configuration in which the model's theoretical machinery contributes
*nothing*; the edge exists on one asset and is destroyed on the other; and a direct
measurement of queue position (Contribution 20) finds that the fill probability the
backtest is using is off by a factor of forty at the one price level that matters most.

## 2. The Optimum Is Degenerate

A random search over A-S and GLFT parameters on LINK/USDT converges to a configuration
that is theoretically degenerate (Contribution 16):

```
gamma        ~ 0          (no reservation-price skew at all)
min_spread   = 6.44 bps   (3.86 ticks - one tick inside the natural spread)
max_inventory = 38 LINK
daily_loss_limit = $25
```

With γ ≈ 0 the reservation price reduces to the mid, the inventory-skew term vanishes, and
the optimal-spread formula is replaced by a constant floor. What survives the search is not
a market-making model but three structural rules: **quote inside the spread, cap the
position, stop on a large loss**. Every component derived in Chapter 2 — the reservation
price, the finite-horizon term, the κ-dependent optimal spread — is optimised away.

The performance of this degenerate configuration on LINK, 11 June – 10 July 2025:

| metric | value |
|---|---|
| mean P&L | +$154/day (total +$4,633) |
| win rate | 30/30 days (100%) |
| daily Sharpe (√365) | 56.5 |
| average markout | +1.2 to +2.5 bps (positive) |
| adverse fills | 17–35% (against 60–100% on BTC) |

The stated mechanism is inventory cycling. The inside-spread floor makes the strategy the
best bid and offer, which guarantees taker flow; the tight inventory cap means that when
the position is long only the ask is quoted and when short only the bid, so the strategy
sells into local highs and buys from local lows, turning over roughly 1,800 inventory sign
changes per day. The positive markout is the striking number: fills are followed by
*favourable* price movement, which is the opposite of what a market maker normally
experiences and the opposite of what Chapter 2 §6 predicts.

That anomaly is worth holding onto. A positive average markout means the strategy is being
filled by counterparties who are, on average, wrong. Chapter 5 explains how a backtest
produces that result.

## 3. The Model Contributes Nothing: GLFT Against a Flat Control

Contribution 16 leaves open whether the parameter regime or the model formula is doing the
work. Contribution 17 answers it with a direct control: pure A-S with γ ≈ 0, given the same
inventory cap, loss limit and spread floor as the GLFT search winner, over the same
out-of-sample period.

| metric | GLFT search-optimum | A-S γ≈0 control |
|---|---|---|
| mean P&L/day | +$88.56 | **+$149.45** |
| win rate | 13/13 | 13/13 |
| Sharpe | 27.4 | **57.7** |
| average spread | 11.9 bps | **7.4 bps** |
| fills/day | 8,812 | **11,060** |

The flat control beats the fitted GLFT model by 69%. The mechanism is identifiable: GLFT's
spread formula widens to 10–18 bps whenever the rolling arrival-rate estimate Â is low,
which happens in about a third of quoting steps on LINK's sparse flow, and each widening
episode costs roughly 2,250 fills a day. The formula's theoretical advantages — infinite
horizon, inventory-proportional skew — are outweighed by the instability of estimating Â on
this asset.

So the risk management is doing the work and the model is a liability. This is a real
result about GLFT under sparse flow, and it survives Chapter 5. But it also means that by
this point in the thesis the "market-making model" has been reduced to a spread floor and a
position cap, and any explanation of the P&L must come from the interaction of those two
rules with the market's microstructure rather than from optimal-control theory.

## 4. Signal Overlays Make It Worse

If the strategy is a mean-reversion cycler, adding a directional signal ought to help it
avoid the fills that lose money. Contribution 18 tests OFI-directed one-sided quoting and
momentum suppression as overlays, across all thresholds, on the full thirty-day period:

| overlay | in-sample win rate | in-sample mean/day | out-of-sample mean/day |
|---|---|---|---|
| baseline (none) | 100% | +$71.8 | +$83.0 |
| OFI-directed (best) | 35% | −$67 | +$129 |
| momentum-suppress (best) | 35% | −$50 | +$132 |

Both overlays collapse the in-sample win rate from 100% to 35% and produce worst-day
drawdowns of −$923 to −$1,004 against a baseline that never has a losing day. The
out-of-sample figures look better only because the overlays happened to miss the two
trending days (22–23 June) that dominate the in-sample losses — an accident of the split,
not evidence of a signal.

The interpretation offered in Contribution 18 is that a directional overlay interrupts the
cycling during precisely the volatile, high-OFI periods that generate the most fills and
therefore the most spread revenue. The regime that looks dangerous to a directional trader
is the profitable one for a cycler. Contribution 22 reaches the same conclusion from the
other direction: order-book imbalance genuinely predicts direction (IC ≈ 0.20 at 0.5s,
peaking at 0.39 at 30s), but shifting both quotes toward the predicted direction *reduces*
P&L by 14%, because it buys extra fills on the side that is about to move against the
quoter. OBI predicts the direction of the next move, not its timing, and a symmetric
response to it is a way of paying for the privilege of being adversely selected.

Contribution 22 also contains a methodological warning that recurs throughout this thesis.
The same OBI signal measures IC = 0.70 with a hit rate of 95.5% if zero returns are excluded
from the calculation, and IC ≈ 0.20 if they are not. LINK's mid moves rarely at 0.5s
resolution because its spread is pinned, so conditioning on non-zero returns selects exactly
the periods when the book was already heavily imbalanced. The 0.70 is an artefact of the
filter. It would have been an easy number to publish.

## 5. It Transfers Nine Months Forward

Contribution 19 applies the June 2025 parameters, unchanged and unrecalibrated, to LINK in
April 2026 — nine months later, after the price has fallen from about $13 to about $9:

| metric | Jun–Jul 2025 | Apr 2026 (zero-shot) |
|---|---|---|
| mean P&L/day | +$154 | +$43.78 |
| win rate | 30/30 | 30/30 |
| Sharpe | 56.5 | 38.7 |
| average markout | +1.8 bps | +1.25 bps |
| adverse fills | 22% | 22% |

The drop in dollar P&L is accounted for by the price level: the same number of ticks per
round trip on a notional roughly 31% smaller. What does not change is the *shape* — the win
rate, the positive markout, and the adverse-fill fraction are nearly identical nine months
apart. Whatever is producing this P&L is a stable property of the asset's microstructure,
not of a particular month's volatility.

This is the strongest-looking result in the chapter, and on a second reading it is the most
informative one. A backtesting artefact that depends on a transient market condition would
not survive a nine-month gap and a 30% price move. An artefact that depends on the asset's
*permanent* structure — a spread pinned at a fixed number of ticks, a book that is hollow at
the touch — would survive exactly this way, and would reproduce the same markout and the
same adverse-fill fraction, because those are consequences of the structure rather than of
the market. Contribution 19 does not distinguish between a robust strategy and a structural
artefact. It only establishes that whichever it is, it is stable.

## 6. Reinforcement Learning: It Works on LINK and Fails on BTC

A tabular Q-learner (120 states × 19 actions; state = inventory bin, volatility ratio,
momentum, spike; action = bid/ask spread in 3–9 ticks × hold time 0.25–2.0s) trained on
seventeen days of LINK produces (Contribution 23):

| period | days | mean P&L/day | win rate | Sharpe | fills/day |
|---|---|---|---|---|---|
| in-sample (Jun 11–27 2025) | 17 | +$68.17 | 100% | 42.7 | 11,688 |
| out-of-sample (Jun 28–Jul 10) | 13 | +$71.24 | 100% | 38.6 | 8,884 |
| April 2026 (zero-shot) | 30 | +$45.94 | 100% | 48.0 | 4,965 |

against the A-S baseline's +$43.78/day at Sharpe 38.7 on the same April 2026 data: a 5%
improvement in mean and a 24% improvement in Sharpe, from a policy trained ten months
earlier on seventeen days. The learned behaviour is interpretable — the agent halts quoting
between 3 and 116 times a day in calm periods and 138 to 1,926 times a day in volatile ones —
and the greedy rollout beats the exploring one, so the Q-values rather than exploration
noise are producing the result. A DQN with a richer continuous state space degrades
monotonically over training toward the classical baseline, which is the expected behaviour
of an over-parameterised model on seventeen days of data.

The same architecture, the same state and action spaces, and the same training procedure
applied to BTC/USDT produce (Contribution 24): −$2.12/day in training, −$2.09/day
out-of-sample, a **0% win rate in every one of thirty epochs**, and — the diagnostic detail —
a mean loss of exactly 0.000 at every epoch, meaning the tabular updates receive no gradient
signal whatsoever. Daily P&L is uniform at about −$2.10 regardless of whether the day
produced 28 fills or 388, and peak inventory pins at the cap on twelve of thirteen days.

Two assets, one algorithm, one code path: on LINK it learns a transferable policy, and on
BTC it produces a flat, featureless loss with no learning signal at all. That is not a
statement about reinforcement learning. It is a statement about the two assets, and it is
the same statement Contribution 16's degenerate optimum was making.

## 7. The Puzzle

Taken at face value, this chapter reports a robust and well-validated strategy: profitable
on thirty consecutive days, stable across a nine-month gap and a 30% price move, insensitive
to whether the quoting rule is fitted by random search or learned by reinforcement learning,
and improved by neither optimal-control theory nor directional signals. Three findings,
however, do not fit that description, and none of them is resolved here.

**First, the optimum is degenerate.** The search does not find a good market-making model;
it finds that the market-making model should be switched off (§2), and a controlled
experiment confirms that the formula is a liability rather than an asset (§3). A P&L that
survives the deletion of the entire theoretical apparatus is not being produced by that
apparatus, and nothing in this chapter identifies what *is* producing it.

**Second, the edge is asset-specific in a way no strategy parameter explains.** Every
positive result is on LINK; BTC yields −$2.10/day with no learning signal (§6), and
Contribution 24's diagnosis is a mismatch between the action space and the microstructure
rather than anything about the strategy. The one axis on which the two assets differ most is
the one Chapter 3 §1 chose them for: relative tick size, and therefore whether the spread is
free to move or pinned at a floor.

**Third, and most concretely, a direct measurement says the fill model is wrong.**
Contribution 20 computes the empirical fill probability on LINK's L2 order book under two
models — the price-only rule the backtests in this chapter use, and a queue-aware rule that
requires cumulative traded volume to exceed the resting volume ahead of the order:

| distance from mid | region | price-only | queue-aware |
|---|---|---|---|
| 1–4 ticks | inside the spread | 2.97% | 2.97% |
| 5 ticks | at the natural bid | 2.97% | **0.073%** |
| 6–15 ticks | outside the spread | 0.10% | 0.0055% |

Inside the spread the two models agree exactly, because an order there has no queue in front
of it. At the touch they differ by a factor of **41**. The strategy of §2 is defined by
quoting one tick inside the natural spread — that is, in the only region where the price-only
model happens to be correct — and Contribution 21 adds that LINK's book is hollow at the
touch, with a median best-bid depth on the order of 8,600 LINK against a 5-LINK order.

The chapter therefore ends with a strategy whose P&L is real within the model that produced
it, whose behaviour is stable across regimes, and whose fill assumption has just been shown
to be wrong by a factor of forty everywhere except at the exact price level the strategy
lives on. Chapter 5 re-runs these strategies against the corrected fill model, and the
difference between the two is the central result of this thesis.
