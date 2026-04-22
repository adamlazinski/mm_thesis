import pandas as pd
import numpy as np

fills = pd.read_parquet("results/2025-05-13_fills.parquet")
fills["timestamp"] = pd.to_datetime(fills["timestamp"], unit="s", utc=True)
fills = fills.sort_values("timestamp").reset_index(drop=True)

# For each bid fill, find the next ask fill after it
round_trips = []

ask_fills = fills[fills["side"] == "ask"].copy()

for _, bid in fills[fills["side"] == "bid"].iterrows():
    # Find first ask fill after this bid
    subsequent_asks = ask_fills[ask_fills["timestamp"] > bid["timestamp"]]
    if subsequent_asks.empty:
        continue
    ask = subsequent_asks.iloc[0]
    round_trips.append({
        "bid_time":        bid["timestamp"],
        "ask_time":        ask["timestamp"],
        "bid_price":       bid["price"],
        "ask_price":       ask["price"],
        "qty":             min(bid["quantity"], ask["quantity"]),
        "spread_captured": ask["price"] - bid["price"],
        "hold_time_sec":   (ask["timestamp"] - bid["timestamp"]).total_seconds(),
    })

rt = pd.DataFrame(round_trips)
rt["profitable"] = rt["spread_captured"] > 0

print(f"Total round trips:     {len(rt)}")
print(f"Profitable:            {rt['profitable'].sum()} ({rt['profitable'].mean()*100:.1f}%)")
print(f"Avg spread captured:   ${rt['spread_captured'].mean():.4f}")
print(f"Avg hold time:         {rt['hold_time_sec'].mean():.2f}s")
print()
print("Spread captured distribution:")
print(rt["spread_captured"].describe())
print()
print("Hold time for losing vs winning:")
print(rt.groupby("profitable")["hold_time_sec"].mean())
fills = pd.read_parquet("results/2025-05-13_fills.parquet")
quotes = pd.read_parquet("results/2025-05-13_quotes.parquet")

# Find periods of sustained short inventory
# What is reservation price vs mid when inventory is negative?
quotes["half_spread"] = (quotes["ask"] - quotes["bid"]) / 2
quotes['half_spread'].plot()
quotes["mid_ask_dist"] = quotes["ask"] - quotes["mid"]
quotes["mid_bid_dist"] = quotes["mid"] - quotes["bid"]
print(quotes['mid_ask_dist'].mean())
neg_inv = quotes[quotes["inventory"] < -0.01]
print("When short >0.02 BTC:")
print(f"avg ask distance from mid: ${neg_inv['mid_ask_dist'].mean():.4f}")
print(f"avg bid distance from mid: ${neg_inv['mid_bid_dist'].mean():.4f}")
print(f"asymmetry (ask-bid dist):  ${(neg_inv['mid_ask_dist'] - neg_inv['mid_bid_dist']).mean():.4f}")