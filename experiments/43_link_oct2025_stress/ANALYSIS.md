# GLFT vs A-S on LINK/USDT — Full Comparative Analysis
*Periods: Jun–Jul 2025, Apr 2026, Oct 2025*

---

## The Core Kappa Problem

GLFT's spread and skew formulas are built on one assumption: fill intensity decays exponentially with spread distance, `λ(δ) = A × exp(-κ × δ)`. The two parameters mean different things:

- **A** — baseline arrival rate (trades per second reaching your quote)
- **κ** — fill sensitivity (how fast fill probability decays per tick away from mid)

On LINK, this assumption breaks immediately. LINK has a **permanent 10-tick spread** with a step-function fill curve:

| Spread distance | Fill rate |
|---|---|
| Inside natural spread (< 5 ticks) | 17–37% |
| At or outside natural spread (≥ 5 ticks) | 1–14%, adversely selected |

There is no smooth exponential decay — there's a cliff at 5 ticks. Fitting an exponential to this gives κ→0 (essentially flat curve), which makes the GLFT optimal spread formula diverge. The model is theoretically inapplicable on LINK.

### Two calibration approaches tried

**Exp 33/34 — live kappa estimation (`kappa_from_stats=True`):**
KappaEstimator estimates A_hat in real time from fills. On LINK's sparse flow (~0.37 trades/s median), A_hat fluctuates wildly. When A_hat drops near zero (33% of quoting steps), the GLFT inventory risk term `σ²γ/(2Aκ)` explodes → spread blows out to 10–18 bps → strategy misses fills. Search found γ=25,809, κ=5,166/$ which produced +$60/day IS but was unstable.

**Exp 42 — fixed A (`kappa_from_stats=False`, A=0.5 fixed):**
Fixed A at the calibrated median (0.37–1.0 trades/s range → A=0.5). This stabilised the denominator. But the search converged to κ=1,088/tick with γ=219 — a κ/γ ratio of ~5, which makes the term `(1 + κ/γ)^(1+κ/γ) = 5.97^5.97 ≈ 43,000`. The spread formula blows out to ~300 bps. The strategy degenerates to wide patient limit orders at the min_spread floor (8.86 bps), essentially quoting outside normal conditions and only filling when price makes a large move.

**Conclusion on kappa:** Both approaches fail on LINK because the exponential assumption doesn't hold. Any calibrated κ either produces a degenerate strategy or an unstable one.

---

## Results Across Periods

### June–July 2025 (IS: Jun 11–27, OOS: Jun 28–Jul 10)

Calm, mean-reverting period. LINK at ~$13–15. Both strategies searched/calibrated here.

| Strategy | IS mean/day | OOS mean/day | OOS win rate | OOS Sharpe |
|---|---|---|---|---|
| **A-S γ≈0** | +$158 | **+$149** | **13/13** | **57.7** |
| GLFT (exp 33/34, live A_hat) | +$60 | +$89 | 13/13 | 27.4 |

**A-S beats GLFT by 69% OOS.** The GLFT formula's dynamic spread widens during low-A_hat periods, costing ~2,250 fills/day. The A-S control experiment (exp 37) with identical inventory/limit/spread but γ≈0 confirmed the GLFT formula itself is what hurts — not the parameter regime.

- Avg spread: A-S 7.4 bps vs GLFT 11.9 bps — extra spread = fewer fills = lower PnL
- Adverse fills: A-S 24.6% vs GLFT 26.8% — both far below 50%, mean-reversion edge holds for both

---

### April 2026 (full month, zero-shot transfer)

LINK fell to ~$9 (−31% from Jun-Jul). 9 months after IS calibration. No recalibration for either strategy.

| Strategy | Period | Mean/day | Win rate | Sharpe |
|---|---|---|---|---|
| **A-S γ≈0 (zero-shot)** | Apr 1–30 | **+$43.78** | **30/30** | **38.7** |
| GLFT proper (IS search Apr 1–15) | Apr 1–15 IS | +$41.36 | 15/15 | 1.7 |
| GLFT proper (OOS Apr 16–30) | Apr 16–30 | **+$72.65** | **15/15** | **3.7** |

Interesting reversal: GLFT OOS beats A-S on the same OOS window (+$72.65 vs ~$52.75 for A-S on Apr 16–30). But this is partly structural: the GLFT winner quotes at 84.67 bps avg spread — much wider than the natural spread. It fills only 4,711 times/day vs A-S's 7,000, but earns more per fill since fills only occur when price makes a large move. This is more like a wide patient limit order than a proper GLFT strategy.

Lower absolute PnL vs Jun-Jul on both strategies is fully explained by price: same tick count, ~31% lower notional per fill at $9.

---

### October 2025 (stress period)

LINK at $17–22, trending month (−23% Oct 1→31). Large directional days: Oct 1 +6%, Oct 6 +6.2%, Oct 21 −5.6%.

| Strategy | Mean/day | Win rate | Total | Worst day | Sharpe | Avg fills/day |
|---|---|---|---|---|---|---|
| **A-S γ≈0** | −$12.66 | 5/31 | −$392 | **−$52** | −0.35 | 1,112 |
| **GLFT proper** | −$7.68 | **15/31** | **−$238** | −$365 | −0.09 | 203 |

Both strategies fail — October is a loss-making period regardless. But the failure modes are completely different.

**A-S failure mode:** At $22, the 6.44 bps floor maps to ~14 ticks — outside the natural spread. Fill rate collapsed to 2.5% (vs 13% in April). Strategy barely trades, accumulates small losses from the few fills it does get. Daily loss limit ($25) provides bounded tail risk — worst day only −$52.

**GLFT failure mode:** Wide spread (179 bps avg) means it sits out most of the time. But when a large price move does fill it, the fill is deeply adverse — a 179 bps move to reach the quote is a strongly directional move, and price continues directionally afterwards. The daily loss limit is useless against a single fill that causes an instant −$50+ mark-to-market. Oct 10: −$365 in a single day.

**The key tradeoff:**

| | A-S | GLFT |
|---|---|---|
| Loss frequency | High (26/31 days) | Moderate (16/31 days) |
| Loss severity | Bounded (worst −$52) | Catastrophic (worst −$365) |
| Loss mechanism | Many small adverse fills | Rare but enormous directional fills |
| Loss limit effectiveness | Works well | Largely ineffective |

---

## Synthesis

**Why A-S wins in calm periods:** Inside-spread quoting (3.86 ticks at $13, ~5.8 ticks at $9) captures all taker flow and forces inventory cycling through the hard cap. The GLFT formula adds noise — its dynamic spread widens during sparse flow windows and costs fills without providing better risk management.

**Why GLFT is less bad in stressed periods:** The wide spread passively reduces participation in trending markets. But this is accidental, not by design — the formula blows out to 179 bps not because it's detecting stress, but because the calibration produces degenerate parameters on LINK's step-function fill curve.

**The thesis point:** Neither strategy handles regime shifts well. A-S fails in October because the bps floor becomes price-level-dependent and the inside-spread mechanism breaks. GLFT fails because its tail risk is unbounded on directional days. The clean motivation for RL: an agent trained with a reward signal that includes losses can learn *when not to quote* — something neither classical model expresses.

---

## Experiment Reference

| Exp | Description | Key result |
|---|---|---|
| 29 | LINK at-spread baseline | Step-function fill curve documented |
| 30 | A-S search Jun IS | +$41.75/day IS winner found |
| 33/34 | GLFT calibrated + OOS | +$60/day IS, +$89/day OOS — unstable A_hat |
| 37 | GLFT vs A-S control | A-S γ≈0 beats GLFT by 69% OOS |
| 40 | A-S zero-shot Apr 2026 | +$43.78/day, 30/30 |
| 42 | GLFT fixed-A Apr IS/OOS | +$41.36 IS, +$72.65 OOS (degenerate wide-spread) |
| 43 | A-S vs GLFT Oct 2025 | Both fail: A-S bounded losses, GLFT catastrophic tail |
