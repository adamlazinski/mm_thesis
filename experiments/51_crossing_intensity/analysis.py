"""
Experiment 51 — Crossing Intensity Kappa Calibration
=====================================================

Approach C: estimate kappa from empirical mid-price crossing rates.

    λ(δ) = P(|m(t+h) - m(t)| ≥ δ) / h

Model-free — no fill simulation, no trade matching.
The crossing rate measures how fast the mid moves ≥ δ ticks per second.

Primary: LINK/USDT April 2026 (quotes + L2 orderbooks)
Secondary: BTC/USDT June 2025 (quotes only, no orderbooks)

Outputs:
    fig1_link_crossing_curve.png    — LINK λ(δ) with exponential fits
    fig2_link_rolling_kappa.png     — intraday κ for LINK
    fig3_btc_crossing_curve.png     — BTC λ(δ) with exponential fits
    fig4_comparison.png             — Approach A vs B vs C (BTC)
    fig5_l2_conditioned.png         — L2-conditioned λ(δ|Q) for LINK
    summary.json                    — numeric results
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.core.fill_analysis import (
    crossing_intensity_curve,
    fit_crossing_intensity,
    crossing_intensity_rolling,
    l2_conditioned_crossing,
    shifted_exponential,
)

OUT      = Path(__file__).parent / 'analysis'
OUT.mkdir(exist_ok=True)
DATA_DIR = ROOT / 'data' / 'real'

LINK_TICK = 0.01
BTC_TICK  = 0.01
HORIZON   = 1.0   # seconds

# April 2026: both quotes + orderbooks exist for LINK
LINK_DATES = [f'2026-04-{d:02d}' for d in range(1, 11)]

# June 2025 BTC (quotes only)
BTC_DATES = [f'2025-06-{d:02d}' for d in range(11, 21)]


# ------------------------------------------------------------------ #
#  Load data                                                          #
# ------------------------------------------------------------------ #
def load_quotes(dates, symbol, tick):
    frames = []
    for d in dates:
        p = DATA_DIR / f'quotes_{symbol}_{d}.parquet'
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df['ts']  = pd.to_datetime(df['time_exchange'], utc=True)
        df['mid'] = (df['bid_price'] + df['ask_price']) / 2
        frames.append(df[['ts', 'mid']].sort_values('ts'))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values('ts')


def load_orderbooks(dates, symbol):
    frames = []
    for d in dates:
        p = DATA_DIR / f'orderbooks_{symbol}_{d}.parquet'
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df['ts'] = pd.to_datetime(df['time_exchange'], utc=True)
        frames.append(df[['ts', 'bids', 'asks']].sort_values('ts'))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values('ts')


print('Loading LINK quotes + orderbooks ...')
link_q  = load_quotes(LINK_DATES, 'LINK', LINK_TICK)
link_ob = load_orderbooks(LINK_DATES, 'LINK')
print(f'  {len(link_q):,} LINK quote rows, {len(link_ob):,} orderbook snapshots')

print('Loading BTC quotes ...')
btc_q = load_quotes(BTC_DATES, 'BTC', BTC_TICK)
print(f'  {len(btc_q):,} BTC quote rows')


# ================================================================== #
#  Fig 1 — LINK crossing curve                                       #
# ================================================================== #
print('\nFig 1: LINK crossing intensity curve ...')
link_curve = crossing_intensity_curve(
    link_q, horizon=HORIZON, eval_step=0.5,
    max_delta_ticks=10, tick=LINK_TICK,
)
link_fits = fit_crossing_intensity(link_curve, min_delta_ticks=0.5)
l_ex = link_fits.get('exponential') or {}
l_sh = link_fits.get('shifted') or {}

x      = link_curve['delta_ticks'].values
y      = link_curve['rate'].values
x_plot = np.linspace(0.5, 10, 200)

fig, ax = plt.subplots(figsize=(8, 5))
ax.scatter(x, y, color='steelblue', s=30, zorder=3, label='Empirical λ(δ)')

if l_ex.get('kappa'):
    y_exp = l_ex['A'] * np.exp(-l_ex['kappa'] * x_plot)
    ax.plot(x_plot, y_exp, 'r--', lw=1.5,
            label=f"Pure exp:  A={l_ex['A']:.3f}, κ={l_ex['kappa']:.3f}  (R²={l_ex['r2']:.3f})")

if l_sh.get('kappa'):
    y_sh = shifted_exponential(x_plot, l_sh['A_liq'], l_sh['kappa'], l_sh['A_floor'])
    ax.plot(x_plot, y_sh, 'g-', lw=2,
            label=(f"Two-comp:  κ={l_sh['kappa']:.3f}, "
                   f"A_liq={l_sh['A_liq']:.3f}, "
                   f"A_mom={l_sh['A_floor']:.3f}  "
                   f"(R²={l_sh['r2']:.3f})"))

ax.set_xlabel('δ (ticks from mid)')
ax.set_ylabel('λ(δ)  [crossings / second]')
ax.set_title(f'LINK/USDT Crossing Intensity  (h={HORIZON}s, {len(LINK_DATES)} days)')
ax.legend(fontsize=8)
ax.set_yscale('log')
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / 'fig1_link_crossing_curve.png', dpi=150)
plt.close()
print(f'  LINK κ (pure exp)   = {l_ex.get("kappa", float("nan")):.4f}')
print(f'  LINK κ (two-comp)   = {l_sh.get("kappa", float("nan")):.4f}')
print(f'  LINK A_mom fraction = {l_sh.get("mom_fraction", float("nan"))*100:.1f}%')


# ================================================================== #
#  Fig 2 — LINK rolling κ                                            #
# ================================================================== #
print('\nFig 2: LINK rolling crossing intensity ...')
link_rolling = crossing_intensity_rolling(
    link_q, horizon=HORIZON, eval_step=0.5,
    window_min=15, step_min=5, max_delta_ticks=10, tick=LINK_TICK,
)

if len(link_rolling):
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    ax = axes[0]
    ax.plot(link_rolling['window_mid'], link_rolling['kappa_exp'], 'r.', ms=4, alpha=0.6, label='Pure exp κ')
    ax.plot(link_rolling['window_mid'], link_rolling['kappa_sh'],  'g.', ms=4, alpha=0.6, label='Two-comp κ')
    kappa_med = link_rolling['kappa_sh'].median()
    ax.axhline(kappa_med, color='green', lw=1.2, ls='--', label=f'Median κ_sh={kappa_med:.3f}')
    ax.set_ylabel('κ (ticks⁻¹)')
    ax.set_title('LINK/USDT — Rolling crossing-intensity κ')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)

    ax = axes[1]
    ax.plot(link_rolling['window_mid'],
            link_rolling['mom_frac'].fillna(0) * 100,
            'b.', ms=4, alpha=0.6)
    ax.set_ylabel('A_mom fraction (%)')
    ax.set_xlabel('Time')
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 100)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(OUT / 'fig2_link_rolling_kappa.png', dpi=150)
    plt.close()
    print(f'  Median κ_sh = {kappa_med:.4f},  '
          f'IQR = [{link_rolling["kappa_sh"].quantile(0.25):.4f}, '
          f'{link_rolling["kappa_sh"].quantile(0.75):.4f}]')
else:
    kappa_med = np.nan
    print('  No rolling results')


# ================================================================== #
#  Fig 3 — BTC crossing curve                                        #
# ================================================================== #
print('\nFig 3: BTC crossing intensity curve ...')
btc_curve = crossing_intensity_curve(
    btc_q, horizon=HORIZON, eval_step=0.5,
    max_delta_ticks=10, tick=BTC_TICK,
)
btc_fits = fit_crossing_intensity(btc_curve, min_delta_ticks=0.5)
b_ex = btc_fits.get('exponential') or {}
b_sh = btc_fits.get('shifted') or {}

xb     = btc_curve['delta_ticks'].values
yb     = btc_curve['rate'].values

fig, ax = plt.subplots(figsize=(8, 5))
ax.scatter(xb, yb, color='darkorange', s=30, zorder=3, label='Empirical λ(δ)')

if b_ex.get('kappa'):
    ye = b_ex['A'] * np.exp(-b_ex['kappa'] * x_plot)
    ax.plot(x_plot, ye, 'r--', lw=1.5,
            label=f"Pure exp:  A={b_ex['A']:.3f}, κ={b_ex['kappa']:.3f}  (R²={b_ex['r2']:.3f})")

if b_sh.get('kappa'):
    ys = shifted_exponential(x_plot, b_sh['A_liq'], b_sh['kappa'], b_sh['A_floor'])
    ax.plot(x_plot, ys, 'g-', lw=2,
            label=(f"Two-comp:  κ={b_sh['kappa']:.3f}, "
                   f"A_liq={b_sh['A_liq']:.3f}, "
                   f"A_mom={b_sh['A_floor']:.3f}  "
                   f"(R²={b_sh['r2']:.3f})"))

ax.set_xlabel('δ (ticks from mid)')
ax.set_ylabel('λ(δ)  [crossings / second]')
ax.set_title(f'BTC/USDT Crossing Intensity  (h={HORIZON}s, {len(BTC_DATES)} days)')
ax.legend(fontsize=8)
ax.set_yscale('log')
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / 'fig3_btc_crossing_curve.png', dpi=150)
plt.close()
print(f'  BTC κ (pure exp)   = {b_ex.get("kappa", float("nan")):.4f}')
print(f'  BTC κ (two-comp)   = {b_sh.get("kappa", float("nan")):.4f}')
print(f'  BTC A_mom fraction = {b_sh.get("mom_fraction", float("nan"))*100:.1f}%')


# ================================================================== #
#  Fig 4 — BTC κ comparison A / B / C                                #
# ================================================================== #
print('\nFig 4: BTC kappa comparison ...')
kappa_C_exp = b_ex.get('kappa', np.nan)
kappa_C_sh  = b_sh.get('kappa', np.nan)

labels = ['A\nTrade dist\n(full day)', 'B\nExec sim\n(HQ wins)', 'B\nExec sim\n(full day)',
          'C\nCrossing\n(pure exp)', 'C\nCrossing\n(two-comp)']
values = [0.31, 1.85, 0.31, kappa_C_exp, kappa_C_sh]
colors = ['#4878cf', '#e06c75', '#4878cf', '#61afef', '#98c379']

fig, ax = plt.subplots(figsize=(9, 5))
bars = ax.bar(labels, values, color=colors, alpha=0.8, edgecolor='black', linewidth=0.8)
for bar, v in zip(bars, values):
    if v == v:
        ax.text(bar.get_x() + bar.get_width()/2, v + 0.02,
                f'{v:.3f}', ha='center', va='bottom', fontsize=10, fontweight='bold')
ax.set_ylabel('κ estimate (ticks⁻¹)')
ax.set_title('Kappa calibration: Approach A vs B vs C — BTC/USDT')
ax.set_ylim(0, max(v for v in values if v == v) * 1.3)
ax.grid(True, axis='y', alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / 'fig4_comparison.png', dpi=150)
plt.close()


# ================================================================== #
#  Fig 5 — L2-conditioned crossing (LINK)                            #
# ================================================================== #
print('\nFig 5: L2-conditioned crossing intensity (LINK) ...')

delta_sweep = [0.5, 1.0, 2.0]
l2_results  = {}

for dt in delta_sweep:
    print(f'  δ={dt} ticks ...')
    df_l2 = l2_conditioned_crossing(
        link_q, link_ob,
        horizon=HORIZON, eval_step=0.5,
        delta_ticks=dt, n_depth_bins=4,
        tick=LINK_TICK,
    )
    l2_results[dt] = df_l2
    if len(df_l2):
        for _, r in df_l2.iterrows():
            print(f'    Q{int(r["depth_bin"])}  depth={r["depth_mean"]:.1f}  rate={r["rate"]:.4f}')

fig, axes = plt.subplots(1, len(delta_sweep), figsize=(14, 5), sharey=False)

for ax, dt in zip(axes, delta_sweep):
    df_l2 = l2_results[dt]
    if len(df_l2) == 0:
        ax.set_title(f'δ={dt}t  (no data)')
        continue

    labels_d = [f'Q{int(r["depth_bin"])}\n≤{r["depth_hi"]:.0f}' for _, r in df_l2.iterrows()]
    bars = ax.bar(labels_d, df_l2['rate'], color='steelblue', alpha=0.75, edgecolor='black')
    for bar, (_, r) in zip(bars, df_l2.iterrows()):
        ax.text(bar.get_x() + bar.get_width()/2, r['rate'] * 1.03,
                f'{r["rate"]:.4f}', ha='center', va='bottom', fontsize=8)

    # Fit a simple regression line: rate ~ A * exp(-b * depth_mean)
    d_vals = df_l2['depth_mean'].values
    r_vals = df_l2['rate'].values
    if len(d_vals) >= 3 and r_vals.min() > 0:
        try:
            from scipy.optimize import curve_fit as _cf
            popt, _ = _cf(lambda d, A, b: A * np.exp(-b * d),
                          d_vals, r_vals, p0=[r_vals[0], 0.001], maxfev=5000)
            d_smooth = np.linspace(d_vals.min(), d_vals.max(), 100)
            ax.set_xlabel('Depth quartile (queue size at δ)')
            # Annotate slope on title
        except Exception:
            pass

    ax.set_title(f'δ={dt} ticks — λ conditioned on depth')
    ax.set_ylabel('λ(δ|Q)  [/sec]')
    ax.grid(True, axis='y', alpha=0.3)

fig.suptitle('LINK/USDT — L2-conditioned crossing intensity λ(δ|Q)')
fig.tight_layout()
fig.savefig(OUT / 'fig5_l2_conditioned.png', dpi=150)
plt.close()


# ================================================================== #
#  Summary JSON                                                       #
# ================================================================== #
def _f(v, d=4):
    if v is None: return None
    try:
        return round(float(v), d) if float(v) == float(v) else None
    except Exception:
        return None

l2_summary = {}
for dt, df_l2 in l2_results.items():
    if len(df_l2):
        l2_summary[f'delta_{dt}_ticks'] = [
            {'depth_bin': int(r['depth_bin']),
             'depth_mean': _f(r['depth_mean'], 1),
             'rate': _f(r['rate'])}
            for _, r in df_l2.iterrows()
        ]

summary = {
    'link': {
        'approach_C_pure_exp': {'kappa': _f(l_ex.get('kappa')), 'A': _f(l_ex.get('A')), 'r2': _f(l_ex.get('r2'))},
        'approach_C_two_comp': {
            'kappa':    _f(l_sh.get('kappa')),
            'A_liq':    _f(l_sh.get('A_liq')),
            'A_mom':    _f(l_sh.get('A_floor')),
            'mom_frac': _f(l_sh.get('mom_fraction')),
            'r2':       _f(l_sh.get('r2')),
        },
        'rolling_kappa_sh_median': _f(kappa_med),
        'l2_conditioned': l2_summary,
    },
    'btc': {
        'approach_C_pure_exp': {'kappa': _f(b_ex.get('kappa')), 'A': _f(b_ex.get('A')), 'r2': _f(b_ex.get('r2'))},
        'approach_C_two_comp': {
            'kappa':    _f(b_sh.get('kappa')),
            'A_liq':    _f(b_sh.get('A_liq')),
            'A_mom':    _f(b_sh.get('A_floor')),
            'mom_frac': _f(b_sh.get('mom_fraction')),
            'r2':       _f(b_sh.get('r2')),
        },
        'reference_approach_A':    0.31,
        'reference_approach_B_hq': 1.85,
    },
    'horizon_s': HORIZON,
}

with open(OUT / 'summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print('\n=== DONE ===')
print(json.dumps(summary, indent=2))
