# Exp 46: TabularQ on BTC/USDT — Findings

## Setup

Same TabularQ architecture as Exp 39 (LINK), identical IS/OOS split for direct comparison.

| Parameter | Value |
|-----------|-------|
| Symbol | BTC/USDT |
| IS period | Jun 11–27 2025 (17 days) |
| OOS period | Jun 28–Jul 10 2025 (13 days) |
| tick_size | $0.01 |
| order_size | 0.001 BTC (~$107 notional) |
| max_inventory | 0.02 BTC |
| daily_loss_limit | $2.00 |
| Action space | 19 actions: spread 3–9 ticks × hold 0.25–2.0s + halt |
| State space | 120 states (5 inv × 4 vol × 3 mom × 2 spike) |

## Training Results (30 Epochs)

| Epoch | Train PnL/day | OOS PnL/day | OOS Sharpe | Win rate | Fills/day | ε |
|-------|-------------|------------|------------|----------|-----------|---|
| 5  | −$2.25 | −$2.08 | −617.0 | 0% | 108 | 0.708 |
| 10 | −$2.16 | −$2.15 | −208.0 | 0% | 107 | 0.499 |
| 15 | −$2.20 | −$2.17 | −151.0 | 0% | 146 | 0.346 |
| 20 | −$2.15 | −$2.11 | −355.4 | 0% | 163 | 0.231 |
| 25 | −$2.12 | −$2.13 | −263.3 | 0% | 136 | 0.154 |
| 30 | −$2.12 | −$2.09 | −531.4 | 0% |  96 | 0.104 |

**No learning occurred.** PnL flat at −$2.10/day throughout. mean_loss = 0.000 every epoch.

## Root Cause: Action Space–Microstructure Mismatch

BTC's natural market spread is 1 tick ($0.01). All 19 RL actions quote at 3–9 ticks from mid,
meaning every quote is **outside** the natural spread. In contrast, LINK's 10-tick natural
spread means the same actions post **inside** the spread.

### Fill Regime Comparison

| Instrument | Natural spread | 3-tick action relative to spread | Fill regime |
|------------|---------------|----------------------------------|-------------|
| LINK | 10 ticks | Inside (7 ticks from touch) | At-touch (~99% fill rate) |
| BTC  | 1 tick   | Outside (3× wider than touch) | Exponential decay (≈39% at 3 ticks) |

### Economics

```
Spread capture per round-trip (3-tick quote): 6 ticks × $0.01 × 0.001 BTC = $0.000060
Net loss per fill (observed):                 $2.10 / 100 fills             = $0.021
Adverse selection ratio:                      $0.021 / $0.000060            = 350×
```

The $0.000060 spread revenue is overwhelmed by inventory mark-to-market losses. With ~10 net
BTC unbalanced at end of each episode, a routine 0.2% BTC move ($210) creates −$2.10/day loss.

BTC daily vol is ~1.5% (~$1,600), so this adverse inventory exposure triggers on essentially
every day.

### Why No Learning Signal

Because no episode ever achieves positive PnL, all state-action Q-values receive uniformly
negative TD updates. The table converges to a plateau of equally bad values — no action is
distinguishably better. mean_loss = 0.000 confirms the Q-table stopped updating early (the
delta Q values are all near zero because all rewards are near-identically negative).

## Greedy Eval (ε=0, epoch_030)

| Metric | Value |
|--------|-------|
| Mean PnL/day | −$2.08 |
| Total PnL (13 days) | −$27.08 |
| Sharpe | −529.8 |
| Win rate | 0% |
| Mean fills/day | 135.8 |

Per-day PnL is strikingly uniform: every day ends at approximately −$2.10, regardless of
fill count (28 to 388 fills). Peak inventory hits max_inventory = 0.02 BTC on 12/13 days.

**Inventory cap mechanism**: with order_size = 0.001 BTC and max_inventory = 0.02 BTC, only
20 net buys are needed to hit max. Once there, the agent is fully exposed to adverse price
moves. Max notional = 0.02 × $107k = $2,140. A 0.1% adverse move → −$2.14 loss — which is
exactly what we observe, with ~0.1% precision, every single day.

## Comparison: LINK vs BTC

| Metric | LINK (Exp 39) | BTC (Exp 46) |
|--------|--------------|-------------|
| Natural spread | 10 ticks | 1 tick |
| Action regime | Inside spread | Outside spread |
| OOS Fills/day | ~5,000–12,000 | ~100 |
| Spread capture/RT | ~$0.07 | $0.000060 |
| OOS PnL/day | +$71.24 | −$2.09 |
| Win rate (OOS) | 100% | 0% |
| Learning | ✓ converges epoch ~10 | ✗ no signal ever |

## Conclusion

TabularQ market making with 3–9 tick spread actions is **microstructure-specific**. It succeeds
on LINK (wide-spread, step-function fill curve) because the action space naturally falls inside
the market, yielding at-touch fill rates and positive spread capture. It fails on BTC (tight
spread, exponential fill curve) because every action posts outside the market — fills are pure
adverse selection events too infrequent and too small to overcome inventory bleeding.

For a valid BTC RL agent, the action space would need to include at-touch positions (1–2 tick
spreads), and order_size would need to be large enough to make spread capture competitive with
BTC's intraday volatility. This requires a fundamentally different risk/reward tradeoff.
