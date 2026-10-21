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
| 7 | `f7_immediacy_premium` | the premium is priced by spread width, and decays as competition arrives | exps 103, 111 |

Figures 4–7 read committed experiment JSONs directly. Figures 1–3 carry values in
`TABLE_*` constants transcribed from the contribution each cites, because those
experiments predate the current results layout.

## Reproducibility flags

Two numbers printed in **C66** could not be reproduced from the committed result
files under any single aggregation, and the figures therefore do **not** show
them. Both need either the original run recovered or the contribution corrected
before the chapter is defended.

1. **The per-coin round-trip table** (C66: HMSTR +20.6, USUAL +16.4, CELO/VINE
   +8–9, ZORA/EIGEN negative). Exp 103's inventory-aware round trip gives, as a
   mean over 2026-07-17/18 at qf=0.5:

   | coin | spread | C66 | exp 103 `none` | exp 103 `A+W` |
   |---|---|---|---|---|
   | HMSTR | 56 bps | +20.6 | +10.46 | +13.78 |
   | USUAL | 16 bps | +16.4 | +19.23 | +15.64 |
   | VINE  | 15 bps | +8–9  | +5.94  | +5.96 |
   | CELO  | 7.7 bps | +8–9 | +0.08  | +4.58 |
   | EIGEN | 7.6 bps | neg  | −2.54 ✓ | −5.79 ✓ |
   | ZORA  | 6.2 bps | neg  | −0.62 ✓ | +4.75 ✗ |

   `none` reproduces the *sign pattern* C66 argues for (the two tightest books
   fail) but not the magnitudes; `A+W` is the defended overlay that C64
   retracted, so it is not the right headline anyway. Figure 7a therefore plots
   the relationship C66 actually claims — round trip against spread width — from
   `none`, which is robust to the choice.

2. **The bridge control** (C66: USUAL +40 bps in July → +0.39 bps in August).
   No run key in exp 111 reproduces that pair. Closest are `blend_k1.5`
   (39.10 → 5.50) and `ewma_k2.5` (32.76 → 0.46). Figure 7b uses `micro_k1`
   (+23.5 → −0.3), named explicitly on the figure, since the micro-price anchor
   is the one Ch8 adopts. The *finding* — a large decay on an unchanged coin as
   the tail tightened — holds under every key tested; only the quoted pair does
   not.

A third, smaller discrepancy: Ch1 and Ch6 describe C62's benign pocket as
"+0.0 ± 0.3 bps". Across the ten asset-days in exp 97 it is **+0.15 ± 0.20 bps**.
Figure 4 panel 4 shows the distribution and states the measured value, which is
the stronger claim — the pocket is an order of magnitude below the cheapest
maker fee either way.
