"""
Hayashi-Yoshida lead-lag: LINK spot vs perp, trade-vs-trade (exp 61, Stage 1b).
================================================================================
The BBO lead-lag (characterize.py) was confounded by the perp top-of-book being
sampled at 1 Hz, which biases perp to look like it lags (stale snapshots). This
script re-measures leadership with the Hayashi-Yoshida (1) estimator on TRADE
prices from both venues — event-time, asynchronous, no gridding, no resampling —
so there is no staleness asymmetry. The lead-lag contrast (Hoffmann, Rosenbaum &
Yoshida 2013) shifts the perp series by θ and reports the normalised cross-
covariance ρ(θ); θ>0 ⇒ PERP leads spot, θ<0 ⇒ SPOT leads perp.

HY cross-covariance at shift θ:
    HY(θ) = Σ_{i,j} ΔX_i ΔY_j · 1{ (a_i,b_i] ∩ (c_j+θ, d_j+θ] ≠ ∅ }
with ΔX_i the spot log-return over consecutive trades (a_i,b_i], ΔY_j the perp
log-return over (c_j,d_j]. Within a venue the trade intervals are consecutive and
non-overlapping, so the perp intervals overlapping a given spot interval form a
contiguous index range — computed in O(N log N) per θ via searchsorted + cumsum.
Normalised: ρ(θ) = HY(θ) / sqrt(ΣΔX² · ΣΔY²).

Run:
    python experiments/61_link_spot_perp/hy_leadlag.py --days 30
"""
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "real"
OUT = Path("experiments/61_link_spot_perp/results")


def dates(sym="LINK"):
    s = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
         for f in glob.glob(str(DATA / f"trades_{sym}_2026-04-*.parquet"))}
    p = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
         for f in glob.glob(str(DATA / f"trades_{sym}_PERP_2026-04-*.parquet"))}
    return sorted(s & p)


def load_trades(path, date):
    """Return (epoch_seconds, price). Handles three timestamp encodings present in
    the dataset: epoch ns (int64, LINK/perp-numeric), ISO strings (object,
    BTC perp), and float seconds-from-midnight (BTC spot — reconciled to epoch by
    adding the day's UTC midnight)."""
    t = pd.read_parquet(path, columns=["time_exchange", "price"])
    te = t["time_exchange"]
    if te.dtype == object or pd.api.types.is_datetime64_any_dtype(te):
        # handles naive, tz-aware (datetime64[ns,UTC]), and ISO-string columns
        dt = pd.to_datetime(te, utc=True).dt.tz_localize(None)
        ts = dt.astype("int64").to_numpy() / 1e9
    else:
        arr = te.to_numpy().astype(float)
        if np.nanmax(arr) < 1e7:                       # seconds-from-midnight
            midnight = pd.Timestamp(date, tz="UTC").value / 1e9
            ts = arr + midnight
        elif arr[0] > 1e17:
            ts = arr / 1e9
        elif arr[0] > 1e14:
            ts = arr / 1e6
        else:
            ts = arr
    px = t["price"].to_numpy().astype(float)
    # drop bad ticks (zero/negative/NaN price) before anything else
    good = np.isfinite(px) & (px > 0) & np.isfinite(ts)
    ts, px = ts[good], px[good]
    order = np.argsort(ts, kind="stable")
    ts, px = ts[order], px[order]
    # collapse exact-timestamp duplicates to last price; keep strictly increasing time
    keep = np.concatenate([np.diff(ts) > 0, [True]])
    ts, px = ts[keep], px[keep]
    return ts, px


def hy_curve(tx, px, ty, py, thetas):
    """Normalised HY cross-correlation ρ(θ); θ>0 ⇒ Y (perp) leads X (spot)."""
    lx = np.log(px); ly = np.log(py)
    dX = np.diff(lx); aX = tx[:-1]; bX = tx[1:]          # spot intervals (aX,bX], return dX
    dY = np.diff(ly); aY = ty[:-1]; bY = ty[1:]          # perp intervals
    varX = float(np.sum(dX * dX)); varY = float(np.sum(dY * dY))
    if varX <= 0 or varY <= 0:
        return np.full(len(thetas), np.nan), 0.0, 0.0
    CY = np.concatenate([[0.0], np.cumsum(dY)])          # prefix sums of perp returns
    norm = np.sqrt(varX * varY)
    out = np.empty(len(thetas))
    for m, th in enumerate(thetas):
        c = aY + th; d = bY + th                          # shifted perp interval endpoints
        # perp intervals overlapping spot interval i: d_j > aX_i AND c_j < bX_i
        jmin = np.searchsorted(d, aX, side="right")       # first j with d_j > aX_i
        jmax = np.searchsorted(c, bX, side="left") - 1    # last  j with c_j < bX_i
        valid = jmin <= jmax
        seg = np.zeros(len(dX))
        seg[valid] = CY[jmax[valid] + 1] - CY[jmin[valid]]
        out[m] = float(np.sum(dX * seg)) / norm
    return out, varX, varY


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbol", default="LINK")
    args = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    sym = args.symbol
    ds = dates(sym)[: args.days]
    thetas = np.round(np.arange(-2.0, 2.01, 0.1), 2)     # ±2 s, 100 ms steps
    print(f"HY lead-lag {sym} spot<->perp, {len(ds)} days, θ∈[-2,2]s")

    acc = []
    for d in ds:
        try:
            tx, px = load_trades(DATA / f"trades_{sym}_{d}.parquet", d)
            ty, py = load_trades(DATA / f"trades_{sym}_PERP_{d}.parquet", d)
            curve, vx, vy = hy_curve(tx, px, ty, py, thetas)
            acc.append(curve)
            pk = thetas[int(np.nanargmax(np.abs(curve)))]
            print(f"  {d}: spot {len(tx):,} / perp {len(ty):,} trades  peak θ={pk:+.1f}s ρ={np.nanmax(np.abs(curve)):.3f}")
        except Exception as e:
            print(f"  {d}: ERROR {e}")

    R = np.nanmean(np.vstack(acc), axis=0)
    kpk = int(np.nanargmax(np.abs(R))); tpk = thetas[kpk]

    print(f"\n{'='*70}\nHY cross-correlation ρ(θ)  [θ>0 ⇒ PERP leads spot]\n{'='*70}")
    for th, r in zip(thetas, R):
        if abs(th * 10) % 5 < 1e-6 or th == tpk:        # print every 0.5s + the peak
            bar = "#" * int(abs(r) * 120) if np.isfinite(r) else ""
            star = "  <-- peak" if th == tpk else ""
            print(f"   θ={th:+5.1f}s  ρ={r:+.3f} {bar}{star}")
    lead = "PERP leads spot" if tpk > 0.05 else ("SPOT leads perp" if tpk < -0.05 else "≈ contemporaneous")
    print(f"\n  peak |ρ| at θ={tpk:+.1f}s  ->  {lead}")
    # asymmetry: net correlation mass on each side
    pos = float(np.nansum(R[thetas > 0])); neg = float(np.nansum(R[thetas < 0]))
    print(f"  Σρ(θ>0) [perp-leads] = {pos:+.3f}   Σρ(θ<0) [spot-leads] = {neg:+.3f}")

    json.dump({"days": len(acc), "thetas": thetas.tolist(), "ccf": R.tolist(),
               "peak_theta_s": float(tpk), "sum_pos": pos, "sum_neg": neg},
              open(OUT / f"hy_leadlag_{sym}.json", "w"), indent=2)
    print(f"\nSaved -> {OUT / 'hy_leadlag.json'}")
    print("\n(1) Hayashi & Yoshida (2005); lead-lag contrast: Hoffmann, Rosenbaum & Yoshida (2013).")


if __name__ == "__main__":
    main()
