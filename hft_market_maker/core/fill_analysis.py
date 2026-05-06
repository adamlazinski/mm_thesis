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

def load_day(date_str: str, data_dir: Path) -> tuple:
    """
    Load one day of CoinAPI BTC/USDT trades and quotes.
    Returns (trades, quotes) DataFrames with 'ts' column and 'mid' on quotes.
    """
    trades = pd.read_parquet(data_dir / f'trades_BTC_{date_str}.parquet')
    quotes = pd.read_parquet(data_dir / f'quotes_BTC_{date_str}.parquet')
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


def compare_fits(
    fp_df: pd.DataFrame,
    min_delta: float = 0.5,
) -> dict:
    """
    Fit both pure and shifted exponential. Use AIC for model selection.

    Returns dict with keys:
        exponential: {A, kappa, A_floor=0, r2, aic, n_params}
        shifted:     {A_liq, kappa, A_floor, A_total, mom_fraction, r2, aic, n_params}
        preferred:   'exponential' or 'shifted'
        delta_aic:   AIC(exponential) - AIC(shifted), positive = shifted better
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

    # Shifted exponential
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

    # Model selection
    if results['exponential'] and results['shifted']:
        delta_aic = results['exponential']['aic'] - results['shifted']['aic']
        results['preferred']  = 'shifted' if delta_aic > 2 else 'exponential'
        results['delta_aic']  = delta_aic
    else:
        results['preferred'] = 'exponential' if results['exponential'] else 'shifted'
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