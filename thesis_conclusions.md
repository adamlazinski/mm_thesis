# Conclusions

This chapter draws together the contributions in `thesis_contributions.md` (cited below as
C1–C36) into a single argument. The project began as an implementation-and-calibration study
of Avellaneda–Stoikov (A-S) and Guéant–Lehalle–Fernández-Tapia (GLFT) market making on
BTC/USDT and LINK/USDT. It ends as a demonstration that **the profitability these models (and
a reinforcement-learning alternative) appear to show in standard event-driven backtests is not
a strategy edge at all, but an artifact of an unmodelled queue-priority assumption — and that
once this is corrected, the honest result is not merely unprofitable but is the *necessary*
outcome of a zero-profit equilibrium that microstructure theory already predicts.** Three
independent escape routes from this conclusion were tested and each closes for a related but
distinct reason.

---

## 1. Headline result

No retail-accessible edge exists in classical (A-S/GLFT) or RL-based crypto spot market making
once the fill model is made physically honest — and this is not an empirical accident of the
May 2025 – April 2026 sample. It follows from a zero-profit equilibrium condition (Wyart,
Bouchaud, Kockelkoren, Potters & Vettorazzo, 2008; Glosten & Milgrom, 1985) that links the
quoted spread to realised volatility per trade. The apparent profitability reported throughout
the early chapters of this thesis (Contributions 16–23) is real *within the backtest*, but is
shown in C30 to be entirely explained by one variable: whether the quote sits inside the
natural bid–ask spread under a fill model that grants it absolute queue priority.

---

## 2. The evidentiary chain

### 2.1 The machinery is validated before it is doubted (C33a–c)

Before any negative result can be trusted, the backtest engine and the two classical strategies
are checked against markets whose profitability is known in closed form
(`experiments/59_synthetic_engine_validation/`).

- **Engine exactness.** A fixed 2-tick quoter resting at the BBO, run on a market with a
  *constant* true value and Poisson taker flow, books

  ```
  expected = n_fills × half_spread × size = 38,520 × $0.02 × 1.0 = $770.40
  realized = $769.44   (residual −$0.96 = open inventory marked at mid)
  ```

  to floating-point precision. Mean-reverting (OU, +$558) and mildly volatile Brownian
  (+$690) worlds are likewise profitable. The fill condition and the
  `cash + inventory × mid` accounting are correct.

- **The negative control is structural, not a bug.** In a high-volatility *martingale*
  (σ = 0.20 $/√s — driftless, so no informational adverse selection), the same fixed quoter
  loses robustly (mean −$920, 12 seeds). This is the **short-gamma cost**: a passive maker's
  ask is lifted as price rises and its bid is hit as price falls, so inventory and price move
  in opposite directions and the realised inventory-variance cost scales with σ². The engine
  books this loss correctly.

- **The strategies are sound when given the truth.** Real `AvellanedaStoikov` and
  `GLFTMarketMaker` objects, injected with the *true* σ, are robustly profitable
  (100% of seeds) in constant, mild, and medium-volatility regimes, and widen their
  half-spread monotonically with σ and risk aversion (A-S 1.0t → 24.6t; GLFT 2.0t → 16.2t) —
  exactly as the `γσ²` / inventory term prescribes.

**Conclusion of this step:** nothing in the chain that follows is an engine bug or a
strategy-implementation error. The code finds profit precisely where theory says it should
exist.

### 2.2 The queue-priority decomposition (C30)

Every profitable backtest result in the project — classical A-S/GLFT and both RL agents, on
both LINK and BTC — shares one structural feature: **the quote sits inside the natural
bid–ask spread**, and the fill model (`order_manager.py`, pre-fix `queue_model='none'`) fills
a resting order on the *first* trade that touches its price, i.e. grants it absolute queue
priority, as though no other order were resting ahead of it.

LINK's natural spread is exactly 10 ticks (5 per side) for 99.9% of April 2026. Decomposing a
flat A-S strategy by regime (30 days, zero fees):

| Regime | Half-spread | Inside natural touch? | Honest fill model? | Fills/day | PnL/day | 1s markout |
|---|---|---|---|---|---|---|
| Deep inside | 2t | yes | no | 7,673 | +$35 | +0.98 bps |
| Inside (optimum) | 4t | yes | no | 7,288 | **+$94** | +2.80 bps |
| At touch | 5t | at | partial | 2,502 | +$33 | −0.41 bps |
| Outside | 8t | no | **yes** | 216 | +$2.5 | **−0.65 bps** |

Only the outside-spread regime is physically honest — a fill there requires the price to trade
*through* your level, so there is no queue to jump. It earns +$2.5/day with a *negative*
1-second markout: every fill is initially adverse, and the small positive total comes only
from longer-horizon mean reversion.

**RL is the same artifact, harder to see.** The TabularQ policy that "outperforms" A-S
(Contribution 23, +$45.94/day on April 2026) runs through the identical fill model and learned
to quote inside/at-touch almost exclusively — its fill rate (median 4,970/day, min 1,495) is
7–38× the honest outside-spread ceiling of 216/day on *every single day*. A paired overfit test
(exp 58, train = eval, 200 epochs) confirms the diagnosis directly: under the artifact-prone
fill model the same TabularQ overfits to +$58/day; under an honest L2-queue model with an
action space that cannot inherit the inside-quote artifact, **no policy over the observable
state can overfit to profit at all** (best stable result +$0.7/day).

**BTC is the control that confirms the mechanism.** BTC's natural spread is 1 tick, so no
action in the RL's action space (which starts at 5 ticks) can land inside it. BTC RL is
therefore forced into the honest regime by construction — and loses (−$2.09/day, 0% win),
exactly as LINK does once forced honest. *The asset that cannot produce the artifact produces
no profit.*

**Queue-position sensitivity** (at-touch, L2 queue model): PnL/day falls from +$11.8 at the
front of the queue (9 LINK ahead) to a +$1.0/day, −2.9 bps-markout noise floor at a realistic
retail queue position (4,313 LINK ahead). From ~5% of visible depth onward, the only fills
that clear the queue are informed sweeps moving against the maker.

**The unified law (C30):**

> Every positive backtest result in this project lives inside the natural spread under a
> no-queue fill model. Every result in the physically honest regime — outside the spread, or
> at-touch behind a realistic L2 queue — is ≈0 or negative. This holds across both assets
> (BTC, LINK) and both strategy classes (classical, RL). The "edge" is not a strategy edge; it
> is a **queue-priority rent**.

### 2.3 The corrected engine strengthens the verdict (exp 62, June 2026)

A later code audit found that the fill engine mis-handled *marketable-on-arrival* orders: an
order that becomes active (after its latency delay) into a market that has already moved
through its limit price was treated as a passive maker — filled at the stale limit and, under
the L2 queue model, forced to wait behind the same-side queue (so it usually never filled). In
reality such an order is a **taker**: it crosses the spread immediately and takes the opposing
liquidity, bypassing the same-side queue entirely.

The engine was corrected (commit `24a687f`): marketable-on-arrival orders now convert to taker
fills at the touch, priced from references at or before the activation timestamp (no
look-ahead), and verified against 6 unit tests and 5 integration invariants — including that
latency-0 results are byte-identical to the pre-fix engine (the bug is scoped entirely to
`latency > 0`).

Re-running the honest at-touch LINK strategy on the corrected engine, over all 30 April days,
with a realistic 4.5 bps taker fee applied to the now-correctly-identified crossing fills:

> **−$7.93/day, negative on 30 of 30 days** (≈10–15% of fills are toxic latency-adverse takers,
> with a 1-second markout of roughly −4 ticks).

The old engine was *systematically too generous* to the honest strategy, by burying these
latency-adverse crossings inside the queue model where they never resolved. Honest market
making is not marginal — it is **reliably money-losing** once latency adverse selection and a
realistic fee are priced. The inside-spread artifact, which never crosses the opposing quote
and therefore never converts to a taker fill, is unaffected by this correction — which is
itself diagnostic: the artifact and the honest regime are not just different magnitudes, they
are different *mechanisms*.

### 2.4 Why: the zero-profit equilibrium (C33d–e)

The synthetic experiments in §2.1 treat the mid-price volatility σ and the order-flow
parameters (arrival rate `A`, fill-decay `κ`) as **independent** — and this decoupling is the
*only* reason the synthetic market maker can be made arbitrarily profitable (dial the
vol-to-flow ratio `σ²/(Aκ)` low). In a real order-driven market, σ and order flow are the same
underlying process, and the coupling pins `κ` to `σ`:

1. **Volatility is flow.** Over an interval `t` there are `N = A·t` trades, so
   `σ_$² · t = N · σ_trade²`, giving `σ_trade = σ_$ / √A` — the volatility *per trade*, which
   is the irreducible adverse-selection cost between quoting and being filled.
2. **Market-maker zero-profit.** Free entry competes the half-spread down to `δ* ≈ σ_trade`.
   The fill curve decays on scale `1/κ`; in equilibrium the quoted spread sits at that scale,
   giving `κ_equilibrium ≈ √A / σ_$` — κ *falls* as σ rises.

This was confirmed directly (`equilibrium_pinning.py`, with a fraction φ = 0.5 of takers
trading in the direction of the next 5-second move, i.e. genuine adverse selection). Locating
the breakeven half-spread `δ_be(σ)`:

| σ_$ | fixed-κ 2-tick quoter PnL | δ_be (ticks) | δ_be / σ_$ | implied κ = 1/δ_be |
|---|---|---|---|---|
| 0.02 | +$118 | 2.0 (floored) | 100 | 0.500 |
| 0.05 | −$540 | 3.9 | 77.5 | 0.258 |
| 0.10 | −$1,436 | 7.6 | 76.0 | 0.132 |
| 0.20 | −$2,843 | 15.2 | 75.9 | 0.066 |

`δ_be / σ_$` is constant at ≈76 across a 10× range of σ — the breakeven half-spread is
**linear in σ**, exactly the Wyart–Bouchaud "spread ≈ volatility per trade" law. The
market-clearing `κ` therefore falls as `1/σ`. A fixed-κ quoter (the implicit assumption of
§2.1's synthetic profitability) is in *disequilibrium*: profitable while σ is small,
catastrophic once σ exceeds the level its spread was calibrated for. At the equilibrium κ, the
spread premium exactly equals the adverse-selection cost: **E[honest profit] = 0**. Breakeven
is the fixed point of the system, not an artifact of this dataset.

**Unification with C30.** `δ* ≈ σ_$ / √A` assumes the quoted spread is free to move. On a
**large-tick** asset such as LINK, the spread is floored at one tick and cannot tighten to
`δ*` — so the market enforces the *same* zero-profit condition on the **queue-depth** axis
instead: the touch queue grows until the marginal back-of-queue order breaks even. This is
precisely the ~8,600 LINK observed in C20/C30. The Wyart–Bouchaud spread equilibrium
(small-tick assets, e.g. BTC) and the C30 queue-priority rent (large-tick assets, e.g. LINK)
are **the same zero-profit law**, enforced through whichever variable is free — spread width
or queue position. Queue priority is the scarce, retail-inaccessible resource *precisely
because* the spread lever is jammed on large-tick assets.

### 2.5 The unifying frame: market making as a short straddle (C35)

Tracking inventory `q(t)` as the *delta* of the book: a passive maker's ask is lifted as price
rises (`q` falls) and bid is hit as price falls (`q` rises), so `dq/dS < 0` — a
**linear-decreasing delta**, i.e. negative gamma. This is not an analogy; a resting two-sided
quote literally *is* a written straddle (the bid a written put, the ask a written call;
Copeland & Galai, 1983). Total P&L decomposes as

```
dPnL = δ · dN        (spread capture, per fill)                         ← THETA
     + q · dS        (inventory mark-to-market)                          ← DELTA · dS
```

and, with `q ≈ −(φ/Δ)(S − S_ref)`, the inventory term integrates to
`∫ q dS ≈ −½(φ/Δ)(ΔS)²` — a **gamma bleed** proportional to realised `(ΔS)²`, the exact
functional form of `−½|Γ|(dS)²` in the Black–Scholes P&L identity `Θ = −½σ²S²Γ`. Every term
maps:

| Market making | Short straddle |
|---|---|
| half-spread `δ` per fill | option premium / implied vol |
| spread-capture rate `δ·dN/dt` | theta |
| inventory `q` | delta |
| fill intensity / tick `φ/Δ` | gamma |
| `∫q dS ≈ −½(φ/Δ)(ΔS)²` | gamma bleed |
| inventory skew (reservation shift) | delta hedging |
| spread widens with σ (`δ* ∝ σ`, §2.4) | short vega |

**§2.4's zero-profit law is the Black–Scholes fair-pricing identity, transplanted into
spread/queue variables.** A short straddle written at fair implied vol has E[P&L] = 0 by
construction (theta exactly funds expected gamma bleed); the competitive market-making spread
`δ* ≈ σ_trade` does the same.

**Where the analogy breaks — and why this is the thesis.** A textbook short-gamma book assumes
the underlying is exogenous (`E[dS]=0`, only the `(dS)²` bleed matters). A maker's fills are
*selected*: the counterparty lifting the ask may be informed, so `E[dS | filled] ≠ 0` — an
adverse **drift** layered on top of the symmetric bleed (Bagehot/Treynor, 1971; Glosten &
Milgrom, 1985). The book therefore has two layers:

- **Layer 1 — symmetric short gamma**, present even with uninformed flow (the synthetic
  −$920 in §2.1). *Curable* by charging enough spread (theta).
- **Layer 2 — adverse-selection drift**, the informed-counterparty selection effect. This is
  what makes the *competitive* spread adverse-selection-driven and the honest markout
  negative even after the spread is collected.

Queue priority is the Layer-2 defence with no options analog: being early in the queue means
being filled by *uninformed* flow before the informed arrive. The foresight oracle (§2.6,
C34) attacks Layer 2 from the other side — knowing the future `dS` lets you decline adverse
fills. **Both convert the breakeven book to profit; both are retail-inaccessible.**

#### C37 — Mapping the curable boundary of Layer 1 (exp 59, Parts E–F, June 2026)

Because the synthetic high-volatility world (§2.1, σ = 0.20) is Layer-1-only, its short-gamma
loss should be fully curable by pricing. Contribution 37 confirms this with a systematic lever
sweep (`experiments/59_synthetic_engine_validation/`), with a sharp boundary:

- **Widening alone** (2t → 6t) lifts −$514 → +$67, but is marginal and noisy (50% days
  positive).
- **Inventory skew** *hurts the mean* while crushing variance — a pure mean-for-variance
  trade, since the cost here is a drift, not variance.
- **Speed alone** (requote 0.5s → 0.05s) turns −$898 → +$169 (80% days positive) — but
  **only at exactly zero latency**; at the same configuration, 20 ms latency is already
  −$95/day.
- **Widen + speed jointly**, however, is materially better than either alone: at 8 ticks and a
  0.05 s requote, the high-volatility world is robustly profitable (+$188 to +$463/day, 60–90%
  days positive) across the *entire* 0–100 ms latency range, only collapsing at 200 ms
  (−$581/day).

This sharpens, but does not overturn, the Layer-1/Layer-2 boundary: an 8-tick resting quote
that is profitable against *uninformed* flow at realistic latency is, on a real venue, exactly
the stale, easy-to-pick-off level that Layer-2 informed flow targets (the deep-reversion
mechanism of C32). The result is useful precisely because it isolates *how good* the curable
Layer-1 problem can be made — and shows that even its best-case corner does not survive contact
with Layer 2.

### 2.6 Closing the alternatives

Three further hypotheses — each a candidate for an edge that does *not* require queue
priority — were tested and each closes, for related but distinct reasons.

**(a) Deep / patient liquidity provision (C32) — refuted.** If informed flow only crosses the
narrow touch, perhaps resting deeper in the book and waiting avoids it. Tested via both a
risk-gated "sit unless conditions change" policy and direct deep-limit reversion analysis: a
price move large enough to *reach* a deep resting limit is, by that very fact, selectively
informed and tends to *continue* rather than revert (adverse selection **by selection**).
Reversion is shallow (8–50 ticks), vanishes by 50 ticks, and is strongly negative beyond, on
both assets and with a censoring-robust (touch-based) re-measurement. The only positive zone
remains the touch — i.e. the queue-rent regime of C30.

**(b) The maker→taker pivot (C31) — a real signal, but fee-gated.** A taker crosses the spread
for an instant fill and needs no queue priority, sidestepping the entire C30 artifact. The
signal is genuinely real and queue-independent: top-decile momentum/OBI is positive on 100% of
days tested (including volatile periods), survives a random-direction control (which floors at
the spread, −1.7 ticks, ruling out look-ahead), and is essentially latency-insensitive (10 ms
to 500 ms barely moves it — the edge plays out over seconds, not milliseconds). But the
per-trade edge is capped at **≈1.1 bps** and *nothing* moves it: neither selectivity (top
decile vs. top 0.1%), nor combining signals, nor a longer hold, nor — critically — XGBoost,
which performs marginally *worse* than the simple OBI signal in both training and OOS regimes
despite a genuinely higher directional AUC (0.75). This is a **predictability wall**, not a
tooling gap. Net of a realistic perpetual taker fee (≈3.6 bps round trip), the edge is
negative everywhere; net of spot taker fees (≈15 bps) it is hopeless.

**(c) Cross-venue spot↔perpetual lead-lag (C36) — closed, no third door.** The one remaining
untested hypothesis was that a *cross-venue* lead-lag could supply a **larger** signal — the
only lever that could produce a bigger edge rather than just a cheaper cost, potentially
escaping both the queue gate and the fee gate at once. Tested on LINK spot vs. perpetual,
30 days. A naive 1-second-grid BBO cross-correlation reported "spot leads perp by ~1 second"
(ρ = 0.31) — but the perpetual's top-of-book updates only once per second (an
orderbook-snapshot artifact), so it *always* appears one second stale on a 1-second grid. The
**Hayashi–Yoshida estimator** (Hayashi & Yoshida, 2005; lead–lag contrast: Hoffmann, Rosenbaum
& Yoshida, 2013) on trade-vs-trade prices — asynchronous, event-time, immune to this staleness
— overturns the naive reading entirely:

| θ (perp shift) | −1.0 s | −0.5 s | **0.0 s** | +0.5 s | +1.0 s |
|---|---|---|---|---|---|
| ρ(θ) | 0.196 | 0.214 | **0.236 (peak)** | 0.151 | 0.132 |

The cross-correlation peaks at **θ = 0** — the venues are contemporaneously integrated at the
100 ms–2 s scale that matters for a ~100 ms-latency retail strategy. A weak, diffuse
spot-leads tilt remains but is smeared across lags, not a sharp exploitable peak. Separately,
the perpetual's spread is 1 tick (BTC-like, ten times tighter than LINK spot) — so a passive
quote on the perpetual is forced outside its spread into the same honest/losing regime as
BTC (C24/C30); the perpetual offers **no inside-spread artifact** to substitute for the spot
one. The only surviving cross-venue construction — warehousing a position on one venue and
hedging directional continuation on the other — is a capital/infrastructure play (a
variance-risk-premium for *bearing risk*, C35's "practical corollary"), not a retail
microstructure edge, and requires two-venue infrastructure regardless. **This was the last
untested escape, and it closes negative.**

---

## 3. Synthesis: why this is necessary, not contingent

Put together, §2.1–2.6 form a closed loop rather than a list of negative results:

1. The machinery is shown sound by reproducing closed-form profitability where it must exist
   (§2.1).
2. Every observed profit in the realistic backtests is shown to come from exactly one source —
   an unmodelled queue-priority assumption (§2.2) — and correcting a second, related
   assumption (latency-adverse fills, §2.3) only deepens the honest loss.
3. The honest loss is shown to be the *equilibrium*, not a calibration failure: the same
   coupling of volatility and order flow that determines the fair spread also determines the
   fair queue-depth on assets where the spread cannot move (§2.4), and both are special cases
   of a single fair-pricing identity for a short-gamma position (§2.5).
4. Every structurally distinct attempt to step outside this equilibrium — deeper resting
   orders, instant taker fills, a second venue — is shown to re-encounter one of the same two
   gates (queue priority or information/fees) in a new guise (§2.6).

The two-gate meta-hypothesis — **every accessible "edge" in this market is gated by queue
priority (a maker problem) or by fee tier / information (a taker problem), and nothing tested
escapes both** — therefore stands not as an empirical summary of one dataset, but as a
consequence of how competitive liquidity provision prices risk.

---

## 4. Methodological contribution

Independent of the substantive (negative) result, this thesis contributes a **diagnostic that
generalises to any limit-order-book backtest, classical or RL**: decompose realised
profitability by the *quote regime relative to the natural spread, under the fill model's
queue-priority assumption*. Applied here, this diagnostic:

- explains a +5%/+24% Sharpe RL "outperformance" over a calibrated classical baseline as two
  measurements of the *same* artifact at different intensities, not as evidence of a learned
  edge (C30);
- predicts, from the natural spread alone, *which assets can produce the artifact* (BTC
  cannot; LINK can) — confirmed by both classical and RL results on both assets (C30);
- localises a latent engine bug (marketable-on-arrival mis-pricing) by identifying exactly
  which fills should, but did not, convert to taker fills (exp 62);
- separates "no edge exists" from "no edge is *causally accessible*" via the foresight-oracle
  construction (C34), turning a single negative number into two numbers that bound the size of
  the information/priority gate.

A backtest that does not report this decomposition cannot distinguish a genuine edge from a
queue-priority rent — a distinction this thesis shows to be the difference between
+$94/day and −$7.93/day on the *same* strategy and data.

---

## 5. Limitations and scope

- **Fees.** Most cells assume zero fees, making every negative result an *upper bound* on
  retail economics; the corrected-engine LINK result (§2.3) and the taker-pivot fee comparison
  (§2.6b) additionally apply realistic fees and remain negative.
- **Latency class.** All "retail" claims assume ~100 ms latency. Sub-100 ms (co-located HFT)
  is explicitly out of scope and is the regime to which queue priority and the C36 cross-venue
  caveat are *deferred*, not refuted.
- **Maker rebates.** Not modelled directly, but addressed in C30: rebates accrue only on
  fills, fills require queue priority, so a rebate is one more component of the same
  queue-priority rent rather than an escape from it.
- **Assets and period.** Binance spot BTC/USDT and LINK/USDT, May 2025 – April 2026, plus LINK
  perpetuals (April 2026) for C36. The BTC cross-asset symmetry check for C36 is blocked by a
  data-integrity issue in the BTC perpetual pull (perpetual trades ≈27% below spot at
  identical timestamps) and remains an open confirmatory item — it would strengthen, not alter,
  the verdict already established on LINK.
- **Order size.** Throughout, order sizes are assumed small relative to L1 depth (a price
  taker for sizing purposes), consistent with the retail framing.

---

## 6. Suggested further work

- **BTC re-run of C36** once clean perpetual trade data is available, to confirm the
  cross-venue closure is not LINK-specific.
- **Live order-placement validation**: the queue-position sensitivity in C30 was simulated via
  an L2 depth model; a small live-paper-trading study would directly measure realised queue
  position and validate the ~$1/day retail ceiling.
- **The capital/hedge construction** flagged in C35/C36 (warehouse + cross-venue hedge) is a
  distinct research question — a variance-risk-premium harvesting strategy — outside this
  thesis's retail-microstructure scope but a natural follow-on.

---

*Full reference list: see `thesis_contributions.md`, References section.*
