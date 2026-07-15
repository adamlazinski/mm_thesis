"""
process_coinbase_capture.py
===========================
Convert raw Coinbase captures (collect_coinbase_l2.py spot + collect_coinbase_perp.py
perp) into CoinAPI-schema parquets, alongside the Binance-processed files, so the
cross-venue analyses load both venues from one directory.

Writes under --out (default data/live/processed):
    trades_{ASSET}_{DATE}.parquet
    quotes_{ASSET}_{DATE}.parquet
    orderbooks_{ASSET}_{DATE}.parquet   (spot only, with --orderbooks)

ASSET naming (kept distinct from Binance's LINK/BTC/LINK_PERP/BTC_PERP):
    CB_LINK, CB_BTC              (spot, full L2)
    CB_LINK_PERP, CB_BTC_PERP    (perp, top-of-book + trades)

Usage:
    python scripts/process_coinbase_capture.py --date 2026-07-16
    python scripts/process_coinbase_capture.py --date 2026-07-16 --orderbooks
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hft_market_maker.data.coinbase_capture import replay_perp_day, replay_spot_day

# spot capture label -> (output asset, CoinAPI-style symbol_id)
SPOT = {
    "LINKUSD": ("CB_LINK", "COINBASE_SPOT_LINK_USD"),
    "BTCUSD":  ("CB_BTC",  "COINBASE_SPOT_BTC_USD"),
}
# perp product id -> output asset  (one combined PERPINTX capture file)
PERP = {
    "BTC-PERP-INTX":  "CB_BTC_PERP",
    "LINK-PERP-INTX": "CB_LINK_PERP",
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, help="UTC date, e.g. 2026-07-16")
    p.add_argument("--capture-dir", default="data/live")
    p.add_argument("--out", default="data/live/processed")
    p.add_argument("--orderbooks", action="store_true",
                   help="also reconstruct top-20 spot orderbooks (heavier)")
    p.add_argument("--only", choices=["spot", "perp"], help="limit to one feed")
    args = p.parse_args()

    reports = {}

    if args.only != "perp":
        for label, (asset, symbol_id) in SPOT.items():
            print(f"\n=== coinbase spot {label} -> {asset} {args.date} ===")
            t0 = time.time()
            try:
                rep = replay_spot_day(args.capture_dir, label, args.date,
                                      symbol_id, args.out, asset,
                                      want_books=args.orderbooks)
            except FileNotFoundError as e:
                print(f"  SKIP: {e}")
                continue
            rep["elapsed_s"] = round(time.time() - t0, 1)
            reports[asset] = rep
            print(f"  l2={rep['n_l2']:,}  trades={rep['n_trades']:,}  "
                  f"quotes={rep['n_quotes']:,}  snapshots={rep['n_snapshots']}  "
                  f"gaps={rep['n_gaps']}  crossed={rep['n_crossed']}  "
                  f"[{rep['elapsed_s']}s]")

    if args.only != "spot":
        print(f"\n=== coinbase perp {list(PERP.values())} {args.date} ===")
        t0 = time.time()
        try:
            rep = replay_perp_day(args.capture_dir, args.date, PERP, args.out)
            rep["elapsed_s"] = round(time.time() - t0, 1)
            reports["perp"] = rep
            for asset, r in rep["products"].items():
                print(f"  {asset}: trades={r['n_trades']:,}  quotes={r['n_quotes']:,}")
            print(f"  [{rep['elapsed_s']}s]")
        except FileNotFoundError as e:
            print(f"  SKIP: {e}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt = out_dir / f"integrity_coinbase_{args.date}.json"
    with open(rpt, "w") as fh:
        json.dump(reports, fh, indent=2)
    print(f"\nIntegrity report -> {rpt}")


if __name__ == "__main__":
    main()
