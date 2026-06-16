"""
characterize_perp_signal.py
============================
Exp 65 -- does LINK PERP order flow carry information about LINK SPOT's
near-term forward returns that is INCREMENTAL over spot's own order flow?

Motivation: exp61 found spot<->perp returns are contemporaneous (theta=0,
no lead-lag edge). But a contemporaneous cross-venue signal can still be a
useful real-time INPUT to spot quoting/skew (REFINEMENT 2026-06-15) -- e.g.
if perp OBI/OFI moves "with" spot returns at theta=0, a spot MM observing
perp flow gets a same-timestamp read on order flow that complements its own
(noisier, thinner) spot-side flow.

Method: 1s grid (matches perp quotes' ~1Hz native rate), all 30 overlapping
LINK Apr-2026 days (spot+perp quotes+trades both fully available). Per grid
point compute:
  - spot_mid, spot_obi (L1, asof latest quote)
  - spot_ofi (60s trailing signed/abs trade-volume ratio)
  - perp_mid, perp_obi, perp_ofi (same definitions, perp venue)
  - spot_fwd_ret[h], perp_fwd_ret[h] for h in {1,5,10,30,60}s (log returns)

Report, pooled across all days:
  (a) own-venue IC: corr(spot_obi/ofi, spot_fwd_ret) and
      corr(perp_obi/ofi, perp_fwd_ret) [sanity check vs exp54's ~0.20-0.28]
  (b) cross-venue IC: corr(perp_obi/ofi, spot_fwd_ret) -- the core question
  (c) redundancy: corr(spot_signal, perp_signal)
  (d) incremental info: residualize perp_signal on spot_signal (OLS), then
      corr(residual, spot_fwd_ret) -- is there anything LEFT in perp flow
      after accounting for what spot's own flow already says?

Run from master2/ root with .venv activated:
    python experiments/65_spot_perp_signal/characterize_perp_signal.py
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "real"
OUT = Path(__file__).resolve().parent / "results"

OFI_WINDOW = 60  # seconds, matches MarketState default arrival_window
HORIZONS = {"1s": 1, "5s": 5, "10s": 10, "30s": 30, "60s": 60}
SECONDS_PER_DAY = 86400


def dates(sym="LINK"):
    sp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / f"quotes_{sym}_2026-04-*.parquet"))}
    pp = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / f"quotes_{sym}_PERP_2026-04-*.parquet"))}
    return sorted(sp & pp)


def to_epoch_seconds(ts: pd.Series) -> np.ndarray:
    dt = pd.to_datetime(ts, utc=True).dt.tz_localize(None)
    return dt.astype("int64").to_numpy() / 1e9


def load_quotes(path):
    q = pd.read_parquet(path, columns=["time_exchange", "bid_price", "ask_price",
                                        "bid_size", "ask_size"])
    t = to_epoch_seconds(q["time_exchange"])
    mid = (q["bid_price"].to_numpy() + q["ask_price"].to_numpy()) / 2.0
    bsz, asz = q["bid_size"].to_numpy(), q["ask_size"].to_numpy()
    obi = np.where(bsz + asz > 0, (bsz - asz) / (bsz + asz), 0.0)
    order = np.argsort(t, kind="stable")
    return t[order], mid[order], obi[order]


def load_trades(path):
    tr = pd.read_parquet(path, columns=["time_exchange", "size", "taker_side"])
    t = to_epoch_seconds(tr["time_exchange"])
    side = tr["taker_side"].str.upper().to_numpy()
    sz = tr["size"].to_numpy()
    signed = np.where(side == "BUY", sz, -sz)
    order = np.argsort(t, kind="stable")
    return t[order], sz[order], signed[order]


def grid_for_day(date):
    midnight = pd.Timestamp(date, tz="UTC").value / 1e9
    return midnight + np.arange(SECONDS_PER_DAY, dtype=float)


def asof_value(grid_t, src_t, src_v):
    idx = np.searchsorted(src_t, grid_t, side="right") - 1
    out = np.full(len(grid_t), np.nan)
    valid = idx >= 0
    out[valid] = src_v[idx[valid]]
    return out


def trailing_ofi(sec0, n, trade_t, trade_sz, trade_signed, window):
    bucket = np.floor(trade_t - sec0).astype(int)
    valid = (bucket >= 0) & (bucket < n)
    buy_sell = np.zeros(n)
    absvol = np.zeros(n)
    np.add.at(buy_sell, bucket[valid], trade_signed[valid])
    np.add.at(absvol, bucket[valid], trade_sz[valid])
    roll_signed = pd.Series(buy_sell).rolling(window, min_periods=1).sum().to_numpy()
    roll_abs = pd.Series(absvol).rolling(window, min_periods=1).sum().to_numpy()
    return np.where(roll_abs > 0, roll_signed / roll_abs, 0.0)


def fwd_log_returns(mid, h):
    n = len(mid)
    out = np.full(n, np.nan)
    out[:n - h] = np.log(mid[h:]) - np.log(mid[:n - h])
    return out


def process_day(date):
    grid_t = grid_for_day(date)
    n = len(grid_t)
    sec0 = grid_t[0]

    sq_t, sq_mid, sq_obi = load_quotes(DATA / f"quotes_LINK_{date}.parquet")
    pq_t, pq_mid, pq_obi = load_quotes(DATA / f"quotes_LINK_PERP_{date}.parquet")
    st_t, st_sz, st_signed = load_trades(DATA / f"trades_LINK_{date}.parquet")
    pt_t, pt_sz, pt_signed = load_trades(DATA / f"trades_LINK_PERP_{date}.parquet")

    spot_mid = pd.Series(asof_value(grid_t, sq_t, sq_mid)).ffill().bfill().to_numpy()
    spot_obi = pd.Series(asof_value(grid_t, sq_t, sq_obi)).ffill().bfill().to_numpy()
    perp_mid = pd.Series(asof_value(grid_t, pq_t, pq_mid)).ffill().bfill().to_numpy()
    perp_obi = pd.Series(asof_value(grid_t, pq_t, pq_obi)).ffill().bfill().to_numpy()

    spot_ofi = trailing_ofi(sec0, n, st_t, st_sz, st_signed, OFI_WINDOW)
    perp_ofi = trailing_ofi(sec0, n, pt_t, pt_sz, pt_signed, OFI_WINDOW)

    cols = {"spot_obi": spot_obi, "spot_ofi": spot_ofi,
            "perp_obi": perp_obi, "perp_ofi": perp_ofi}
    for label, h in HORIZONS.items():
        cols[f"spot_fwd_{label}"] = fwd_log_returns(spot_mid, h)
        cols[f"perp_fwd_{label}"] = fwd_log_returns(perp_mid, h)
    return pd.DataFrame(cols)


def corr(x, y):
    mask = np.isfinite(x) & np.isfinite(y)
    return float(np.corrcoef(x[mask], y[mask])[0, 1])


def residualize(target, regressor):
    mask = np.isfinite(target) & np.isfinite(regressor)
    slope, intercept = np.polyfit(regressor[mask], target[mask], 1)
    resid = np.full_like(target, np.nan)
    resid[mask] = target[mask] - (intercept + slope * regressor[mask])
    return resid


def main():
    days = dates()
    print(f"Days with full LINK spot+perp overlap: {len(days)} ({days[0]}..{days[-1]})\n")

    frames = []
    for i, d in enumerate(days):
        frames.append(process_day(d))
        print(f"  [{i + 1}/{len(days)}] {d} done")
    df = pd.concat(frames, ignore_index=True)
    print(f"\nPooled rows: {len(df):,}\n")

    results = {"n_days": len(days), "n_rows": len(df), "horizons": {}}
    for label in HORIZONS:
        results["horizons"][label] = {}

    print("(a) own-venue IC: corr(signal, own-venue fwd log-return)")
    print(f"{'horizon':>8} {'spot_obi':>10} {'spot_ofi':>10} {'perp_obi':>10} {'perp_ofi':>10}")
    for label in HORIZONS:
        a = corr(df["spot_obi"].to_numpy(), df[f"spot_fwd_{label}"].to_numpy())
        b = corr(df["spot_ofi"].to_numpy(), df[f"spot_fwd_{label}"].to_numpy())
        c = corr(df["perp_obi"].to_numpy(), df[f"perp_fwd_{label}"].to_numpy())
        e = corr(df["perp_ofi"].to_numpy(), df[f"perp_fwd_{label}"].to_numpy())
        print(f"{label:>8} {a:10.4f} {b:10.4f} {c:10.4f} {e:10.4f}")
        results["horizons"][label].update({
            "spot_obi_vs_spot_fwd": a, "spot_ofi_vs_spot_fwd": b,
            "perp_obi_vs_perp_fwd": c, "perp_ofi_vs_perp_fwd": e,
        })

    print("\n(b) cross-venue IC: PERP signal vs SPOT fwd log-return (core question)")
    print(f"{'horizon':>8} {'perp_obi':>10} {'perp_ofi':>10}")
    for label in HORIZONS:
        cc = corr(df["perp_obi"].to_numpy(), df[f"spot_fwd_{label}"].to_numpy())
        ee = corr(df["perp_ofi"].to_numpy(), df[f"spot_fwd_{label}"].to_numpy())
        print(f"{label:>8} {cc:10.4f} {ee:10.4f}")
        results["horizons"][label].update({
            "perp_obi_vs_spot_fwd": cc, "perp_ofi_vs_spot_fwd": ee,
        })

    print("\n(c) redundancy: corr(spot_signal, perp_signal)")
    redund_obi = corr(df["spot_obi"].to_numpy(), df["perp_obi"].to_numpy())
    redund_ofi = corr(df["spot_ofi"].to_numpy(), df["perp_ofi"].to_numpy())
    print(f"   obi: {redund_obi:.4f}   ofi: {redund_ofi:.4f}")
    results["redundancy"] = {"obi": redund_obi, "ofi": redund_ofi}

    print("\n(d) incremental info: corr(resid[perp_signal ~ spot_signal], spot_fwd_ret)")
    print(f"{'horizon':>8} {'resid_obi':>10} {'resid_ofi':>10}")
    resid_obi = residualize(df["perp_obi"].to_numpy(), df["spot_obi"].to_numpy())
    resid_ofi = residualize(df["perp_ofi"].to_numpy(), df["spot_ofi"].to_numpy())
    for label in HORIZONS:
        ro = corr(resid_obi, df[f"spot_fwd_{label}"].to_numpy())
        rf = corr(resid_ofi, df[f"spot_fwd_{label}"].to_numpy())
        print(f"{label:>8} {ro:10.4f} {rf:10.4f}")
        results["horizons"][label].update({
            "resid_perp_obi_vs_spot_fwd": ro, "resid_perp_ofi_vs_spot_fwd": rf,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "characterize_perp_signal.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
