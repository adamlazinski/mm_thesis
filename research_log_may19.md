# Week in Review — LINK/BTC Market Making Research
*May 19 2026*

---

## Phase 1: BTC/USDT on June 2025 — Everything Fails

We started the week testing all existing strategies on the June 2025 BTC data (Jun 11–13 initially, later expanded). This was the stress test — June was volatile and directional compared to the calmer May data where strategies had shown some promise.

### What we ran

| Experiment | Strategy | Mean PnL/day | Verdict |
|---|---|---|---|
| Exp 01 (June) | Pure A-S baseline | −$2 | Too wide to fill |
| Exp 16 (June) | OFI optimized | −$8 | Jun 12 disaster: hit max inv, −$21 |
| Exp 09 (June) | Shifted GLFT | −$70 | Too tight, constant adverse fills |
| Search 18 | Pure A-S sweep | −$4.89 best | No profitable combo exists |
| Search 17 | Vol-inv + OFI/mom gate | −$46 best | Gating doesn't reduce fills enough |
| Search 19 | Vol-inv + OFI directed | −$122 best | Trade-flow OFI too lagged |
| Search 20 | OBI counter-trade | −$238 best | Queue model gap — see below |

**Key finding:** June 2025 BTC is structurally unprofitable for passive market making. Mean markout across all strategies: −1 to −12 bps. 60–100% of fills adversely selected.

### New infrastructure built

- `stats.obi` — instantaneous top-of-book size imbalance added to `MarketState`
- **Post-fill markout tracker** — measures mid price 1s after every fill, adds `avg_markout_bps` and `pct_adverse_fills` to every `_metrics.json`. Became the primary diagnostic tool for the rest of the week.
- `OBIDirectedFilter` — counter-OBI wrapper strategy replicating Albers et al. 2025

### The OBI counter-trade finding (Exp 20)

A thesis contribution in itself: we couldn't replicate Albers et al.'s near-zero adverse selection (−0.058 bps markout on BTC perps) because their mechanism depends on queue position — orders only fill during reversals when they're at the front of the queue. Our fill model (price-only, no queue depth) fills any order at the price level immediately. Without LOB depth data, the mechanism cannot operate. Documented as thesis contribution (Section 14).

---

## Phase 2: Switching to LINK/USDT — A Different Animal

We pivoted to LINK/USDT (Jun 11 – Jul 10 2025) after recognising that BTC's 1-tick spread and heavy HFT presence makes passive market making nearly impossible without queue simulation. LINK has structural differences worth exploiting.

### First discovery — the step-function fill curve (Exp 29)

LINK has a permanent 10-tick ($0.010) spread essentially 100% of the time. Inside that spread, fill rate is 17–37%. At or outside it, fill rate drops to 1–14% and fills are adversely selected (avg markout −1.89 bps, 66% adverse vs 40% at-spread). This immediately pointed to inside-spread quoting as the mechanism to exploit.

### The search found a surprising winner (Exps 30, 34, 35, 37)

The random search found parameters that look like a theoretically degenerate strategy:
- γ ≈ 0 (zero inventory skew)
- min_spread = 6.44 bps (3.86 ticks — one tick inside LINK's natural 5-tick bid/ask side)
- max_inventory = 38 LINK (~$465 notional)
- daily_loss_limit = $25

This is essentially a **constrained flat market maker** — no model-theoretic skew, just quote inside the spread with a tight inventory cap and a kill switch.

| Period | Days | Mean/day | Win rate | Sharpe |
|---|---|---|---|---|
| IS Jun 11–27 | 17 | +$158/day | 17/17 | 56.1 |
| OOS Jun 28–Jul 10 | 13 | +$149/day | 13/13 | 57.7 |
| Combined 30 days | 30 | +$154/day | 30/30 | 56.5 |

Including Jun 22 (−4.3% trending day, still +$114) and Jun 23 (+10% rally, still +$128).

### The GLFT control experiment (Exp 37) — the most revealing result

We ran A-S γ≈0 with the exact same inventory/limit/spread as the GLFT search winner to isolate whether the GLFT formula added any value. It didn't — A-S **outperformed by 69%** (+$149/day vs +$89/day OOS). Reason: GLFT's dynamic spread widens to 10–18 bps when estimated arrival rate A_hat is low (which happens 33% of the time on LINK's sparse order flow), costing ~2,250 fills/day relative to the fixed-spread A-S.

The deeper finding: this isn't really market making. It's **mean-reversion grid trading** disguised as market making. The small inventory cap forces rapid cycling — when long you can only quote ask, so you sell into local highs; when short you buy from local lows. 1,799 inventory sign changes on a single day (Jul 3). Positive markout (+1.2 to +2.5 bps) across all 30 days confirms it.

### Sensitivity analysis (within Exp 37)

- **max_inventory**: Sharpe peaks at 38 LINK and declines sharply above 75. Beyond 150, win rate falls below 100%. The winner is Sharpe-optimal, not PnL-optimal.
- **min_spread_bps**: Step-function response driven by tick rounding. Clear cliff at 7.5 bps (= natural spread boundary). Inside 4.5 bps loses money.
- **daily_loss_limit**: Never triggered on OOS period — irrelevant for this data, but critical on trending days like Jun 22–23.

### OFI overlay experiment (Exp 38) — completed

Tested whether OFI-directed one-sided quoting or momentum suppression improved the A-S winner on Jun 11 – Jul 10.

| Filter | IS mean/day | OOS mean/day | IS win rate |
|---|---|---|---|
| **Baseline (no filter)** | **+$71.8** | **+$83.0** | **100%** |
| OFI directed (best threshold) | −$67 | +$129 | 35% |
| Momentum suppress (best threshold) | −$50 | +$132 | 35% |

Both filters hurt IS performance badly. They look better OOS only because they dodge Jun 22–23 trending days, but the IS disaster and worst-day drawdowns (−$923 to −$1,004) make them useless in practice. **No filter is the finding.**

---

## Phase 3: April 2026 — Does It Still Work?

Loaded April 2026 LINK data (Apr 1–30, 30 days, ~$9 LINK vs ~$13 in mid-2025).

### Exp 40 — zero-shot transfer

Ran the Jun 2025 IS winner unchanged on April 2026. Zero recalibration.

| Metric | Result |
|---|---|
| Win rate | 30/30 (100%) |
| Mean PnL/day | +$43.78 |
| Sharpe (daily) | 38.7 |
| Max drawdown | $0.00 |
| Avg markout | +1.25 bps |
| Avg adverse fills | 22% |

Lower PnL than 2025 consistent with $9 vs $13 price — same tick count, lower notional per fill. The mean-reversion edge is intact 9+ months out of sample. Natural spread still 10 ticks. The mechanism generalises.

See [`experiments/40_link_apr2026_baseline/ANALYSIS.md`](experiments/40_link_apr2026_baseline/ANALYSIS.md) for figures.

---

## Currently Running

**Exp 39 — RL (TabularQ + DQN):** Training on Jun 11–27 LINK data, evaluating on Jun 28–Jul 10. Both jobs pegged at 100% CPU since ~8:30am. Each epoch iterates 17 full days of tick data (~60–90 min per epoch, 30 epochs total). Motivation: learn the optimal inventory policy dynamically rather than relying on the fixed `max_inventory=38` found by grid search.

---

## What Failed vs What Worked

| | Failed | Worked |
|---|---|---|
| **BTC June** | Everything — all strategies, all param combos | Markout tracker as diagnostic |
| **BTC mechanism** | OBI counter-trade replication (queue position gap) | Documenting *why* it fails (thesis contribution) |
| **GLFT on LINK** | GLFT formula adds noise via dynamic spread in sparse conditions | GLFT inventory skew concept correct in principle |
| **OFI/momentum overlays** | Both hurt IS performance badly across all thresholds | No filter confirmed as best baseline |
| **LINK** | Wide-spread A-S, at-spread quoting without inventory control | Inside-spread + tight inventory cap + loss limit = 30/30 days |
| **Generalisation** | — | Zero-shot Apr 2026 transfer held perfectly |

---

## Core Thesis Finding So Far

On BTC, passive market making is broken by adverse selection and the impossibility of queue-position modelling without LOB depth data. On LINK, the 10-tick structural spread creates an exploitable gap: inside-spread quoting with a tight inventory cap degenerates to **constrained mean-reversion trading** that profits from the asset's short-term price oscillations. The A-S and GLFT model-theoretic machinery (inventory skew, optimal spread formula) adds marginal or negative value once the key structural insight (inside-spread + small cap) is found by search.

This motivates the RL approach: learn the inventory policy directly from reward rather than deriving it from model assumptions that don't hold on this asset.
