"""
options_markout.py
==================
Exp 112 — The delta-hedged markout: C59, one dimension up.

C59 measured what a spot maker keeps after adverse selection, model-free, from
the tape alone. This does the same for an OPTIONS maker on Deribit, where the
inventory is fundamentally different: delta can be hedged away, but gamma and
vega cannot be flattened except by trading another option. Under this thesis's
central claim — markets pay for risk-bearing, not prediction — an un-hedgeable
inventory is exactly the configuration that should be compensated.

The delta-hedged maker's P&L, per fill:

    entry edge      = D * (price - mark)                      what the spread pays
    hedged markout  = D * [price - (fair_{t+h} - delta*dS)]   what survives to h

where D = +1 when the taker BOUGHT (so the maker SOLD, and is short the option),
D = -1 when the taker sold. Subtracting `delta*dS` removes the directional leg a
maker would have hedged on the perp, leaving precisely the gamma/theta/vega P&L —
the risk that cannot be hedged away.

fair_{t+h} is recomputed with Black-Scholes at the underlying's later price,
holding IV at its trade-time value, which ISOLATES the gamma-vs-theta term (the
variance risk premium the maker is short/long). The vega leg is measured
separately by revaluing at the later ATM IV, so the two risks are reported apart
rather than confounded.

Fees: Deribit options charge on the UNDERLYING notional (default 3bps) capped at
a fraction of the premium (default 12.5%) — punitive on cheap options, so the cap
binds constantly and is modelled explicitly rather than assumed away.

Everything comes from the public trade tape: instrument name gives strike/expiry,
each trade carries its own IV, index price and mark. The underlying and ATM-IV
series are reconstructed from the tape itself.

Run: python experiments/112_options_markout/options_markout.py --hours 24 --currency BTC
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
API = "https://www.deribit.com/api/v2/public/"

HORIZONS_S = (60.0, 300.0, 1800.0, 7200.0)
FEE_BPS_UNDERLYING = 3.0      # Deribit option fee, bps of underlying notional
FEE_CAP_FRAC = 0.125          # capped at this fraction of the premium
MONEYNESS_EDGES = (-np.inf, -0.10, -0.03, 0.03, 0.10, np.inf)
MONEYNESS_LABELS = ("deep OTM put-side", "OTM put-side", "ATM",
                    "OTM call-side", "deep OTM call-side")
EXPIRY_MAP = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
              "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
INST_RE = re.compile(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+)-([CP])$")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "opt-markout/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return json.load(r)


def fetch_trades(currency: str, hours: float) -> pd.DataFrame:
    """Paginate the public option-trade tape backwards over `hours`."""
    end = int(time.time() * 1000)
    start = end - int(hours * 3600 * 1000)
    rows, cursor = [], end
    while True:
        u = (f"{API}get_last_trades_by_currency_and_time?currency={currency}"
             f"&kind=option&start_timestamp={start}&end_timestamp={cursor}"
             f"&count=1000&sorting=desc")
        res = _get(u)["result"]
        tr = res.get("trades", [])
        if not tr:
            break
        rows.extend(tr)
        oldest = min(t["timestamp"] for t in tr)
        if oldest <= start or not res.get("has_more") or len(tr) < 2:
            break
        cursor = oldest - 1
        time.sleep(0.12)
    df = pd.DataFrame(rows).drop_duplicates(subset="trade_id")
    return df.sort_values("timestamp").reset_index(drop=True)


def load_capture(currency: str, capture_dir: str = "data/live") -> pd.DataFrame:
    """
    Read the locally captured option tape (collect_deribit_options.py).

    Preferred over fetch_trades: Deribit's REST history endpoint silently
    truncates — it returned ~4.8k BTC trades for a day where the live tape shows
    ~18.7k, keeping only the most recent slice, which is a biased subsample.
    """
    import gzip
    import zlib
    rows = []
    for f in sorted(glob.glob(str(Path(capture_dir) / f"deribit_{currency}_*.jsonl.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        m = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if m.get("stream") == "trades":
                        rows.extend(m["data"])
        except (EOFError, zlib.error):
            pass          # in-progress hourly file: take what decompresses
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates(subset="trade_id")
    return df.sort_values("timestamp").reset_index(drop=True)


def parse_instrument(name: str):
    m = INST_RE.match(name)
    if not m:
        return None
    _, dd, mon, yy, strike, cp = m.groups()
    try:
        exp = datetime(2000 + int(yy), EXPIRY_MAP[mon], int(dd), 8, 0,
                       tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    return float(strike), exp.timestamp(), (cp == "C")


def _nd(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_usd(F, K, T, sigma, is_call):
    """
    Undiscounted Black-76 on the FORWARD: USD price and dV/dF.

    Deribit prices options off the forward, not the spot index, and quotes the
    premium in the underlying (BTC). Working in USD on the forward keeps the
    hedge ratio honest; the BTC-quoted premium is converted once, at the index.
    """
    if T <= 0 or sigma <= 0 or F <= 0:
        intrinsic = max(0.0, (F - K) if is_call else (K - F))
        dv = (1.0 if (is_call and F > K) else
              (-1.0 if (not is_call and F < K) else 0.0))
        return intrinsic, dv
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if is_call:
        return F * _nd(d1) - K * _nd(d2), _nd(d1)
    return K * _nd(-d2) - F * _nd(-d1), _nd(d1) - 1.0


def implied_forward(mark_usd, K, T, sigma, is_call, S):
    """Invert Black-76 for the forward Deribit's own mark+IV imply. Monotone in F."""
    if T <= 0 or sigma <= 0 or mark_usd <= 0:
        return np.nan
    lo, hi = 0.2 * S, 5.0 * S
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        v, _dv = bs_usd(mid, K, T, sigma, is_call)
        if v < mark_usd:
            lo = mid
        else:
            hi = mid
        if is_call:
            pass
    f = 0.5 * (lo + hi)
    # puts are decreasing in F, so the bisection above must be flipped for them
    if not is_call:
        lo, hi = 0.2 * S, 5.0 * S
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            v, _dv = bs_usd(mid, K, T, sigma, is_call)
            if v > mark_usd:
                lo = mid
            else:
                hi = mid
        f = 0.5 * (lo + hi)
    return f


def build_series(df):
    """Underlying index and ATM implied-vol series, reconstructed from the tape."""
    t = df["timestamp"].to_numpy() / 1e3
    idx = df["index_price"].to_numpy(dtype=float)
    atm = df[np.abs(df["log_m"]) < 0.02]
    at = atm["timestamp"].to_numpy() / 1e3
    av = atm["iv"].to_numpy(dtype=float) / 100.0
    return t, idx, at, av


def asof(xs, ys, q, tol=None):
    i = np.searchsorted(xs, q, side="right") - 1
    ok = i >= 0
    out = np.full(len(q), np.nan)
    out[ok] = ys[i[ok]]
    if tol is not None:
        stale = np.zeros(len(q), bool)
        stale[ok] = (q[ok] - xs[i[ok]]) > tol
        out[stale] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--currency", default="BTC")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--fee-bps", type=float, default=FEE_BPS_UNDERLYING,
                    help="maker fee, bps of underlying; 0 = hypothetical top tier")
    ap.add_argument("--from-capture", action="store_true",
                    help="use the locally captured tape (complete) instead of "
                         "Deribit REST history (silently truncated)")
    args = ap.parse_args()

    if args.from_capture:
        print(f"loading captured {args.currency} option tape ...")
        df = load_capture(args.currency)
    else:
        print(f"fetching {args.currency} option trades, last {args.hours}h ...")
        df = fetch_trades(args.currency, args.hours)
    if df.empty:
        raise SystemExit("no trades")
    parsed = [parse_instrument(n) for n in df["instrument_name"]]
    keep = [p is not None for p in parsed]
    df = df[keep].reset_index(drop=True)
    parsed = [p for p in parsed if p is not None]
    df["strike"] = [p[0] for p in parsed]
    df["expiry"] = [p[1] for p in parsed]
    df["is_call"] = [p[2] for p in parsed]
    df["ts"] = df["timestamp"] / 1e3
    df["iv_f"] = df["iv"].astype(float) / 100.0
    df["log_m"] = np.log(df["strike"] / df["index_price"].astype(float))
    span_h = (df["ts"].iloc[-1] - df["ts"].iloc[0]) / 3600
    print(f"  {len(df):,} trades over {span_h:.1f}h, "
          f"{df['instrument_name'].nunique():,} instruments")

    t_idx, idx, t_atm, v_atm = build_series(df)

    # maker side: taker "buy" => maker SOLD (short the option) => D=+1
    D = np.where(df["direction"].to_numpy() == "buy", 1.0, -1.0)
    S0 = df["index_price"].to_numpy(dtype=float)
    P0 = df["price"].to_numpy(dtype=float)              # in underlying units
    M0 = df["mark_price"].to_numpy(dtype=float)
    K = df["strike"].to_numpy(dtype=float)
    T0 = np.maximum(df["expiry"].to_numpy() - df["ts"].to_numpy(), 0.0) / (365 * 86400)
    sig0 = df["iv_f"].to_numpy()
    call = df["is_call"].to_numpy()
    ts = df["ts"].to_numpy()

    # --- forward calibration -------------------------------------------------
    # Deribit prices off the forward. Recover it from Deribit's OWN mark + IV
    # (self-consistent), using near-ATM trades where the forward is well
    # identified, then carry a per-expiry basis multiplier b = F/S to every
    # trade of that expiry.
    mark_usd = M0 * S0
    atm_mask = np.abs(df["log_m"].to_numpy()) < 0.10
    basis = {}
    for e in np.unique(df["expiry"].to_numpy()):
        sel = atm_mask & (df["expiry"].to_numpy() == e) & (T0 > 0) & (mark_usd > 0)
        if sel.sum() < 5:
            continue
        fs = [implied_forward(mark_usd[i], K[i], T0[i], sig0[i], call[i], S0[i])
              for i in np.flatnonzero(sel)]
        rr = np.array(fs) / S0[sel]
        rr = rr[np.isfinite(rr) & (rr > 0.5) & (rr < 2.0)]
        if len(rr):
            basis[e] = float(np.median(rr))
    b = np.array([basis.get(e, 1.0) for e in df["expiry"].to_numpy()])
    F0 = b * S0
    print(f"  forward basis F/S by expiry: "
          f"{ {datetime.utcfromtimestamp(k).strftime('%d%b%y'): round(v,4) for k,v in sorted(basis.items())[:6]} }")

    px_bs = np.array([bs_usd(F0[i], K[i], T0[i], sig0[i], call[i])[0]
                      for i in range(len(df))]) / S0
    dVdF = np.array([bs_usd(F0[i], K[i], T0[i], sig0[i], call[i])[1]
                     for i in range(len(df))])
    delta0 = b * dVdF                      # dV_usd / dS, hedged on the underlying
    # validation: the trade's own IV must reprice to the trade's own price
    rel = np.abs(px_bs - P0) / np.maximum(P0, 1e-9)
    print(f"  pricing check |BS(iv_trade) - price|/price: "
          f"p50={np.nanmedian(rel)*100:.2f}%  p90={np.nanpercentile(rel,90)*100:.2f}%")

    # entry edge vs Deribit's own fair value. NB the %-of-premium ratio is
    # heavy-tailed (near-worthless OTM options have premium ~1e-4), so the mean
    # of that ratio is meaningless — the median is reported instead, and bps of
    # underlying is the statistic used everywhere else.
    edge = D * (P0 - M0)
    prem = np.maximum(M0, 1e-9)
    fee = np.minimum(args.fee_bps * 1e-4, FEE_CAP_FRAC * prem)

    out = {"currency": args.currency, "hours_span": round(span_h, 2),
           "n_trades": int(len(df)),
           "n_instruments": int(df["instrument_name"].nunique()),
           "fee_bps_underlying": args.fee_bps, "fee_cap_frac": FEE_CAP_FRAC,
           "pricing_check_rel_p50_pct": float(np.nanmedian(rel) * 100),
           "entry": {
               "edge_pct_premium_median": float(np.nanmedian(edge / prem) * 100),
               "edge_bps_underlying_mean": float(np.nanmean(edge) * 1e4),
               "edge_bps_underlying_median": float(np.nanmedian(edge) * 1e4),
               "fee_bps_underlying_eff": float(np.nanmean(fee) * 1e4),
               "net_entry_bps_underlying": float(np.nanmean(edge - fee) * 1e4)},
           "horizons": {}}
    e = out["entry"]
    print(f"\nENTRY (vs Deribit mark): edge median={e['edge_pct_premium_median']:+.2f}% of premium; "
          f"mean={e['edge_bps_underlying_mean']:+.3f} / median={e['edge_bps_underlying_median']:+.3f} bps of underlying")
    print(f"  fee (3bps of underlying, capped at 12.5% of premium): "
          f"{e['fee_bps_underlying_eff']:.3f}bps effective  "
          f"=> net entry {e['net_entry_bps_underlying']:+.3f}bps of underlying")

    print(f"\n{'horizon':>9s} {'n':>7s} {'gamma/theta':>12s} {'+vega':>10s} "
          f"{'net of fee':>11s}  (bps of underlying, maker-signed)")
    v_at_trade = asof(t_atm, v_atm, ts, tol=1800.0)
    for h in HORIZONS_S:
        S1 = asof(t_idx, idx, ts + h, tol=600.0)
        v1 = asof(t_atm, v_atm, ts + h, tol=1800.0)
        T1 = np.maximum(T0 - h / (365 * 86400), 0.0)
        ok = np.isfinite(S1) & (ts + h <= ts[-1])
        if ok.sum() < 20:
            continue
        F1 = b * S1                                # basis carried forward
        # (a) constant-IV revaluation -> isolates gamma vs theta
        fair_const = np.array([bs_usd(F1[i], K[i], T1[i], sig0[i], call[i])[0]
                               if ok[i] else np.nan for i in range(len(df))]) / S0
        # (b) revalue at the later ATM IV, shifted by this option's smile offset
        sig1 = np.where(np.isfinite(v1) & np.isfinite(v_at_trade),
                        np.maximum(sig0 + (v1 - v_at_trade), 1e-4), sig0)
        fair_vega = np.array([bs_usd(F1[i], K[i], T1[i], sig1[i], call[i])[0]
                              if ok[i] else np.nan for i in range(len(df))]) / S0
        hedge = delta0 * (S1 - S0) / S0            # delta leg, normalised by S0
        gt = D * (P0 - (fair_const - hedge))       # gamma/theta only
        gv = D * (P0 - (fair_vega - hedge))        # gamma/theta + vega
        m = ok & np.isfinite(gt) & np.isfinite(gv)
        rec = {"n": int(m.sum()),
               "gamma_theta_bps": float(np.mean(gt[m]) * 1e4),
               "with_vega_bps": float(np.mean(gv[m]) * 1e4),
               "net_of_fee_bps": float(np.mean(gv[m] - fee[m]) * 1e4),
               "hit_rate": float(np.mean(gv[m] > 0))}
        out["horizons"][f"{h:g}s"] = rec
        print(f"{h:>8.0f}s {rec['n']:>7d} {rec['gamma_theta_bps']:>+12.3f} "
              f"{rec['with_vega_bps']:>+10.3f} {rec['net_of_fee_bps']:>+11.3f}"
              f"   hit={rec['hit_rate']:.2f}")

    # by moneyness at the 300s horizon
    h = 300.0
    S1 = asof(t_idx, idx, ts + h, tol=600.0)
    T1 = np.maximum(T0 - h / (365 * 86400), 0.0)
    ok = np.isfinite(S1) & (ts + h <= ts[-1])
    fair = np.array([bs_usd(b[i]*S1[i], K[i], T1[i], sig0[i], call[i])[0] if ok[i] else np.nan
                     for i in range(len(df))]) / S0
    hedge = delta0 * (S1 - S0) / S0
    gt = D * (P0 - (fair - hedge)) - fee
    bucket = pd.cut(df["log_m"], MONEYNESS_EDGES, labels=MONEYNESS_LABELS)
    print(f"\nby moneyness @300s (net of fee, bps of underlying):")
    bym = {}
    for lab in MONEYNESS_LABELS:
        m = ok & (bucket == lab).to_numpy() & np.isfinite(gt)
        if m.sum() < 20:
            continue
        bym[lab] = {"n": int(m.sum()), "net_bps": float(np.mean(gt[m]) * 1e4),
                    "median_bps": float(np.median(gt[m]) * 1e4)}
        print(f"  {lab:22s} n={m.sum():5d}  mean={np.mean(gt[m])*1e4:+8.3f}  "
              f"median={np.median(gt[m])*1e4:+8.3f}")
    out["by_moneyness_300s"] = bym

    tag = (f"{args.currency}_capture" if args.from_capture
           else f"{args.currency}_{int(args.hours)}h")
    with open(OUT / f"options_markout_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved -> {OUT}/options_markout_{tag}.json")


if __name__ == "__main__":
    main()
