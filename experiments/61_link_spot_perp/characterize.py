"""
LINK spot <-> perp characterization (exp 61, Stage 1).
======================================================
Make-or-break first cut for the cross-venue fusion hypothesis (the one unrefuted
escape in the register). Three measurements over LINK April 2026:

  1. SPREAD: perp vs spot, in ticks and $ (verify exp 54's perp~1t vs spot~10t).
  2. LEAD-LAG: who moves first, spot or perp, and by how much. Cross-correlation
     of mid returns, ρ(k) = corr(r_perp[t], r_spot[t+k]); a peak at k>0 means perp
     LEADS spot by k. If perp leads by an exploitable margin there is a signal; if
     contemporaneous, the fusion idea is dead on arrival.
  3. BASIS: perp_mid - spot_mid (level and volatility).

Data note: the perp BBO is sampled at 1 Hz (orderbook-snapshot rate), so BBO-based
lead-lag is resolved to 1 s. A finer (250 ms) check uses the perp LAST-TRADE price
(~4 trades/s) against the spot mid to catch any sub-second lead.

Run:
    python experiments/61_link_spot_perp/characterize.py --days 30
"""
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "real"
OUT = Path("experiments/61_link_spot_perp/results")


def link_dates():
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_2026-04-*.parquet"))}
    pp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_PERP_2026-04-*.parquet"))}
    return sorted(sp & pp)


def load_bbo(path):
    q = pd.read_parquet(path, columns=["time_exchange", "bid_price", "ask_price"])
    ts = q["time_exchange"].astype("int64").to_numpy()
    ts = ts / 1e9 if ts[0] > 1e17 else (ts / 1e6 if ts[0] > 1e14 else ts.astype(float))
    mid = (q["bid_price"].to_numpy() + q["ask_price"].to_numpy()) / 2.0
    spread = q["ask_price"].to_numpy() - q["bid_price"].to_numpy()
    return ts, mid, spread


def load_trade_px(path):
    t = pd.read_parquet(path, columns=["time_exchange", "price"])
    ts = t["time_exchange"].astype("int64").to_numpy()
    ts = ts / 1e9 if ts[0] > 1e17 else (ts / 1e6 if ts[0] > 1e14 else ts.astype(float))
    return ts, t["price"].to_numpy().astype(float)


def infer_tick(prices, n=200000):
    u = np.unique(np.round(prices[:n], 6))
    d = np.diff(u)
    d = d[d > 1e-9]
    return float(np.min(d)) if len(d) else np.nan


def on_grid(ts, val, grid):
    idx = np.searchsorted(ts, grid, side="right") - 1
    ok = idx >= 0
    idx = np.clip(idx, 0, len(val) - 1)
    out = val[idx].astype(float)
    out[~ok] = np.nan
    return out


def ccf(rx, ry, lags):
    """ρ(k) = corr(rx[t], ry[t+k]) for k in lags (k>0 => rx leads ry)."""
    out = []
    for k in lags:
        if k >= 0:
            a, b = rx[:len(rx) - k], ry[k:]
        else:
            a, b = rx[-k:], ry[:len(ry) + k]
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < 100:
            out.append(np.nan); continue
        a, b = a[m], b[m]
        sa, sb = a.std(), b.std()
        out.append(float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb)) if sa > 0 and sb > 0 else np.nan)
    return np.array(out)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    dates = link_dates()[: args.days]
    print(f"LINK spot<->perp on {len(dates)} days ({dates[0]}..{dates[-1]})")

    DT1 = 1.0;   LAGS1 = np.arange(-10, 11)          # 1 s grid, ±10 s (BBO)
    DT2 = 0.25;  LAGS2 = np.arange(-12, 13)          # 250 ms grid, ±3 s (perp trades)
    spreads = {"spot_ticks": [], "perp_ticks": [], "spot_dollar": [], "perp_dollar": []}
    basis = []
    ccf1_acc, ccf2_acc = [], []
    tick_spot = tick_perp = np.nan

    for d in dates:
        try:
            s_ts, s_mid, s_spr = load_bbo(DATA / f"quotes_LINK_{d}.parquet")
            p_ts, p_mid, p_spr = load_bbo(DATA / f"quotes_LINK_PERP_{d}.parquet")
            pt_ts, pt_px = load_trade_px(DATA / f"trades_LINK_PERP_{d}.parquet")
            if np.isnan(tick_spot):
                tick_spot = infer_tick(s_mid * 2); tick_perp = infer_tick(p_mid * 2)
            ts_p = tick_perp if tick_perp > 0 else 0.001
            ts_s = tick_spot if tick_spot > 0 else 0.001

            spreads["spot_dollar"].append(np.nanmedian(s_spr))
            spreads["perp_dollar"].append(np.nanmedian(p_spr))
            spreads["spot_ticks"].append(np.nanmedian(s_spr) / ts_s)
            spreads["perp_ticks"].append(np.nanmedian(p_spr) / ts_p)

            t0 = max(s_ts[0], p_ts[0]); t1 = min(s_ts[-1], p_ts[-1])
            # 1 s grid: spot mid (BBO) vs perp mid (BBO)
            g1 = np.arange(np.ceil(t0), np.floor(t1), DT1)
            sm1 = on_grid(s_ts, s_mid, g1); pm1 = on_grid(p_ts, p_mid, g1)
            basis.append(float(np.nanmedian(pm1 - sm1)))
            rs1 = np.diff(sm1, prepend=np.nan); rp1 = np.diff(pm1, prepend=np.nan)
            ccf1_acc.append(ccf(rp1, rs1, LAGS1))   # rp leads rs if peak k>0

            # 250 ms grid: spot mid vs perp last-trade price
            g2 = np.arange(np.ceil(t0), np.floor(t1), DT2)
            sm2 = on_grid(s_ts, s_mid, g2); pp2 = on_grid(pt_ts, pt_px, g2)
            rs2 = np.diff(sm2, prepend=np.nan); rp2 = np.diff(pp2, prepend=np.nan)
            ccf2_acc.append(ccf(rp2, rs2, LAGS2))
            print(f"  {d}: ok ({len(g1):,} 1s pts)")
        except Exception as e:
            print(f"  {d}: ERROR {e}")

    ccf1 = np.nanmean(np.vstack(ccf1_acc), axis=0)
    ccf2 = np.nanmean(np.vstack(ccf2_acc), axis=0)
    k1 = LAGS1[int(np.nanargmax(np.abs(ccf1)))]
    k2 = LAGS2[int(np.nanargmax(np.abs(ccf2)))]

    print(f"\n{'='*70}\nSPREAD (median/day)\n{'='*70}")
    print(f"  tick: spot={tick_spot:.4f}  perp={tick_perp:.4f}")
    print(f"  spot:  {np.mean(spreads['spot_ticks']):.2f} ticks  (${np.mean(spreads['spot_dollar']):.4f})")
    print(f"  perp:  {np.mean(spreads['perp_ticks']):.2f} ticks  (${np.mean(spreads['perp_dollar']):.4f})")

    print(f"\n{'='*70}\nLEAD-LAG  ρ(k)=corr(r_perp[t], r_spot[t+k]);  k>0 ⇒ PERP LEADS\n{'='*70}")
    print("  [1s grid, BBO mids]")
    for k, c in zip(LAGS1, ccf1):
        bar = "#" * int(abs(c) * 100) if np.isfinite(c) else ""
        star = "  <-- peak" if k == k1 else ""
        print(f"    k={k:+3d}s  ρ={c:+.3f} {bar}{star}")
    print(f"  peak |ρ| at k={k1:+d}s  ->  {'PERP leads spot' if k1>0 else ('SPOT leads perp' if k1<0 else 'contemporaneous')}")
    print(f"\n  [250ms grid, perp trade-px vs spot mid] peak |ρ| at k={k2*DT2:+.2f}s "
          f"({'perp leads' if k2>0 else ('spot leads' if k2<0 else 'contemporaneous')})")

    print(f"\n{'='*70}\nBASIS (perp_mid - spot_mid), median/day: ${np.mean(basis):+.4f}\n{'='*70}")

    json.dump({
        "dates": dates,
        "tick": {"spot": tick_spot, "perp": tick_perp},
        "spread_ticks": {"spot": float(np.mean(spreads["spot_ticks"])),
                          "perp": float(np.mean(spreads["perp_ticks"]))},
        "spread_dollar": {"spot": float(np.mean(spreads["spot_dollar"])),
                          "perp": float(np.mean(spreads["perp_dollar"]))},
        "leadlag_1s": {"lags": LAGS1.tolist(), "ccf": ccf1.tolist(), "peak_k_s": int(k1)},
        "leadlag_250ms": {"lags_s": (LAGS2 * DT2).tolist(), "ccf": ccf2.tolist(),
                          "peak_k_s": float(k2 * DT2)},
        "basis_dollar": float(np.mean(basis)),
    }, open(OUT / "characterize.json", "w"), indent=2)
    print(f"\nSaved -> {OUT / 'characterize.json'}")


if __name__ == "__main__":
    main()
