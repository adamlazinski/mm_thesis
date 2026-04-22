"""
synthetic_generator.py
======================
Synthetic BTC market data generator faithful to the Avellaneda-Stoikov model.

AS Fill Model
-------------
Market orders arrive as independent Poisson processes on each side:
    Intensity of ask fills: lambda_a(t) = A * exp(-kappa * delta_a)
    Intensity of bid fills: lambda_b(t) = A * exp(-kappa * delta_b)

where delta = distance of your quote from current mid price (in $ for BTC).

Key design decisions vs. original generator
-------------------------------------------
1. Trades now arrive via Poisson(A*exp(-kappa*delta)*dt) per tick — the exact
   AS intensity process — rather than a fixed trade_rate.
2. A new mm_fills stream is returned: fills against YOUR quoted spread.
   This is the primary signal for estimating kappa.
3. estimate_kappa_poisson() uses the correct Poisson likelihood (not Bernoulli),
   which is required when lambda/tick is not << 1 (true for BTC at any reasonable
   spread/quote-rate combination).
4. rolling_kappa_estimate() uses adaptive regularization lam ~ 1/sqrt(n_fills),
   consistent with Cao et al. (arXiv 2409.02025).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_synthetic_btc(
    n_seconds: int = 86400,
    mid_start: float = 102000.0,
    sigma_per_sec: float = 0.00006,
    autocorr: float = -0.05,
    # AS fill model
    A: float = 2.0,             # baseline arrival intensity (fills/sec per side at delta=0)
    kappa: float = 1.5,         # price sensitivity of liquidity takers (1/$)
    mm_half_spread: float = 0.30,  # your quoted half-spread ($)
    mm_quote_size: float = 0.1,
    # Quote stream
    quote_rate: float = 5.0,    # BBO updates per second
    bbo_spread: float = 0.20,   # background BBO half-spread ($)
    seed: int = 42,
):
    """
    Generate synthetic BTC trades, BBO quotes, and MM fills.

    Returns
    -------
    trades   : DataFrame  — background taker market orders (original schema)
    quotes   : DataFrame  — BBO snapshots at quote_rate Hz  (original schema)
    mm_fills : DataFrame  — fills against your MM quotes (kappa estimation signal)
    params   : dict       — ground truth parameters for validation
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / quote_rate
    n_ticks = int(n_seconds * quote_rate)

    # ------------------------------------------------------------------
    # 1. Mid-price — AR(1) log returns (same as your original)
    # ------------------------------------------------------------------
    sigma_per_tick = sigma_per_sec * np.sqrt(dt)
    rets = np.zeros(n_ticks)
    noise = rng.normal(0, sigma_per_tick, n_ticks)
    for i in range(1, n_ticks):
        rets[i] = autocorr * rets[i - 1] + noise[i] * np.sqrt(1 - autocorr ** 2)

    mid = mid_start * np.exp(np.cumsum(rets))
    times = np.arange(n_ticks) * dt

    # ------------------------------------------------------------------
    # 2. BBO quotes — original schema
    # ------------------------------------------------------------------
    quotes = pd.DataFrame({
        "time_exchange": times,
        "time_coinapi":  times,
        "ask_price":     mid + bbo_spread,
        "ask_size":      rng.uniform(0.5, 2.0, n_ticks),
        "bid_price":     mid - bbo_spread,
        "bid_size":      rng.uniform(0.5, 2.0, n_ticks),
    })

    # ------------------------------------------------------------------
    # 3. Background trades — Poisson(A * exp(-kappa * bbo_spread) * dt)
    # ------------------------------------------------------------------
    lam_bbo = A * np.exp(-kappa * bbo_spread) * dt
    trade_rows = []
    for i in range(n_ticks):
        t, m = times[i], mid[i]
        for _ in range(rng.poisson(lam_bbo)):
            trade_rows.append({"time_exchange": t + rng.uniform(0, dt),
                                "time_coinapi":  t + rng.uniform(0, dt),
                                "price": m + bbo_spread + rng.exponential(bbo_spread * 0.1),
                                "size":  rng.exponential(0.01), "taker_side": "buy"})
        for _ in range(rng.poisson(lam_bbo)):
            trade_rows.append({"time_exchange": t + rng.uniform(0, dt),
                                "time_coinapi":  t + rng.uniform(0, dt),
                                "price": m - bbo_spread - rng.exponential(bbo_spread * 0.1),
                                "size":  rng.exponential(0.01), "taker_side": "sell"})

    trades = (pd.DataFrame(trade_rows)
              .sort_values("time_exchange").reset_index(drop=True))

    # ------------------------------------------------------------------
    # 4. MM fills — Poisson(A * exp(-kappa * mm_half_spread) * dt) per side
    #    This is the signal you use to estimate kappa
    # ------------------------------------------------------------------
    lam_mm = A * np.exp(-kappa * mm_half_spread) * dt
    mm_fill_rows = []
    for i in range(n_ticks):
        t, m = times[i], mid[i]
        for _ in range(rng.poisson(lam_mm)):
            mm_fill_rows.append({"time_exchange": t + rng.uniform(0, dt),
                                  "mid_at_fill": m,
                                  "fill_price":  m + mm_half_spread,
                                  "fill_size":   min(mm_quote_size, rng.exponential(mm_quote_size)),
                                  "side": "ask", "delta": mm_half_spread})
        for _ in range(rng.poisson(lam_mm)):
            mm_fill_rows.append({"time_exchange": t + rng.uniform(0, dt),
                                  "mid_at_fill": m,
                                  "fill_price":  m - mm_half_spread,
                                  "fill_size":   min(mm_quote_size, rng.exponential(mm_quote_size)),
                                  "side": "bid", "delta": mm_half_spread})

    mm_fills = (pd.DataFrame(mm_fill_rows)
                .sort_values("time_exchange").reset_index(drop=True))

    params = {
        "A": A, "kappa": kappa,
        "mm_half_spread": mm_half_spread,
        "sigma_per_sec": sigma_per_sec,
        "bbo_spread": bbo_spread,
        "lambda_mm":  A * np.exp(-kappa * mm_half_spread),   # fills/sec per side
        "lambda_bbo": A * np.exp(-kappa * bbo_spread),
        "lam_mm_per_tick": lam_mm,
    }
    return trades, quotes, mm_fills, params


# ---------------------------------------------------------------------------
# Kappa estimation — Poisson MLE
# ---------------------------------------------------------------------------

def build_poisson_obs(mm_fills: pd.DataFrame,
                      n_seconds: float,
                      quote_rate: float,
                      mm_half_spread: float) -> pd.DataFrame:
    """
    Build per-tick fill count observations for Poisson MLE.

    One row per tick: how many fills arrived in that tick interval.
    This is exact — no Bernoulli/rare-event approximation needed.
    Works correctly even when lambda/tick > 1.

    Returns DataFrame with columns: [delta, count, dt]
    """
    dt = 1.0 / quote_rate
    n_ticks = int(n_seconds * quote_rate)
    fill_times = mm_fills["time_exchange"].values
    tick_idx = np.floor(fill_times / dt).astype(int).clip(0, n_ticks - 1)
    counts = np.bincount(tick_idx, minlength=n_ticks)
    return pd.DataFrame({
        "delta": np.full(n_ticks, mm_half_spread),
        "count": counts,
        "dt":    np.full(n_ticks, dt),
    })


def estimate_kappa_poisson(obs_list: list,
                            kappa_prior: float = 1.5,
                            lam: float = 0.1) -> dict:
    """
    Regularized Poisson MLE for kappa across one or more spread levels.

    Model: count_i ~ Poisson(A * exp(-kappa * delta_i) * dt_i)
    Objective: max  ell(kappa) - (lam/2)*(kappa - kappa_prior)^2
    A is concentrated out analytically at each kappa evaluation.

    Parameters
    ----------
    obs_list    : list of DataFrames from build_poisson_obs(), one per spread level.
                  A single DataFrame is also accepted.
                  Using multiple spread levels is required to separately identify
                  kappa from A (otherwise only A*exp(-kappa*delta) is identified).
    kappa_prior : prior / initial estimate from offline calibration
    lam         : regularization strength. Use lam ~ lam_base/sqrt(n_fills)
                  for adaptive regularization (Cao et al. recommendation).

    Returns dict: kappa_hat, A_hat, se, n_obs, converged

    Note on A_hat
    -------------
    If obs_list combines bid+ask fills (both sides), A_hat will be ~2x the
    per-side A. Divide by 2 to recover the per-side baseline intensity.
    """
    if isinstance(obs_list, pd.DataFrame):
        obs_list = [obs_list]
    obs = pd.concat(obs_list, ignore_index=True)

    deltas = obs["delta"].values
    counts = obs["count"].values
    dts    = obs["dt"].values
    n = len(obs)

    if counts.sum() < 10:
        return {"kappa_hat": kappa_prior, "A_hat": None, "se": None,
                "n_obs": n, "note": "too few fills, returning prior"}

    def neg_ll(log_kappa):
        k = np.exp(log_kappa)
        exp_terms = np.exp(-k * deltas)
        # Concentrate out A: dℓ/dA = 0 → A = mean(count/dt) / mean(exp(-k*delta))
        A_hat = np.clip(
            np.mean(counts / dts) / (np.mean(exp_terms) + 1e-12),
            1e-6, 1e6
        )
        lam_i = np.clip(A_hat * exp_terms * dts, 1e-10, None)
        ll = np.sum(counts * np.log(lam_i) - lam_i)
        penalty = (lam / 2) * (k - kappa_prior) ** 2
        return -(ll - penalty)

    result = minimize_scalar(neg_ll,
                             bounds=(np.log(0.01), np.log(100.0)),
                             method="bounded")
    k_hat = np.exp(result.x)

    exp_terms = np.exp(-k_hat * deltas)
    A_hat = np.mean(counts / dts) / (np.mean(exp_terms) + 1e-12)

    h = 1e-4
    hess = (neg_ll(result.x+h) - 2*neg_ll(result.x) + neg_ll(result.x-h)) / h**2
    se = k_hat / np.sqrt(max(hess, 1e-10))

    return {
        "kappa_hat": k_hat,
        "A_hat":     A_hat,      # NOTE: divide by 2 if obs combine both sides
        "se":        se,
        "n_obs":     int(counts.sum()),
        "converged": result.success,
    }


def rolling_kappa_estimate(mm_fills: pd.DataFrame,
                            n_seconds: float,
                            quote_rate: float,
                            mm_half_spread: float,
                            window_seconds: float = 300.0,
                            step_seconds: float = 60.0,
                            kappa_prior: float = 1.5,
                            lam_base: float = 0.5) -> pd.DataFrame:
    """
    Rolling Poisson MLE for kappa through time.

    Regularization adapts to observation count per Cao et al.:
        lam = lam_base / sqrt(n_fills)
    Short windows (few fills) stay close to the prior.
    Longer windows trust the data.

    Returns DataFrame: [time, kappa_hat, A_hat, se, n_fills, fill_rate]
    """
    dt = 1.0 / quote_rate
    records = []
    t = window_seconds
    while t <= n_seconds:
        window_fills = mm_fills[
            (mm_fills["time_exchange"] >= t - window_seconds) &
            (mm_fills["time_exchange"] <  t)
        ]
        n_fills = len(window_fills)
        obs = build_poisson_obs(window_fills, window_seconds, quote_rate, mm_half_spread)

        lam = lam_base / np.sqrt(max(n_fills, 1))
        est = estimate_kappa_poisson(obs, kappa_prior=kappa_prior, lam=lam)

        n_ticks = int(window_seconds * quote_rate)
        records.append({
            "time":      t,
            "kappa_hat": est["kappa_hat"],
            "A_hat":     est["A_hat"],
            "se":        est["se"],
            "n_fills":   n_fills,
            "fill_rate": n_fills / (n_ticks * 2),  # per tick per side
        })
        t += step_seconds

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Demo / smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)

    TRUE_KAPPA  = 1.5
    TRUE_A      = 2.0   # fills/sec per side at delta=0
    MM_SPREAD   = 0.30
    N_SECONDS   = 3600
    QUOTE_RATE  = 5.0

    print("=" * 55)
    print("AS Synthetic Generator — Smoke Test")
    print("=" * 55)

    trades, quotes, mm_fills, params = generate_synthetic_btc(
        n_seconds=N_SECONDS, sigma_per_sec=0.00009, autocorr=0,
        A=TRUE_A, kappa=TRUE_KAPPA, mm_half_spread=MM_SPREAD,
        quote_rate=QUOTE_RATE, bbo_spread=0.20, seed=42,
    )

    print(f"\nGround truth:   A={TRUE_A},  kappa={TRUE_KAPPA}")
    print(f"Fill rate:      {params['lambda_mm']:.3f} fills/sec per side at delta={MM_SPREAD}")
    print(f"MM fills total: {len(mm_fills)}")
    print(f"Bg trades:      {len(trades)}")

    # --- Single-spread MLE (only identifies A*exp(-kappa*delta)) ---
    obs_single = build_poisson_obs(mm_fills, N_SECONDS, QUOTE_RATE, MM_SPREAD)
    est_single = estimate_kappa_poisson(obs_single, kappa_prior=1.5, lam=0.01)
    print(f"\nSingle-spread MLE (delta={MM_SPREAD}):")
    print(f"  kappa_hat = {est_single['kappa_hat']:.4f}  (only A*exp(-k*d) identified — "
          f"kappa not separately recoverable)")
    print(f"  A_hat/2   = {est_single['A_hat']/2:.4f}  (true A={TRUE_A})")

    # --- Multi-spread MLE: vary delta to separately identify kappa and A ---
    print(f"\nMulti-spread MLE (5 spread levels — separately identifies kappa and A):")
    SPREADS = [0.10, 0.20, 0.30, 0.50, 0.80]
    obs_list = []
    for s in SPREADS:
        _, _, fills_s, _ = generate_synthetic_btc(
            n_seconds=N_SECONDS, A=TRUE_A, kappa=TRUE_KAPPA,
            mm_half_spread=s, quote_rate=QUOTE_RATE, bbo_spread=0.08,
            autocorr=0, seed=42,
        )
        obs_list.append(build_poisson_obs(fills_s, N_SECONDS, QUOTE_RATE, s))
        print(f"  delta={s:.2f}: {len(fills_s):>5} fills  "
              f"({len(fills_s)/N_SECONDS:.2f}/sec)")

    est_multi = estimate_kappa_poisson(obs_list, kappa_prior=1.5, lam=0.01)
    print(f"\n  kappa_hat = {est_multi['kappa_hat']:.4f}  (true={TRUE_KAPPA})")
    print(f"  A_hat/2   = {est_multi['A_hat']/2:.4f}  (true A={TRUE_A})")
    print(f"  se        = {est_multi['se']:.5f}")

    # --- Rolling estimation (single spread — tracks kappa drift over time) ---
    print(f"\nRolling kappa (5-min windows, 1-min steps):")
    rolling = rolling_kappa_estimate(
        mm_fills, n_seconds=N_SECONDS, quote_rate=QUOTE_RATE,
        mm_half_spread=MM_SPREAD, window_seconds=300, step_seconds=60,
        kappa_prior=1.5, lam_base=0.5,
    )
    print(rolling[["time", "kappa_hat", "se", "n_fills"]].to_string(index=False))

    # Save
    try:
        trades.to_parquet("data/trades_BTC_2026-04-15.parquet")
        quotes.to_parquet("data/quotes_BTC_2026-04-15.parquet")
        mm_fills.to_parquet("data/mm_fills_BTC_2026-04-15.parquet")
        print("\nSaved as parquet.")
    except Exception:
        trades.to_csv("data/trades_BTC_2026-04-15.csv", index=False)
        quotes.to_csv("data/quotes_BTC_2026-04-15.csv", index=False)
        mm_fills.to_csv("data/mm_fills_BTC_2026-04-15.csv", index=False)
        print("\nSaved as CSV.")