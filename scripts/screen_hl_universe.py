"""
screen_hl_universe.py
=====================
Route-5 screening tool (the C55 roadmap item, realized): rank every Hyperliquid
perp by "wide spread x thin book x non-trivial volume" — the configuration where
the Wyart-Bouchaud equilibrium may be under-enforced because maker competition
is thin. Candidates feed the collector; the pipeline (exp 93 horizon, maker
census, exp 103 round-trip) decides.

Uses the public info endpoint (no auth):
  metaAndAssetCtxs      -> every perp's day notional volume, mark/mid, OI
  l2Book (per candidate)-> spread, touch + 10-level depth

Run: python scripts/screen_hl_universe.py [--min-vol 100000] [--max-vol 5000000]
Writes search/hl_universe_screen_<date>.json and prints the ranked table.
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.request
from datetime import date
from pathlib import Path

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()

API = "https://api.hyperliquid.xyz/info"


def post(payload: dict):
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "screen/1.0"})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vol", type=float, default=100_000.0)
    ap.add_argument("--max-vol", type=float, default=5_000_000.0)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    meta, ctxs = post({"type": "metaAndAssetCtxs"})
    rows = []
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset.get("isDelisted"):
            continue
        try:
            vol = float(ctx.get("dayNtlVlm") or 0)
            mid = float(ctx.get("midPx") or 0)
            oi = float(ctx.get("openInterest") or 0)
        except (TypeError, ValueError):
            continue
        if mid <= 0 or not (args.min_vol <= vol <= args.max_vol):
            continue
        rows.append({"coin": asset["name"], "day_vol_usd": vol,
                     "mid": mid, "oi_usd": oi * mid})
    print(f"universe: {len(meta['universe'])} perps; "
          f"{len(rows)} in volume band [${args.min_vol:,.0f}, ${args.max_vol:,.0f}]")

    # book stats per candidate
    for r in rows:
        try:
            book = post({"type": "l2Book", "coin": r["coin"]})
            bids, asks = book["levels"][0], book["levels"][1]
            if not bids or not asks:
                continue
            bb, ba = float(bids[0]["px"]), float(asks[0]["px"])
            m = (bb + ba) / 2
            r["spread_bps"] = 1e4 * (ba - bb) / m
            r["touch_usd"] = (float(bids[0]["sz"]) * bb + float(asks[0]["sz"]) * ba) / 2
            r["depth10_usd"] = (sum(float(x["sz"]) * float(x["px"]) for x in bids[:10])
                                + sum(float(x["sz"]) * float(x["px"]) for x in asks[:10])) / 2
            r["n_orders_touch"] = int(bids[0].get("n", 0)) + int(asks[0].get("n", 0))
        except Exception as e:  # noqa: BLE001 — screening: skip failures
            r["spread_bps"] = None
        time.sleep(0.15)

    ok = [r for r in rows if r.get("spread_bps") is not None]
    # rank: wide spread, thin touch, enough volume to matter
    for r in ok:
        r["score"] = r["spread_bps"] * (r["day_vol_usd"] / 1e6) ** 0.5
    ok.sort(key=lambda r: -r["score"])

    print(f"\n{'coin':10s} {'spread':>8s} {'vol/day':>12s} {'touch':>10s} "
          f"{'depth10':>11s} {'n@touch':>7s} {'OI':>12s} {'score':>7s}")
    for r in ok[:args.top]:
        print(f"{r['coin']:10s} {r['spread_bps']:7.1f}b {r['day_vol_usd']:>11,.0f} "
              f"{r['touch_usd']:>9,.0f} {r['depth10_usd']:>10,.0f} "
              f"{r['n_orders_touch']:>7d} {r['oi_usd']:>11,.0f} {r['score']:>7.1f}")

    out_dir = Path("search")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"hl_universe_screen_{date.today().isoformat()}.json"
    with open(path, "w") as fh:
        json.dump({"date": date.today().isoformat(),
                   "band": [args.min_vol, args.max_vol], "rows": ok}, fh, indent=2)
    print(f"\nSaved -> {path}")


if __name__ == "__main__":
    main()
