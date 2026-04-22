import pandas as pd
import numpy as np

def generate_synthetic_btc(
    n_seconds: int = 86400,
    mid_start: float = 102000.0,
    sigma_per_sec: float = 0.00006,
    autocorr: float = -0.05,
    trade_rate: float = 44.0,
    quote_rate: float = 10.0,
    spread: float = 0.01,
    seed: int = 42,
):
    rng = np.random.default_rng(seed)
    dt = 1.0 / quote_rate
    n_quotes = int(n_seconds * quote_rate)

    # AR(1) mid price at quote frequency
    sigma_per_tick = sigma_per_sec * np.sqrt(dt)
    rets = np.zeros(n_quotes)
    noise = rng.normal(0, sigma_per_tick, n_quotes)
    for i in range(1, n_quotes):
        rets[i] = autocorr * rets[i-1] + noise[i] * np.sqrt(1 - autocorr**2)

    mid = mid_start * np.exp(np.cumsum(rets))
    times_quotes = np.arange(n_quotes) * dt

    # Quotes — match exact schema
    quotes = pd.DataFrame({
        "time_exchange": times_quotes,
        "time_coinapi":  times_quotes,
        "ask_price":     mid + spread / 2,
        "ask_size":      rng.uniform(0.5, 2.0, n_quotes),
        "bid_price":     mid - spread / 2,
        "bid_size":      rng.uniform(0.5, 2.0, n_quotes),
    })

    # Trades — Poisson arrivals
    n_trades = int(n_seconds * trade_rate)
    trade_times = np.sort(rng.uniform(0, n_seconds, n_trades))
    quote_idx = np.searchsorted(times_quotes, trade_times).clip(0, n_quotes - 1)
    trade_mids = mid[quote_idx]

    sides = rng.choice(["buy", "sell"], n_trades)
    trade_prices = np.where(
        sides == "buy",
        trade_mids + spread / 2+rng.uniform(0,spread/4,n_trades),
        trade_mids - spread / 2- rng.uniform(0, spread/4, n_trades),
    )

    trades = pd.DataFrame({
        "time_exchange": trade_times,
        "time_coinapi":  trade_times,
        "price":         trade_prices,
        "size":          rng.uniform(0.001, 0.05, n_trades),
        "taker_side":    sides,
    })

    return trades, quotes


# Save
trades, quotes = generate_synthetic_btc(autocorr=0, n_seconds=3600, sigma_per_sec=0.00009,
                                        trade_rate=8,quote_rate=5,spread=0.6)
trades.to_parquet("data/trades_BTC_2026-04-15.parquet")
quotes.to_parquet("data/quotes_BTC_2026-04-15.parquet")