"""
process_hyperliquid_capture.py
==============================
Convert raw Hyperliquid captures (collect_hyperliquid.py) into CoinAPI-schema
parquets (trades with counterparty wallets, quotes from bbo, funding/OI), written
alongside the Binance/Coinbase processed files.

Writes under --out (default data/live/processed):
    trades_{ASSET}_{DATE}.parquet     (+ taker_wallet / maker_wallet columns)
    quotes_{ASSET}_{DATE}.parquet
    funding_{ASSET}_{DATE}.parquet
    orderbooks_{ASSET}_{DATE}.parquet  (with --orderbooks)

ASSET = HL_<COIN>, e.g. HL_BTC, HL_LINK, HL_HYPE.

Usage:
    python scripts/process_hyperliquid_capture.py --date 2026-07-16
    python scripts/process_hyperliquid_capture.py --date 2026-07-16 --coin HYPE --orderbooks
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hft_market_maker.data.hyperliquid_capture import replay_coin_day

DEFAULT_COINS = ["BTC", "ETH", "SOL", "LINK", "HYPE"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, help="UTC date, e.g. 2026-07-16")
    p.add_argument("--capture-dir", default="data/live")
    p.add_argument("--out", default="data/live/processed")
    p.add_argument("--coin", action="append", help="coin(s) (default: BTC ETH SOL LINK HYPE)")
    p.add_argument("--orderbooks", action="store_true",
                   help="also write l2Book snapshots (top-20)")
    args = p.parse_args()

    coins = args.coin or DEFAULT_COINS
    reports = {}
    for coin in coins:
        asset = f"HL_{coin}"
        print(f"\n=== hyperliquid {coin} -> {asset} {args.date} ===")
        t0 = time.time()
        try:
            rep = replay_coin_day(args.capture_dir, coin, args.date,
                                  f"HYPERLIQUID_PERP_{coin}_USD", args.out, asset,
                                  want_books=args.orderbooks)
        except FileNotFoundError as e:
            print(f"  SKIP: {e}")
            continue
        rep["elapsed_s"] = round(time.time() - t0, 1)
        reports[asset] = rep
        print(f"  trades={rep['n_trades']:,}  quotes={rep['n_quotes']:,}  "
              f"funding={rep['n_funding']:,}  l2Book={rep['n_l2Book']:,}  "
              f"gaps={rep['n_gaps']}")
        print(f"  unique wallets: makers={rep['uniq_maker_wallets']:,}  "
              f"takers={rep['uniq_taker_wallets']:,}  [{rep['elapsed_s']}s]")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt = out_dir / f"integrity_hyperliquid_{args.date}.json"
    with open(rpt, "w") as fh:
        json.dump(reports, fh, indent=2)
    print(f"\nIntegrity report -> {rpt}")


if __name__ == "__main__":
    main()
