"""
regime_markout.py
=================
Exp 114 — Regime-aware market making: does the maker's realized half-spread turn
positive in mean-reverting regimes?

The idea, and why it is not already covered:
  * C1 established short-horizon MOMENTUM in returns; C59 showed the maker's
    half-spread is eaten within ~100ms. A maker is hurt by momentum and helped by
    mean reversion, so if mean-reverting regimes can be identified IN ADVANCE the
    maker should quote only in those.
  * C13 found calendar regime dominates the sign of A-S P&L (May +$11.48/day vs
    June -$4.89/day) — but ex post, on the old price-only engine.
  * C61 conditioned adverse selection on six state variables (perp pressure,
    order flow, book imbalance, volatility, intensity, spread) and found no
    benign pocket — but realized AUTOCORRELATION was not among them. It is a
    property of the price process rather than of the flow, so it is untested.

Regime variable (strictly causal, computed only from data before the fill):
  VR(k) = Var(k-bar returns) / (k * Var(1-bar returns))   over a trailing window
  VR < 1 => mean reverting, VR > 1 => trending. Lag-1 autocorrelation of 1-bar
  returns is reported alongside as a cross-check.

For every trade we then compute the C59 maker-signed realized half-spread and
bucket it by the prevailing regime. Two questions are answered at once:

  (a) Does realized half-spread rise in mean-reverting regimes, and does it turn
      POSITIVE anywhere?
  (b) EQUILIBRIUM CHECK: does the quoted spread TIGHTEN in those same regimes?
      Wyart-Bouchaud predicts the spread tracks the cost it must cover, so a
      favourable regime should be competed away by a narrower spread — which
      would explain a null in (a) rather than leaving it unexplained.

Run: python experiments/114_regime_markout/regime_markout.py --date 2026-07-16 --asset HL_BTC
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

BAR_S = 1.0            # return sampling interval
WIN_BARS = 600         # trailing window for the regime estimate (10 min at 1s)
VR_K = 5               # variance-ratio horizon, in bars
HORIZONS = (0.1, 1.0, 5.0, 30.0, 120.0)
QUOTE_TOL = pd.Timedelta("5s")
N_BUCKETS = 5
CAP_TICKS = 5.0


def load(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    q["spread"] = q["ask_price"] - q["bid_price"]
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    q = q[keep].reset_index(drop=True)
    tr = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    return q, tr


def regime_series(qt, qm):
    """Causal VR(k) and lag-1 autocorrelation on a fixed bar grid."""
    t0, t1 = qt[0], qt[-1]
    edges = np.arange(t0, t1, BAR_S)
    idx = np.searchsorted(qt, edges, side="right") - 1
    ok = idx >= 0
    px = np.full(len(edges), np.nan)
    px[ok] = qm[idx[ok]]
    px = pd.Series(px).ffill().to_numpy()
    r = np.diff(np.log(px))
    bars_t = edges[1:]

    s = pd.Series(r)
    var1 = s.rolling(WIN_BARS).var()
    # k-bar returns on the same grid, rolling variance over the same window
    rk = pd.Series(np.log(px)).diff(VR_K)
    vark = rk.rolling(WIN_BARS).var().iloc[1:].reset_index(drop=True)
    vr = (vark / (VR_K * var1)).to_numpy()
    # lag-1 autocorrelation, rolling
    ac = s.rolling(WIN_BARS).apply(
        lambda x: np.corrcoef(x[:-1], x[1:])[0, 1] if np.std(x) > 0 else np.nan,
        raw=True).to_numpy()
    return bars_t, vr, ac


def asof(xs, ys, q, tol=None):
    i = np.searchsorted(xs, q, side="right") - 1
    out = np.full(len(q), np.nan)
    ok = i >= 0
    out[ok] = ys[i[ok]]
    if tol is not None:
        stale = np.zeros(len(q), bool)
        stale[ok] = (q[ok] - xs[i[ok]]) > tol
        out[stale] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tick", type=float, default=None)
    ap.add_argument("--bar", type=float, default=BAR_S,
                    help="return bar in seconds; mean-reverting regimes "
                         "only exist at 30s+ (see exp 114 notes)")
    ap.add_argument("--win", type=int, default=WIN_BARS)
    args = ap.parse_args()
    globals()["BAR_S"] = args.bar
    globals()["WIN_BARS"] = args.win

    q, tr = load(args.asset, args.date)
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qm = q["mid"].to_numpy()
    qs = q["spread"].to_numpy()
    bars_t, vr, ac = regime_series(qt, qm)

    qq = q[["time_exchange", "mid"]]
    tt = tr["time_exchange"].astype("int64").to_numpy() / 1e9
    D = np.where(tr["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    price = tr["price"].to_numpy()

    def mid_at(times):
        left = pd.DataFrame({"time_exchange": times}).sort_values("time_exchange")
        m = pd.merge_asof(left, qq, on="time_exchange", direction="backward",
                          tolerance=QUOTE_TOL)
        return m["mid"].to_numpy()[np.argsort(left.index.to_numpy(), kind="stable")]

    mid_t = mid_at(tr["time_exchange"])
    tick = args.tick or float(np.nanmedian(qs))
    eff = D * (price - mid_t)
    base = np.isfinite(mid_t) & (np.abs(eff) <= CAP_TICKS * max(tick, 1e-12))

    # regime as of just before the trade (causal by construction)
    vr_t = asof(bars_t, vr, tt, tol=60.0)
    ac_t = asof(bars_t, ac, tt, tol=60.0)
    spr_t = asof(qt, qs, tt, tol=2.0)

    out = {"asset": args.asset, "date": args.date, "bar_s": BAR_S,
           "win_bars": WIN_BARS, "vr_k": VR_K,
           "n_trades": int(len(tr)), "buckets": {}}

    m0 = base & np.isfinite(vr_t)
    if m0.sum() < 500:
        raise SystemExit(f"only {m0.sum()} usable trades")
    qb = pd.qcut(vr_t[m0], N_BUCKETS, labels=False, duplicates="drop")
    mid_h = {h: mid_at(tr["time_exchange"] + pd.to_timedelta(h, unit="s"))
             for h in HORIZONS}

    print(f"=== {args.asset} {args.date}   {int(m0.sum()):,} usable trades")
    print(f"    regime = causal VR({VR_K}) over {WIN_BARS} x {BAR_S:g}s bars "
          f"(VR<1 mean-reverting, VR>1 trending)")
    print(f"\n{'bucket':>7s} {'VR':>7s} {'acf1':>7s} {'spread(bps)':>12s}"
          + "".join(f"{'rh@'+str(h)+'s':>11s}" for h in HORIZONS))
    idx_all = np.flatnonzero(m0)
    for bnum in range(int(np.nanmax(qb)) + 1):
        sel = idx_all[qb == bnum]
        if len(sel) < 50:
            continue
        row = {"n": int(len(sel)),
               "vr_mean": float(np.nanmean(vr_t[sel])),
               "acf1_mean": float(np.nanmean(ac_t[sel])),
               "spread_bps": float(np.nanmean(spr_t[sel] / mid_t[sel]) * 1e4)}
        cells = []
        for h in HORIZONS:
            rh = D[sel] * (price[sel] - mid_h[h][sel])
            good = np.isfinite(rh)
            v = float(np.nanmean(rh[good] / mid_t[sel][good]) * 1e4)
            row[f"rh_{h}s_bps"] = v
            cells.append(v)
        out["buckets"][str(bnum)] = row
        print(f"{bnum:>7d} {row['vr_mean']:>7.3f} {row['acf1_mean']:>+7.3f} "
              f"{row['spread_bps']:>12.3f}" + "".join(f"{c:>+11.3f}" for c in cells))

    b = out["buckets"]
    if len(b) >= 2:
        lo, hi = b[min(b)], b[max(b)]
        h_last = HORIZONS[-1]
        out["mean_revert_minus_trend"] = {
            f"rh_{h_last}s_bps": lo[f"rh_{h_last}s_bps"] - hi[f"rh_{h_last}s_bps"],
            "spread_bps": lo["spread_bps"] - hi["spread_bps"]}
        print(f"\n  most mean-reverting minus most trending: "
              f"realized@{h_last}s {out['mean_revert_minus_trend'][f'rh_{h_last}s_bps']:+.3f}bps, "
              f"spread {out['mean_revert_minus_trend']['spread_bps']:+.3f}bps")
        print(f"  (equilibrium check: if the favourable regime also shows a "
              f"TIGHTER spread, the edge is competed away)")

    with open(OUT / f"regime_markout_{args.asset}_{args.date}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/regime_markout_{args.asset}_{args.date}.json")


if __name__ == "__main__":
    main()
