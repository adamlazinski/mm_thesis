"""
Experiment 52 — LINK Classical Market Making: Full Calibration Workflow
=======================================================================
Compares three strategies, all calibrated from exp 51 crossing intensity:

  1. A-S flat      — no inventory management (gamma~0), touch posting
  2. A-S calibrated v2 — kappa_as_min=2.08, gamma=3.57e-4 (~2-tick skew at max_inv)
  3. GLFT touch v2    — A=0.072, kappa=208, gamma=4.3, max_spread=11bps (touch posting)

A-S gamma×1000 hack removed; GLFT max_spread_bps caps formula spread at touch level.
All three post at ~1-tick touch; difference is purely in reservation price / inventory skew.

Outputs:
  fig1_daily_pnl.png         — daily P&L comparison
  fig2_cumulative_pnl.png    — cumulative P&L path
  fig3_spread_comparison.png — spread distributions
  fig4_inventory_sample.png  — inventory dynamics on a representative day
  fig5_skew_comparison.png   — reservation price skew vs inventory (theory)
  summary.json               — aggregate metrics
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EXP   = Path(__file__).parent
OUT   = EXP / 'analysis'
OUT.mkdir(exist_ok=True)

CONFIGS = {
    'as_flat':            ('A-S flat (γ≈0)',                     '#4878cf', '--'),
    'as_calibrated_v2':   ('A-S calibrated (γ=3.57e-4, 2-tick)', '#e06c75', '-'),
    'glft_touch_v2':      ('GLFT touch (γ=4.3, max=11bps)',       '#98c379', '-'),
}


# ------------------------------------------------------------------ #
#  Load summary CSVs                                                  #
# ------------------------------------------------------------------ #
summaries = {}
for key in CONFIGS:
    p = EXP / f'results_{key}' / 'summary.csv'
    if not p.exists():
        print(f'WARNING: {p} not found — skipping {key}')
        continue
    df = pd.read_csv(p)
    df = df[df['status'] == 'ok'].copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    summaries[key] = df
    print(f'{key}: {len(df)} days  total_pnl={df["total_pnl"].sum():.4f}')

if not summaries:
    print('No results found. Run the backtests first.')
    sys.exit(0)


# ------------------------------------------------------------------ #
#  Load view parquets for one sample day                             #
# ------------------------------------------------------------------ #
def load_view(key, date_str):
    p = EXP / f'results_{key}' / f'{date_str}_view.parquet'
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    return df

# Pick a representative day (first available in all strategies)
dates_all = set()
for df in summaries.values():
    dates_all.update(df['date'].dt.strftime('%Y-%m-%d').tolist())
sample_date = sorted(dates_all)[0]
print(f'\nSample day: {sample_date}')


# ================================================================== #
#  Fig 1 — Daily P&L comparison                                      #
# ================================================================== #
fig, ax = plt.subplots(figsize=(13, 5))
for key, (label, color, ls) in CONFIGS.items():
    if key not in summaries:
        continue
    df = summaries[key]
    ax.bar(np.arange(len(df)) + list(CONFIGS.keys()).index(key) * 0.25,
           df['total_pnl'],
           width=0.23, label=label, color=color, alpha=0.8)

ax.axhline(0, color='black', lw=0.8)
ax.set_xlabel('Day index')
ax.set_ylabel('Daily P&L ($)')
ax.set_title('LINK/USDT — Daily P&L: A-S vs GLFT (Apr 2026)')
ax.legend()
ax.grid(True, axis='y', alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / 'fig1_daily_pnl.png', dpi=150)
plt.close()


# ================================================================== #
#  Fig 2 — Cumulative P&L                                            #
# ================================================================== #
fig, ax = plt.subplots(figsize=(13, 5))
for key, (label, color, ls) in CONFIGS.items():
    if key not in summaries:
        continue
    df = summaries[key]
    cumul = df['total_pnl'].cumsum()
    ax.plot(df['date'], cumul, color=color, ls=ls, lw=2, label=label)
    ax.axhline(0, color='black', lw=0.7, ls=':')

ax.set_xlabel('Date')
ax.set_ylabel('Cumulative P&L ($)')
ax.set_title('LINK/USDT — Cumulative P&L: A-S vs GLFT (Apr 2026)')
ax.legend()
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig(OUT / 'fig2_cumulative_pnl.png', dpi=150)
plt.close()


# ================================================================== #
#  Fig 3 — Spread comparison (from summary stats)                    #
# ================================================================== #
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

ax = axes[0]
keys_av  = [k for k in CONFIGS if k in summaries]
labels   = [CONFIGS[k][0] for k in keys_av]
avg_sprd = [summaries[k]['avg_spread_bps'].mean() for k in keys_av]
fills    = [summaries[k]['total_fills'].sum() for k in keys_av]
colors   = [CONFIGS[k][1] for k in keys_av]

bars = ax.bar(labels, avg_sprd, color=colors, alpha=0.8, edgecolor='black')
for bar, v in zip(bars, avg_sprd):
    ax.text(bar.get_x() + bar.get_width()/2, v + 0.1,
            f'{v:.2f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
ax.set_ylabel('Avg quoted spread (bps)')
ax.set_title('Average quoted spread')
ax.grid(True, axis='y', alpha=0.3)

ax = axes[1]
bars = ax.bar(labels, fills, color=colors, alpha=0.8, edgecolor='black')
for bar, v in zip(bars, fills):
    ax.text(bar.get_x() + bar.get_width()/2, v + 5,
            f'{int(v):,}', ha='center', va='bottom', fontsize=9, fontweight='bold')
ax.set_ylabel('Total fills (30 days)')
ax.set_title('Total fills')
ax.grid(True, axis='y', alpha=0.3)

fig.suptitle('LINK/USDT — Spread and Fill Comparison (Apr 2026)')
fig.tight_layout()
fig.savefig(OUT / 'fig3_spread_comparison.png', dpi=150)
plt.close()


# ================================================================== #
#  Fig 4 — Inventory dynamics (sample day)                           #
# ================================================================== #
views = {k: load_view(k, sample_date) for k in CONFIGS if k in summaries}
views = {k: v for k, v in views.items() if v is not None}

if views:
    n = len(views)
    fig, axes = plt.subplots(n, 1, figsize=(14, 4*n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, (key, vw) in zip(axes, views.items()):
        label, color, ls = CONFIGS[key]
        t = vw.index

        ax2 = ax.twinx()
        if 'inv' in vw.columns:
            ax2.fill_between(t, vw['inv'], 0, alpha=0.15, color='gray', label='Inventory (R)')
            ax2.set_ylabel('Inventory (LINK)', color='gray', fontsize=8)
            ax2.tick_params(axis='y', colors='gray', labelsize=8)

        if 'pnl' in vw.columns:
            ax.plot(t, vw['pnl'], color=color, ls=ls, lw=1.5, label='PnL (L)')
        ax.axhline(0, color='black', lw=0.6, ls=':')
        ax.set_ylabel('P&L ($)')
        ax.set_title(f'{label} — {sample_date}')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT / 'fig4_inventory_sample.png', dpi=150)
    plt.close()


# ================================================================== #
#  Fig 5 — Theoretical skew comparison                               #
# ================================================================== #
sigma    = 0.00589
mid      = 8.98
tick     = 0.01
A        = 0.072
kappa_d  = 208.0
T        = 3600

q_range = np.linspace(-50, 50, 200)

# A-S flat: gamma=1e-9 (no ×1000 hack) — essentially zero skew
skew_as_flat = q_range * 1e-9 * sigma**2 * T * mid

# A-S calibrated v2: gamma=3.57e-4 (no ×1000), ~2-tick skew at q=50
skew_as_cal = q_range * 3.57e-4 * sigma**2 * T * mid

# GLFT touch v2: gamma=4.3, same 2-tick skew at q=50
sigma_d2 = (sigma * mid)**2
skew_glft = q_range * 4.3 * sigma_d2 / (2 * A * kappa_d)

fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(q_range, skew_as_flat / tick, color=CONFIGS['as_flat'][1],
        ls=CONFIGS['as_flat'][2], lw=2, label='A-S flat (γ≈0)')
ax.plot(q_range, skew_as_cal / tick, color=CONFIGS['as_calibrated_v2'][1],
        ls=CONFIGS['as_calibrated_v2'][2], lw=2, label='A-S calibrated v2 (γ=3.57e-4)')
ax.plot(q_range, skew_glft / tick, color=CONFIGS['glft_touch_v2'][1],
        ls=CONFIGS['glft_touch_v2'][2], lw=2,
        label='GLFT touch v2 (γ=4.3, A=0.072, κ=208)')

ax.axhline(0, color='black', lw=0.7)
ax.axvline(0, color='black', lw=0.5, ls=':')
ax.set_xlabel('Inventory (LINK)')
ax.set_ylabel('Reservation price shift (ticks)')
ax.set_title('Theoretical reservation price skew — LINK/USDT (correctly calibrated)')
ax.legend()
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / 'fig5_skew_comparison.png', dpi=150)
plt.close()
print('\nFig 5: reservation price skew at q=50 LINK:')
print(f'  A-S flat:         {skew_as_flat[-1]/tick:.3f} ticks')
print(f'  A-S calibrated:   {skew_as_cal[-1]/tick:.3f} ticks')
print(f'  GLFT touch v2:    {skew_glft[-1]/tick:.3f} ticks')


# ================================================================== #
#  Summary JSON                                                       #
# ================================================================== #
def _f(v, d=4):
    try:
        return round(float(v), d) if float(v) == float(v) else None
    except Exception:
        return None

result = {}
for key, (label, *_) in CONFIGS.items():
    if key not in summaries:
        continue
    df = summaries[key]
    std = df['total_pnl'].std()
    result[key] = {
        'label': label,
        'n_days':         int(len(df)),
        'total_pnl':      _f(df['total_pnl'].sum()),
        'mean_daily_pnl': _f(df['total_pnl'].mean()),
        'std_daily_pnl':  _f(std),
        'sharpe':         _f(df['total_pnl'].mean() / std if std > 0 else 0),
        'pct_profitable': _f((df['total_pnl'] > 0).mean() * 100),
        'total_fills':    int(df['total_fills'].sum()),
        'avg_spread_bps': _f(df['avg_spread_bps'].mean()),
        'mm_only_pnl':    _f(df.get('mm_only_pnl', pd.Series([0])).sum()),
    }

with open(OUT / 'summary.json', 'w') as f:
    json.dump(result, f, indent=2)

print('\n=== RESULTS ===')
print(json.dumps(result, indent=2))
