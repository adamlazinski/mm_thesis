# Front Matter

## Abstract

Classical market-making theory — Avellaneda–Stoikov and the Guéant–Lehalle–Fernández-Tapia
ergodic refinement — prescribes an optimal half-spread and an inventory-dependent reservation
price, and it is the standard apparatus for automated liquidity provision. This thesis asks
whether that apparatus earns anything for a participant without co-location, exchange
membership or a volume-tier fee schedule, on venues where such a participant can actually
trade: lit cryptocurrency order books.

The answer is that it earns **exactly zero**, and the precision of that word is the thesis's
central claim. It rests on two tiers of data — 346 days
of purchased Binance tick history and an original four-venue live capture spanning Binance,
Coinbase, Hyperliquid and Deribit — every apparently profitable configuration decomposes into
one of five accounting illusions: queue priority the simulator granted but the exchange would
not, prices strictly inside a one-tick spread that the venue's own grid forbids, valuation at
the mid rather than at an executable touch, fee tiers unreachable at the strategy's volume, and
selection on the fills a maker would not have received. What remains after all five are removed
is measured four mutually independent ways — a model-free markout on the tape, a speed
experiment at the co-location limit, conditioning on every observable state variable, and
counterparty identity resolved to the wallet on a transparent venue — and all four terminate at
zero rather than below it, which is what an enforced equilibrium looks like from the inside
rather than what a difficult market looks like. The zero is also *derived* rather than merely
observed: the breakeven half-spread holds a constant ratio of about 76 to dollar volatility
across a tenfold range of σ, which unifies the spread-axis and queue-axis regimes into one
Glosten–Milgrom condition.

Three structural positions survive that argument, and the second half of the thesis is about
what distinguishes them from a signal. Each is compensation for bearing a risk rather than a
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

- **`contributions.md`** — the C1–C68 log, the source of truth for every number. Each entry states its experiment, its result and its scope; corrections are appended in place and dated rather than overwritten, so the record of what was believed when is intact.
- **`hypotheses.md`** — what was predicted against what the data said, including the retractions, marked `⊘`.
- **`intervals.md`** — 95% bootstrap intervals for every headline quantity.
- **`references.md`** — the bibliography, grouped by theme.

Every figure is embedded at the point of use and referenced as **Figure N**. Every number is traceable to a committed experiment JSON in `experiments/`, and `scripts/verify_contributions.py` checks the log against the repository.


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

**Gaps.** Each capture day writes an integrity manifest recording reconnects, sequence gaps and message counts per channel (`data/live/processed/integrity_*.json`). In the backtest, gaps longer than 30 seconds close out inventory at the last mid and reset rolling state; gaps of 2–30 seconds cancel resting orders and pause requoting. Chapter 3 §6 reports the observed statistics.

**Ticks.** LINK's tick differs between the tiers and **both are correct for their period**: the purchased history is $0.01 at ~$9 (~11 bps/tick), and Binance cut it to $0.001 between April and July 2026 as the price fell to ~$8 (~1.25 bps/tick). No tick-denominated quantity crosses that boundary. Chapter 3 §6 states the reconciliation; Contribution 54 is the correction that made it necessary.

**Coverage is uneven by design.** The capture was steered by what each chapter needed: three dense days of Binance BTC and LINK for the markout instruments, three days of four venues simultaneously for the lead-lag matrix, five days of six screened tail books for the immediacy premium, and a disjoint four-day window a month later for the pre-registered replication. HL_USUAL spans both tail windows because it is the bridge control.

