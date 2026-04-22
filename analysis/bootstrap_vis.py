import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def generate_synthetic_btc(
    n_seconds: int = 86400,
    mid_start: float = 102000.0,
    sigma_per_sec: float = 0.000029,
    autocorr: float = -0.05,
    trade_rate: float = 44.0,
    quote_rate: float = 8.0,
    spread: float = 0.01,
    seed: int = 42,
):
    rng = np.random.default_rng(seed)
    dt = 1.0 / quote_rate
    n_quotes = int(n_seconds * quote_rate)
    
    sigma_per_tick = sigma_per_sec * np.sqrt(dt)
    rets = np.zeros(n_quotes)
    noise = rng.normal(0, sigma_per_tick, n_quotes)
    for i in range(1, n_quotes):
        rets[i] = autocorr * rets[i-1] + noise[i] * np.sqrt(1 - autocorr**2)
    
    mid = mid_start * np.exp(np.cumsum(rets))
    times_quotes = np.arange(n_quotes) * dt
    
    quotes = pd.DataFrame({
        "time_exchange": times_quotes,
        "mid": mid,
        "best_bid": mid - spread / 2,
        "best_ask": mid + spread / 2,
    })
    return quotes

# Generate three scenarios
scenarios = {
    "Mean-reverting (autocorr=-0.05)": -0.05,
    "Random walk (autocorr=0.00)":      0.00,
    "Trending (autocorr=+0.18)":       +0.18,
}

fig, axes = plt.subplots(3, 2, figsize=(14, 10))
fig.suptitle("Synthetic BTC mid price — 1s resampled", fontsize=13)

for row, (label, autocorr) in enumerate(scenarios.items()):
    quotes = generate_synthetic_btc(autocorr=autocorr)
    
    # Convert to datetime index and resample to 1s
    quotes["timestamp"] = pd.to_datetime(quotes["time_exchange"], unit="s")
    quotes = quotes.set_index("timestamp")
    mid_1s = quotes["mid"].resample("200ms").last().ffill()
    ret_1s = np.log(mid_1s).diff().dropna()
    
    # Price path
    axes[row, 0].plot(mid_1s.values, linewidth=0.5)
    axes[row, 0].set_title(label)
    axes[row, 0].set_ylabel("Mid price")
    axes[row, 0].set_xlabel("Seconds")
    
    # ACF of 1s returns
    from statsmodels.graphics.tsaplots import plot_acf
    plot_acf(ret_1s, lags=20, ax=axes[row, 1], title=f"ACF 1s returns")
    axes[row, 1].set_xlabel("Lag (seconds)")

plt.tight_layout()
plt.savefig("synthetic_scenarios.png", dpi=150)
plt.show()
print("Saved synthetic_scenarios.png")