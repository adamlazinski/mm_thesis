"""
adverse_selection_at_fills.py
==============================
Direct test of the adverse-selection / momentum-fill mechanism for exp 64
(closed-form GLFT, calibrated).

For every step where our inventory changes (a fill on our bid = "buy fill",
inventory +0.001; a fill on our ask = "sell fill", inventory -0.001), we look
at:

  1. The forward path of the mid price ("close") over the next few quote-log
     steps (~0.5-0.6s each). Adverse selection predicts: after a buy fill the
     mid tends to FALL, after a sell fill the mid tends to RISE -- i.e. the
     market continues in the direction of the flow that just filled us.

  2. The order-flow-imbalance ("ofi", trailing 60s taker buy/sell imbalance,
     range [-1,1]) recorded at the moment of the fill. Adverse selection
     predicts: buy fills (we got hit on our bid) cluster on NEGATIVE ofi
     (net taker selling pressure), sell fills cluster on POSITIVE ofi (net
     taker buying pressure) -- i.e. our fills are concentrated exactly when
     informed flow is running against the side we just took on.

Both are compared against the unconditional (all-steps) baseline.

Run from master2/ root with .venv activated:
    python scripts/adverse_selection_at_fills.py
"""

from __future__ import annotations

import glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RESULTS_DIR = "experiments/64_glft_calibrated/results"
ORDER_SIZE = 0.001  # BTC, from config.json
HORIZONS = [1, 2, 5, 10, 20, 40, 60]  # steps (~0.5-0.6s each)

files = sorted(glob.glob(f"{RESULTS_DIR}/*_view.parquet"))
print(f"Found {len(files)} days")

buy_paths = {k: [] for k in HORIZONS}
sell_paths = {k: [] for k in HORIZONS}
base_paths = {k: [] for k in HORIZONS}

buy_ofi = []
sell_ofi = []
all_ofi = []

n_buy_fills = 0
n_sell_fills = 0
dt_samples = []

for f in files:
    df = pd.read_parquet(f)
    close = df["close"].values
    ofi = df["ofi"].values
    dinv = df["inv"].diff().values
    n = len(df)

    # median step size in seconds, for labeling horizons
    t = df.index.values.astype("datetime64[ns]").astype("int64") / 1e9
    dt_samples.append(np.median(np.diff(t)))

    buy_idx = np.where(dinv > 5e-4)[0]   # ~+0.001
    sell_idx = np.where(dinv < -5e-4)[0]  # ~-0.001
    n_buy_fills += len(buy_idx)
    n_sell_fills += len(sell_idx)

    all_ofi.append(ofi[~np.isnan(ofi)])
    buy_ofi.append(ofi[buy_idx])
    sell_ofi.append(ofi[sell_idx])

    max_h = max(HORIZONS)
    valid_base = np.arange(0, n - max_h)
    for k in HORIZONS:
        buy_k = buy_idx[buy_idx + k < n]
        sell_k = sell_idx[sell_idx + k < n]
        buy_paths[k].append(close[buy_k + k] - close[buy_k])
        sell_paths[k].append(close[sell_k + k] - close[sell_k])
        base_paths[k].append(close[valid_base + k] - close[valid_base])

print(f"\nTotal buy fills (bid hit):  {n_buy_fills:,}")
print(f"Total sell fills (ask hit): {n_sell_fills:,}")

dt = np.median(dt_samples)
print(f"Median step size: {dt:.3f} s")

# ------------------------------------------------------------------
# 1. Forward mid-price path after fills vs baseline
# ------------------------------------------------------------------
print(f"\nForward mid-price change E[close(t+k) - close(t)], in $:")
print(f"{'horizon':>10} {'~sec':>6} {'after BUY fill':>16} {'after SELL fill':>16} {'baseline (all t)':>18}")

buy_means, sell_means, base_means = [], [], []
for k in HORIZONS:
    b = np.concatenate(buy_paths[k])
    s = np.concatenate(sell_paths[k])
    base = np.concatenate(base_paths[k])
    bm, sm, basem = b.mean(), s.mean(), base.mean()
    buy_means.append(bm)
    sell_means.append(sm)
    base_means.append(basem)
    print(f"{k:>10} {k*dt:6.1f} {bm:16.5f} {sm:16.5f} {basem:18.5f}")

# $ PnL impact on the just-traded 0.001 BTC clip
print(f"\nSame, scaled to $ impact on the {ORDER_SIZE} BTC clip just traded "
      f"(negative = adverse):")
print(f"{'horizon':>10} {'~sec':>6} {'buy-fill clip $':>16} {'sell-fill clip $':>16}")
for k, bm, sm in zip(HORIZONS, buy_means, sell_means):
    # buy fill: we are now long ORDER_SIZE -> P&L impact = ORDER_SIZE * d(mid)
    # sell fill: we are now short ORDER_SIZE (relative to before) -> impact = -ORDER_SIZE * d(mid)
    print(f"{k:>10} {k*dt:6.1f} {ORDER_SIZE*bm:16.6f} {-ORDER_SIZE*sm:16.6f}")

# ------------------------------------------------------------------
# 2. OFI at the moment of the fill vs baseline
# ------------------------------------------------------------------
all_ofi = np.concatenate(all_ofi)
buy_ofi = np.concatenate(buy_ofi)
sell_ofi = np.concatenate(sell_ofi)

print(f"\nOFI (trailing 60s taker buy/sell imbalance, [-1,1]) at fill time:")
print(f"  unconditional : mean={all_ofi.mean():+.4f}  median={np.median(all_ofi):+.4f}  "
      f"P(ofi<0)={100*(all_ofi<0).mean():.1f}%  P(ofi>0)={100*(all_ofi>0).mean():.1f}%")
print(f"  buy fills     : mean={buy_ofi.mean():+.4f}  median={np.median(buy_ofi):+.4f}  "
      f"P(ofi<0)={100*(buy_ofi<0).mean():.1f}%  (more negative = more taker SELLING "
      f"right when we bought)")
print(f"  sell fills    : mean={sell_ofi.mean():+.4f}  median={np.median(sell_ofi):+.4f}  "
      f"P(ofi>0)={100*(sell_ofi>0).mean():.1f}%  (more positive = more taker BUYING "
      f"right when we sold)")

# ------------------------------------------------------------------
# 3. Plot
# ------------------------------------------------------------------
secs = np.array(HORIZONS) * dt
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

ax = axes[0]
ax.plot(secs, buy_means, "o-", color="tab:green", label="after BUY fill (we hold +0.001 BTC)")
ax.plot(secs, sell_means, "o-", color="tab:red", label="after SELL fill (we hold -0.001 BTC)")
ax.plot(secs, base_means, "--", color="gray", label="unconditional baseline")
ax.axhline(0, color="black", lw=0.5)
ax.set_xlabel("seconds after fill")
ax.set_ylabel("E[mid(t+k) - mid(t)]  ($)")
ax.set_title("Forward mid-price move after our fills")
ax.legend(fontsize=8)

ax = axes[1]
bins = np.linspace(-1, 1, 41)
ax.hist(all_ofi, bins=bins, density=True, histtype="step", color="gray", label="all steps")
ax.hist(buy_ofi, bins=bins, density=True, histtype="step", color="tab:green", label="buy fills")
ax.hist(sell_ofi, bins=bins, density=True, histtype="step", color="tab:red", label="sell fills")
ax.axvline(0, color="black", lw=0.5)
ax.set_xlabel("OFI (trailing 60s)")
ax.set_ylabel("density")
ax.set_title("OFI at moment of fill vs unconditional")
ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig("/tmp/adverse_selection_at_fills.png", dpi=130)
print("\nSaved /tmp/adverse_selection_at_fills.png")
