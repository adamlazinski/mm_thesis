# Exp 61 — LINK Spot ↔ Perp: the Cross-Venue Escape Is Closed

**Purpose.** Test the one unrefuted hypothesis in the register: that a *cross-venue
spot↔perp lead-lag* yields a **larger** signal than the within-venue ones (the only
lever that could produce a bigger edge rather than just a cheaper cost). LINK April
2026, 30 days, spot + perp trades/quotes/L2.

## 1. Spread & basis

- **Dollar spreads: spot $0.0100, perp $0.0010 — perp is 10× tighter.** At the true
  $0.001 LINK tick, spot sits at its 10-tick natural spread; perp trades at 1 tick.
  Confirms exp 54: the perp is the tight, liquid (BTC-like) venue.
- **Basis: perp ≈ $0.0049 below spot** (~−5.5 bps), stable (funding-related).

## 2. Lead-lag — the make-or-break number

**BBO cross-correlation (1 s grid) was confounded.** It reported "spot leads perp by
~1 s" (ρ=0.31 at −1s), but the perp BBO is sampled at **1 Hz** (orderbook-snapshot
rate), so the perp mid is a stale snapshot and *always* looks like it lags — a pure
sampling artifact.

**Hayashi–Yoshida, trade-vs-trade (event-time, asynchronous, no gridding) is the clean
measurement** and it overturns the artifact:

| θ (perp shift) | −1.0s | −0.5s | **0.0s** | +0.5s | +1.0s |
|---|---|---|---|---|---|
| ρ(θ) | 0.196 | 0.214 | **0.236 (peak)** | 0.151 | 0.132 |

- **Peak at θ = 0.0 s — contemporaneous.** Spot and perp move together; the strong
  1 s "spot leads" was the 1 Hz BBO staleness.
- A **mild, diffuse spot-leads tilt** remains (Σρ spot-side 3.93 vs perp-side 2.71) but
  it is weak and smeared across lags — not a sharp, exploitable peak.

## 3. Verdict

- **The lead-lag *signal* route is closed.** No exploitable cross-venue lead at the
  100 ms–2 s scale; the venues are contemporaneously integrated. "Trade spot using
  perp's lead" has no foundation — perp does not lead, and the mild spot tilt is not
  sharp enough to beat costs.
- **The perp does not rescue passive making.** Its 1-tick spread is BTC-like, forcing
  any maker outside the spread → the honest/losing regime (C24/C30 mechanism); no
  inside-spread artifact is available on the perp.
- **The only surviving cross-venue angle is the capital/hedge play** (warehouse on
  spot, hedge the directional continuation on perp) — a *variance-risk-premium for
  risk-bearing* (C35), not retail alpha, requiring two-venue infrastructure. It does
  not open a third door.

**Caveat.** Resolution is ~100 ms (trade frequency ~4/s limits finer); a *sub-100 ms*
HFT-race lead cannot be excluded — but that is below the 100 ms latency assumption and
squarely in the infrastructure-gated regime, irrelevant to a retail strategy.

**Conclusion.** The last open question resolves **negative for a retail edge**: spot↔perp
are contemporaneously integrated with no exploitable lead-lag, and the perp's tight spread
reproduces the BTC no-artifact loss. The two-gate meta-verdict stands — there is no third
door in cross-venue.

## Cross-asset (BTC) check — blocked by BTC perp data integrity

Attempting the same HY check on BTC (Apr 14–15, the only BTC spot days) surfaced a
**data-integrity problem in the BTC perp files, not a result**: at identical wall-clock
times the BTC **spot** trades sit at ~$101.7k while the BTC **perp** trades sit at
~$74.5k — a ~27% gap, impossible as funding basis (real spot↔perp basis is <0.5%). The
spot level matches the thesis's BTC (~$101k); the perp series (~$68k on Apr 1 drifting to
~$74k) is internally consistent but ~30% below where BTC actually traded, i.e. the BTC
perp pull appears mislabeled or from a different period/instrument. The HY cross-correlation
was ≈0 at all lags precisely because the two series are not the same price. **The BTC
cross-asset symmetry check cannot be run until the BTC perp data is re-pulled.** The LINK
result above is unaffected (LINK perp basis ≈ −5.5 bps is sane).

The estimator (`hy_leadlag.py`) was generalised in the process — it now handles all three
timestamp encodings in the dataset (epoch-ns int64; tz-aware datetime64; float
seconds-from-midnight reconciled to epoch) and any `--symbol`, so it is ready to run on BTC
the moment clean perp data exists.

Reproduce:
```
python experiments/61_link_spot_perp/characterize.py --days 30              # spread, basis, BBO lead-lag
python experiments/61_link_spot_perp/hy_leadlag.py  --symbol LINK --days 30 # Hayashi-Yoshida trade lead-lag
```
