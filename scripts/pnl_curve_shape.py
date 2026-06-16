"""
pnl_curve_shape.py
===================
Quick look at the SHAPE of the PnL curve for exp 64 (closed-form GLFT, calibrated):
is it a near-linear bleed, or a noisy path with local up-runs that nets negative?

Uses the per-step `pnl` (mark-to-market total PnL) column already saved in
`_view.parquet` (quote_log resolution, ~0.5-0.6s).

Run from master2/ root with .venv activated:
    python scripts/pnl_curve_shape.py
"""

from __future__ import annotations

import glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RESULTS_DIR = "experiments/64_glft_calibrated/results"
files = sorted(glob.glob(f"{RESULTS_DIR}/*_view.parquet"))
print(f"Found {len(files)} days")

# ------------------------------------------------------------------
# 1. Plot a couple of representative days
# ------------------------------------------------------------------
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=False)
for ax, f in zip(axes, [files[0], files[4]]):
    df = pd.read_parquet(f)
    day = f.split("/")[-1].replace("_view.parquet", "")
    ax.plot(df.index, df["pnl"], lw=0.6, color="steelblue")
    ax.set_title(f"PnL curve — {day}  (final = ${df['pnl'].iloc[-1]:.2f})")
    ax.set_ylabel("PnL ($)")
    ax.axhline(0, color="gray", lw=0.5, ls="--")
fig.tight_layout()
fig.savefig("/tmp/pnl_curve_examples.png", dpi=130)
print("Saved /tmp/pnl_curve_examples.png")

# ------------------------------------------------------------------
# 2. Step-level statistics, pooled over all days
# ------------------------------------------------------------------
all_diffs = []
hourly_changes = []
run_lengths_up = []
run_lengths_down = []

for f in files:
    df = pd.read_parquet(f)
    diffs = df["pnl"].diff().dropna()
    all_diffs.append(diffs.values)

    # hour-of-day net pnl change
    tmp = df.copy()
    tmp["pnl_diff"] = tmp["pnl"].diff().fillna(0.0)
    tmp["hour"] = tmp.index.hour
    hourly_changes.append(tmp.groupby("hour")["pnl_diff"].sum())

    # run lengths of consecutive up/down moves (sign of diff)
    sign = np.sign(diffs.values)
    sign = sign[sign != 0]
    if len(sign):
        change_pts = np.where(np.diff(sign) != 0)[0] + 1
        runs = np.split(sign, change_pts)
        for r in runs:
            if r[0] > 0:
                run_lengths_up.append(len(r))
            else:
                run_lengths_down.append(len(r))

all_diffs = np.concatenate(all_diffs)
n = len(all_diffs)
n_up = (all_diffs > 0).sum()
n_down = (all_diffs < 0).sum()
n_flat = (all_diffs == 0).sum()

print(f"\nStep-level (n={n:,} steps, ~0.5-0.6s each, pooled over {len(files)} days):")
print(f"  steps PnL increases : {n_up:,} ({100*n_up/n:.1f}%)")
print(f"  steps PnL decreases : {n_down:,} ({100*n_down/n:.1f}%)")
print(f"  steps PnL unchanged : {n_flat:,} ({100*n_flat/n:.1f}%)")
print(f"  mean step diff      : {all_diffs.mean():.6f}")
print(f"  std  step diff      : {all_diffs.std():.6f}")
print(f"  mean(up) / mean(|down|): {all_diffs[all_diffs>0].mean():.6f} / "
      f"{-all_diffs[all_diffs<0].mean():.6f}")

print(f"\nRun lengths (consecutive steps moving same direction):")
print(f"  up-runs:   mean={np.mean(run_lengths_up):.2f}, "
      f"max={np.max(run_lengths_up)}, n={len(run_lengths_up)}")
print(f"  down-runs: mean={np.mean(run_lengths_down):.2f}, "
      f"max={np.max(run_lengths_down)}, n={len(run_lengths_down)}")

# ------------------------------------------------------------------
# 3. Hour-of-day pattern (averaged across days)
# ------------------------------------------------------------------
hourly_df = pd.concat(hourly_changes, axis=1)
hourly_df.columns = [f.split("/")[-1].replace("_view.parquet", "") for f in files]
mean_by_hour = hourly_df.mean(axis=1)
pos_frac_by_hour = (hourly_df > 0).mean(axis=1)

print(f"\nMean net PnL change by UTC hour-of-day (across {len(files)} days):")
for h in range(24):
    if h in mean_by_hour.index:
        print(f"  {h:02d}:00  mean=${mean_by_hour[h]:7.3f}   "
              f"P(hour net positive)={100*pos_frac_by_hour[h]:5.1f}%")

# 1-hour PnL changes, pooled
hour_changes_pooled = hourly_df.values.flatten()
hour_changes_pooled = hour_changes_pooled[~np.isnan(hour_changes_pooled)]
print(f"\nAcross all {len(hour_changes_pooled)} (day x hour) cells:")
print(f"  hours with NET POSITIVE pnl change: "
      f"{(hour_changes_pooled > 0).sum()} "
      f"({100*(hour_changes_pooled>0).mean():.1f}%)")
print(f"  mean hourly change: ${hour_changes_pooled.mean():.4f}, "
      f"std: ${hour_changes_pooled.std():.4f}")

fig2, ax2 = plt.subplots(figsize=(10, 4))
ax2.bar(mean_by_hour.index, mean_by_hour.values, color="steelblue")
ax2.axhline(0, color="gray", lw=0.5)
ax2.set_xlabel("UTC hour of day")
ax2.set_ylabel("Mean net PnL change ($)")
ax2.set_title("Mean hourly PnL change, averaged across 11 days (exp 64)")
fig2.tight_layout()
fig2.savefig("/tmp/pnl_hourly_pattern.png", dpi=130)
print("\nSaved /tmp/pnl_hourly_pattern.png")
