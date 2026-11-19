# Figures

Built by `scripts/make_figures.py` (run from the repo root with `.venv/bin/python3`).
Each figure writes a `.png` at 150 dpi for slides and a vector `.pdf` for the thesis.

| # | file | carries | source |
|---|---|---|---|
| 1 | `f1_quote_regime_decomposition` | Part I's central result: profit sits only where the fill model is dishonest, and the markout inverts where it is honest | C30 table (Ch5 §2) |
| 2 | `f2_queue_position_collapse` | the mechanism — P&L decays to a sub-$1/day floor by ~5% of visible depth | C30 table (Ch5 §2) |
| 3 | `f3_breakeven_equilibrium` | why the zero is *derived*: δ_be/σ_$ constant at ≈76 across a tenfold volatility range | exp 59 `equilibrium_pinning.json` |
| 4 | `f4_four_instruments` | Ch6 in one figure: markout / speed / observable state / counterparty identity, all terminating at zero | exps 93, 96, 97 + C60 |
| 5 | `f5_venue_clock_law` | Part II's organising law: the adverse-selection horizon spans three orders of magnitude and tracks the venue's clock | exp 93 (all dates) |
| 6 | `f6_dislocation` | the surviving alpha and its two gates, plus the common-clock robustness check | exp 99 (HL_BTC only) |
| 7 | `f7_immediacy_premium` | four of six tail books clear the base fee; the bridge control prices the premium by competition | exps 103, 111 |
| 8 | `f8_fill_curve` | the exponential-intensity premise A-S and GLFT share, against BTC's momentum floor and LINK's step function | `analysis/fill_intensity_calibration.json`, exp 44 |
| 9 | `f9_carry` | funding is contractual and positive on all four majors; the basis, not the funding, decides the outcome | exps 107, 108 |

Figures 3–9 read committed experiment JSONs directly. Figures 1 and 2 carry
values in `TABLE_*` constants, but those are no longer unverified transcriptions:
each was checked against its source data on 2026-11-16 (see below).

Figure 3 was converted to a direct read of exp 59 on 2026-11-16. The transcribed
version had rounded δ_be to 3.9 at σ_$ = 0.05 and then recomputed the ratio from
the rounded value, printing 78.0 where both the source and Ch5's table carry
77.5; the fitted constant moves from 76.7 to 76.5, i.e. the "about 76" the
chapters quote.

## Resolved: the C66 reproducibility gap (2026-11-16)

An earlier pass found that two numbers printed in **C66** could not be reproduced
from the committed results. The cause was that only two of the five captured days
had been committed for exp 103, and one of those two (2026-07-17) is a partial
10.3-hour session. Re-running exp 103 for 2026-07-19/20/21 across all six coins
completed the set to **thirty coin-days**, and C66 and Chapter 8 have been
corrected against it.

**What changed.** The per-coin table was wrong in both magnitude and membership:

| coin | measured spread | C66 (old) | 5-day, mid-marked | 5-day, **liquidated** | days positive |
|---|---|---|---|---|---|
| HMSTR | 56 bps | +20.6 | +14.40 | **+13.36** | 4/5 |
| USUAL | 16 bps | +16.4 | +12.91 | **+12.65** | 4/5 |
| ZORA | 6 bps | *negative* | +7.51 | **+7.42** | 4/5 |
| CELO | 8 bps | +8 to +9 | +3.49 | **+3.33** | 4/5 |
| VINE | 15 bps | +8 to +9 | +0.96 | **+0.63** | 4/5 |
| EIGEN | 8 bps | negative | −1.12 | **−1.16** | 2/5 |

The count of four-of-six clearing the 1.5 bps base fee survives; the identity of
the four does not — ZORA clears and VINE does not. C66's interpretation that "the
two tightest and most-competed books are negative" is **false**: ZORA is the
tightest book in the screen and the third most profitable. The per-coin
cross-section therefore supports the spread-width thesis only weakly
(Spearman ρ = 0.60, n = 6), and Chapter 8 now places that claim's weight on the
within-instrument bridge control instead.

The bridge control itself was quoted as +40 → +0.39 bps, which no run reproduces.
Verified, on the micro-price anchor Chapter 8 adopts: **+23.5 → −0.3 bps**, with
**15 of 16** anchor × distance configurations falling over the same two months
(median 24 bps). The spread compression 56 → 14 bps is confirmed exactly
(HMSTR in July, SAGA in August).

**Also corrected.** C62's benign pocket, described as "+0.0 ± 0.3 bps", is
**+0.15 ± 0.20 bps** across the ten asset-days in exp 97 — still an order of
magnitude below the cheapest 1.0 bps maker fee, so the argument strengthens.
Chapter 8 §2's screen table is a *screening snapshot*: the spreads actually
quoted during the capture differ (CELO 25 → 7.7, ZORA 16 → 6.2), and §5 relates
the round trip to the measured spread, which is contemporaneous with the P&L.

**Verified unchanged.** The exp 111 basket figures (+$243/day mid-anchored,
+$291 micro-anchored, micro ≥ mid on 4 of 5 days) reproduce exactly, as does the
basket being positive on all five days. Under the liquidated terminal treatment
(below) they are +$230 and +$278, with the comparison unaffected.

## The terminal-mark and sample-rule audits (2026-11-19)

Four reruns closed the four open methodological gaps the chapters had declared.
Figures 4, 5 and 7 are rebuilt against them; 1, 2, 3, 6, 8 and 9 are unaffected.

**Terminal mark (exps 103, 111 → F7).** Both round-trip simulators valued the
position left open at the end of a day at the final *mid*. They now book P&L on
matched volume by average cost and report the residual twice — marked at the mid,
and crossed out at the closing touch (`hft_market_maker/terminal_accounting.py`).
The two sum back to the old figure by construction, so every previously reported
number reproduces exactly. Pooled over the thirty coin-days: **+6.36 bps
mid-marked, +6.04 liquidated, +6.05 on matched volume only.** The mark carried
about five per cent, not the result. F7's bars are now the liquidated figures.
One reclassification: VINE's +0.96 was entirely terminal mark (−0.13 on matched
volume). An exp-111 configuration at k = 2.5 reported the sweep's highest margin
on 4.7 fills/day with *exactly zero* matched-volume P&L — it opens positions and
never closes one.

**Sample rule for the horizon curve (exp 93 → F4, F5).** Each horizon's markout
required a quote within 0.5 s of *t + h* and dropped the trade otherwise, with
the mask recomputed per horizon — a selection on the outcome, worst exactly where
the long readings came from (26% of VINE's and ZORA's trades retained at 10 s,
against 97–100% on Binance BTC). Redone with carry-forward quotes, right-censored
only past the last observed quote, with retention reported at every horizon under
three sample rules. **Every crossing moves later and none earlier:** HL_LINK
3.41 → 4.16 s and 0.94 → 1.35 s, HL_EIGEN 3.31 → 6.23 s, while Binance BTC holds
at 15 ms and Binance LINK at 73–79 ms to four decimals. The gate had been
flattering the slow books by keeping their busy-period trades. F5's caveat is
withdrawn and its censored tail now reads "> 10 s".

**Exit-side depth (exp 99 → F6).** The clip was capped by entry-side touch depth
and then unwound in full regardless of what rested on the exit. Now capped at
`min(entry, exit, cap)`. The correction is small — 6–16% of BTC events bind, at
most 7% of P&L — because the exit is five seconds after the event and the median
exit touch holds $0.2–0.7M against an entry touch of $1.3–8.5k. F6 is unchanged
in shape.

**GLFT on the corrected formula (exp 117).** Not a figure, but it closes the
scope note in Ch4 §3: the search winner rerun on the published closed form earns
+$25.44/day against the mis-transcribed +$88.56 and the flat control's +$149.45,
with mean markout per fill falling to +0.055 bps. C17 strengthens.


## Verification status (2026-11-16)

Part I's claims were checked against their committed data. Four reproduce exactly:

| claim | figure | source | result |
|---|---|---|---|
| C30 quote-regime decomposition | F1 | exp 53 spread sweep | **exact** — +$35.37/7,673, +$94.13/7,288, +$33.23/2,502, +$2.52/216 |
| C30 queue-position collapse | F2 | exp 53 queue sweep | **exact** — +$11.8, +$2.8, +$0.4, +$0.9, +$1.0 |
| C33 breakeven law | F3 | exp 59 | **exact** — ratios 100 / 77.5 / 76.0 / 75.9 |
| C20 fill-model gap | F8b | exp 44 | **exact** — 2.97% vs 0.073% at the touch (40.5×) |
| C29/C30 corrected engine | — | exp 62 | **exact** — −$7.93/day, 0/30 days positive |
| C67 carry | F9 | exps 107, 108 | **exact** — 6.74 / 1.65 / 8.39, Sharpe 1.26 |

One did not. **C34's foresight oracle**: the chapters quoted the pre-engine-fix
table (+$0.60 to +$4.06/day honest, $19.76–$30.03 oracle, 39.7–48.9% of fills
positive). C34 itself carries a corrected-engine update from exp 62 that the
chapters never picked up, and the committed JSON is the corrected run:

| horizon | causal $/day | oracle $/day | fraction positive |
|---|---|---|---|
| 1 s | **−9.78** | 28.62 | 0.359 |
| 10 s | −2.87 | 37.24 | 0.444 |
| 30 s | +1.35 | 47.24 | 0.482 |

The honest residue is not a small positive — it is negative before fees at the
horizons on which a maker turns inventory. This sharpens Part I: the
causal-versus-foresight gap widens. Corrected in Ch1, Ch5, Ch6, Ch10 and
`hypotheses.md`.

A related **unit error** surfaced during the check. Exp 53's configs are
half-spreads in basis points; Ch5 labelled them "2/4/5/8 ticks", which is the
invalid $0.001 grid of Contribution 54. On the true $0.01 tick at LINK's ~$9,
11.1 bps *is* one tick — which is why that row is "at touch". Ch4's and Ch5's
tables now quote basis points with true-tick equivalents.

Still unverified: the contributions outside Part I and C66/C67 — principally
C1–C15 and C25–C28, the microstructure characterisation behind Chapter 3, for
which no experiment pointers exist in the log. They are the remaining gap in the
verification sweep.

## Interval estimates (2026-11-19)

`thesis/intervals.md` now carries a 95% bootstrap interval for every headline
quantity, generated by `scripts/make_intervals.py` from the committed JSONs with
a fixed seed. Method in Chapter 3 §8: moving-block bootstrap for daily series,
cluster bootstrap on the coin for Chapter 8's thirty coin-days, effective sample
size for overlapping markout and event series, and an explicit multiplicity note
at each arg-max site. The figures do not yet plot intervals; the table is the
reference.
