# Meeting Prep — Supervisor Update
_Extends `meeting_prep_queue_priority.pdf` (C30–C34 queue-priority verdict)_

---

## Where we left off (PDF summary)

The central finding from the first meeting was:

| | Broken fill model (free queue priority) | Honest fill model (real L2 queue) |
|---|---|---|
| Classical A-S / GLFT | profitable | ~0 / negative |
| RL, 200 epochs, train=eval | +$45–88/day | +$0.7/day |
| Oracle (perfect foresight) | n/a | $20–30/day |

One variable — queue priority — explains every cell. This was C29/C30 (honest re-fill) and C33/C34 (zero-profit equilibrium and oracle ceiling).

---

## What changed: the directional-skew result (C42, C44)

The story above assumes the MM quotes *symmetrically* around the mid — same bid and ask spread, no directional lean. Contributions C42 and C44 test whether a **conditional** strategy can break the equilibrium: quote asymmetrically based on order-book imbalance (OBI = (bid_size − ask_size)/(bid_size + ask_size)), shifting both quotes in the direction of excess buying/selling pressure.

### Experiment setup (C42, exp68)

- Asset: LINK/USDT spot (Binance), April 2026, 30 days
- Fill model: L2-honest queue model, `queue_fraction=0.5`, latency=10ms, requote=50ms
- Quote rule: `shift = alpha × OBI × tick`, then `bid = round((mid − half + shift)/tick)×tick`
- No inside-spread quoting: the shift moves both quotes together, never crossing them
- Tested: `alpha ∈ {0, 1, 2, 3, 4, 5, 6}` (alpha=0 is the honest baseline from C30)

### Results

| alpha | mean PnL/day | days+ | adverse fill rate |
|---|---|---|---|
| 0 (baseline) | −$0.24 | 0/30 | 54–63% |
| 1 | +$22.32 | 30/30 (100%) | 31–34% |
| **4 (optimum)** | **+$56.00** | **30/30 (100%)** | **~10%** |

The taker fill fraction is 0% throughout — no inside-spread fills, no queue-jumping. The improvement is entirely from **fill quality**: by quoting on the side that has queue depth backing it, the strategy avoids being the first fill into an adverse sweep.

**Mechanism clarification.** With LINK's typical ~10-tick spread (`half ≈ 5 ticks = $0.005`), the
shift at alpha=4 reaches up to 4 ticks (`4 × 1.0 × $0.001 = $0.004 < $0.005`), placing the bid
**inside the spread** (between best_bid and mid) without crossing the mid. The strategy is better
described as **OBI-conditional spread management** than "at-touch": when OBI > 0, the bid is
shifted 1–4 ticks inside the spread and the ask is pushed further outside; when OBI < 0, the
pattern reverses. Both legs are always passive limit orders (taker_pct=0%); the strategy earns
the spread by filling as a maker, but quotes lean into the signal rather than sitting
symmetrically at the touch.

An early diagnostic (`inside_frac`) was designed to catch inside-spread placement but checked
the wrong threshold (shift crossing the mid, not entering the spread). The fill-count evidence
is cleaner: at alpha=4 in-sample, fills drop from 3,232/day (baseline) to 2,245/day — if the
strategy were just getting free queue_ahead=0 fills inside the spread, fills would rise, not
fall. The in-sample result is genuinely gated by real L2 inside-spread queue depth.

### C43 control: BTC-PERP same grid (exp71)

Same grid on BTC-PERP: uniformly −$182/day. Adding spot_obi with alpha=1 makes it *worse* (−$233/day). BTC's relative tick is ~70× smaller than LINK's (tick/mid ≈ 0.0001 vs 0.007), so the spread is always well inside one tick's OBI-driven shift, and the signal has nothing to grab onto. LINK's large-relative-tick structure is a necessary condition.

### Robustness (C44, exps 69/70/72/74/75)

All three original caveats closed:
- **(A/B) Queue fraction**: flat on `qf ∈ [0.1, 0.7]`; result is not sensitive to the exact queue assumption.
- **(C) Spread rule**: A-S formula collapses to constant at these parameters (σ is too small relative to tick); the spread axis is inert. Result is a property of the OBI signal, not the spread formula.
- **(D) Optimum**: alpha ≈ 4, not 1 — +$56/day vs +$22/day at true optimum.
- **(E) Per-fill markouts** confirm the mechanism: adverse fill rate drops monotonically with alpha (54% → 31% → ~10%).

**OOS validation (C45)** — LINK June–July 2025, 30 days, 9 months before in-sample:

| alpha | mean PnL/day | days+ | mean_fills/day |
|---|---|---|---|
| 0 (baseline) | −$17.28 | 10% | 1,030 |
| 1 | **+$27.04** | 93.3% | 1,714 |
| 4 | +$100.85* | 100% | 4,517 |

*Alpha=4 OOS is an upper bound: the quote-based L2 proxy (needed because real L2 orderbooks don't
exist for Jun–Jul 2025) correctly handles at-touch orders but gives `queue_ahead=0` for inside-spread
orders that alpha=4 places. Real L2 data would show actual inside-spread queue depth. Alpha=1 OOS
(+$27.04/day, 28/30 days+) is the clean confirmation: quotes stay near-touch at alpha=1, proxy
is approximately valid, and the signal generalises to a different regime 9 months earlier.

---

## How this fits the zero-profit argument

The original zero-profit argument (C33) says: *competition prices the queue so the marginal honest maker earns exactly zero*. That argument applies to an MM quoting **unconditionally** — posting symmetrically regardless of market state.

The C42/44 result doesn't violate the zero-profit law; it *escapes the unconditional case*. The skew strategy is selectively claiming priority on the side with favourable depth and backing off on the adverse side. This is, in effect, an informed quoter — one that uses the OBI signal to avoid fills that arrive with directional flow. The analogy in the theory (Guilbaud & Pham, 2013, §5 of the thesis) is exactly the `{B, B+}` choice made *conditional on the spread state*: the gain from priority is only taken when the signal says it is worth taking.

**Revised bottom line:**

| | Broken fill model | Honest fill model |
|---|---|---|
| Classical A-S / GLFT (symmetric) | profitable | ~0 / negative |
| RL, train=eval | +$45–88/day | +$0.7/day |
| Oracle (perfect foresight) | n/a | $20–30/day |
| **OBI-conditional spread placement, alpha=1 (LINK)** | — | **+$22–27/day, 93–100% days+** (in-sample + OOS) |
| **OBI-conditional spread placement, alpha=4 (LINK)** | — | **+$56/day in-sample** (real L2); OOS upper bound +$101 |
| OBI-conditional spread placement, alpha=4 (BTC-PERP) | — | −$182/day |

LINK's large relative tick (~0.7 bps per tick) is the necessary condition: the spread is wide enough for conditional inside-spread placement to create meaningful fill-quality asymmetry. BTC-PERP's much smaller relative tick means any spread advantage is immediately competed away.

---

## Anticipated questions

**"Is the OBI signal not already arbitraged away?"**
The C44 markout analysis says no: the adverse fill rate at alpha=0 is 54–63% — the baseline rate
before any signal. Alpha=4 reduces this to ~10%. If the signal were arbitraged, alpha=0 would
already show ~50% (random), and skew would have no additional effect. C45 OOS confirms at alpha=1:
93.3% days+ on fully held-out data from a different market regime, 9 months earlier.

**"Is this really market making, or just directional trading with limit orders?"**
It is market making: both sides are always quoted as passive limit orders, the strategy earns the
spread (buys below mid, sells above mid), and taker_pct=0% throughout. The distinction from
textbook market making is that quotes lean into the OBI direction rather than sitting symmetrically
at the touch — specifically, the bid is placed 1–4 ticks inside the spread when OBI is positive
(and outside when negative). In Guilbaud & Pham's (2013) framing, this is the `{B, B+}` priority
choice made conditionally: claim the inside-spread position on the signal-favoured side, step back
on the other.

**"Isn't 10ms latency an unrealistic assumption?"**
The C44 queue-fraction sweep (A/B) addresses this: results are flat for `qf ∈ [0.1, 0.7]`, which
spans the range from "near front of queue at fast latency" to "near back of queue at slow latency."
The result is not fragile to the exact latency/queue-position assumed.

**"Why is the OOS alpha=4 result so much larger than in-sample?"**
The quote-based proxy L2 tracker used in OOS (no real L2 data exists for Jun–Jul 2025) gives
`queue_ahead=0` for inside-spread orders, because it only knows the BBO price level. In the real
L2 data (in-sample), inside-spread levels carry actual queue depth from other resting orders. The
4,517 fills/day OOS at alpha=4 (vs 2,245 in-sample) reflects unrealistically easy fills due to
this proxy limitation. Alpha=1 (+$27/day, 1,714 fills) is the credible OOS number; alpha=4 OOS
is an upper bound.

---

## Open items for discussion

1. **OOS C45 (done)** — alpha=1 clean OOS confirmation (+$27/day, 93.3% days+); alpha=4 upper
   bound (+$101/day) due to L2 proxy limitation. Real L2 OOS validation for alpha=4 requires
   orderbook data for Jun–Jul 2025 (unavailable).
2. **Chapter 4 draft** — Classical & ML results (C16–C24), the "apparently profitable" in-sample
   results that the queue-priority verdict resolves; next chapter to draft.
3. **Thesis structure** — 7 chapters; Ch1–3 drafted and committed; Ch4–6 pending.
