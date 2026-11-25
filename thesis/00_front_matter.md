# Front Matter

## Abstract

Classical market-making theory — Avellaneda–Stoikov and the Guéant–Lehalle–Fernández-Tapia
ergodic refinement — prescribes an optimal half-spread and an inventory-dependent reservation
price, and it is the standard apparatus for automated liquidity provision. This thesis asks
whether that apparatus earns anything for a participant without co-location, exchange
membership or a volume-tier fee schedule, on venues where such a participant can actually
trade: lit cryptocurrency order books.

The answer is that across every book, sample and configuration tested, it earns a quantity
**indistinguishable from zero at the precision these samples support**, and negative before
fees at the horizons on which a maker turns inventory. The thesis rests on two tiers of data —
346 days
of purchased Binance tick history and an original four-venue live capture spanning Binance,
Coinbase, Hyperliquid and Deribit — every apparently profitable configuration decomposes into
one of five accounting illusions: queue priority the simulator granted but the exchange would
not, prices strictly inside a one-tick spread that the venue's own grid forbids, valuation at
the mid rather than at an executable touch, fee tiers unreachable at the strategy's volume, and
selection on the fills a maker would not have received. What remains after all five are removed
is probed four ways — a model-free markout on the tape, a speed experiment at the co-location
limit, conditioning on every observable state variable, and counterparty identity resolved to
the wallet on a transparent venue — and all four terminate at zero rather than below it, which
is what an enforced equilibrium looks like from the inside rather than what a difficult market
looks like. That the residue is *pinned* rather than merely small is the thesis's
interpretation rather than its measurement, and is held to a lower standard: it rests on the
four probes landing together, on a synthetic control in which the engine reproduces the
scaling theory predicts where the answer is known, and on a reading that unifies the
spread-axis and queue-axis regimes into one Glosten–Milgrom condition. The four probes share data, code paths and a market regime, so they are not
four independent replications, and no equivalence interval or power calculation is offered:
failing to find a positive result is not the same as demonstrating equality to zero.

Three structural positions survive that argument, and the second half of the thesis is about
what distinguishes them from a signal. All three rest on short windows — two days, five days,
thirty-six hours — and are offered as **exploratory evidence locating the boundary** of the
equilibrium rather than as established strategies. Each is compensation for bearing a risk rather than a
reward for prediction: a cross-venue dislocation taker that rents a slow venue's clock and is
bounded by threshold, fee tier and the few thousand dollars resting at the touch; an immediacy
premium in Hyperliquid's tail books, where two or three makers quote and a round trip clears
base fees on four of six instruments; and a funding-basis carry whose cash flow is contractual
and whose risk is the basis rather than the funding. A single law organises them: the
adverse-selection horizon — how long a maker's edge survives — tracks the venue's repricing
clock across nearly three orders of magnitude, from 15 ms on Binance BTC to beyond ten seconds
on a book with three makers. A pre-registered replication on disjoint instruments, and a bridge
control in which the *same* instrument is observed two months apart as the tail tightens from 56
to 14 basis points of spread, establish that the premium's magnitude is priced by competition
rather than produced by technique.

The methodological contribution is a ten-rule honest-accounting discipline, each rule
introduced because its absence produced a false positive in this project. Its credibility rests
on having removed the author's own results: a directional-skew strategy that survived robustness
sweeps, a 182-day fresh out-of-sample window and a reinforcement-learning variant before falling
to a tick-size validation outside the backtest entirely; a defended-maker configuration reversed
within a day by its own inventory-aware follow-up; and a fitted anchor rule abandoned out of
sample. Five further errors of the author's analysis are documented in place rather than
silently corrected, including one — a mis-transcribed GLFT closed form — whose repair made the
chapter's conclusion stronger, since the correctly implemented policy quotes to a markout
indistinguishable from zero.

*Keywords:* market microstructure, market making, Avellaneda–Stoikov, GLFT, adverse selection,
Glosten–Milgrom, queue priority, tick size, cryptocurrency, Hyperliquid, backtest overfitting.


## How to read this thesis

Ten chapters in two co-equal parts, with a three-chapter foundation. `structure.md` carries the reading order and what each chapter holds. Three files support them and are referenced throughout rather than read in sequence:

- **`contributions.md`** — the C1–C71 log, the source of truth for every number. Each entry states its experiment, its result and its scope; corrections are appended in place and dated rather than overwritten, so the record of what was believed when is intact.
- **`hypotheses.md`** — what was predicted against what the data said, including the retractions, marked `⊘`.
- **`intervals.md`** — 95% bootstrap intervals for every headline quantity.
- **`references.md`** — the bibliography, grouped by theme.
- **`provenance.md`** — which commit produced each experiment's results, and which engine corrections that commit post-dates.

Every figure is embedded at the point of use and referenced as **Figure N**. Every number is traceable to a committed experiment JSON in `experiments/`, and `scripts/verify_contributions.py` checks the log against the repository.


## Reproducibility

Every derived artefact in `thesis/` is generated from the committed experiment results by one
command:

```
bash scripts/build_thesis.sh
```

It rebuilds the nine figures, the interval table and the provenance table, then runs the
contribution verifier and the cross-reference and figure-embedding checks. The build is
deterministic — the bootstrap seed is fixed and figure PDFs pin `SOURCE_DATE_EPOCH`, so a clean
`git status` afterwards is itself the reproducibility check.

What is and is not in the repository: all experiment code, all results JSONs, the processed
parquet files for the live capture, and the analysis notebooks. The purchased CoinAPI tick
history (19.75 GB) is licensed and is not redistributed, so Part I's backtests can be inspected
and audited but not re-run without that data; Part II rests entirely on the original capture,
which is committed.

A caveat the raw-first capture design does not remove: the collector could still have dropped,
duplicated, reordered or mis-timestamped messages, and writing raw frames first makes that
detectable rather than impossible. The integrity table below is what detection looks like — the
zero crossed books across all 89 instrument-day records is the strongest single check that the
L2 reconstruction is sound, and the Binance figures show what the reconstruction cost in
discarded pre-sync messages and re-anchors.

## Notation

Symbols are used consistently across chapters. Where the literature is ambiguous — κ above all —
this thesis fixes a meaning and says so at the point of first use.

| symbol | meaning | units | fixed where |
|---|---|---|---|
| δ | half-spread: distance of a quote from the fair-value anchor | ticks, or $ where stated | Ch2 §2 |
| δ\* | the model's optimal half-spread | ticks | Ch2 §2–3 |
| δ_be | breakeven half-spread: the δ at which a fixed quoter earns zero | ticks | Ch5 §7 |
| κ | decay rate of fill intensity in distance from the touch, `λ(δ) = A·e^(−κδ)` | 1/tick | Ch2 §4, Ch3 §3 |
| A | fill-intensity scale: arrival rate at δ = 0 | fills/second | Ch2 §4 |
| A_liq, A_mom | the two components of the measured fill curve — liquidity-driven decay and the momentum floor | fills/second | Ch3 §2, C6 |
| γ | risk-aversion / inventory-penalty coefficient | 1/$ | Ch2 §2 |
| σ | volatility of the mid, as a log return | per √second | Ch3 §3 |
| σ_$ | **dollar** volatility, `σ × mid` — the quantity A-S and GLFT actually require | $/√second | Ch3 §3 |
| q | inventory, signed | units of base asset | Ch2 §2 |
| T | terminal time in the finite-horizon A-S formulation | seconds | Ch2 §2 |
| λ(δ) | fill intensity at half-spread δ | fills/second | Ch2 §4 |
| M | number of competing liquidity suppliers (Grossman–Miller) | count | Ch2 §7 |
| qf | `queue_fraction`: the engine multiplies visible depth ahead by this. **qf = 0 is the front of the queue, qf = 1 is behind the whole visible book** | fraction | Ch3 §4, Ch6 §5 |
| h | markout horizon after a fill | seconds | Ch3 §8, Ch6 §4 |

Three conventions are worth stating once because they cause the most confusion:

- **κ is per tick, not per dollar**, and this thesis separates it from A rather than fitting a
  single blended decay (Contribution 4). Both are estimated from data, never taken from
  equity-literature defaults — which, applied to crypto's much smaller σ², are wrong by orders
  of magnitude (Contribution 26).
- **Spreads quoted in basis points are full quote-to-quote widths**, not half-spreads. The
  `min_spread_bps` parameter is applied as `mid × bps / 20000` per side, so 11.1 bps at LINK's
  ~$9 is one $0.01 tick. Earlier drafts labelled these half-spreads; Chapter 5 §3 records the
  correction.
- **Latency is 10 ms by default** throughout, which a standard cloud instance in the venue's
  region achieves without co-location. Where a result is reported at 1 ms it says so.


## Data Inventory

Two tiers. **Purchased tick history** from CoinAPI, used for all of Part I's backtests, covering Binance spot and perpetual markets from May 2025 to April 2026. **An original live capture** written for this thesis, running four venues' public websocket feeds to disk with per-day integrity manifests, used for Chapter 6 onward. Only the capture carries exchange timestamps at full resolution on every message together with a clock-validation record, which is why Part II's venue-clock claims rest on it and not on the purchased tier.


### Tier 1 — purchased history (CoinAPI; Part I)

| venue | instrument | window | days | channels | size |
|---|---|---|---|---|---|
| Binance spot | BTC/USDT | 2025-05-13 – 2026-04-15 | 44 | quotes, trades, L2 books | 6.05 GB |
| Binance spot | LINK/USDT | 2025-06-11 – 2026-04-30 | 242 | quotes, trades, L2 books | 7.62 GB |
| Binance perp | BTCUSDT | 2026-04-01 – 2026-04-30 | 30 | quotes, trades, L2 books | 4.95 GB |
| Binance perp | LINKUSDT | 2026-04-01 – 2026-04-30 | 30 | quotes, trades, L2 books | 1.13 GB |

**346 instrument-days, 19.75 GB.** All timestamps are exchange timestamps (`time_exchange`), at the vendor's 100 ms resolution. The period contains no market-wide stress event.


### Tier 2 — original live capture (Part II)

| venue | instrument | window | days | quotes | trades | L2 books |
|---|---|---|---|---|---|---|
| Binance spot | BTC | 2026-07-10 – 2026-07-12 | 3 | 1,322,902 | 5,371,871 | 2,244,870 |
| Binance perp | BTC_PERP | 2026-07-10 – 2026-07-16 | 5 | 3,230,654 | 10,839,857 | 3,898,224 |
| Coinbase | CB_BTC | 2026-07-15 – 2026-07-17 | 3 | 1,148,492 | 1,139,978 | — |
| Coinbase | CB_BTC_PERP | 2026-07-15 – 2026-07-16 | 2 | 178,050 | 654,243 | — |
| Coinbase | CB_LINK | 2026-07-15 – 2026-07-17 | 3 | 434,698 | 65,777 | — |
| Coinbase | CB_LINK_PERP | 2026-07-15 – 2026-07-16 | 2 | 50,155 | 5,046 | — |
| Hyperliquid | HL_ACE | 2026-08-05 – 2026-08-08 | 4 | 1,405,349 | 116,861 | — |
| Hyperliquid | HL_BTC | 2026-07-15 – 2026-07-17 | 3 | 1,256,095 | 579,306 | — |
| Hyperliquid | HL_CELO | 2026-07-17 – 2026-07-21 | 5 | 358,895 | 10,641 | — |
| Hyperliquid | HL_EIGEN | 2026-07-17 – 2026-07-21 | 5 | 1,040,579 | 23,375 | — |
| Hyperliquid | HL_ETH | 2026-07-15 – 2026-07-16 | 2 | 961,391 | 317,249 | — |
| Hyperliquid | HL_GRASS | 2026-08-05 – 2026-08-08 | 4 | 435,658 | 23,294 | — |
| Hyperliquid | HL_HMSTR | 2026-07-17 – 2026-07-21 | 5 | 145,901 | 9,534 | — |
| Hyperliquid | HL_HYPE | 2026-07-15 – 2026-07-16 | 2 | 750,696 | 468,638 | — |
| Hyperliquid | HL_LINK | 2026-07-15 – 2026-07-17 | 3 | 459,052 | 26,520 | — |
| Hyperliquid | HL_REZ | 2026-08-05 – 2026-08-08 | 4 | 79,379 | 8,605 | — |
| Hyperliquid | HL_SAGA | 2026-08-05 – 2026-08-08 | 4 | 993,519 | 12,490 | — |
| Hyperliquid | HL_SOL | 2026-07-15 – 2026-07-16 | 2 | 662,955 | 120,688 | — |
| Hyperliquid | HL_TURBO | 2026-08-05 – 2026-08-08 | 4 | 53,897 | 9,822 | — |
| Hyperliquid | HL_USUAL | 2026-07-17 – 2026-08-08 | 9 | 2,457,108 | 19,741 | — |
| Hyperliquid | HL_VINE | 2026-07-17 – 2026-07-21 | 5 | 196,594 | 13,622 | — |
| Hyperliquid | HL_W | 2026-08-05 – 2026-08-08 | 4 | 681,724 | 9,482 | — |
| Hyperliquid | HL_ZORA | 2026-07-17 – 2026-07-21 | 5 | 247,750 | 12,197 | — |
| Binance spot | LINK | 2026-07-10 – 2026-07-16 | 5 | 657,883 | 362,138 | 1,515,585 |
| Binance perp | LINK_PERP | 2026-07-10 – 2026-07-16 | 5 | 961,506 | 787,753 | 2,058,274 |
| | **25 instruments** | 2026-07-10 – 2026-08-08 | **98** | **20,170,882** | **21,008,728** | **9,716,953** |

**98 instrument-days, 50,896,563 messages.** Plus per-instrument **funding-rate series** for all seventeen Hyperliquid perpetuals in the capture set (Chapter 9), and **Deribit BTC options chains** over 2026-08-18 – 2026-08-25, eight days of hourly snapshots, for the options negative result.

**Clock.** Every row carries both the venue's own exchange timestamp and the local receive time. All cross-venue work uses `time_exchange`; Chapter 7 §3 shows why, and reports the same analysis on the receive clock as a control. The purchased tier's 100 ms resolution is what made Contribution 36's θ = 0 finding a resolution artefact, corrected in Contribution 56 once the capture provided finer stamps.

### Capture integrity

Each capture day writes a manifest (`data/live/processed/integrity_*.json`). Aggregated over
the whole capture:

| | Binance | Coinbase | Hyperliquid |
|---|---|---|---|
| instrument-day records | 15 | 6 | 68 |
| crossed books emitted | **0** | **0** | **0** |
| stream gaps | — | 108 (≤25/day) | 1,180 (≤24/day) |
| book re-anchors | 47 (≤5/day) | 0 | 0 |
| sequence-sync violations | 34 (≤4/day) | 0 | 0 |
| messages dropped pre-sync | 166,373 | 0 | 0 |
| snapshot best-price mismatches | 183 / 1,941 checks (9.4%) | — | — |
| receive − exchange, median | **+40.9 ms** | **−14.4 ms** | — |
| receive − exchange, p99 | +175 ms | — | — |

Four things in that table bear on results and are stated where they do.

**No crossed book was ever emitted**, on any venue, on any day — the single strongest check that
the L2 reconstruction is sound, since a crossed book is what a mis-ordered or mis-applied diff
produces.

**Binance's 166,373 pre-sync drops** are messages arriving before the first snapshot anchors the
diff stream; they are discarded by construction rather than lost, and the re-anchor count (47)
is the number of times the stream had to be re-seeded. The 9.4% snapshot best-price mismatch
rate is a bound on reconstruction error at the touch, measured by comparing the reconstructed
book against an independent REST snapshot every ~10 minutes.

**Coinbase's receive-minus-exchange median is negative (−14.4 ms).** The venue's own timestamps
run *ahead* of the capture host's clock. This is a venue clock offset, not a measurement of
latency, and it is the direct reason Chapter 7 §3 treats the cross-venue clock as a problem to
be solved rather than a given: a lead-lag estimate on raw exchange timestamps inherits every
venue's offset. Chapter 7 reports its headline on `time_exchange` and repeats it on the receive
clock as a control.

**Hyperliquid's 1,180 stream gaps** are spread over 68 instrument-days, at most 24 on any one
day, and the backtest's gap policy (below) governs how each is handled.

**Gap handling.** Each capture day writes an integrity manifest recording reconnects, sequence gaps and message counts per channel (`data/live/processed/integrity_*.json`). In the backtest, gaps longer than 30 seconds close out inventory at the last mid and reset rolling state; gaps of 2–30 seconds cancel resting orders and pause requoting. Chapter 3 §6 reports the observed statistics.

**Ticks.** LINK's tick differs between the tiers and **both are correct for their period**: the purchased history is $0.01 at ~$9 (~11 bps/tick), and Binance cut it to $0.001 between April and July 2026 as the price fell to ~$8 (~1.25 bps/tick). No tick-denominated quantity crosses that boundary. Chapter 3 §6 states the reconciliation; Contribution 54 is the correction that made it necessary.

**Coverage is uneven by design.** The capture was steered by what each chapter needed: three dense days of Binance BTC and LINK for the markout instruments, three days of four venues simultaneously for the lead-lag matrix, five days of six screened tail books for the immediacy premium, and a disjoint four-day window a month later for the pre-registered replication. HL_USUAL spans both tail windows because it is the bridge control.

