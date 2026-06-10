"""
Derive quotes_<SYMBOL>_<date>.parquet from orderbooks_<SYMBOL>_<date>.parquet.
The CoinAPI perp feed ships L2 orderbook snapshots + trades but no separate
top-of-book quotes file. The backtest's DataLoader needs a quotes file with
columns: time_exchange, time_coinapi, ask_price, ask_size, bid_price, bid_size.
We extract L1 (best bid/ask) from each orderbook snapshot.

Usage:
    python scripts/derive_perp_quotes.py --symbol LINK_PERP \
        --start 2026-04-01 --end 2026-04-30 --data-dir data/real
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def l1_from_level(level):
    """level is the asks/bids ndarray of {'price','size'} dicts; [0] is best."""
    best = level[0]
    return float(best["price"]), float(best["size"])


def derive_day(ob_path: Path, out_path: Path) -> int:
    ob = pd.read_parquet(ob_path)
    asks = ob["asks"].values
    bids = ob["bids"].values

    ask_price = np.empty(len(ob)); ask_size = np.empty(len(ob))
    bid_price = np.empty(len(ob)); bid_size = np.empty(len(ob))
    for i in range(len(ob)):
        ask_price[i], ask_size[i] = l1_from_level(asks[i])
        bid_price[i], bid_size[i] = l1_from_level(bids[i])

    out = pd.DataFrame({
        "time_exchange": ob["time_exchange"].values,
        "time_coinapi":  ob["time_coinapi"].values,
        "ask_price": ask_price,
        "ask_size":  ask_size,
        "bid_price": bid_price,
        "bid_size":  bid_size,
    })
    # Drop any crossed/zero rows defensively
    out = out[(out["ask_price"] > out["bid_price"]) & (out["bid_price"] > 0)]
    out.to_parquet(out_path)
    return len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="LINK_PERP")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--data-dir", default="data/real")
    args = ap.parse_args()

    dd = Path(args.data_dir)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    total = 0
    for d in daterange(start, end):
        ds = d.isoformat()
        ob_path = dd / f"orderbooks_{args.symbol}_{ds}.parquet"
        out_path = dd / f"quotes_{args.symbol}_{ds}.parquet"
        if not ob_path.exists():
            print(f"  {ds}: no orderbook, skip")
            continue
        n = derive_day(ob_path, out_path)
        total += n
        print(f"  {ds}: wrote {n:,} quotes -> {out_path.name}")
    print(f"Done. {total:,} total quote rows.")


if __name__ == "__main__":
    main()
