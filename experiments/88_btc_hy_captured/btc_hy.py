"""
btc_hy.py
==========
Exp 88 — BTC spot ↔ perp Hayashi–Yoshida lead-lag on captured live data.

Completes C36's cross-asset symmetry check, previously blocked by the
mislabeled CoinAPI BTC-PERP trade file. Uses the live-captured day processed by
scripts/process_binance_capture.py and the HY estimator from exp 61 unchanged.

Run: python experiments/88_btc_hy_captured/btc_hy.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "hy61", ROOT / "experiments/61_link_spot_perp/hy_leadlag.py")
hy61 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hy61)

PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    args = p.parse_args()

    thetas = np.round(np.arange(-2.0, 2.01, 0.1), 2)
    tx, px = hy61.load_trades(PROC / f"trades_BTC_{args.date}.parquet", args.date)
    ty, py = hy61.load_trades(PROC / f"trades_BTC_PERP_{args.date}.parquet", args.date)
    print(f"spot trades: {len(tx):,}  perp trades: {len(ty):,}")

    curve, vx, vy = hy61.hy_curve(tx, px, ty, py, thetas)
    kpk = int(np.nanargmax(np.abs(curve)))
    print(f"peak theta = {thetas[kpk]:+.1f}s  rho = {curve[kpk]:.3f}")
    for th, r in zip(thetas, curve):
        if abs(th) <= 1.0 and round(th * 10) % 5 == 0:
            print(f"  theta={th:+.1f}s  rho={r:.3f}")
    pos = float(np.nansum(curve[thetas > 0]))
    neg = float(np.nansum(curve[thetas < 0]))
    print(f"sum rho (theta>0, perp leads): {pos:.3f}   (theta<0, spot leads): {neg:.3f}")

    with open(OUT / f"btc_hy_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "thetas": thetas.tolist(),
                   "ccf": [float(x) for x in curve],
                   "peak_theta_s": float(thetas[kpk]),
                   "peak_rho": float(curve[kpk]),
                   "sum_pos": pos, "sum_neg": neg,
                   "n_spot": len(tx), "n_perp": len(ty)}, fh, indent=2)
    print(f"Saved -> {OUT}/btc_hy_{args.date}.json")


if __name__ == "__main__":
    main()
