# Data, Microstructure & Methodology

---

## 1. Data

This thesis uses tick-level trade and quote data from CoinAPI for two Binance Spot pairs —
BTC/USDT and LINK/USDT — across three periods: May–June 2025 (BTC, the primary calibration
and backtest sample), June–July 2025 (LINK, in-sample and out-of-sample backtest windows),
and April 2026 (both assets, used for zero-shot transfer checks and, for LINK, alongside a
matching LINK perpetual-futures sample used in Chapter 6). Trade files carry
`time_exchange, time_coinapi, price, size, taker_side`; quote files carry
`time_exchange, time_coinapi, bid_price, bid_size, ask_price, ask_size`. A full trading day
is on the order of four million combined trade-and-quote events.

The two assets were not chosen for their names but for what they represent on opposite ends
of a single axis: **tick size relative to price**. BTC trades with a $0.01 tick at a price
of roughly $100,000 — a relative tick of ~1 part in 10 million — and its quoted spread is
almost always exactly one tick (CLAUDE.md: "Mid price is always at X.5 cents since market
spread is almost always 1 tick"). LINK trades at a price of roughly $9–10 with an exchange
tick of **$0.01** throughout the sample period — a relative tick of ~11 bps, four orders of
magnitude coarser than BTC's — and its quoted spread is pinned at exactly that one tick
essentially 100% of the time. (Establishing this tick size is itself a result: the
experiments of Chapters 4–6 were originally parameterised with a $0.001 tick, under which
the spread appears as a constant "10 ticks"; Contribution 54 documents how live-feed
validation exposed the mis-specification — every price in the dataset sits on the $0.01
grid — and what it retracts. Binance reduced the tick to $0.001 only after the sample
period.)
BTC is what the market-microstructure literature calls a **small-tick asset** (the spread is
free to move and is set by competition at close to its minimum); LINK is a **large-tick
asset** in the sense of Dayri & Rosenbaum (2015): the spread is pinned at its floor and
price dynamics are dominated by queue formation and depletion rather than continuous
repricing. Chapter 5 (Contribution 33) shows this single axis — spread-free vs. spread-floored
— is what determines *how* the zero-profit equilibrium of Chapter 2 §6 is enforced on each
asset, which is why both assets are carried through the whole thesis rather than one being
used as a robustness check on the other.

---

## 2. Empirical Microstructure: Stylized Facts

Three stylized facts, established empirically before any strategy is run, motivate every
calibration choice in §3 and anticipate the central result of Chapter 5.

**(a) Return autocorrelation and the momentum decay horizon (Contribution 1).** BTC/USDT
return autocorrelation at the 300ms horizon is ≈0.18 at lag 1 and ≈0.08 at lag 2, both
statistically significant; at the 1-second horizon lag-1 autocorrelation is ≈0.15. By a
20-second horizon, autocorrelation is indistinguishable from zero. The momentum decay
horizon is therefore roughly 5–10 seconds. This number recurs throughout the thesis: it sets
the scale for "fast" vs "slow" in the requote-frequency sweep (Contribution 2), it is the
scale at which Contribution 31's taker-pivot signal is evaluated, and Contribution 12's
post-fill markout is measured at exactly this horizon.

**(b) Fill curves are not exponential, and not the same on the two assets (Contributions 6,
15, 25).** A-S and GLFT assume `λ(δ) = A·exp(−κδ)` (Chapter 2 §4). On BTC, the empirical fill
curve is better described by a **two-component** model,

```
λ(δ) = A_liq · exp(−κ·δ)  +  A_mom
```

where the liquidity term `A_liq·exp(−κδ)` decays quickly (κ≈1.85/tick in the
highest-quality 15-minute windows, R²>0.8) but a distance-invariant **momentum floor**
`A_mom` — roughly 15% of total arrivals — persists no matter how far the quote sits from the
mid. On LINK, the picture is different again: a crossing-intensity estimate of κ (Approach
C, Contribution 25, fit directly to how often the mid moves a given number of ticks, with no
order-placement simulation) gives κ=2.08 per measurement tick with R²=0.97 — a *clean*
exponential, but with essentially **no momentum floor** (`A_mom≈0`). Combined with the
spread pinned at one true tick, this produces the step-function shape of Contribution 15:
fill probability is roughly flat (17–37%) for any quote *inside* the natural spread, and
roughly flat at a much lower level (1–14%, markout −1.89 bps) for any quote *at or outside*
it. There is no smooth exponential regime on LINK at all — the curve has two plateaus and a
cliff between them. Contribution 54 supplies the structural explanation: these distances are
denominated in the $0.001 measurement grid, but the exchange grid was $0.01, so the
"inside-spread" plateau spans sub-tick price points that were never placeable order levels —
the two plateaus are the two *real* price regions (at the touch, and behind it), and the
cliff between them is the tick boundary itself.

**(c) The exponential/Poisson model is regime-dependent on BTC, and regime dominates
strategy choice (Contributions 7, 13).** Restricting to BTC, the two-component fit of (b)
achieves R²>0.8 in only 34 of 276 fifteen-minute windows (≈12%) — concentrated in low-σ
periods (σ_$ ≲ 3 $/√s) during EU-morning and US-evening sessions, where κ rises to ≈1.85/tick
vs. ≈0.31/tick full-day. Outside these windows the exponential assumption is not a slightly
worse fit; the model regime itself does not hold. Consistent with this, a direct May-vs-June
2025 comparison (Contribution 13) finds the *same* A-S configuration profitable in May (calm,
mean-reverting; best random-search cell +$11.48/day) and unprofitable in June (volatile,
directional; best cell −$4.89/day) — calendar regime, not model or parameter choice, is the
single largest determinant of the sign of the result.

A fourth fact, established later via L2 order-book snapshots (Contribution 20) but stated
here because §5 depends on it, is that LINK's order book is **hollow at the touch**: the
median resting size at the best bid is on the order of 8,600 LINK — roughly 1,700× a 5-LINK
order — and L2 depth (within a few ticks) is ≈6.5× L1 depth. A resting order of retail size
is a vanishingly small fraction of the queue at any price level on LINK.

---

## 3. Calibration Methodology

**Disentangling A and κ (Contribution 4).** The A-S/GLFT literature typically proxies κ with
the total trade arrival rate (≈44/s on BTC), conflating two distinct quantities: the
*baseline* arrival rate `A` (how often anything happens) and the *price-sensitivity* `κ` (how
quickly fill probability decays with distance from mid). This thesis separates them: `A` is
estimated from the fill probability at the touch (δ≈0.5 ticks), and `κ` from the decay of the
fill curve beyond it. So estimated, κ is regime-dependent and follows approximately
`κ(σ_$) ∝ σ_$^{−1}` — already a hint of the σ–κ coupling that becomes Contribution 33's
central result.

**Three estimation approaches for κ.**
- *Approach A — unconditional market-distance*: fit the exponential decay to the
  unconditional distribution of trade distances from mid. Simple, but overstates fill
  sensitivity: it includes price moves that occur over timescales longer than any realistic
  exposure window.
- *Approach B — execution-aware simulation* (Contribution 5): at each requote (0.5s), place a
  synthetic order and check whether a trade *during the exposure window*
  `[t+latency, t+quote_interval+latency]` would have filled it, sweeping over δ. On BTC
  (2025-05-13) this gives κ≈0.311/tick vs. Approach A's 0.065/tick — roughly 5× higher, and a
  better fit (R²=0.46 vs. 0.38) — because large price excursions that drive Approach A's
  estimate typically unfold over longer horizons than a 0.5s exposure window.
- *Approach C — crossing intensity* (Contribution 25): estimate
  `λ(δ) = P(|Δmid(h)| ≥ δ) / h` directly from how often the mid crosses δ ticks within a
  horizon h (60–120s), with no order-placement model at all. This is the model-free limit of
  the GLFT arrival intensity, and is the approach used for LINK's κ=2.08/tick, R²=0.97 above.

**Gamma (γ) and dollar units (Contributions 3, 11, 26).** A-S's inventory-skew term scales
with `γ·σ²`. With BTC's log-return σ≈2.9e-5/s, σ²≈8.4e-10 — squaring an already tiny number
makes the skew negligible at equity-literature values of γ≈0.1. Producing a dollar-meaningful
skew on BTC requires γ on the order of 30–100. A related but distinct error (Contribution 11)
is unit mismatch: GLFT's formulas are written in *dollar* volatility
`σ_$ = σ_log-return × mid`; using log-return σ directly produces skew ~10,000× too small at
BTC's price level. A third, compounding issue (Contribution 26) was a hardcoded `γ ← γ×1000`
rescaling, introduced so BTC config files could use "human-scale" γ values; this hack
happened to put BTC's *effective* γ in the correct 30–100 range, but applied to LINK — whose
σ² is ≈40,000× BTC's — it produced a 56-tick reservation-price shift (5.7 natural spreads) at
a routine 50-LINK inventory. Removing the hack (so config values *are* the effective γ) is a
breaking change: BTC configs need γ≈86 directly, in the same 30–100 range the uncorrected
analysis had already identified — the bug was in how that number was expressed, not in the
number itself.

**The GLFT spread blowup (Contribution 27).** GLFT's spread formula (Chapter 2 §3) contains
`(1+κ/γ)^{1+κ/γ}`, which grows super-exponentially as κ/γ moves away from 1. For LINK's
κ≈208/$ (≈2.08/tick at LINK's price), every economically sensible γ produces a half-spread of
many ticks to many dollars — GLFT's own formula recommends a spread far wider than LINK's
1-tick floor allows it to clear, i.e. unquotable. The pragmatic fix implemented here is a
`max_spread_bps` ceiling that caps the *formula* spread while leaving the reservation-price
(inventory-skew) term intact — decoupling "how wide GLFT wants to quote" from "how wide GLFT
is allowed to quote."

---

## 4. Backtest Engine Architecture

The engine is event-driven: trade and quote events are merged into a single chronological
stream (~4M events/day) and processed by three components.

- **MarketState** maintains rolling estimates of σ (volatility), κ (via a Poisson-MLE
  `KappaEstimator`), order-flow imbalance (OFI), order-book imbalance (OBI), and short-horizon
  momentum, updated incrementally as events arrive.
- **OrderManager** tracks at most two live orders (`_active`, O(1) hot-path checks) plus a
  `_archive` of dead orders, applies the latency and fill model (below), and accounts cash and
  inventory. PnL is `cash + inventory × last_mid`, marked to market continuously. A full day
  runs in ≈4 minutes.
- **Strategy** (A-S, GLFT, shifted-GLFT, OFI/momentum extensions, regime filters, tabular-Q /
  DQN RL) receives the current `MarketState` and returns target quotes.

**Latency and exposure window (Contribution 8).** Orders become live at `timestamp + latency`
and are cancelled from `timestamp + latency`; a naive implementation that calls
`cancel_all()` without passing the current timestamp effectively disables cancel-latency
(since `0 + latency` is immediately in the past for any real Unix time). Once corrected — every
`cancel_all(timestamp)` call passes the current time — the cancel-latency delay to *removing*
a stale quote and the activation-latency delay to *posting* a new one cancel exactly, giving
the clean result `exposure_window = quote_interval`, independent of latency. This identity is
used directly in the theoretically-scaled minimum spread of Contribution 2,
`min_spread = 2σ√(exposure_window)`.

**Hysteresis.** Recomputing quotes every 100ms but only cancelling/reposting when the new
optimal quote diverges from the live one by more than `tolerance_ticks` (default 0.5)
dramatically reduces churn — typically only 1–4% of recompute steps trigger an actual
requote, so an order's effective lifetime is much longer than the nominal recompute interval.

**Gap handling.** Data gaps >30s close out inventory at the last mid and reset
`MarketState`; gaps of 2–30s cancel resting orders and pause requoting until data resumes.

**Fill condition for a discontinuous trade series (Contribution 9).** The textbook fill rule
— a resting bid fills only on an incoming *sell* trade at or below the bid — assumes a
continuous order book where every price level the market passes through is visited by a
trade with the corresponding aggressor side. CoinAPI's trade series can be discontinuous: a
single printed trade at $101,900 can leave a resting bid at $102,000 in its wake without any
trade ever printing *at* $102,000. The engine instead fills on **price alone** — any resting
order whose price was crossed by a trade is filled, regardless of the trade's recorded
aggressor side. This is the correct treatment of the data as given — but, as §5 develops, it
is also the assumption that turns out to matter most.

---

## 5. The Fill-Model Audit: From Price-Only to Honest

The price-only fill condition of §4 is, in the language of Chapter 2 §5, a **front-of-queue**
assumption: it fills every order whose price was crossed, with no regard for what else was
resting at that price or when the order was placed relative to it. Three successive pieces of
work probe how much this assumption is doing.

**Contribution 14** is the first sign of trouble. Albers et al. (2025) report that
counter-trading order-book imbalance (OBI) — posting the ask when the book is buy-heavy,
the bid when it is sell-heavy — achieves near-zero adverse selection on BTC perpetuals,
because such orders fill *during reversals*, when they have already queued long enough to be
near the front. Replicating the same logic against the price-only engine gives the opposite
result (best: −$238/day): the price-only model fills the OBI-counter order on the *initial*
sweep, before any reversal — exactly the fill the paper's mechanism depends on the order
*not* getting. The discrepancy is entirely attributable to queue position, which the
price-only model does not have.

**Contribution 29** quantifies this directly by implementing an **L2 queue-clearing** fill
model. Each order is assigned `queue_ahead` — the resting volume estimated to be ahead of it
at submission — and only fills once cumulative traded volume since submission exceeds
`queue_ahead`. Calibrated from §2(d)'s ~8,600-LINK median best-bid depth, `queue_fraction
=0.001` represents `queue_ahead≈8.6 LINK` — one similarly-sized competing market maker ahead
of a 5-LINK order, already a generous (queue-light) assumption. Re-running the best LINK
configuration (Contribution 28's flat A-S, +$1,428 over 30 days under price-only) through
this model gives **+$588** — a **59% reduction**. More striking is what happens to the
distribution: daily *Sharpe* ratio rises slightly (0.97→1.07) even as the mean falls 59%,
because the queue model converts frequent small fills into rare, large, sweep-driven ones —
and adverse-fill rate on those rare fills rises from 24% to 45%. Waiting in the queue
selects for the fills that happen *because the market already moved against you*; this is
the adverse-selection cost the price-only model cannot see by construction.

**The corrected-engine addendum to Contribution 30** closes the remaining gap on the other
side of the book. Even under the L2 queue model, an order that arrives **marketable** — i.e.,
it would cross the spread immediately on submission — was still being treated as a patient
limit order subject to the queue model, when in reality such an order *is a taker*: it
crosses immediately, pays the taker side of the spread (and, on perpetuals, the taker fee),
and bypasses the queue entirely. Correcting this — marketable-on-arrival orders fill
instantly as takers, with the corresponding fee — together with applying a realistic 4.5 bps
taker fee, is the final methodological change this thesis makes to the engine. Its effect on
the headline LINK result, and the full queue-priority decomposition this section has been
building toward, is the subject of Chapter 5.

---

## 6. The 2026 Live Multi-Venue Capture

The data of §1 is purchased history, and Contribution 54 showed how badly that can fail: the
vendor files were silently wrong about the single most basic parameter of the market — the
price grid — and an entire arc of results had been placing orders at prices the exchange
would have rejected. Three further needs pointed the same way. The queue-priority
decomposition of Chapter 5 rests on real resting depth, which a quote feed can only proxy.
The cross-venue questions of Part II require *synchronised* observation of several venues at
once. And the flow-sorting question of Chapter 6 requires knowing who the counterparty is,
which no centralised exchange discloses. All four needs are met by recording the market
directly, so the second half of the thesis rests on a purpose-built capture rather than on
vendor files.

**Venues and streams.** Four venues were recorded concurrently over July–August 2026:

| venue | instruments | depth captured |
|---|---|---|
| Binance spot | LINK/USDT, BTC/USDT | full L2 (depth-diff + REST anchors), trades, bookTicker |
| Binance USDT-M perp | LINK, BTC | full L2, trades |
| Coinbase Exchange spot | LINK-USD, BTC-USD | full L2 (snapshot + `l2update`), matches |
| Coinbase International perp | BTC-PERP, LINK-PERP | top-of-book + trades (L2 requires auth) |
| Hyperliquid perp | BTC, ETH, SOL, LINK, HYPE + a screened tail | trades **with both counterparty wallet addresses**, BBO, 20-level book, funding and open interest |

**Raw-first design.** Every websocket message is appended verbatim, with a local receive
timestamp, to hourly-rotated gzipped JSONL; nothing is interpreted at capture time, so a
collector bug cannot corrupt the record. REST depth snapshots are written into the same
stream at start, on every reconnect, and periodically as safety anchors; detected gaps are
logged in band. Book reconstruction happens offline, replaying snapshot-plus-diff under each
venue's official synchronisation rules (Binance spot's `U`/`u` chain, futures' `pu` chain,
Coinbase's snapshot + `l2update`, Hyperliquid's native snapshots). Each instrument-day
produces an integrity report — sync violations, re-anchors, crossed books, and the
receive-minus-exchange clock offset distribution — and the reconstructed output is written in
the same CoinAPI schema as §1, so every experiment script consumes purchased and captured
data interchangeably.

**Two clocks per event.** Each record carries both the venue's own timestamp and our local
receive time. This dual-clock record is not bookkeeping: §7 and Contribution 63 show that
inter-venue timestamp offsets can manufacture an apparent price-discovery lead of several
hundred milliseconds, and only a common-clock recomputation distinguishes a real lead from an
artifact.

**Scale and what it enabled.** A single instrument-day runs to millions of events (3.0M
trades and 838k depth updates for BTC perp on 2026-07-15 alone). The capture is what makes
possible: real-L2 validation of the quote proxy and the queue-fraction bracket (C55), the
model-free adverse-selection decomposition across four books (C59), counterparty-resolved
toxicity (C62), the venue-clock hierarchy and its clock-artifact check (C63), the thin-book
screen and immediacy-premium tests (C66), and the funding-basis book (C67).

**Limits, stated plainly.** The capture spans days to weeks, not months, so every result
drawn from it is a short-window result and seasonal or regime claims cannot be made from it
alone — Contribution 66's bridge control is a direct demonstration of how much regime
matters. Observation is from a single geographic vantage, so receive timestamps carry this
location's network path. No centralised venue discloses order-level (L3) data, so queue
position remains inferred rather than observed even here. Coinbase International's book and
Hyperliquid's depth beyond the touch are gated behind authentication and were not captured.

---

## 7. The Honest-Accounting Discipline

The fill-model audit of §5 is one instance of a general problem: a backtest is a claim about
counterfactual executions, and every simplification in it biases the same direction — toward
fills that a real order would not have received, at prices it could not have transacted. Over
the course of this thesis six distinct such errors were found, four of them in results this
author had already accepted. The response is a standing set of rules, each traceable to the
failure that motivated it. They are stated here as method because Chapters 4–9 apply them
uniformly, and because the discipline is itself a contribution.

1. **Exchange-valid prices.** Every quoted price must lie on the venue's real tick grid,
   validated against a live feed rather than inferred from a vendor's data (C54).
2. **Real queue, not price-only.** Price-only filling is a front-of-queue assumption; fills
   are cleared against estimated resting volume, with `queue_fraction` bracketed from L2 and
   from a book-side census of touch-level disappearances (C29, C30, C55, C58).
3. **Taker-on-arrival.** An order that is marketable when it reaches the venue is a taker: it
   crosses immediately, bypasses the queue, and pays the taker fee (C30 addendum).
4. **Round-trip pricing at executable touches.** Entry and exit are both priced where a
   transaction could actually occur — crossing the touch to take, joining it to make — never
   at the mid. Mark-to-mid overstates edge at the level of a single fill (C60) and again, more
   severely, at the level of a position (C64).
5. **Inventory-aware simulation.** A per-fill number is a diagnostic, not a P&L. Positions are
   tracked with explicit caps, because one-sided flow fills a maker *to* its cap and the
   apparently positive unrealised mark never realises (C64, C66).
6. **Placebo and anti-signal controls.** A signal is compared against its own structure
   destroyed — timing scrambled, labels shuffled — preserving event counts and magnitudes, and
   must beat that distribution; where a direction exists, the inverted signal is a second
   control (C60, C62, C65).
7. **Out-of-sample replication.** Results are replicated on separate days, and where the
   sample itself was selected, on a fresh disjoint sample with the prediction registered in
   version control before the data is examined (C51, C63, C66).
8. **Depth-capped capacity.** Fills are limited to what the touch actually holds, and results
   are reported per unit of capital deployable rather than per event, since an edge that
   exists only at unavailable size is not an edge (C63).
9. **Common-clock validation.** Any cross-venue signal is recomputed on a single clock, since
   inter-venue timestamp offsets manufacture leads that do not exist (C63).
10. **Explicit fee tiers.** P&L is reported across the realistic fee schedule, because a
    strategy alive only at a tier its own volume cannot earn is not alive (C47, C53).

The test of such a discipline is whether it can kill the author's own positive results, and in
this thesis it did so twice: the defended maker of Contribution 64, which survived per-fill
accounting and was reversed within a day by its inventory-aware follow-up, and the
depth-conditioned anchor rule of Contribution 66, which was fitted, extended out of sample,
and abandoned. Both retractions are reported in full. A method that only ever confirms is not
evidence; the value of the surviving results in Part II rests on the same rules having
removed the others.

---

## 8. Summary

This chapter has three outputs that the rest of the thesis depends on. The first is a set of
calibrated parameters and functional forms — §3's κ/A/γ/σ_$ values and §2's two fill-curve
shapes — that Chapter 4 plugs into A-S, GLFT, and their extensions exactly as derived here,
with no further tuning. The second is the engine itself, ending at the point described in §5:
an event-driven backtest with a corrected latency model, a discontinuity-safe price-only fill
condition, an optional L2 queue-clearing fill mode calibrated to LINK's real order-book
depth, and a taker-on-arrival correction for marketable orders. Chapter 4 runs strategies
against the *first* of these fill conditions (price-only — the conventional choice, and the
one implicit in nearly all published backtests of this kind). Chapter 5 re-runs the same
strategies against the *last* — and the gap between the two is the thesis's central result.

The third is the empirical and methodological foundation for Part II: the multi-venue capture of §6,
which supplies real order books, four venues observed at once, counterparty identity, and two
clocks per event; and the discipline of §7, under which every result in Chapters 6–9 —
including the two that were withdrawn — was obtained.
