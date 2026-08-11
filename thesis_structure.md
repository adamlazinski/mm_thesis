# Thesis Structure and Writing Plan

Supersedes the provisional 7-chapter plan drafted 2026-06-16, which predates the
live multi-venue capture (C55+), the tick-misspecification correction (C54), and
the three affirmative results. That plan's central narrative — queue-priority
verdict with OBI-skew as the exception — is obsolete: C54 removed the exception,
and the capture arc replaced it with a stronger and differently shaped argument.

---

## 1. Central claim

Competitive, retail-accessible market making on lit crypto venues earns **exactly
zero** — not approximately, not negative-after-costs, but pinned to the
competitive equilibrium. This is the Glosten–Milgrom zero-profit condition,
measured live with four mutually independent instruments. Every apparently
profitable backtest in this project decomposed into one of five accounting
illusions. What survives honest accounting is never a *signal*: it is
compensation for bearing a **structural risk** — latency exposure, inventory and
jump risk in thin books, or basis risk across venues.

**One sentence:** *markets pay for risk-bearing and structural position, not for
prediction a single participant can compute.*

## 2. Research questions

- **RQ1** Can a retail-accessible market maker earn positive risk-adjusted P&L on
  lit crypto books, once fills, queue position, ticks, and fees are modelled
  honestly?
- **RQ2** If not, *why* — is the constraint signal quality, speed, or structure?
- **RQ3** What distinguishes the strategies that appear profitable in backtest
  from those that survive honest accounting?
- **RQ4** What, if anything, does survive — and what is it compensation *for*?

## 3. Chapter structure

### Foundations

**Ch1 — Introduction.** `thesis_introduction.md` — DRAFTED (1,917w).
*Revision needed:* headline result and contribution roadmap now cover both halves;
§6 structure section must be rewritten to this plan.

**Ch2 — Theoretical Background.** `thesis_theory.md` — DRAFTED (3,999w).
*Additions needed:* Grossman–Miller (immediacy premium — the theory behind Part II
Ch8); Stoikov micro-price (the fair-value anchor, exp 111); Bergault–Guéant
multi-asset closed forms (§, with the measured 0.04-tick cross-asset skew showing
it quantizes away on one-tick books).

**Ch3 — Data, Venues and Methodology.** `thesis_data_methodology.md` — DRAFTED
(2,662w) but covers only CoinAPI 2025.
*Major addition:* the 2026 live capture — four venues (Binance spot+perp,
Coinbase spot+perp, Hyperliquid majors + tail), collectors, raw-first design,
reconstruction and integrity checks (C55). Plus a new section stating the
**honest-accounting discipline** as method: exchange-valid ticks, real L2,
post-only, round-trip pricing at executable touches (never mark-to-mid), placebo
and anti-signal controls, OOS replication, depth-capped capacity, common-clock
validation.

### Part I — The Competitive Zero

**Ch4 — Apparent Profits: Classical and ML Strategies.** C16–C24.
Sets the puzzle: A-S/GLFT variants, OFI/momentum extensions, RL — all apparently
profitable. Ends by stating the puzzle rather than resolving it.

**Ch5 — The Anatomy of Illusory Profit.** C29–C35, C46–C54.
The five mirages, each dissected with the experiment that exposed it:
queue-priority artifacts (C30); tick mis-specification (C54); mark-to-mid
accounting (C60, and again in the exp-103 retraction); fee-tier fantasy
(C47/C53); maker fill-selection / winner's curse (exp 100). Includes the
corrected-engine work (C29/C32) and the foresight oracle (C34).

**Ch6 — The Zero, Measured Four Ways.** C55–C62.
The central chapter. Four independent instruments, one answer:
model-free Glosten–Milgrom markout (C59); speed/co-location (C60 + exp 95);
anonymous state (C61); counterparty identity (C62). Book geometry (C58) hardens
the premises; C56/C57 supply the sharpest signal and its failure to cross.

### Part II — The Boundary

**Ch7 — Cross-Venue Dislocation: Renting a Slow Venue's Clock.** C63.
Exps 89/90/99/109/110. The lead-lag hierarchy, the surviving taker alpha, its
capacity and fee gates, the premium-gate null (exp 109), and the clock-artifact
validation — the check that made the result stronger.

**Ch8 — The Immediacy Premium in Thin Books.** C66.
Exps 93/103/111 + the route-5 screen. Adverse-selection horizon by venue clock;
the defended-maker retraction; fair-value (micro-price) anchoring and quote
distance; the pre-registered fresh-sample replication and the bridge control that
showed the premium is priced by spread width (Grossman–Miller).

**Ch9 — Carry and the Funding Basis.** C67.
Exps 106/107/108. The intraday cointegration null; the cross-venue funding
differential; the delta-neutral book with basis mark-to-market; why realized
short-window carry is basis-dominated; the unmeasured cascade tail.

### Synthesis

**Ch10 — Conclusions.** `thesis_conclusions.md` — EXISTS (5,853w) but predates the
capture arc; needs substantial rewrite, not a light pass. Sections: headline
result; the evidentiary chain across both parts; why the zero is necessary rather
than contingent; the methodological contribution (including the two
self-retractions as evidence the discipline has teeth); limitations; further work.

## 4. Source of truth

`thesis_contributions.md` (36,983w, C1–C61) is the lab notebook and every chapter
is drafted from it. **C62–C67 must be written first** — they are the raw material
for Ch6–Ch9:

| entry | content | experiments |
|---|---|---|
| C62 | Wallet identity reaches the equilibrium exactly | 97 |
| C63 | The cross-venue dislocation taker, clock-validated | 99, 109, 110 |
| C64 | Maker withdrawal leads price; the defended-maker retraction | 102, 103 |
| C65 | Meta-order drift priced to the wall; flow-family closure | 98, 101, 104, 105 |
| C66 | Route 5: the immediacy premium and fair-value anchoring | 93, 103, 111 |
| C67 | Cointegration null and the funding-carry book | 106, 107, 108 |

## 5. Schedule (5 weeks)

- **Week 1** — C62–C67 into `thesis_contributions.md`; Ch3 capture + discipline sections.
- **Week 2** — Ch4, Ch5.
- **Week 3** — Ch6, Ch7.
- **Week 4** — Ch8, Ch9.
- **Week 5** — Ch1/Ch2 revisions; Ch10 conclusions rewrite; cross-reference and
  consistency pass; figures.

## 6. Conventions

Markdown per chapter, one top-level file, `## N. Section Title` headers, no
"Chapter N" prefix, plain-ASCII formulas with unicode Greek. Latency default 10ms.
Every number traceable to a committed experiment JSON.

## 7. Open items

- Length target not yet fixed; if the draft runs long, Ch8+Ch9 can merge into a
  single "Two Risk Premia" chapter.
- Figures not yet planned; candidates: the four-instrument zero, the
  adverse-selection horizon by venue clock, the lead-lag matrix, the route-5
  basket equity curve.
- Ch3 loose ends carried from June: survival-analysis vs two-component fill-rate
  framing; LINK tick $0.001 vs $0.01 in older derivations (C15/C25/C27).
