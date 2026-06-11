# Exp 58 — Honest-RL Overfit Demonstration

**Purpose.** Closes the strongest remaining attack on the queue-priority verdict:
*"You never gave RL a fair chance under the honest fill model — maybe it could find a
profitable policy you missed."* The rebuttal is a **paired overfit test**: same
algorithm, same days, same protocol — only the fill model differs. Give the learner
license to **memorize** (train = eval, few days × many epochs) and ask whether it can
find *any* profitable honest policy. If it cannot find profit even while overfitting,
the edge is not in the data accessible to retail.

## Design

- **Days:** LINK Apr 1–3 2026 (3 days with L2 order-book data). Train = eval = the
  same 3 days — deliberate overfitting; greedy in-sample evaluation.
- **The artifact-vs-honest distinction is load-bearing.** Under `queue_model='l2'`
  the backtest assigns queue depth only to quotes *at or behind* the touch — an
  inside-spread quote gets `queue_ahead=0` and keeps the first-touch artifact
  (C30). So the honest arms use a **63-action `link_honest_xl`** space where every
  quoting leg is ≥ at-touch (≥5 ticks from mid); the control uses the original
  19-action space (which includes inside-spread actions) with `queue_model='none'`.
- **Capacity is controlled by pairing:** the *same* TabularQ that found +$45.94/day
  under the artifact model (Contribution 23) is run under the honest model. A DQN
  arm (continuous 9-dim state incl. L1/L3 OBI) is the "state too coarse" backstop.

| Arm | action space | fill model | agent |
|---|---|---|---|
| A control | 19 (incl. inside) | `none` (free queue priority) | TabularQ |
| B honest | 63 (≥ at-touch) | `l2`, queue_fraction 0.5 | TabularQ |
| C honest (generous) | 63 (≥ at-touch) | `l2`, queue_fraction **0.05** | TabularQ |
| D honest (capacity) | 63 (≥ at-touch) | `l2`, queue_fraction 0.5 | DQN |

## Results (greedy in-sample eval, $/day)

| Arm | best epoch | last-10 mean | final | final fills/day |
|---|---|---|---|---|
| **A control (artifact)** | **+$88.1** | **+$58.0** | +$28.9 | 2,634 |
| B honest (qf=0.5) | +$8.5 | +$0.14 | +$1.2 | 707 |
| C honest (qf=0.05) | +$4.8 | −$0.6 | +$0.4 | 453 |
| D honest DQN | +$4.7 | +$0.7 | +$0.15 | **0** |

## Conclusion

- **The control overfits to profit as expected** — +$58/day stable, +$88 best,
  reproducing the C23/C30 artifact (the policy harvests inside-spread first-touch
  fills, ~2,600/day).
- **No honest arm can overfit to profit.** Across 200 epochs of memorizing 3 days,
  the best *stable* (last-10) honest PnL is +$0.7/day; single-epoch bests top out at
  $4.7–8.5 — pure noise-band chatter, no monotone climb. The control's **worst** eval
  sits far above every honest arm's **best**.
- **Even the generous and high-capacity variants fail.** qf=0.05 (only 5% of
  displayed depth assumed ahead of us — very kind to retail) and the continuous-state
  DQN both stay pinned at zero. The DQN's tell is sharp: it converges to **~0 fills/day**
  — given no honest edge, the value function learns that *not quoting* dominates.
- **Verdict:** RL given the artifact fill model finds +$45–88/day; under the honest
  L2 model **no policy expressible over the observable microstructure state profits** —
  even with 200 epochs of memorising 3 days. The "edge" RL found in Contribution 23 was
  the queue-priority rent, not a learnable strategy.

- **Scope (important — see exp 60).** This is a statement about *causal* policies over
  observable state, **not** "no in-sample profit exists." The RL state (120 buckets /
  9 features) has no future-conditioning, so within any state bucket the favourable and
  adverse fills are aggregated and the learnable optimum is the bucket average — ≈0 under
  the honest model. A strategy that could *see the future* would profit honestly by
  selecting the favourable fills: the perfect-foresight oracle (exp 60) earns ~$24/day
  in-sample vs the honest causal ~$2/day. The honest edge is therefore **zero causally,
  positive with foresight** — and the foresight (or the queue priority that substitutes
  for it) is exactly the retail-inaccessible ingredient. Exp 58 shows the causal null;
  exp 60 supplies the foresight ceiling.

Reproduce:
```
python scripts/train_rl.py --config experiments/58_rl_honest_overfit/config_control_tabular.json
python scripts/train_rl.py --config experiments/58_rl_honest_overfit/config_honest_tabular.json
python scripts/train_rl.py --config experiments/58_rl_honest_overfit/config_honest_tabular_qf05.json
python scripts/train_rl.py --config experiments/58_rl_honest_overfit/config_honest_dqn.json
```
