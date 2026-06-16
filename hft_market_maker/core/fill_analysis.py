"""
fill_analysis.py
================
Shared functions for kappa estimation and fill probability analysis.
Used by kappa_analysis.ipynb and shifted_check.ipynb.

All functions are pure — no global state, no side effects.
Import everything from here in both notebooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


# ============================================================
# Constants
# ============================================================

TICK            = 0.01    # BTC/USDT tick size in dollars
MAX_DELTA_TICKS = 10      # fit only first N ticks
MAX_QUOTE_AGE   = 200     # ms — drop trades with stale mid
MIN_TRADES      = 200     # min trades per window to attempt fit
LATENCY         = 0.10    # seconds
QUOTE_INTERVAL  = 0.50    # seconds
ROLL_WINDOW     = 15      # minutes
ROLL_STEP       = 5       # minutes



# ============================================================
# Data loading
# ============================================================

def load_day(date_str: str, data_dir: Path, symbol: str = "BTC") -> tuple:
    """
    Load one day of CoinAPI tick data for any symbol.
    Returns (trades, quotes) DataFrames with 'ts' column and 'mid' on quotes.
    """
    trades = pd.read_parquet(data_dir / f'trades_{symbol}_{date_str}.parquet')
    quotes = pd.read_parquet(data_dir / f'quotes_{symbol}_{date_str}.parquet')
    trades['ts'] = pd.to_datetime(trades['time_exchange'], utc=True)
    quotes['ts'] = pd.to_datetime(quotes['time_exchange'], utc=True)
    trades = trades.sort_values('ts').reset_index(drop=True)
    quotes = quotes.sort_values('ts').reset_index(drop=True)
    quotes['mid'] = (quotes['bid_price'] + quotes['ask_price']) / 2
    return trades, quotes


# ============================================================
# Approach A — market trade curve
# ============================================================

def compute_fill_curve(
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    max_quote_age_ms: int = MAX_QUOTE_AGE,
    tick: float = TICK,
) -> pd.DataFrame:
    """
    Merge mid + sigma onto each trade, compute distance from mid in ticks.
    Drops trades where mid is stale (quote_age_ms > max_quote_age_ms).

    Returns merged DataFrame with columns:
        ts, price, size, mid, sigma, sigma_dollar,
        quote_age_ms, delta_dollar, delta, hour
    """
    q = quotes.copy()
    q['log_ret']          = np.log(q['mid']).diff()
    dt_sec                = q['ts'].diff().dt.total_seconds().clip(lower=1e-6)
    q['ret_per_sqrt_sec'] = q['log_ret'] / np.sqrt(dt_sec)
    q['sigma']            = q['ret_per_sqrt_sec'].rolling(200, min_periods=10).std()
    q['sigma_dollar']     = q['sigma'] * q['mid']

    merged = pd.merge_asof(
        trades[['ts', 'price', 'size']].sort_values('ts'),
        q[['ts', 'mid', 'sigma', 'sigma_dollar']].sort_values('ts')
          .rename(columns={'ts': 'quote_ts'}),
        left_on='ts', right_on='quote_ts',
        direction='backward',
    )
    merged = merged.dropna(subset=['mid', 'sigma_dollar'])
    merged['quote_age_ms'] = (
        merged['ts'] - merged['quote_ts']
    ).dt.total_seconds() * 1000
    merged = merged[merged['quote_age_ms'] < max_quote_age_ms]
    merged['delta_dollar'] = np.abs(merged['price'] - merged['mid'])
    merged['delta']        = merged['delta_dollar'] / tick
    merged['hour']         = merged['ts'].dt.hour
    merged = merged[merged['delta'] > 0]
    return merged.reset_index(drop=True)


def empirical_fill_prob(
    merged_all: pd.DataFrame,
    max_delta_ticks: int = MAX_DELTA_TICKS,
    tick: float = TICK,
) -> pd.DataFrame:
    """
    Compute P(fill | delta >= bin) using half-tick bins (0.5, 1.5, 2.5, ...).
    Denominator is always the full fresh-mid dataset passed in.

    Returns DataFrame with columns: delta, fill_prob
    """
    all_deltas = merged_all['delta'].values
    bins = np.arange(0.5, max_delta_ticks + 0.5, 1.0)
    probs = [(b, (all_deltas >= b).mean()) for b in bins]
    df = pd.DataFrame(probs, columns=['delta', 'fill_prob'])
    return df[df['fill_prob'] > 0].reset_index(drop=True)


# ============================================================
# Approach B — execution-aware simulation
# ============================================================

def simulate_order_fills(
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    half_spread_ticks: float,
    latency: float = LATENCY,
    quote_interval: float = QUOTE_INTERVAL,
    max_quote_age_ms: int = MAX_QUOTE_AGE,
    tick: float = TICK,
) -> tuple[float, pd.DataFrame]:
    """
    Simulate placing limit orders at half_spread_ticks from mid at every
    quote_interval, respecting latency.

    Exposure window: [t + latency, t + quote_interval + latency]
    (cancel latency extends window by same amount as activation latency delays it)

    Returns (fill_rate, results_df).
    """
    half_spread = half_spread_ticks * tick

    trades_ts  = (trades['ts'].astype(np.int64) / 1e9).values
    trades_px  = trades['price'].values
    quotes_ts  = (quotes['ts'].astype(np.int64) / 1e9).values
    quotes_mid = quotes['mid'].values

    t_min = trades_ts[0]
    t_max = trades_ts[-1]

    results = []
    t = t_min

    while t < t_max - quote_interval:
        q_idx = np.searchsorted(quotes_ts, t, side='right') - 1
        if q_idx < 0:
            t += quote_interval
            continue

        quote_age_ms = (t - quotes_ts[q_idx]) * 1000
        if quote_age_ms > max_quote_age_ms:
            t += quote_interval
            continue

        mid = quotes_mid[q_idx]
        bid = mid - half_spread
        ask = mid + half_spread

        active_from = t + latency
        active_to   = t + quote_interval + latency

        lo = np.searchsorted(trades_ts, active_from, side='left')
        hi = np.searchsorted(trades_ts, active_to,   side='right')
        window_px = trades_px[lo:hi]

        bid_filled = bool(np.any(window_px <= bid))
        ask_filled = bool(np.any(window_px >= ask))

        results.append({
            'ts':         t,
            'mid':        mid,
            'bid_filled': bid_filled,
            'ask_filled': ask_filled,
            'any_filled': bid_filled or ask_filled,
            'n_window':   len(window_px),
        })
        t += quote_interval

    df = pd.DataFrame(results)
    fill_rate = df['any_filled'].mean() if len(df) > 0 else 0.0
    return fill_rate, df


def simulate_fill_curve(
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    deltas: Optional[np.ndarray] = None,
    latency: float = LATENCY,
    quote_interval: float = QUOTE_INTERVAL,
    max_delta_ticks: int = MAX_DELTA_TICKS,
    tick: float = TICK,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Sweep spread distances and return fill rate DataFrame.
    Returns DataFrame with columns: delta, fill_prob
    """
    if deltas is None:
        deltas = np.arange(0.5, max_delta_ticks + 0.5, 1.0)
    rows = []
    for d in deltas:
        rate, _ = simulate_order_fills(
            trades, quotes,
            half_spread_ticks=d,
            latency=latency,
            quote_interval=quote_interval,
            tick=tick,
        )
        rows.append({'delta': d, 'fill_prob': rate})
        if verbose:
            print(f'  delta={d:.1f} ticks: fill_rate={rate:.4f}')
    return pd.DataFrame(rows)


# ============================================================
# Curve fitting — pure exponential
# ============================================================

def fit_exponential(
    fp_df: pd.DataFrame,
    min_delta: float = 0.5,
) -> tuple:
    """
    Fit A * exp(-kappa * delta) to fill probability curve.

    Parameters
    ----------
    fp_df : DataFrame with columns delta, fill_prob
    min_delta : minimum delta to include in fit

    Returns
    -------
    (A, kappa, se_A, se_kappa, r2) or all None on failure
    """
    df = fp_df[fp_df['delta'] >= min_delta].copy()
    if len(df) < 3:
        return None, None, None, None, None

    def model(delta, A, kappa):
        return A * np.exp(-kappa * delta)

    try:
        p0 = [df['fill_prob'].iloc[0], 0.5]
        popt, pcov = curve_fit(
            model, df['delta'].values, df['fill_prob'].values,
            p0=p0, bounds=([0, 1e-4], [5, 200]), maxfev=10000,
        )
        A_hat, kappa_hat = popt
        se = np.sqrt(np.diag(pcov))
        y      = df['fill_prob'].values
        y_hat  = model(df['delta'].values, A_hat, kappa_hat)
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return A_hat, kappa_hat, se[0], se[1], r2
    except Exception:
        return None, None, None, None, None


# ============================================================
# Curve fitting — shifted exponential
# ============================================================

def shifted_exponential(
    delta: np.ndarray,
    A_liq: float,
    kappa: float,
    A_floor: float,
) -> np.ndarray:
    """Two-component fill intensity: A_liq * exp(-kappa * delta) + A_floor."""
    return A_liq * np.exp(-kappa * delta) + A_floor


def fit_shifted_exponential(
    fp_df: pd.DataFrame,
    min_delta: float = 0.5,
) -> tuple:
    """
    Fit A_liq * exp(-kappa * delta) + A_floor to fill probability curve.

    Returns
    -------
    (A_liq, kappa, A_floor, se_A_liq, se_kappa, se_A_floor, r2)
    or all None on failure.
    """
    df = fp_df[fp_df['delta'] >= min_delta].copy()
    if len(df) < 4:
        return None, None, None, None, None, None, None

    y = df['fill_prob'].values
    x = df['delta'].values

    A_floor_guess = float(y[-3:].mean())
    A_liq_guess   = float(max(y[0] - A_floor_guess, 0.01))
    kappa_guess   = 2.0

    try:
        popt, pcov = curve_fit(
            shifted_exponential, x, y,
            p0=[A_liq_guess, kappa_guess, A_floor_guess],
            bounds=([0, 0.01, 0], [5, 200, float(y.min()) + 0.05]),
            maxfev=20000,
        )
        A_liq, kappa, A_floor = popt
        se = np.sqrt(np.diag(pcov))
        y_hat  = shifted_exponential(x, A_liq, kappa, A_floor)
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return A_liq, kappa, A_floor, se[0], se[1], se[2], r2
    except Exception:
        return None, None, None, None, None, None, None


def linear_decay_shifted(
    delta: np.ndarray,
    A_liq: float,
    kappa: float,
    a: float,
    b: float,
) -> np.ndarray:
    """
    Two-component fill intensity with a *finite-range* toxic-flow term:
        A_liq * exp(-kappa * delta) + max(a - b * delta, 0)

    Unlike `shifted_exponential`'s constant floor, the toxic/momentum
    component decays linearly to zero at delta = a/b, so fills cannot
    continue "forever" at a fixed background rate.
    """
    return A_liq * np.exp(-kappa * delta) + np.clip(a - b * np.asarray(delta, dtype=float), 0, None)


def fit_linear_decay_shifted(
    fp_df: pd.DataFrame,
    min_delta: float = 0.5,
) -> tuple:
    """
    Fit A_liq * exp(-kappa * delta) + max(a - b * delta, 0) to fill curve.

    Returns
    -------
    (A_liq, kappa, a, b, se_A_liq, se_kappa, se_a, se_b, r2)
    or all None on failure.
    """
    df = fp_df[fp_df['delta'] >= min_delta].copy()
    if len(df) < 5:
        return (None,) * 9

    y = df['fill_prob'].values
    x = df['delta'].values

    # Estimate the tail slope (-b) via a linear fit on the back half of the curve,
    # then extrapolate the intercept `a` back to delta=0.
    n_tail = max(2, len(df) // 2)
    tail_x = x[-n_tail:]
    tail_y = y[-n_tail:]
    if tail_x.max() > tail_x.min():
        slope, intercept = np.polyfit(tail_x, tail_y, 1)
        b_guess = float(max(-slope, 1e-6))
        a_guess = float(max(intercept, tail_y.min()))
    else:
        b_guess = 1e-4
        a_guess = float(tail_y.mean())

    A_liq_guess = float(max(y[0] - max(a_guess - b_guess * x[0], 0.0), 0.01))
    kappa_guess = 2.0

    y_span = float(max(y.max() - y.min(), 1e-6))
    x_span = float(max(x.max() - x.min(), 1e-6))

    try:
        popt, pcov = curve_fit(
            linear_decay_shifted, x, y,
            p0=[A_liq_guess, kappa_guess, a_guess, b_guess],
            bounds=(
                [0, 1e-3, 0, 0],
                [3 * y.max() + 0.1, 200, 3 * y.max() + 0.1, 5 * y_span / x_span + 1.0],
            ),
            maxfev=20000,
        )
        A_liq, kappa, a, b = popt
        se = np.sqrt(np.diag(pcov))
        y_hat  = linear_decay_shifted(x, A_liq, kappa, a, b)
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return A_liq, kappa, a, b, se[0], se[1], se[2], se[3], r2
    except Exception:
        return (None,) * 9


def compare_fits(
    fp_df: pd.DataFrame,
    min_delta: float = 0.5,
    include_linear_decay: bool = False,
) -> dict:
    """
    Fit pure exponential, constant-floor shifted exponential, and (optionally)
    linear-decay shifted exponential. Use AIC for model selection.

    Returns dict with keys:
        exponential:  {A, kappa, A_floor=0, r2, aic, n_params}
        shifted:      {A_liq, kappa, A_floor, A_total, mom_fraction, r2, aic, n_params}
        linear_decay: {A_liq, kappa, a, b, cutoff, r2, aic, n_params} or None
                      (only populated if include_linear_decay=True)
        preferred:    'exponential', 'shifted', or 'linear_decay'
        delta_aic:    AIC(exponential) - AIC(preferred), positive = preferred better
    """
    df = fp_df[fp_df['delta'] >= min_delta].copy()
    x  = df['delta'].values
    y  = df['fill_prob'].values
    n  = len(y)
    results = {}

    # Pure exponential
    A_e, k_e, _, _, r2_e = fit_exponential(fp_df, min_delta)
    if A_e is not None:
        y_hat = A_e * np.exp(-k_e * x)
        ss_res = np.sum((y - y_hat) ** 2)
        aic = n * np.log(ss_res / n + 1e-12) + 2 * 2
        results['exponential'] = {
            'A': A_e, 'kappa': k_e, 'A_floor': 0.0,
            'r2': r2_e, 'aic': aic, 'n_params': 2,
        }
    else:
        results['exponential'] = None

    # Shifted exponential (constant floor)
    A_liq, kappa, A_floor, *_, r2_sh = fit_shifted_exponential(fp_df, min_delta)
    if A_liq is not None:
        y_hat = shifted_exponential(x, A_liq, kappa, A_floor)
        ss_res = np.sum((y - y_hat) ** 2)
        aic = n * np.log(ss_res / n + 1e-12) + 2 * 3
        results['shifted'] = {
            'A_liq': A_liq, 'kappa': kappa, 'A_floor': A_floor,
            'A_total': A_liq + A_floor,
            'mom_fraction': A_floor / (A_liq + A_floor) if (A_liq + A_floor) > 0 else 0.0,
            'r2': r2_sh, 'aic': aic, 'n_params': 3,
        }
    else:
        results['shifted'] = None

    # Linear-decay shifted exponential (toxic flow decays to zero at delta=a/b)
    results['linear_decay'] = None
    if include_linear_decay:
        A_liq_ld, kappa_ld, a_ld, b_ld, *_, r2_ld = fit_linear_decay_shifted(fp_df, min_delta)
        if A_liq_ld is not None:
            y_hat = linear_decay_shifted(x, A_liq_ld, kappa_ld, a_ld, b_ld)
            ss_res = np.sum((y - y_hat) ** 2)
            aic = n * np.log(ss_res / n + 1e-12) + 2 * 4
            results['linear_decay'] = {
                'A_liq': A_liq_ld, 'kappa': kappa_ld, 'a': a_ld, 'b': b_ld,
                'cutoff': a_ld / b_ld if b_ld > 1e-12 else np.inf,
                'r2': r2_ld, 'aic': aic, 'n_params': 4,
            }

    # Model selection: pick lowest-AIC model, but require >2 AIC improvement
    # over pure exponential before preferring a more complex model (Occam's razor)
    candidates = [
        (name, results[name]) for name in ('shifted', 'linear_decay')
        if results.get(name) is not None
    ]
    if results['exponential'] and candidates:
        best_name, best = min(candidates, key=lambda kv: kv[1]['aic'])
        delta_aic = results['exponential']['aic'] - best['aic']
        if delta_aic > 2:
            results['preferred'] = best_name
            results['delta_aic'] = delta_aic
        else:
            results['preferred'] = 'exponential'
            results['delta_aic'] = delta_aic
    elif candidates:
        best_name, _ = min(candidates, key=lambda kv: kv[1]['aic'])
        results['preferred'] = best_name
        results['delta_aic'] = 0.0
    else:
        results['preferred'] = 'exponential'
        results['delta_aic'] = 0.0

    return results


# ============================================================
# Rolling estimation helpers
# ============================================================

def rolling_fit(
    merged_all: pd.DataFrame,
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    window_min: int = ROLL_WINDOW,
    step_min: int = ROLL_STEP,
    min_trades: int = MIN_TRADES,
    max_delta_ticks: int = MAX_DELTA_TICKS,
    latency: float = LATENCY,
    quote_interval: float = QUOTE_INTERVAL,
    fit_shifted: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Rolling window estimation of both pure and shifted exponential parameters.

    For each window:
      - Runs execution simulation (Approach B)
      - Fits pure exponential
      - Optionally fits shifted exponential
      - Computes AIC model selection

    Returns DataFrame with one row per window.
    """
    results = []
    t_min = trades['ts'].min()
    t_max = trades['ts'].max()
    window = pd.Timedelta(minutes=window_min)
    step   = pd.Timedelta(minutes=step_min)
    t = t_min

    while t + window <= t_max:
        t_end = t + window
        sub_t = trades[(trades['ts'] >= t) & (trades['ts'] < t_end)]
        sub_q = quotes[
            (quotes['ts'] >= t - pd.Timedelta(seconds=5)) &
            (quotes['ts'] < t_end + pd.Timedelta(seconds=5))
        ]

        if len(sub_t) < min_trades or len(sub_q) < 10:
            t += step
            continue

        # Simulate fill curve
        fp_w = simulate_fill_curve(
            sub_t, sub_q,
            deltas=np.arange(0.5, max_delta_ticks + 0.5, 1.0),
            latency=latency,
            quote_interval=quote_interval,
            max_delta_ticks=max_delta_ticks,
            verbose=False,
        )

        comp = compare_fits(fp_w, min_delta=0.5) if fit_shifted else {}
        ex_w = comp.get('exponential') or {}
        sh_w = comp.get('shifted') or {}

        # If compare_fits not used, fall back to pure fit
        if not comp:
            A_e, k_e, _, _, r2_e = fit_exponential(fp_w)
            ex_w = {'A': A_e, 'kappa': k_e, 'r2': r2_e, 'aic': np.nan}

        sub_m = merged_all[(merged_all['ts'] >= t) & (merged_all['ts'] < t_end)]
        sigma_d = sub_m['sigma_dollar'].mean() if len(sub_m) > 0 else np.nan

        row = {
            'window_mid':   t + window / 2,
            'sigma_dollar': sigma_d,
            'n':            len(sub_t),
            # Pure exponential
            'A_exp':        ex_w.get('A'),
            'kappa_exp':    ex_w.get('kappa'),
            'r2_exp':       ex_w.get('r2'),
            'aic_exp':      ex_w.get('aic'),
            # Shifted exponential
            'A_liq':        sh_w.get('A_liq'),
            'A_mom':        sh_w.get('A_floor'),
            'kappa_sh':     sh_w.get('kappa'),
            'A_total':      sh_w.get('A_total'),
            'mom_frac':     sh_w.get('mom_fraction'),
            'r2_sh':        sh_w.get('r2'),
            'aic_sh':       sh_w.get('aic'),
            'delta_aic':    comp.get('delta_aic', 0.0),
            'preferred':    comp.get('preferred', 'exponential'),
        }
        results.append(row)

        if verbose:
            print(
                f"  {(t+window/2).strftime('%H:%M')}  "
                f"kappa_exp={ex_w.get('kappa', float('nan')):.3f}  "
                f"kappa_sh={sh_w.get('kappa', float('nan')):.3f}  "
                f"A_mom={sh_w.get('A_floor', float('nan')):.3f}  "
                f"mom%={sh_w.get('mom_fraction', float('nan'))*100:.0f}%  "
                f"R2_sh={sh_w.get('r2', float('nan')):.3f}  "
                f"pref={comp.get('preferred', '?')}"
            )
        t += step

    df = pd.DataFrame(results)
    if len(df) > 0:
        df['window_mid'] = pd.to_datetime(df['window_mid'])
        df['hour']       = df['window_mid'].dt.hour
    return df

# ============================================================
# Approach C — crossing intensity kappa
# ============================================================

def crossing_intensity_curve(
    quotes: pd.DataFrame,
    horizon: float = 1.0,
    eval_step: float = 0.5,
    max_delta_ticks: int = 10,
    tick: float = TICK,
) -> pd.DataFrame:
    """
    Compute empirical mid-price crossing rate λ(δ) = P(|Δm(h)| ≥ δ) / h.

    Evaluates on a uniform eval_step grid, looks up mid(t+horizon) from quotes.
    Returns DataFrame with columns: delta_ticks, delta, rate.
    """
    ts  = (quotes['ts'].astype(np.int64) / 1e9).values
    mid = quotes['mid'].values

    t_grid = np.arange(ts[0], ts[-1] - horizon, eval_step)

    idx_t  = np.searchsorted(ts, t_grid,           side='right') - 1
    idx_th = np.searchsorted(ts, t_grid + horizon, side='right') - 1

    valid = (idx_t >= 0) & (idx_th >= 0) & (idx_th < len(mid))
    mid_t  = mid[idx_t[valid]]
    mid_th = mid[idx_th[valid]]
    abs_move = np.abs(mid_th - mid_t)

    deltas_ticks = np.arange(0.5, max_delta_ticks + 0.5, 0.5)
    rows = []
    for dt in deltas_ticks:
        d = dt * tick
        rate = (abs_move >= d).mean() / horizon
        rows.append({'delta_ticks': dt, 'delta': d, 'rate': rate, 'n': valid.sum()})
    return pd.DataFrame(rows)


def fit_crossing_intensity(
    curve: pd.DataFrame,
    min_delta_ticks: float = 0.5,
    tick: float = TICK,
) -> dict:
    """
    Fit pure and two-component exponential to a crossing intensity curve.

    Parameters
    ----------
    curve : output of crossing_intensity_curve()
    min_delta_ticks : skip sub-tick noise near δ=0

    Returns dict with keys: exponential, shifted, preferred, delta_aic
    Same structure as compare_fits() — drop-in comparable.
    """
    sub = curve[curve['delta_ticks'] >= min_delta_ticks].copy()
    x   = sub['delta_ticks'].values
    y   = sub['rate'].values

    rate_df = pd.DataFrame({'delta': x, 'fill_prob': y})
    return compare_fits(rate_df, min_delta=min_delta_ticks)


def crossing_intensity_rolling(
    quotes: pd.DataFrame,
    horizon: float = 1.0,
    eval_step: float = 0.5,
    window_min: int = ROLL_WINDOW,
    step_min: int = ROLL_STEP,
    max_delta_ticks: int = 10,
    tick: float = TICK,
) -> pd.DataFrame:
    """
    Rolling crossing intensity — one fit per time window.
    Returns DataFrame with kappa_exp, kappa_sh, A_mom, mom_frac per window.
    """
    t_min = quotes['ts'].min()
    t_max = quotes['ts'].max()
    window = pd.Timedelta(minutes=window_min)
    step   = pd.Timedelta(minutes=step_min)

    results = []
    t = t_min
    while t + window <= t_max:
        t_end = t + window
        sub_q = quotes[
            (quotes['ts'] >= t) & (quotes['ts'] < t_end + pd.Timedelta(seconds=horizon))
        ]
        if len(sub_q) < 100:
            t += step
            continue

        curve = crossing_intensity_curve(sub_q, horizon, eval_step, max_delta_ticks, tick)
        fits  = fit_crossing_intensity(curve)

        ex = fits.get('exponential') or {}
        sh = fits.get('shifted') or {}
        results.append({
            'window_mid':  t + window / 2,
            'kappa_exp':   ex.get('kappa'),
            'A_exp':       ex.get('A'),
            'r2_exp':      ex.get('r2'),
            'kappa_sh':    sh.get('kappa'),
            'A_liq':       sh.get('A_liq'),
            'A_mom':       sh.get('A_floor'),
            'mom_frac':    sh.get('mom_fraction'),
            'r2_sh':       sh.get('r2'),
            'preferred':   fits.get('preferred'),
        })
        t += step

    df = pd.DataFrame(results)
    if len(df):
        df['window_mid'] = pd.to_datetime(df['window_mid'])
        df['hour']       = df['window_mid'].dt.hour
    return df


# ============================================================
# L2-conditioned crossing intensity (requires orderbook data)
# ============================================================

def _depth_at_level(levels: list, target_price: float, side: str) -> float:
    """Cumulative size from best quote out to target_price (inclusive)."""
    total = 0.0
    for lvl in levels:
        p = lvl['price']
        if side == 'bid' and p >= target_price:
            total += lvl['size']
        elif side == 'ask' and p <= target_price:
            total += lvl['size']
        else:
            break
    return total


def l2_conditioned_crossing(
    quotes: pd.DataFrame,
    orderbooks: pd.DataFrame,
    horizon: float = 1.0,
    eval_step: float = 0.5,
    delta_ticks: float = 0.5,
    n_depth_bins: int = 4,
    tick: float = 0.01,
) -> pd.DataFrame:
    """
    L2-conditioned crossing intensity at a single δ.

    For each evaluation point t:
      - Record |Δm(h)| (crossed or not at δ)
      - Look up queue depth Q at the target level from the nearest orderbook snapshot
    Then bin events by Q and compute λ(δ | Q) for each bin.

    Returns DataFrame with columns: depth_bin, depth_lo, depth_hi,
                                    rate, n, depth_mean.
    """
    if 'ts' not in orderbooks.columns:
        orderbooks = orderbooks.copy()
        orderbooks['ts'] = pd.to_datetime(orderbooks['time_exchange'], utc=True)
    ob_ts  = (orderbooks['ts'].astype(np.int64) / 1e9).values
    ob_bids = orderbooks['bids'].values
    ob_asks = orderbooks['asks'].values

    ts  = (quotes['ts'].astype(np.int64) / 1e9).values
    mid = quotes['mid'].values

    t_grid = np.arange(ts[0], ts[-1] - horizon, eval_step)
    idx_t  = np.searchsorted(ts, t_grid,           side='right') - 1
    idx_th = np.searchsorted(ts, t_grid + horizon, side='right') - 1
    valid  = (idx_t >= 0) & (idx_th >= 0) & (idx_th < len(mid))

    delta = delta_ticks * tick

    crossed  = []
    q_depths = []
    for i in np.where(valid)[0]:
        m0  = mid[idx_t[i]]
        m1  = mid[idx_th[i]]
        t0  = t_grid[i]
        moved = abs(m1 - m0) >= delta

        ob_idx = np.searchsorted(ob_ts, t0, side='right') - 1
        if ob_idx < 0:
            continue

        bids = ob_bids[ob_idx]
        asks = ob_asks[ob_idx]
        best_bid = float(bids[0]['price']) if len(bids) > 0 else np.nan
        best_ask = float(asks[0]['price']) if len(asks) > 0 else np.nan
        mid_snap = (best_bid + best_ask) / 2 if not (np.isnan(best_bid) or np.isnan(best_ask)) else m0

        # Depth on both sides out to δ from mid_snap
        bid_target = mid_snap - delta
        ask_target = mid_snap + delta
        q_bid = _depth_at_level(list(bids), bid_target, 'bid')
        q_ask = _depth_at_level(list(asks), ask_target, 'ask')
        q_avg = (q_bid + q_ask) / 2

        crossed.append(float(moved))
        q_depths.append(q_avg)

    if not crossed:
        return pd.DataFrame()

    crossed  = np.array(crossed)
    q_depths = np.array(q_depths)

    quantiles = np.linspace(0, 100, n_depth_bins + 1)
    edges     = np.percentile(q_depths, quantiles)

    rows = []
    for k in range(n_depth_bins):
        lo, hi = edges[k], edges[k + 1]
        mask = (q_depths >= lo) & (q_depths < hi) if k < n_depth_bins - 1 \
               else (q_depths >= lo) & (q_depths <= hi)
        n  = mask.sum()
        if n == 0:
            continue
        rate = crossed[mask].mean() / horizon
        rows.append({
            'depth_bin':  k + 1,
            'depth_lo':   lo,
            'depth_hi':   hi,
            'depth_mean': q_depths[mask].mean(),
            'rate':       rate,
            'n':          int(n),
        })
    return pd.DataFrame(rows)


def simulate_survival_data_fast(
    trades, quotes,
    half_spread_ticks,
    
    max_lifetime,
    recompute_freq,
    tolerance_ticks,
    latency=LATENCY,
    max_quote_age_ms=200,
    tick=TICK,
):
    half_spread = half_spread_ticks * tick
    tolerance   = tolerance_ticks * tick

    trades_ts  = (trades['ts'].astype(np.int64) / 1e9).values
    trades_px  = trades['price'].values
    quotes_ts  = (quotes['ts'].astype(np.int64) / 1e9).values
    quotes_mid = quotes['mid'].values

    t_min = trades_ts[0]
    t_max = trades_ts[-1] - max_lifetime

    # Generate all submission times at once
    submit_times = np.arange(t_min, t_max, recompute_freq)

    # Vectorised mid lookup at submission time
    q_indices = np.searchsorted(quotes_ts, submit_times, side='right') - 1
    valid = q_indices >= 0
    submit_times = submit_times[valid]
    q_indices    = q_indices[valid]

    quote_ages = (submit_times - quotes_ts[q_indices]) * 1000
    fresh = quote_ages < max_quote_age_ms
    submit_times = submit_times[fresh]
    q_indices    = q_indices[fresh]

    mids_at_submit = quotes_mid[q_indices]
    bids = mids_at_submit - half_spread
    asks = mids_at_submit + half_spread

    results = []

    for i, (t, mid_submit, bid, ask) in enumerate(
            zip(submit_times, mids_at_submit, bids, asks)):

        active_from = t + latency
        active_to   = active_from + max_lifetime

        # All trades in the full lifetime window — one searchsorted per order
        lo = np.searchsorted(trades_ts, active_from, side='left')
        hi = np.searchsorted(trades_ts, active_to,   side='right')
        window_ts = trades_ts[lo:hi]
        window_px = trades_px[lo:hi]

        if len(window_ts) == 0:
            results.append({
                'delta': half_spread_ticks,
                'observed_time': max_lifetime,
                'filled': 0,
                'time_to_fill': None,
                'time_to_cancel': max_lifetime,
                'censored_reason': 'timeout',
                'submit_time': t,
            })
            continue

        # Fill times — first trade hitting bid or ask
        bid_hits = window_ts[window_px <= bid]
        ask_hits = window_ts[window_px >= ask]
        fill_candidates = []
        if len(bid_hits) > 0: fill_candidates.append(bid_hits[0])
        if len(ask_hits) > 0: fill_candidates.append(ask_hits[0])

        fill_time = (min(fill_candidates) - active_from) if fill_candidates else None

        # Divergence times — when mid moves beyond tolerance
        q_window_idx = np.searchsorted(quotes_ts, window_ts, side='right') - 1
        q_window_idx = np.clip(q_window_idx, 0, len(quotes_mid) - 1)
        mids_during  = quotes_mid[q_window_idx]
        diverged     = np.abs(mids_during - mid_submit) > tolerance
        cancel_time  = (window_ts[diverged][0] - active_from) if diverged.any() else max_lifetime
        censored_reason = 'diverged' if diverged.any() else 'timeout'

        if fill_time is not None and fill_time <= cancel_time:
            results.append({
                'delta': half_spread_ticks,
                'observed_time': fill_time,
                'filled': 1,
                'time_to_fill': fill_time,
                'time_to_cancel': None,
                'censored_reason': None,
                'submit_time': t,
            })
        else:
            results.append({
                'delta': half_spread_ticks,
                'observed_time': cancel_time,
                'filled': 0,
                'time_to_fill': None,
                'time_to_cancel': cancel_time,
                'censored_reason': censored_reason,
                'submit_time': t,
            })

    return pd.DataFrame(results)


# ============================================================
# Survival-based hazard rate estimation
# ============================================================

def fit_exponential_hazard(times, events) -> tuple:
    """
    MLE for an exponential survival model: S(t) = exp(-lambda * t).
    Correctly handles right-censoring (cancelled/timed-out orders
    contribute their full observed time without an event).

    lambda_hat = n_events / sum(observed_times)

    Returns (lambda_hat, se) or (None, None) if there is no information.
    """
    times  = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=float)
    n_events   = events.sum()
    total_time = times.sum()
    if total_time < 1e-10 or n_events == 0:
        return None, None
    lam = n_events / total_time
    se  = lam / np.sqrt(n_events)
    return lam, se


def hazard_curve(
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    deltas: np.ndarray,
    latency: float = LATENCY,
    max_lifetime: float = 10.0,
    recompute_freq: float = 0.10,
    tolerance_ticks: float = 1.0,
    tick: float = TICK,
) -> pd.DataFrame:
    """
    Survival-based fill hazard rate lambda(delta) across a grid of spread
    distances, correctly handling right-censoring via `fit_exponential_hazard`.

    Returns DataFrame with columns: delta, fill_prob (= hazard rate, fills/sec),
    se, n, n_fills. (Named `fill_prob` for drop-in compatibility with
    `fit_exponential`, `fit_shifted_exponential`, `fit_linear_decay_shifted`,
    and `compare_fits`.)
    """
    rows = []
    for d in deltas:
        df = simulate_survival_data_fast(
            trades, quotes,
            half_spread_ticks=d,
            max_lifetime=max_lifetime,
            recompute_freq=recompute_freq,
            tolerance_ticks=tolerance_ticks,
            latency=latency,
            tick=tick,
        )
        lam, se = fit_exponential_hazard(df['observed_time'].values, df['filled'].values)
        rows.append({
            'delta': d,
            'fill_prob': lam,
            'se': se,
            'n': len(df),
            'n_fills': int(df['filled'].sum()),
        })
    return pd.DataFrame(rows).dropna(subset=['fill_prob']).reset_index(drop=True)


# ============================================================
# Markout analysis (post-fill price drift / adverse selection)
# ============================================================

def compute_markouts(fills, quote_events, horizons=(0.5, 1.0, 2.0, 5.0, 10.0)) -> pd.DataFrame:
    """
    Signed markout per fill: sign * (mid(t + h) - fill.price), where
    sign = +1 for bid fills (we bought) and -1 for ask fills (we sold).

    Positive markout = mid moved in our favor after the fill (bought before
    a rise / sold before a fall). Negative = adverse selection (picked off).

    quote_events must be sorted by timestamp ascending (as returned by
    DataLoader.load_coinapi). mid(t+h) is an as-of lookup (last quote at or
    before t+h); fills where t+h exceeds the last available quote timestamp
    get NaN for that horizon.

    Returns one row per fill: side, price, timestamp, markout_<h> per h.
    """
    cols = ["side", "price", "timestamp", *[f"markout_{h}" for h in horizons]]
    if not fills:
        return pd.DataFrame(columns=cols)

    qts = np.array([q.timestamp for q in quote_events])
    qmids = np.array([q.mid for q in quote_events])
    last_t = qts[-1]

    fill_ts = np.array([f.timestamp for f in fills])
    fill_px = np.array([f.price for f in fills])
    sign = np.array([1.0 if f.side == "bid" else -1.0 for f in fills])

    data = {"side": [f.side for f in fills], "price": fill_px, "timestamp": fill_ts}
    for h in horizons:
        target = fill_ts + h
        idx = np.searchsorted(qts, target, side="right") - 1
        mid_at_h = np.where(idx >= 0, qmids[np.clip(idx, 0, None)], np.nan)
        mid_at_h = np.where(target <= last_t, mid_at_h, np.nan)
        data[f"markout_{h}"] = sign * (mid_at_h - fill_px)

    return pd.DataFrame(data)


def markout_summary(df: pd.DataFrame, horizons=(0.5, 1.0, 2.0, 5.0, 10.0)) -> pd.DataFrame:
    """
    Aggregate compute_markouts() output: mean signed markout (price units)
    and % of fills with negative (adverse) markout, per horizon, overall and
    split by fill side.
    """
    rows = []
    for h in horizons:
        col = f"markout_{h}"
        vals = df[col].dropna()
        rows.append({"horizon": h, "side": "all",
                      "mean_markout": vals.mean(), "pct_adverse": 100 * (vals < 0).mean(),
                      "n": len(vals)})
        for side in ("bid", "ask"):
            sub = df.loc[df["side"] == side, col].dropna()
            rows.append({"horizon": h, "side": side,
                          "mean_markout": sub.mean(), "pct_adverse": 100 * (sub < 0).mean(),
                          "n": len(sub)})
    return pd.DataFrame(rows)