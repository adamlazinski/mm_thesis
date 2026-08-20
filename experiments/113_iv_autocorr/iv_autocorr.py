"""
iv_autocorr.py
==============
Exp 113 — Is implied volatility autocorrelated the way spot returns are?

Exp 112 found the options maker's vega leg loses after a fill. That is the
*conditional* statement (adverse selection in vol space) and it does not by
itself establish momentum: it is equally consistent with informed vol traders in
a market whose IV changes have zero unconditional autocorrelation. C1 measured
the unconditional side for spot (return autocorrelation ~0.15 at 1s, ~0 by 20s).
This does the same for IV, on the same window, from the same capture.

Two measurement points matter:

1. **Bounce.** A trade at the bid prints a lower IV than one at the ask, so
   trade-IV carries a bid-ask bounce in vol space, which manufactures NEGATIVE
   autocorrelation in measured dIV (Roll). The bounce-free series is Deribit's
   mark: mark IV is recovered by inverting Black-76 on `mark_price` at the
   forward, per trade. Both series are reported so the bounce is visible.
2. **Same-window comparison.** The captured files carry the underlying index
   ticks alongside the option tape, so spot return autocorrelation is computed on
   the identical window rather than quoted from C1's 2025 sample.

ATM is |log(K/F)| < ATM_BAND; series are resampled onto fixed grids and
differenced, and autocorrelation is reported for lags 1..LAGS with a
Bartlett-style 95% band (1.96/sqrt(n)) for scale.

Run: python experiments/113_iv_autocorr/iv_autocorr.py --currency BTC
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "experiments" / "112_options_markout"))
from options_markout import (bs_usd, implied_forward, parse_instrument)  # noqa: E402

ATM_BAND = 0.03
GRIDS_S = (10, 60, 300)
LAGS = 8


def load_capture(currency, capture_dir="data/live"):
    trades, idx = [], []
    for f in sorted(glob.glob(str(Path(capture_dir) / f"deribit_{currency}_*.jsonl.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        m = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if m.get("stream") == "trades":
                        trades.extend(m["data"])
                    elif m.get("stream") == "index":
                        d = m["data"]
                        idx.append((d["timestamp"] / 1e3, float(d["price"])))
        except (EOFError, zlib.error):
            pass
    tr = pd.DataFrame(trades).drop_duplicates(subset="trade_id")
    tr = tr.sort_values("timestamp").reset_index(drop=True)
    ix = pd.DataFrame(idx, columns=["ts", "price"]).drop_duplicates("ts")
    return tr, ix.sort_values("ts").reset_index(drop=True)


def implied_vol(mark_usd, F, K, T, is_call):
    """Invert Black-76 for sigma. Price is monotone increasing in sigma."""
    if T <= 0 or mark_usd <= 0 or F <= 0:
        return np.nan
    lo, hi = 1e-4, 5.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        v, _ = bs_usd(F, K, T, mid, is_call)
        if v < mark_usd:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def acf(x, lags):
    x = x[np.isfinite(x)]
    x = x - x.mean()
    n = len(x)
    if n < 50:
        return None, n
    d = (x * x).sum()
    return [float((x[:n - k] * x[k:]).sum() / d) for k in range(1, lags + 1)], n


def grid_series(ts, vals, step):
    """Last value in each fixed bucket, forward-filled one bucket."""
    if len(ts) == 0:
        return np.array([]), np.array([])
    t0, t1 = ts[0], ts[-1]
    edges = np.arange(t0, t1 + step, step)
    idx = np.searchsorted(edges, ts, side="right") - 1
    out = np.full(len(edges), np.nan)
    out[idx] = vals            # later writes win => last-in-bucket
    return edges, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--currency", default="BTC")
    args = ap.parse_args()

    tr, ix = load_capture(args.currency)
    if tr.empty:
        raise SystemExit("no captured trades")
    parsed = [parse_instrument(n) for n in tr["instrument_name"]]
    keep = [p is not None for p in parsed]
    tr = tr[keep].reset_index(drop=True)
    parsed = [p for p in parsed if p is not None]
    tr["strike"] = [p[0] for p in parsed]
    tr["expiry"] = [p[1] for p in parsed]
    tr["is_call"] = [p[2] for p in parsed]
    tr["ts"] = tr["timestamp"] / 1e3
    tr["sig_trade"] = tr["iv"].astype(float) / 100.0
    S = tr["index_price"].astype(float).to_numpy()
    T = np.maximum(tr["expiry"].to_numpy() - tr["ts"].to_numpy(), 0.0) / (365 * 86400)
    K = tr["strike"].to_numpy(dtype=float)
    call = tr["is_call"].to_numpy()

    # per-expiry forward basis from near-ATM marks (as in exp 112)
    mark_usd = tr["mark_price"].astype(float).to_numpy() * S
    lm_spot = np.log(K / S)
    basis = {}
    for e in np.unique(tr["expiry"].to_numpy()):
        sel = (np.abs(lm_spot) < 0.10) & (tr["expiry"].to_numpy() == e) & (T > 0) & (mark_usd > 0)
        if sel.sum() < 5:
            continue
        fs = [implied_forward(mark_usd[i], K[i], T[i], tr["sig_trade"].to_numpy()[i],
                              call[i], S[i]) for i in np.flatnonzero(sel)]
        rr = np.array(fs) / S[sel]
        rr = rr[np.isfinite(rr) & (rr > 0.5) & (rr < 2.0)]
        if len(rr):
            basis[e] = float(np.median(rr))
    b = np.array([basis.get(e, 1.0) for e in tr["expiry"].to_numpy()])
    F = b * S
    lm = np.log(K / F)

    atm = (np.abs(lm) < ATM_BAND) & (T > 1.0 / 365)      # drop same-day expiries
    n_atm = int(atm.sum())
    span_h = (tr["ts"].iloc[-1] - tr["ts"].iloc[0]) / 3600
    print(f"=== {args.currency}: {len(tr):,} trades over {span_h:.1f}h, "
          f"{n_atm:,} ATM (|log K/F|<{ATM_BAND}, T>1d)")

    # bounce-free mark IV, ATM only
    idxs = np.flatnonzero(atm)
    sig_mark = np.array([implied_vol(mark_usd[i], F[i], K[i], T[i], call[i])
                         for i in idxs])
    ts_atm = tr["ts"].to_numpy()[idxs]
    sig_tr = tr["sig_trade"].to_numpy()[idxs]
    ok = np.isfinite(sig_mark) & (sig_mark > 0.01) & (sig_mark < 4.0)
    ts_atm, sig_mark, sig_tr = ts_atm[ok], sig_mark[ok], sig_tr[ok]
    print(f"  mark-IV recovered for {len(sig_mark):,} ATM trades; "
          f"median trade-IV {np.median(sig_tr)*100:.1f}%, mark-IV {np.median(sig_mark)*100:.1f}%")

    out = {"currency": args.currency, "span_h": round(span_h, 2),
           "n_trades": int(len(tr)), "n_atm": n_atm, "grids": {}}

    for step in GRIDS_S:
        e1, v_mark = grid_series(ts_atm, sig_mark, step)
        _, v_trade = grid_series(ts_atm, sig_tr, step)
        e2, px = grid_series(ix["ts"].to_numpy(), ix["price"].to_numpy(), step)
        s_mark = pd.Series(v_mark).ffill(limit=2).to_numpy()
        s_trade = pd.Series(v_trade).ffill(limit=2).to_numpy()
        s_px = pd.Series(px).ffill(limit=2).to_numpy()
        d_mark = np.diff(s_mark)
        d_trade = np.diff(s_trade)
        r_spot = np.diff(np.log(s_px))
        a_mark, n_m = acf(d_mark, LAGS)
        a_trade, n_t = acf(d_trade, LAGS)
        a_spot, n_s = acf(r_spot, LAGS)
        if a_mark is None or a_spot is None:
            continue
        band = 1.96 / math.sqrt(max(n_m, 1))
        out["grids"][f"{step}s"] = {
            "n_iv": n_m, "n_spot": n_s, "band95": band,
            "acf_dIV_mark": a_mark, "acf_dIV_trade": a_trade,
            "acf_spot_returns": a_spot}
        print(f"\n  grid={step}s   n_iv={n_m}  n_spot={n_s}  95% band=±{band:.3f}")
        print(f"    {'lag':>4s} {'dIV (mark, bounce-free)':>24s} {'dIV (trade, bounced)':>22s} {'spot returns':>14s}")
        for k in range(min(LAGS, 5)):
            star = "*" if abs(a_mark[k]) > band else " "
            print(f"    {k+1:>4d} {a_mark[k]:>+23.3f}{star} {a_trade[k]:>+22.3f} {a_spot[k]:>+14.3f}")

    with open(OUT / f"iv_autocorr_{args.currency}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT}/iv_autocorr_{args.currency}.json")


if __name__ == "__main__":
    main()
