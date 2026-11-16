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

Figures 4–7 read committed experiment JSONs directly. Figures 1–3 carry values in
`TABLE_*` constants transcribed from the contribution each cites, because those
experiments predate the current results layout.

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
