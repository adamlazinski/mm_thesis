# Exp 62 — Engine-Fix Reruns (marketable-on-arrival / taker conversion)

Regenerates the latency-sensitive maker results on the **corrected engine** (commit
`24a687f`): an order that becomes active into a market already through its limit is a
**taker** that crosses at the touch and bypasses the L2 queue, rather than a passive
maker filled at its stale limit. The old engine suppressed these latency-adverse
crossings (it buried them in the same-side queue), so it was systematically *too kind*
to the honest market maker.

Taker fee = **4.5 bps** (Binance VIP0) on marketable-on-arrival fills; maker fee 0.

## 1. Honest at-touch LINK MM — the central C29/C30 update (`honest_mm.py`)

TouchMM (quote at the touch), `queue_model='l2'`, `queue_fraction=0.5`, latency 0.1s,
all 30 April 2026 LINK days with L2 data.

| | mean PnL/day | days positive |
|---|---|---|
| fee = 0 | +$0.87 | 53% |
| **fee = 4.5 bps** | **−$7.93** | **0 / 30** |

The old engine reported the honest at-touch regime as ≈breakeven noise floor (~$1–2/day,
mixed sign). The corrected engine + realistic taker fee gives **−$7.93/day, negative on
every one of 30 days.** ~10–15% of fills are marketable-on-arrival takers (1s markout
≈ −4 ticks — toxic), and the taker fee on them is a hard, unavoidable cost. So the honest
MM doesn't merely fail to beat the floor — it **reliably loses** once latency adverse
selection and fees are modeled.

## 2. Foresight oracle — corrected (`../60_foresight_oracle/`)

Same touch quoter through the corrected engine: fills/day **3,595 → 5,768** (the added
takers). Honest causal markout (fee=0) flips negative; foresight ceiling rises:

| Horizon | honest causal (was → now) | oracle ceiling (was → now) |
|---|---|---|
| 1 s | +$0.60 → **−$9.78** | $19.76 → $28.62 |
| 10 s | +$2.03 → **−$2.87** | $24.07 → $37.24 |
| 30 s | +$4.06 → +$1.35 | $30.03 → $47.24 |

Honest causal is now negative even **before** fees; the causal-vs-foresight gap widens.
The C34 reading is unchanged and sharpened: zero (now negative) causally, positive only
with foresight/queue priority.

## 3. RL re-eval on the corrected engine (`eval_rl_corrected.py`)

Existing exp-58 greedy policies (epoch-200 tabular / 060 DQN) re-evaluated on the
corrected engine, honest arms +4.5 bps, control idealized (fee 0), same Apr 1–3 days:

| arm | old engine | corrected engine |
|---|---|---|
| control (artifact) | +$28.93 | +$25.90 |
| honest_tabular | +$1.24 | −$0.12 |
| honest_qf05 | +$0.41 | +$0.31 |
| honest_dqn | +$0.15 | +$0.15 |

**Control artifact intact** (+$26): inside-spread quotes don't cross the ask, so they're
never marketable-on-arrival → no taker conversion. **Honest arms stay ≈0/negative.** The
honest RL policies avoid the toxic-taker bleed by *halting / quoting wide* (the DQN halts,
~0 fills) — they dodge the loss by not trading, and still can't profit. The aggressive
at-touch quoter (§1) instead eats the toxic takers and loses −$8/day. Either way: **no
honest profit.** The RL conclusion is unchanged a fortiori.

## Verdict

The engine correction **strengthens the queue-priority / honest-breakeven verdict** on
every axis. Honest market making is not "≈breakeven" — once latency adverse selection
(getting crossed during your own latency) and the taker fee are modeled, it is reliably
**money-losing**, while the inside-spread artifact (queue-priority rent) is unaffected.
The only positive territory remains gated by queue priority or foresight, neither
retail-accessible.

Reproduce:
```
python experiments/62_engine_fix_reruns/honest_mm.py
python experiments/60_foresight_oracle/foresight_oracle.py
python experiments/62_engine_fix_reruns/eval_rl_corrected.py
```
