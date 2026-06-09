# Experiment 52: LINK Classical MM — Findings

LINK/USDT, Binance Spot, April 2026 (30 trading days, Apr 1–30).
All runs use: order_size=5 LINK, tick_size=$0.01, latency=100ms, quote_freq=0.5s,
min_spread_bps=11.0, max_inventory=50 LINK, maker_fee=0.

---

## Workflow Summary

### Step 1 — Kappa calibration (Approach C, Exp 51)
Fit crossing intensity λ(δ) = P(|Δm(h)| ≥ δ) / h to an exponential using h=60s.
Result: κ=2.08/tick, R²=0.97. No momentum floor (A_mom≈0). Pure exponential.
Implication: optimal A-S spread at γ→0 = 2/κ ≈ 1 tick ≈ 11 bps.

### Step 2 — A-S gamma calibration
Bug fixed: removed the ×1000 gamma hack in `avellaneda_stoikov.py` (was compensating
for BTC's tiny σ², but LINK σ² is ~40,000× larger — made effective gamma 40,000× too large).

For 2-tick ($0.02) reservation price skew at q=50 LINK:
  γ = 0.02 / (50 × (5.89e-3)² × 3600 × 8.98) = 3.57e-4

### Step 3 — GLFT calibration
GLFT spread formula contains (1+κ/γ)^(1+κ/γ) which blows up for LINK parameters.
Minimum formula spread ≈ 13 ticks for any economically sensible γ.
Fix: max_spread_bps=11.0 caps the spread at touch while the reservation price formula
still applies inventory skew.

For equivalent 2-tick skew at q=50 LINK (GLFT formula):
  γ = 4.3  (from: 0.02 = 50 × 4.3 × (0.053)² / (2 × 0.072 × 208))

---

## Core Results (30-day April 2026)

| Config | γ | Total PnL | Mean/day | Std/day | Sharpe | Win rate | Fills |
|---|---|---|---|---|---|---|---|
| A-S flat | ≈0 | **+$1,428** | +$47.6 | $49.0 | **0.97** | **90%** | 94,226 |
| A-S calibrated v2 | 3.57e-4 | +$677 | +$22.6 | $37.0 | 0.61 | 67% | 95,651 |
| GLFT touch v2 | 4.3 | +$648 | +$21.6 | $37.3 | 0.58 | 67% | 95,672 |
| A-S flat + L2 queue | ≈0 | +$588 | +$19.6 | $18.3 | **1.07** | 83% | 107,562 |

All strategies post at ~11 bps (touch). Fill counts for flat vs calibrated are nearly identical.
The PnL difference is entirely from how inventory skew interacts with sweep-driven fills.

---

## Key Finding: Why Inventory Skew Hurts on LINK

LINK fills are **sweep-driven**. The permanent 10-tick spread means ordinary flow only crosses
the spread during large block orders that sweep multiple levels. These sweeps arrive randomly
with respect to our inventory state.

When the reservation price is skewed away from mid (e.g., bid shifted down when long):
- We quote further from mid on the buy side → inventory-unwinding fills become harder
- We quote at normal touch on the sell side → fills still occur, adding to long position
- Net: skew reduces the rate of inventory-reducing fills without blocking adverse sweeps

The flat MM stays symmetric → captures both sides of random sweeps equally → natural cycling.
This is not a failure of calibration. Both calibrated strategies use correctly derived gammas
that produce 2-tick skew at max inventory. The mechanism itself is counterproductive when the
fill curve is approximately flat across the inventory skew range.

**General condition:** Inventory skew is counterproductive when:
1. Fill probability is approximately flat across the δ range spanned by the skew
2. Fills are initiated by market sweeps, not spread-sensitive taker flow

Both conditions hold on LINK. Neither holds on BTC (where fill rate decays sharply with δ
and taker flow is much more distributed).

---

## L2 Queue Model

### Motivation
Standard fill model (`queue_model='none'`) fills immediately on price match.
At LINK's touch, L2 depth ≈ 8,625 LINK (mean), median trade = 2 LINK.
Queue/trade ratio ≈ 1,968×. Only ~0.1% of trades are large enough to clear the queue.
The no-queue model overstates fills by ~41× at the touch (from Contribution 20).

### Implementation
`queue_model='l2'` in OrderManager: accumulates trade volume at our price since submission.
Order only fills once cumulative volume exceeds `queue_ahead`.
`queue_ahead = best_bid_depth × queue_fraction` at submission time.

`queue_fraction=0.001` → ~8.6 LINK ahead of us ≈ 1–2 competing MMs of our size.

### Results vs No-Queue

| Metric | No queue | L2 queue (frac=0.001) | Δ |
|---|---|---|---|
| Total PnL | +$1,428 | +$588 | −59% |
| Daily std | $49 | $18 | −63% |
| Sharpe | 0.97 | **1.07** | +10% |
| Win rate | 90% | 83% | −7pp |
| Fill records | 94,226 | 107,562 | +14% (partial) |
| Avg markout | +4.14 bps | +2.73 bps | −34% |
| Typical adverse fill rate | ~24% | ~45% | +21pp |

Sharpe *improves* despite 59% PnL drop: most days have near-zero fills (queue never clears);
PnL arrives in infrequent large pulses when sweeps clear the queue. Variance collapses faster
than mean. Adverse fill rate doubles because queue-clearing sweeps are inherently informed.

### Interpretation
- No-queue model: +$1,428 → upper bound (all fills instantaneous)
- L2 queue model: +$588 → lower bound (every fill must clear full queue)
- True answer lies between; actual fill rate depends on queue position dynamics

---

## Analysis Figures

Located in `analysis/`:
- `fig1_daily_pnl.png` — Daily P&L bar chart (3 strategies)
- `fig2_cumulative_pnl.png` — Cumulative P&L path
- `fig3_spread_comparison.png` — Average spread and fill count comparison
- `fig4_inventory_sample.png` — Inventory dynamics on sample day
- `fig5_skew_comparison.png` — Theoretical reservation price skew (all strategies)

---

## Configs

| File | Strategy | Key params |
|---|---|---|
| `config_as_flat.json` | pure_as | γ=1e-9, kappa_as_min=2.08 |
| `config_as_calibrated_v2.json` | pure_as | γ=3.57e-4, kappa_as_min=2.08 |
| `config_glft_touch_v2.json` | glft | γ=4.3, A=0.072, κ=208, max_spread_bps=11.0 |
| `config_as_flat_queue.json` | pure_as | γ=1e-9, queue_model=l2, queue_fraction=0.001 |
