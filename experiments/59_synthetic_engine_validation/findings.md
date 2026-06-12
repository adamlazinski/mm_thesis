# Exp 59 — Synthetic Ground-Truth Validation (engine + strategies)

**Purpose.** Validate the backtest engine and the classical strategies on markets
whose profitability is known in closed form. If they did not book the expected
profit here, every real-data conclusion would be suspect. They pass — and they
also lose *only* where theory says they must (a too-tight spread under a
short-gamma inventory cost), which is itself a correctness check.

Two scripts:
- `synthetic_validation.py` — engine check with a fixed-spread quoter.
- `as_validation.py` — strategy check: real Avellaneda-Stoikov & GLFT fed the
  **true** volatility, on an A-S/GLFT-faithful market.

Common setup: true value `V(t)` driven by one of several processes; Poisson taker
flow (2 orders/s, 50/50 side); zero fees, zero latency, `queue_model='none'`; 6 h
of data. Mid = `(bid+ask)/2`; P&L = `cash + inventory × mid`.

---

## Part A — Engine (fixed 2-tick quoter at the BBO)

`bbo` fill model: every taker prints at the BBO, so the MM quoting at the touch
captures the spread on each fill.

| Regime | Fills | PnL ($) | PnL/fill | Note |
|---|---|---|---|---|
| **constant** | 38,520 | **+769.44** | +0.0200 | matches closed form |
| **ou** (mean-reverting) | 31,213 | +557.91 | +0.0179 | reversion unwinds inventory |
| **brownian** (mild, σ=0.01) | 33,982 | +689.54 | +0.0203 | spread > short-gamma cost |

**Gold check (constant).** With `V` constant there is no adverse selection at all,
so every fill earns exactly the half-spread vs. true value:

```
expected = n_fills × half_spread × size = 38,520 × $0.02 × 1.0 = $770.40
realized = $769.44      →  residual −$0.96  (= the 36-unit open inventory marked at mid)
```

The fill and P&L accounting is exact to floating precision. The engine is sound.

---

## Part B — The short-gamma cost (why a tight spread can lose in a *martingale*)

A passive MM is structurally short gamma: its ask is lifted as price rises
(accumulating shorts into a rally) and its bid is hit as price falls. Even though
a random-walk mid has **zero expected informational adverse selection**, the
realized inventory-variance cost scales with σ². When σ is large relative to the
spread, that cost swamps spread capture. This is not an engine artifact — it is
the real economics A-S/GLFT are built to price.

High-vol brownian (σ=0.20 $/√s ≈ ±$29 over the path), fixed 2-tick quoter,
**12 seeds** (a single path is pure noise here):

| Fill model | mean PnL | std | range |
|---|---|---|---|
| bbo | **−$919.85** | 625 | −2,291 … −126 |
| exponential | **−$760.11** | 840 | −2,511 … +382 |

Robustly negative — the σ²-cost, not bad luck.

**The positive zone exists.** Sweeping the fixed half-spread on the same high-vol
world (exponential fills, 8 seeds) is non-monotonic with a clear profitable width:

| half-spread | 2t | 4t | **8t** | 16t | 32t |
|---|---|---|---|---|---|
| mean PnL | −626 | −115 | **+113** | +52 | +5 |
| days > 0 | 12% | 50% | **62%** | 62% | 25% |

Too tight → short-gamma loss; too wide → no fills. A *vol-appropriate* spread
(~8t) is profitable. That is precisely what a vol-aware strategy should target.

---

## Part C — Strategies fed the true volatility (A-S & GLFT)

Real `AvellanedaStoikov` and `GLFTMarketMaker`, **injected with the true σ** (and
true fill-decay κ, rate A), exponential-fill world, 6 seeds/cell. Half-spread
shown in ticks; "days>0" = fraction of seeds positive.

**Avellaneda-Stoikov** (γ sweep)

| Regime | best mean PnL | half-spread | days>0 |
|---|---|---|---|
| constant | +$382 | 1.0t | 100% |
| brownian (σ=0.01) | +$414 | 1.0t | 100% |
| brownian_medvol (σ=0.05) | +$209 | 2.2t | 100% |
| brownian_highvol (σ=0.20) | −$5 (γ=10) | 24.6t | breakeven |

**GLFT ergodic** (γ sweep)

| Regime | best mean PnL | half-spread | days>0 |
|---|---|---|---|
| constant | +$765 | 2.0t | 100% |
| brownian (σ=0.01) | +$592 | 2.0t | 100% |
| brownian_medvol (σ=0.05) | +$245 | 4.7t | 100% |
| brownian_highvol (σ=0.20) | −$33 (γ=50) | 16.2t | 33% |

**Reading it.**
1. In the constant, mild, and **medium-vol** regimes both strategies fed true σ
   are **clearly and robustly positive** (100% of seeds). This is the user's claim
   confirmed: a vol-aware MM with the true volatility makes money in its own world.
2. Both strategies **widen monotonically with σ and with risk aversion** — A-S
   1.0t→24.6t, GLFT 2.0t→16.2t — i.e. the `γσ²` / `θ` vol term works. The widening
   pulls high-vol PnL up from the −$900 tight-quote loss toward breakeven.
3. At the **extreme** σ=0.20 the profitable band is narrow (~8t) and each
   strategy's *own* optimum brackets it (A-S overshoots to 25t, GLFT bottoms at
   16t), so both land at ≈breakeven rather than clearly positive. Two
   implementation notes contribute: A-S scales κ by the horizon T (the
   miscalibration flagged in CLAUDE.md), inflating its spread; GLFT's
   `(1+κ/γ)^(1+κ/γ)` term forces a ~16t floor near its own optimum γ≈κ. Neither
   changes the qualitative verdict — at realistic vol they are solidly positive.

---

## Part D — Why honest MM is breakeven: σ and κ are not independent

Parts A–C treat the mid-volatility σ and the order-flow parameters (A, κ) as
**independent**, which makes the vol-to-flow ratio `σ²/(Aκ)` a free knob — that is
the *only* reason the synthetic MM can be made arbitrarily profitable. In a real
order-driven market σ and flow are the same process, and the coupling pins κ to σ.

Two facts (Glosten–Milgrom 1985; Wyart–Bouchaud et al. 2008):
1. **Volatility is flow.** Over time `t` there are `N = A·t` trades, so
   `σ_$²·t = N·σ_trade²` ⟹ `σ_trade = σ_$/√A` — the volatility *per trade*, the
   irreducible adverse-selection cost between quoting and filling.
2. **MM zero-profit.** Free entry competes the half-spread down to where the
   premium just covers that cost: `δ* ≈ σ_trade`. Since the fill curve decays on
   scale `1/κ`, in equilibrium `1/κ ≈ δ*`, giving **κ_eq ≈ √A / σ_$**.

`equilibrium_pinning.py` confirms this directly. Informed flow (a fraction φ=0.5 of
takers trade in the direction of the next 5 s move) supplies real adverse
selection, and we locate the breakeven half-spread δ_be(σ) where mean PnL = 0
(4 seeds/cell):

| σ_$ | fixed 2t quoter PnL | δ_be (ticks) | δ_be/σ_$ | implied κ = 1/δ_be |
|---|---|---|---|---|
| 0.02 | +$118 | 2.0 (floored) | 100 | 0.500 |
| 0.05 | −$540 | 3.9 | 77.5 | 0.258 |
| 0.10 | −$1,436 | 7.6 | 76.0 | 0.132 |
| 0.20 | −$2,843 | 15.2 | 75.9 | 0.066 |

**δ_be/σ_$ is constant (~76)** — the breakeven half-spread is *linear in σ*
(Wyart–Bouchaud), so the market-clearing **κ = 1/δ_be falls as 1/σ** (halving each
time σ doubles). κ is not a free parameter; it is pinned to σ by zero-profit. A
fixed-κ quoter (left column) is therefore living in a disequilibrium — fine while σ
is small, catastrophic once σ exceeds the level its spread was set for.

**The large-tick twist (= C30).** `δ* ≈ σ_$/√A` assumes the spread can move freely.
On a large-tick asset like LINK the spread is floored at 1 tick and *cannot* tighten
to the zero-profit width — so the market enforces breakeven on the **queue-depth**
axis instead: the touch queue grows until the marginal back-of-queue order breaks
even (the ~8,600 LINK of Contribution 20/30). The Wyart–Bouchaud spread equilibrium
(small-tick, e.g. BTC) and the C30 queue-priority rent (large-tick, LINK) are the
**same zero-profit law**, enforced through whichever variable is free: spread width
or queue position. That is *why* queue priority is the scarce, retail-inaccessible
resource.

---

## Part E — Path to profit in the high-vol world (and the latency gate)

The high-vol loss is not symmetric inventory variance — it is **staleness adverse
selection**: between requotes the fast mid drifts and a taker lifts the stale quote
after the price has moved (at σ=0.20 the mid moves ~6 ticks in 0.1 s, swamping a
2-tick spread). This diagnosis dictates the levers (exponential-fill high-vol, 10
seeds; `high_vol_profit.py`, run on the corrected taker-on-arrival engine, cafc7ae):

- **Lever 1 — widen the spread:** 2t→6t lifts −$514 → +$67. Cushions the drift, but
  marginal and noisy (50% days positive); too wide starves fills. Necessary, not
  sufficient.
- **Lever 2 — inventory skew:** *hurts the mean* (+$67 → −$369) while crushing
  variance ($590 → $41). The cost is a drift, not variance, so flattening forfeits
  spread for nothing — a pure mean-for-variance trade, useless for the mean.
- **Lever 3 — speed:** requote 0.5 s→0.05 s turns −$898 → **+$169, 80% of
  days positive** — track the mid and the pick-off vanishes. (Levers 1-3 use
  latency=0 and are confirmed unchanged by the engine fix — byte-identical to the
  pre-fix run.)
- **The latency gate (now charged honestly):** at fixed 0.02 s requoting, **only
  exact zero latency is positive** — 0 ms +$153 (70% days>0); 20 ms −$95 (50%),
  50 ms −$389 (40%), 100 ms −$786 (10%), 200 ms −$1,580 (0%). The marketable-on-
  arrival fix makes every nonzero-latency cell *worse* than the pre-fix estimate
  (old engine: 20 ms was a marginal −$12; now a clear −$95) — the toxic
  latency-adverse crossings the old engine suppressed are now charged here too.

**Implication.** At the Lever-3 configuration tested here — 4t, requote 0.02s —
only **zero latency** is positive; any realistic co-location delay (even 20 ms)
reintroduces a losing marketable-on-arrival tail and flips the result negative. The
pre-fix framing ("needs sub-20 ms HFT co-location") was too optimistic: the corrected
engine shows 20 ms is *already* solidly negative at this width. But 4t/0.02s is only
one point in a 2D (spread, requote) space — Part F sweeps spread jointly with
latency at the fast requote and finds the picture is less bleak at a wider spread.

---

## Part F — Joint sweep: does widen + speed cross back to breakeven at realistic latency?

Part E tested its levers mostly one-at-a-time: Lever 1 (widen) at requote 0.1s /
latency 0; Levers 3-4 (speed / latency) at half=4t. A single combined probe — half=8t,
requote=0.05s, latency=0.05s — gave **+$389.8 (70% days>0)**, sharply better than the
4t/0.02s/50ms cell (−$388.9). `breakeven_sweep.py` generalizes this into a full 2D
sweep: half-spread ∈ {6, 8, 12, 16}t × latency ∈ {0, 20, 50, 100, 200} ms, fixed
requote=0.05s, β=0, 10 seeds/cell.

Mean P&L (days>0 in parentheses):

| half-spread | 0 ms | 20 ms | 50 ms | 100 ms | 200 ms |
|---|---|---|---|---|---|
| 6t | +$255 (60%) | +$165 (70%) | +$14 (60%) | −$309 (30%) | −$1060 (0%) |
| **8t** | +$262 (60%) | **+$463 (90%)** | **+$390 (70%)** | **+$188 (70%)** | −$581 (10%) |
| 12t | +$32 (50%) | +$196 (60%) | −$169 (40%) | +$175 (70%) | +$19 (50%) |
| 16t | +$106 (60%) | +$157 (80%) | −$50 (50%) | +$56 (70%) | +$127 (60%) |

**Reading it.**
1. **8t + 0.05s requote is the standout combination**: robustly positive (+$188 to
   +$463, 60-90% days>0) across the *entire* 0-100 ms latency range, only collapsing
   at 200 ms (−$581, 10%). This widens Part E's latency-tolerant band from "zero
   only" (at 4t/0.02s) to roughly **100 ms** — a realistic non-co-located venue
   latency.
2. 6t shows the monotone decay the 4t/0.02s cell already hinted at: positive at
   0-20 ms, breakeven near 50 ms, clearly negative beyond. Narrower spreads stay
   latency-fragile even at the faster requote.
3. 12t and 16t are too noisy to read (std $500-850 against means of $20-200,
   10 seeds) — neither confirms nor rules out a similar band; more seeds would be
   needed.
4. So **yes — there is a combination** (widen to the vol-appropriate ~8t *and*
   requote fast at 0.05s) that is robustly positive at realistic latencies, not just
   at zero. This refines Part E's "speed alone fails at 20 ms" verdict: speed
   *combined with* the right width is a materially better lever than either alone.

**Caveat (unchanged from Levers 1-3).** This remains the Layer-1-only synthetic
world: martingale mid, uninformed Poisson fills, zero fees. An 8t quote here only
ever meets uninformed flow. On a real venue with informed counterparties (Layer 2),
an 8-tick-wide resting quote is exactly the kind of stale, easy-to-pick-off level that
gets adversely selected (exp 57 deep-reversion) — so this band does not transfer to a
retail edge. It does, however, sharpen the picture of *when* a vol-aware MM is
profitable in its own world: Part C already showed medium-vol (σ=0.05) is robustly
positive with the true σ fed to A-S/GLFT, and Part F shows that even the high-vol
(σ=0.20) regime has a profitable, latency-tolerant corner once spread width and
requote speed are jointly tuned — it just requires both, and a real venue's
informational Layer 2 (not modeled here) is why this corner is not a tradeable
strategy.

---

## Conclusion

The engine captures spread exactly when there is none to lose to (constant),
profits in benign / mean-reverting / mild-to-medium-vol worlds (ou, brownian,
medvol), and loses only where a too-tight spread is overrun by the σ² short-gamma
cost — the very effect A-S and GLFT are designed to price, and which they correct
(monotonic vol-widening, restoring profit up to medium vol). **Therefore the
breakeven-to-negative honest-regime results on real LINK/BTC are not an engine or
strategy-implementation artifact.** The synthetic A-S/GLFT world — no queue, no
informational adverse selection — is profitable as theory demands; the real market
is not, because of the two gates the thesis identifies (queue priority for the
maker, fees for the taker). This is the constructive complement to C30: when the
profit *should* be there, the code finds it.

Reproduce:
```
python experiments/59_synthetic_engine_validation/synthetic_validation.py
python experiments/59_synthetic_engine_validation/as_validation.py
```
