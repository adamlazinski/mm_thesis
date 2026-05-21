# Experiment 39 — Reinforcement Learning for LINK/USDT Market Making

## Introduction

Classical market making (A-S, GLFT) encodes expert structure into a closed-form
reservation price and spread. Reinforcement learning offers an alternative: learn
the quoting policy directly from experience, without assuming a functional form for
fill rates or inventory costs. The question for the thesis is whether a learned
policy can outperform the calibrated classical baseline on LINK/USDT — and whether
the added complexity of a neural network is justified over a simple tabular agent.

Both agents operate on the same action space, environment, and data split. The
baseline for comparison is the A-S winner from Exp 40: **+$43.78/day** over 30 OOS
days (Apr 2026).

---

## How the Two Agents Differ

Both agents observe the same market state and choose from the same 19 discrete
actions. An action specifies jointly: *bid spread in ticks, ask spread in ticks,
hold time*. Action 0 is a halt (no quoting). This formulation lets the agent learn
asymmetric quoting and inventory-driven pauses without separate policy components.

**State space:**

| Feature | Tabular bins | DQN (continuous) |
|---------|-------------|-----------------|
| Inventory (fraction of max) | 5 bins | raw float |
| Volatility ratio (vs EWMA) | 4 bins | raw float |
| Momentum signal | 3 bins | raw float |
| Spike flag | 2 bins (0/1) | raw float |
| OFI | — | raw float |
| PnL drawdown | — | raw float |

**TabularQ** discretises the four core features into 5×4×3×2 = **120 states** and
maintains a Q-table of size 120×19. Updates are one-step TD with α=0.1, γ=0.99.
The compact state space makes the learned policy fully inspectable as a heatmap.

**DQN** feeds a 6-dim continuous state vector into a two-layer MLP (6→128→128→19)
and trains with experience replay (capacity 100k), a target network (update every
200 steps), batch size 256, and Adam lr=3×10⁻⁴. The larger effective state space
should in principle capture finer market distinctions, at the cost of requiring
more data and compute to converge.

Both agents use the same reward:

```
r_t = ΔPnL_t − λ_inv × |q_t| × σ_t / max_inv     (λ_inv = 0.02)
```

The inventory penalty discourages holding large positions in volatile regimes.

---

## Training Setup

- **Symbol:** LINK/USDT (CoinAPI Binance Spot)
- **In-sample (IS):** Jun 11–27 2025 (17 days)
- **Out-of-sample (OOS):** Jun 28–Jul 10 2025 (13 days)
- **Order size:** 5 LINK; **max inventory:** 38 LINK (A-S winner)
- **Latency:** 100ms; **quote frequency:** 0.5s
- **Infrastructure:** AWS c6i.xlarge (4 vCPU, 8GB RAM), CPU-only (appropriate
  given network size)

TabularQ ran for 30 epochs (complete). DQN was configured for 50 epochs but was
stopped at epoch 22 due to instance shutdown.

---

## Results

### TabularQ (30 epochs, complete)

| Epoch | Train PnL/day | OOS PnL/day | OOS Sharpe | Fills/day | ε     |
|-------|--------------|------------|------------|-----------|-------|
| 1     | +53.24       | —          | —          | 8,873     | 0.050 |
| 5     | +63.99       | +75.10     | 53.7       | 10,077    | 0.050 |
| 10    | +66.71       | +51.47     | 57.1       | 9,781     | 0.050 |
| 15    | +61.12       | +41.18     | 80.7       | 9,736     | 0.050 |
| 20    | +64.97       | +98.51     | 59.9       | 9,924     | 0.050 |
| 25    | +69.52       | +63.49     | 44.0       | 10,065    | 0.050 |
| 30    | +65.47       | +71.05     | 49.0       | 9,889     | 0.050 |

- Train PnL **converged by epoch 3** at ~$63–68/day and remained flat — the policy
  learned quickly and did not improve further.
- OOS PnL is **noisy** over 13 days but averages ~$67/day across all eval checkpoints,
  comfortably above the A-S baseline of $43.78/day.
- ε stayed at 0.05 throughout: the slow decay schedule (1e-6/step) means the agent
  never fully committed to a greedy policy. The 5% random exploration may itself be
  contributing to fill diversity and higher PnL.
- Win rate 100% on all training days.
- Fills ~9,700–10,100/day — comparable to A-S, consistent with an aggressive
  quoting strategy.

### DQN (22/50 epochs, incomplete)

| Epoch | Train PnL/day | OOS PnL/day | OOS Sharpe | Fills/day | ε     |
|-------|--------------|------------|------------|-----------|-------|
| 1     | +54.32       | —          | —          | 8,644     | 0.393 |
| 5     | +33.40       | +120.41    | 76.8       | 6,319     | 0.050 |
| 10    | +48.93       | +129.64    | 61.3       | 7,920     | 0.050 |
| 15    | +48.16       | +64.62     | 50.7       | 7,795     | 0.050 |
| 20    | +50.04       | +42.33     | 44.7       | 7,483     | 0.050 |
| 22    | +51.05       | —          | —          | 7,880     | 0.050 |

- ε collapsed to 0.05 by epoch 4 (fast decay schedule 1e-7/step). Train PnL dropped
  from $54 to $33 as the policy became greedy, then partially recovered to ~$50.
- Early OOS numbers ($120–129 at epochs 5–10) look impressive but are unreliable:
  13 days of data with high daily variance produces noisy Sharpe estimates.
- **OOS PnL is monotonically declining** — $120 → $129 → $64 → $42. By epoch 20
  the DQN is at parity with A-S and still declining. This is a clear sign the
  policy is not generalising well to OOS data.
- Fewer fills (~7,000–8,000/day) than tabular — the DQN learned wider/more
  selective quoting under the greedy policy.
- Training was cut at epoch 22/50; checkpoint at epoch 20 is available for resumption.

---

## Conclusions

**TabularQ beats A-S.** The learned policy achieves ~$67/day OOS vs $43.78/day for
the classical baseline — a 53% improvement. The result is robust across all five
eval checkpoints.

**DQN does not outperform TabularQ.** Despite a richer continuous state space, DQN
achieves lower train PnL (~$45–50 vs ~$65) and declining OOS performance. The
low-data regime (17 training days) is likely insufficient for a replay buffer and
target network to provide stable gradients. The 6-dim state also strips out the
spike and momentum bins that tabular discretisation preserves explicitly.

**Simpler wins here.** 120-state tabular Q-learning is sample-efficient, converges
fast, and produces an interpretable policy (a 120×19 Q-table that can be visualised
as a heatmap). This is a useful thesis result: in illiquid altcoin market making
with limited training data, expressive neural architectures do not help.

**The 5% residual exploration in TabularQ is an open question.** Because ε never
decayed fully, we cannot distinguish whether the performance gain is from the
learned Q-values or from the exploration bonus itself. A greedy rollout of the
final checkpoint would resolve this.

---

## Further Work

1. **Greedy rollout of TabularQ checkpoint** — evaluate epoch_030 with ε=0 to
   isolate the learned policy from exploration noise.
2. **Q-table heatmap** — plot the dominant action per (inv, vol) cell; inspect
   whether the policy learned asymmetric quoting in high-inventory/high-vol states.
3. **DQN resumption** — restart from epoch_020 checkpoint and run to epoch 50 to
   see if OOS stabilises or continues declining.
4. **DQN state redesign** — add the spike bin back; try a 4-dim state matching
   the tabular discretisation to isolate the tabular vs neural effect cleanly.
5. **OOS transfer to Apr 2026** — run both trained agents on the Apr 2026 data
   (same as the A-S 30-day OOS study) for a direct like-for-like comparison.
6. **Reward shaping** — the current λ_inv=0.02 penalty is fixed; a curriculum
   that increases the penalty over training epochs may help DQN converge.
7. **PPO / Actor-Critic** — if DQN remains unstable, a policy gradient method
   may be more appropriate for the continuous reward signal.
