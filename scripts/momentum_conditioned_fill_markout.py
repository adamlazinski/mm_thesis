"""
momentum_conditioned_fill_markout.py
=====================================
Cheap test of the "momentum + passive limit orders" idea, before building a
new backtest engine for it.

Idea: "I expect the market to go up, so I place a passive bid (queue
priority); if filled I'm long, and I exit via a limit sell once the market
has moved up." Symmetric for the short side (expect down -> passive ask ->
exit via limit buy).

Part F showed that, UNCONDITIONALLY, our fills (exp 64, honest queue model)
carry a strong adverse markout: after a buy fill the mid tends to FALL, after
a sell fill the mid tends to RISE -- the opposite of what either side of this
strategy needs.

This script asks: does conditioning on the OFI signal (trailing 60s taker
buy/sell imbalance) AGREEING with the position direction at fill time change
that picture? I.e. among buy fills where OFI>0 (bullish flow, consistent with
"I expect market to go up"), is the post-fill path less adverse / actually
favorable, compared to all buy fills or to OFI<0 buy fills?

raw_markout (positive = good for the position just entered by the fill):
  buy fill : close[t+k] - close[t]   (we're long, want price up)
  sell fill: close[t] - close[t+k]   (we're short, want price down)

(this is the NEGATIVE of Part F's "adverse magnitude" convention)

Run from master2/ root with .venv activated:
    python scripts/momentum_conditioned_fill_markout.py
"""

from __future__ import annotations

import glob

import numpy as np
import pandas as pd

RESULTS_DIR = "experiments/64_glft_calibrated/results"
HORIZONS = {"0.6s": 1, "3s": 5, "6s": 10, "12s": 20, "36s": 60}

files = sorted(glob.glob(f"{RESULTS_DIR}/*_view.parquet"))
print(f"Found {len(files)} days\n")

max_k = max(HORIZONS.values())

buy_ofi, sell_ofi = [], []
buy_markout = {h: [] for h in HORIZONS}
sell_markout = {h: [] for h in HORIZONS}

for f in files:
    df = pd.read_parquet(f)
    close = df["close"].values
    ofi = df["ofi"].values
    dinv = df["inv"].diff().values
    n = len(df)

    buy_idx = np.where(dinv > 5e-4)[0]
    sell_idx = np.where(dinv < -5e-4)[0]
    buy_idx = buy_idx[buy_idx + max_k < n]
    sell_idx = sell_idx[sell_idx + max_k < n]

    buy_ofi.append(ofi[buy_idx])
    sell_ofi.append(ofi[sell_idx])

    for h, k in HORIZONS.items():
        buy_markout[h].append(close[buy_idx + k] - close[buy_idx])
        sell_markout[h].append(close[sell_idx] - close[sell_idx + k])

buy_ofi = np.concatenate(buy_ofi)
sell_ofi = np.concatenate(sell_ofi)
for h in HORIZONS:
    buy_markout[h] = np.concatenate(buy_markout[h])
    sell_markout[h] = np.concatenate(sell_markout[h])

print(f"Buy fills:  {len(buy_ofi):,}")
print(f"Sell fills: {len(sell_ofi):,}")

# ------------------------------------------------------------------
# 1. Split by OFI sign at fill time
# ------------------------------------------------------------------
print("\nBuy fills (we go long): raw markout = E[close(t+k)-close(t)]"
      "  (positive = good for the long)")
print(f"{'horizon':>8} {'all':>10} {'OFI>0 (signal agrees)':>22} "
      f"{'OFI<0 (signal disagrees)':>24}")
for h in HORIZONS:
    m = buy_markout[h]
    pos = m[buy_ofi > 0]
    neg = m[buy_ofi < 0]
    print(f"{h:>8} {m.mean():10.4f} {pos.mean():22.4f} {neg.mean():24.4f}")

print(f"\n  P(OFI>0 | buy fill) = {100*(buy_ofi > 0).mean():.1f}%  "
      f"(n={(buy_ofi > 0).sum():,} of {len(buy_ofi):,})")

print("\nSell fills (we go short): raw markout = E[close(t)-close(t+k)]"
      "  (positive = good for the short)")
print(f"{'horizon':>8} {'all':>10} {'OFI<0 (signal agrees)':>22} "
      f"{'OFI>0 (signal disagrees)':>24}")
for h in HORIZONS:
    m = sell_markout[h]
    pos = m[sell_ofi < 0]
    neg = m[sell_ofi > 0]
    print(f"{h:>8} {m.mean():10.4f} {pos.mean():22.4f} {neg.mean():24.4f}")

print(f"\n  P(OFI<0 | sell fill) = {100*(sell_ofi < 0).mean():.1f}%  "
      f"(n={(sell_ofi < 0).sum():,} of {len(sell_ofi):,})")

# ------------------------------------------------------------------
# 2. Quantile bins of OFI, to check for a monotonic relationship
# ------------------------------------------------------------------
NBINS = 5

print(f"\nBuy fills, by OFI quintile -- raw markout at 0.6s / 12s / 36s:")
edges = np.quantile(buy_ofi, np.linspace(0, 1, NBINS + 1))
edges[0] -= 1e-9
bin_idx = np.clip(np.digitize(buy_ofi, edges) - 1, 0, NBINS - 1)
for b in range(NBINS):
    mask = bin_idx == b
    print(f"  OFI in [{edges[b]:+.3f},{edges[b+1]:+.3f}]  n={mask.sum():7d}  "
          f"mean_ofi={buy_ofi[mask].mean():+.4f}   "
          f"m_0.6s={buy_markout['0.6s'][mask].mean():8.4f}  "
          f"m_12s={buy_markout['12s'][mask].mean():8.4f}  "
          f"m_36s={buy_markout['36s'][mask].mean():8.4f}")

print(f"\nSell fills, by OFI quintile -- raw markout at 0.6s / 12s / 36s:")
edges = np.quantile(sell_ofi, np.linspace(0, 1, NBINS + 1))
edges[0] -= 1e-9
bin_idx = np.clip(np.digitize(sell_ofi, edges) - 1, 0, NBINS - 1)
for b in range(NBINS):
    mask = bin_idx == b
    print(f"  OFI in [{edges[b]:+.3f},{edges[b+1]:+.3f}]  n={mask.sum():7d}  "
          f"mean_ofi={sell_ofi[mask].mean():+.4f}   "
          f"m_0.6s={sell_markout['0.6s'][mask].mean():8.4f}  "
          f"m_12s={sell_markout['12s'][mask].mean():8.4f}  "
          f"m_36s={sell_markout['36s'][mask].mean():8.4f}")

print("\nDone.")
