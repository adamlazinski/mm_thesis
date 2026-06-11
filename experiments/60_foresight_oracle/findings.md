# Exp 60 — Perfect-Foresight Oracle: the in-sample upper bound on honest MM

**Purpose.** Exp 58 showed no *causal* RL policy over observable microstructure state
profits under the honest L2-queue fill model. That is **not** the same as "no in-sample
profit exists." A strategy that could see the future would profit even honestly, by
selecting only the favourable fills out of a zero-mean fill distribution. This experiment
quantifies that gap directly on real LINK Apr 1–3 2026 L2 data, answering: *how much would
perfect 10 s foresight be worth?*

## Method

1. Run an honest touch-quoter (post at best_bid / best_ask) through the real engine under
   `queue_model='l2'`, `queue_fraction=0.5`, 0.1 s latency — the fills a realistic honest
   MM actually gets (3,595/day).
2. For each fill, compute the forward markout at horizon H:
   `bid fill → mid(t+H) − price`, `ask fill → price − mid(t+H)`; PnL = quantity × markout.
3. Compare two sums:
   - **Σ all fills** = the honest MM's markout PnL (no foresight; the C30 at-touch cell).
   - **Σ positive fills only** = the perfect-foresight ceiling (skip every adverse fill).

## Results (mean per day, 3 days)

| Horizon | honest PnL/day (Σ all) | oracle ceiling/day (Σ positive) | % fills positive | mean markout (ticks) |
|---|---|---|---|---|
| 1 s | $0.60 | **$19.76** | 39.7% | −1.04 |
| 5 s | $2.18 | **$22.41** | 45.6% | −0.47 |
| 10 s | $2.03 | **$24.07** | 46.3% | −0.48 |
| 30 s | $4.06 | **$30.03** | 48.9% | −0.13 |

## Reading it

- **In-sample honest profit exists — with foresight.** Keeping only the ~40–49% of fills
  with positive markout yields ~$20–30/day, ~10× the honest causal ~$2/day. The honest
  causal figure matches the C30 at-touch cell (≈breakeven, mean markout negative ~−0.5
  ticks = the at-touch adverse selection).
- **The RL was representation-limited, not wrong.** A TabularQ over 120 microstructure
  buckets (or a 9-feature DQN) has no future-conditioning, so within any state bucket the
  good and adverse fills are aggregated and the learnable optimum is the bucket *average* —
  ≈0 honestly. Exp 58's null is "no causal policy over observable state profits," not "no
  in-sample edge exists." Exp 60 supplies the missing half.
- **Foresight < queue artifact.** The ~$24/day foresight ceiling is *below* the
  queue-priority artifact (+$45–58/day, exp 58 control). The artifact wins on volume
  (2,600–7,000 inside-spread fills with free priority); foresight wins on selection within
  the thinner honest stream. This ceiling is conservative — it only keeps/drops the
  touch-quoter's existing fills, not where/when to quote.

## Conclusion

The honest edge is **zero causally, ≈$24/day with perfect 10 s foresight.** Both halves are
the thesis: the foresight (knowing which fills are adverse) — or the queue priority that
substitutes for it by letting uninformed flow fill you first — is the retail-inaccessible
ingredient. When the future is unknown (live, causal) the honest MM is at breakeven; the
profit lives entirely in information/priority retail does not have.

Reproduce: `python experiments/60_foresight_oracle/foresight_oracle.py`
