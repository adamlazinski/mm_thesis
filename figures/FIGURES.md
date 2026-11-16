# Figures

Built by `scripts/make_figures.py` (run from the repo root with `.venv/bin/python3`).
Each figure writes a `.png` at 150 dpi for slides and a vector `.pdf` for the thesis.

| # | file | carries | source |
|---|---|---|---|
| 1 | `f1_quote_regime_decomposition` | Part I's central result: profit sits only where the fill model is dishonest, and the markout inverts where it is honest | C30 table (Ch5 §2) |
| 2 | `f2_queue_position_collapse` | the mechanism — P&L decays to a sub-$1/day floor by ~5% of visible depth | C30 table (Ch5 §2) |
| 3 | `f3_breakeven_equilibrium` | why the zero is *derived*: δ_be/σ_$ constant at ≈77 across a tenfold volatility range | C33 table (Ch5 §7) |
| 4 | `f4_four_instruments` | Ch6 in one figure: markout / speed / observable state / counterparty identity, all terminating at zero | exps 93, 96, 97 + C60 |
| 5 | `f5_venue_clock_law` | Part II's organising law: the adverse-selection horizon spans three orders of magnitude and tracks the venue's clock | exp 93 (all dates) |
| 6 | `f6_dislocation` | the surviving alpha and its two gates, plus the common-clock robustness check | exp 99 (HL_BTC only) |
| 7 | `f7_immediacy_premium` | four of six tail books clear the base fee; the bridge control prices the premium by competition | exps 103, 111 |
| 8 | `f8_fill_curve` | the exponential-intensity premise A-S and GLFT share, against BTC's momentum floor and LINK's step function | `analysis/fill_intensity_calibration.json`, exp 44 |
| 9 | `f9_carry` | funding is contractual and positive on all four majors; the basis, not the funding, decides the outcome | exps 107, 108 |

Figures 4–9 read committed experiment JSONs directly. Figures 1–3 carry values in
`TABLE_*` constants, but those are no longer unverified transcriptions: each was
checked against its source data on 2026-11-16 (see below).

## Resolved: the C66 reproducibility gap (2026-11-16)

An earlier pass found that two numbers printed in **C66** could not be reproduced
from the committed results. The cause was that only two of the five captured days
had been committed for exp 103, and one of those two (2026-07-17) is a partial
10.3-hour session. Re-running exp 103 for 2026-07-19/20/21 across all six coins
completed the set to **thirty coin-days**, and C66 and Chapter 8 have been
corrected against it.

**What changed.** The per-coin table was wrong in both magnitude and membership:

| coin | measured spread | C66 (old) | verified 5-day | days positive |
|---|---|---|---|---|
| HMSTR | 56 bps | +20.6 | **+14.40** | 5/5 |
| USUAL | 16 bps | +16.4 | **+12.91** | 4/5 |
| ZORA | 6 bps | *negative* | **+7.51** | 4/5 |
| CELO | 8 bps | +8 to +9 | **+3.49** | 4/5 |
| VINE | 15 bps | +8 to +9 | **+0.96** | 4/5 |
| EIGEN | 8 bps | negative | **−1.12** | 2/5 |

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
basket being positive on all five days.


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

Still unverified: the contributions outside Part I and C66/C67, which have not
been checked against their data in this way.
