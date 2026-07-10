"""
process_binance_capture.py
===========================
Convert raw Binance L2 captures (from collect_binance_l2.py) into
CoinAPI-schema parquets consumable by DataLoader.load_coinapi/load_orderbook.

For each instrument and UTC date this writes, under --out:
    trades_{ASSET}_{DATE}.parquet
    quotes_{ASSET}_{DATE}.parquet
    orderbooks_{ASSET}_{DATE}.parquet     (top-20 levels, every depth event)
plus integrity_{DATE}.json with per-instrument sync/gap/clock stats.

ASSET naming matches the existing convention: LINK, BTC, LINK_PERP, BTC_PERP —
so downstream experiment scripts can point at the output directory unchanged.
Outputs are written to a separate directory (default data/live/processed), not
data/real, to keep captured and purchased data apart.

Usage:
    python scripts/process_binance_capture.py --date 2026-07-10
    python scripts/process_binance_capture.py --date 2026-07-10 --only LINKUSDT
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hft_market_maker.data.binance_capture import replay_day

# capture label -> (market, output asset name, CoinAPI-style symbol_id)
INSTRUMENTS = {
    "LINKUSDT":      ("spot", "LINK",      "BINANCE_SPOT_LINK_USDT"),
    "BTCUSDT":       ("spot", "BTC",       "BINANCE_SPOT_BTC_USDT"),
    "LINKUSDT_PERP": ("perp", "LINK_PERP", "BINANCE_PERP_LINK_USDT"),
    "BTCUSDT_PERP":  ("perp", "BTC_PERP",  "BINANCE_PERP_BTC_USDT"),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, help="UTC date, e.g. 2026-07-10")
    p.add_argument("--capture-dir", default="data/live")
    p.add_argument("--out", default="data/live/processed")
    p.add_argument("--only", action="append",
                   help="capture label(s) to process (default: all four)")
    args = p.parse_args()

    labels = args.only or list(INSTRUMENTS)
    reports = {}
    for label in labels:
        market, asset, symbol_id = INSTRUMENTS[label]
        print(f"\n=== {label} ({market}) -> {asset} {args.date} ===")
        t0 = time.time()
        try:
            rep = replay_day(args.capture_dir, label, args.date,
                             market=market, symbol_id=symbol_id,
                             out_dir=args.out, asset=asset)
        except FileNotFoundError as e:
            print(f"  SKIP: {e}")
            continue
        rep["elapsed_s"] = round(time.time() - t0, 1)
        reports[label] = rep
        print(f"  depth={rep['n_depth']:,}  trades={rep['n_trades']:,}  "
              f"snapshots={rep['n_snapshots']}  reanchors={rep['n_reanchors']}  "
              f"sync_violations={rep['n_sync_violations']}  "
              f"crossed={rep['n_crossed']}")
        if "recv_minus_exch_ms_p50" in rep:
            print(f"  clock offset recv-exch: p50={rep['recv_minus_exch_ms_p50']:.0f}ms "
                  f"p99={rep['recv_minus_exch_ms_p99']:.0f}ms")
        print(f"  elapsed {rep['elapsed_s']}s")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt_path = out_dir / f"integrity_{args.date}.json"
    with open(rpt_path, "w") as fh:
        json.dump(reports, fh, indent=2)
    print(f"\nIntegrity report -> {rpt_path}")


if __name__ == "__main__":
    main()
