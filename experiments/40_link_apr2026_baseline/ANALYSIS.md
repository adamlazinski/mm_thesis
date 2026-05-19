# LINK April 2026 — Zero-Shot Transfer Baseline

**Period**: April 1–30 2026 (30 days)
**Asset**: LINK/USDT, CoinAPI tick data (Binance Spot)
**Tick size**: $0.001, **Order size**: 5 LINK ≈ $45–50
**Params**: unchanged from Jun–Jul 2025 IS winner (γ≈0, min_spread=6.44 bps, max_inv=38, limit=$25)

---

## Summary

| Metric | Value |
|---|---|
| Days run | 30 |
| Win rate | 30/30 (100%) |
| Mean PnL/day | +$43.78 |
| Total PnL | +$1,313.50 |
| Sharpe (daily, √365) | 38.7 |
| Max drawdown | $0.00 |
| Avg markout | +1.248 bps |
| Avg adverse fills | 22.0% |
| Avg fills/day | 7,577 |
| Avg quoted spread | 7.14 bps |

Mean PnL is lower than the Jun–Jul 2025 period (+$149/day) consistent with LINK trading
at ~$9 in April 2026 vs ~$13 in mid-2025 — same tick-count spread, lower notional per fill.
The mean-reversion edge persists 9+ months out of sample with zero recalibration.

---

## Figures

![Cumulative equity and daily PnL](analysis/fig1_equity_daily.png)
*fig1 — 30-day cumulative PnL and daily bars*

![Markout and adverse fills](analysis/fig2_markout.png)
*fig2 — Avg markout (bps) and % adverse fills per day*

![Fill count and quoted spread](analysis/fig3_fills_spread.png)
*fig3 — Daily fill count and avg quoted half-spread*

![Intraday Apr 17 (best day, +$121)](analysis/fig4_intraday_apr17.png)
*fig4 — Apr 17 intraday at 1-min resolution: PnL, inventory saw-tooth, mid price, spread*

![Intraday Apr 10 (quiet day, +$14)](analysis/fig5_intraday_apr10.png)
*fig5 — Apr 10 intraday at 1-min resolution: same panels on a lower-volume day*
