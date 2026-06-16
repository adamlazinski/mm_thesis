"""
characterize_perp_signal_10ms.py
==================================
Exp 65 follow-up -- re-run the spot/perp cross-venue OBI/OFI characterization
(characterize_perp_signal.py) on a 10ms grid with SUB-SECOND forward-return
horizons, to test whether perp OBI's cross-venue edge for spot forward
returns (1s-grid result: cross-venue IC ~0.04-0.06, peaking at 10s, vs
spot's own OBI IC ~0.21-0.36) is actually concentrated in the sub-second
range that the 1s grid couldn't resolve.

LINK PERP quotes are natively ~1Hz, so perp_obi/perp_ofi are still step
functions updating ~1x/sec on this finer grid -- the new resolution is on
the SPOT side: spot quotes are ~21Hz (~48ms spacing), so a 10ms grid resolves
spot's reaction to a perp update within ~10-50ms instead of averaging it
into the next full second.

GRID_DT = 0.01s (10ms) -> 8.64M grid points/day x 30 days = 259.2M obs.
Pooling this into one DataFrame (as the 1s version did) would need ~30GB+,
so this version uses exact single-pass pairwise-sum accumulators (mean,
var, cov) and computes correlations AND partial correlations (= corr of
the OLS residual) in closed form:
    rho_{yz.x} = (rho_yz - rho_xy*rho_xz) / sqrt((1-rho_xy^2)(1-rho_xz^2))
which is exactly corr(resid[y ~ x], z) -- the "(d) incremental info" metric
from the 1s version, here exact in a single pass.

HORIZONS: {10ms, 50ms, 100ms, 250ms, 500ms, 1s} -- all <=1s, the range the
1s-grid version could not probe.

Run from master2/ root with .venv activated:
    python experiments/65_spot_perp_signal/characterize_perp_signal_10ms.py
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

GRID_DT = 0.01  # 10ms
OFI_WINDOW = 60  # seconds, matches MarketState default arrival_window
HORIZONS = {"10ms": 0.01, "50ms": 0.05, "100ms": 0.1, "250ms": 0.25, "500ms": 0.5, "1s": 1.0}
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
    n = round(SECONDS_PER_DAY / GRID_DT)
    return midnight + np.arange(n) * GRID_DT


def asof_value(grid_t, src_t, src_v):
    idx = np.searchsorted(src_t, grid_t, side="right") - 1
    out = np.full(len(grid_t), np.nan)
    valid = idx >= 0
    out[valid] = src_v[idx[valid]]
    return out


def trailing_ofi(sec0, n, trade_t, trade_sz, trade_signed, window_seconds):
    bucket = np.floor((trade_t - sec0) / GRID_DT).astype(int)
    valid = (bucket >= 0) & (bucket < n)
    buy_sell = np.zeros(n)
    absvol = np.zeros(n)
    np.add.at(buy_sell, bucket[valid], trade_signed[valid])
    np.add.at(absvol, bucket[valid], trade_sz[valid])
    window = round(window_seconds / GRID_DT)
    roll_signed = pd.Series(buy_sell).rolling(window, min_periods=1).sum().to_numpy()
    roll_abs = pd.Series(absvol).rolling(window, min_periods=1).sum().to_numpy()
    return np.where(roll_abs > 0, roll_signed / roll_abs, 0.0)


def fwd_log_returns(mid, h_seconds):
    h = round(h_seconds / GRID_DT)
    n = len(mid)
    out = np.full(n, np.nan)
    out[:n - h] = np.log(mid[h:]) - np.log(mid[:n - h])
    return out


class PairAcc:
    """Single-pass accumulator of pairwise sums -> exact Pearson correlation."""
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")

    def __init__(self):
        self.n = 0
        self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0

    def add(self, x, y):
        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]
        self.n += x.size
        self.sx += x.sum()
        self.sy += y.sum()
        self.sxx += float(x @ x)
        self.syy += float(y @ y)
        self.sxy += float(x @ y)

    def corr(self):
        n = self.n
        mx, my = self.sx / n, self.sy / n
        cov = self.sxy / n - mx * my
        vx = self.sxx / n - mx * mx
        vy = self.syy / n - my * my
        return float(cov / np.sqrt(vx * vy))


def partial_corr(rxy, rxz, ryz):
    """corr(resid[y ~ x], z) in closed form."""
    return (ryz - rxy * rxz) / np.sqrt((1 - rxy ** 2) * (1 - rxz ** 2))


def process_day(date, acc):
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

    acc[("spot_obi", "perp_obi")].add(spot_obi, perp_obi)
    acc[("spot_ofi", "perp_ofi")].add(spot_ofi, perp_ofi)

    for label, h in HORIZONS.items():
        spot_fwd = fwd_log_returns(spot_mid, h)
        perp_fwd = fwd_log_returns(perp_mid, h)
        acc[("spot_obi", "spot_fwd", label)].add(spot_obi, spot_fwd)
        acc[("perp_obi", "spot_fwd", label)].add(perp_obi, spot_fwd)
        acc[("perp_obi", "perp_fwd", label)].add(perp_obi, perp_fwd)
        acc[("spot_ofi", "spot_fwd", label)].add(spot_ofi, spot_fwd)
        acc[("perp_ofi", "spot_fwd", label)].add(perp_ofi, spot_fwd)
        acc[("perp_ofi", "perp_fwd", label)].add(perp_ofi, perp_fwd)


def main():
    days = dates()
    n_grid = round(SECONDS_PER_DAY / GRID_DT)
    print(f"GRID_DT={GRID_DT * 1000:.0f}ms -> {n_grid:,} pts/day x {len(days)} days "
          f"= {n_grid * len(days):,} obs (single-pass accumulators, no pooled DataFrame)\n")

    acc = {("spot_obi", "perp_obi"): PairAcc(), ("spot_ofi", "perp_ofi"): PairAcc()}
    for label in HORIZONS:
        for key in [("spot_obi", "spot_fwd", label), ("perp_obi", "spot_fwd", label),
                    ("perp_obi", "perp_fwd", label), ("spot_ofi", "spot_fwd", label),
                    ("perp_ofi", "spot_fwd", label), ("perp_ofi", "perp_fwd", label)]:
            acc[key] = PairAcc()

    for i, d in enumerate(days):
        process_day(d, acc)
        print(f"  [{i + 1}/{len(days)}] {d} done")

    redund_obi = acc[("spot_obi", "perp_obi")].corr()
    redund_ofi = acc[("spot_ofi", "perp_ofi")].corr()
    print(f"\n(c) redundancy: corr(spot_signal, perp_signal)")
    print(f"   obi: {redund_obi:.4f}   ofi: {redund_ofi:.4f}")

    results = {"grid_dt": GRID_DT, "n_days": len(days), "n_obs": n_grid * len(days),
               "redundancy": {"obi": redund_obi, "ofi": redund_ofi}, "horizons": {}}

    print("\n(a) own-venue IC: corr(signal, own-venue fwd log-return)")
    print(f"{'horizon':>8} {'spot_obi':>10} {'spot_ofi':>10} {'perp_obi':>10} {'perp_ofi':>10}")
    for label in HORIZONS:
        a = acc[("spot_obi", "spot_fwd", label)].corr()
        b = acc[("spot_ofi", "spot_fwd", label)].corr()
        c = acc[("perp_obi", "perp_fwd", label)].corr()
        e = acc[("perp_ofi", "perp_fwd", label)].corr()
        print(f"{label:>8} {a:10.4f} {b:10.4f} {c:10.4f} {e:10.4f}")
        results["horizons"][label] = {
            "spot_obi_vs_spot_fwd": a, "spot_ofi_vs_spot_fwd": b,
            "perp_obi_vs_perp_fwd": c, "perp_ofi_vs_perp_fwd": e,
        }

    print("\n(b) cross-venue IC: PERP signal vs SPOT fwd log-return (core question)")
    print(f"{'horizon':>8} {'perp_obi':>10} {'perp_ofi':>10}")
    for label in HORIZONS:
        cc = acc[("perp_obi", "spot_fwd", label)].corr()
        ee = acc[("perp_ofi", "spot_fwd", label)].corr()
        print(f"{label:>8} {cc:10.4f} {ee:10.4f}")
        results["horizons"][label].update({
            "perp_obi_vs_spot_fwd": cc, "perp_ofi_vs_spot_fwd": ee,
        })

    print("\n(d) incremental info (exact partial corr): "
          "corr(resid[perp_signal ~ spot_signal], spot_fwd_ret)")
    print(f"{'horizon':>8} {'resid_obi':>10} {'resid_ofi':>10}")
    for label in HORIZONS:
        ro = partial_corr(redund_obi,
                           results["horizons"][label]["spot_obi_vs_spot_fwd"],
                           results["horizons"][label]["perp_obi_vs_spot_fwd"])
        rf = partial_corr(redund_ofi,
                           results["horizons"][label]["spot_ofi_vs_spot_fwd"],
                           results["horizons"][label]["perp_ofi_vs_spot_fwd"])
        print(f"{label:>8} {ro:10.4f} {rf:10.4f}")
        results["horizons"][label].update({
            "resid_perp_obi_vs_spot_fwd": ro, "resid_perp_ofi_vs_spot_fwd": rf,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "characterize_perp_signal_10ms.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved results to {out_path}")


if __name__ == "__main__":
    main()
