"""
BTC taker — XGBoost forecast vs the ~1 bps single-signal ceiling (OOS).
======================================================================
Tests whether a supervised nonlinear forecast (XGBoost on the 8 microstructure
features from ml/train_forecast.py) lifts the per-trade taker edge above the
~1 bps ceiling that selectivity / conviction / hold / latency could not break
(Contribution 31).

DISCIPLINE: strict out-of-sample. Train on Jun 2025; evaluate ONLY on held-out
later days (Jul 2025) and a different regime (May 2025). The model fits
parameters, so same-day evaluation would be meaningless — unlike the
contemporaneous-signal feasibility checks which had no overfit risk.

Evaluation uses the EXACT exp-55 latency-aware fill model so results are
directly comparable to the OBI baseline:
  signal at t -> order at t -> ENTRY fills t+LATENCY at real ask(long)/bid(short)
  EXIT crosses back at t+LATENCY+HOLD at real bid(long)/ask(short)
  pnl_ticks = (exit-entry)/TICK  ;  bps = pnl_ticks * TICK/mid * 1e4
Take only the top-decile |model signal| points (the model's high-conviction set);
compare per-trade bps to the OBI top-decile baseline on the SAME days.

Usage:
    python experiments/55_taker_feasibility/btc_taker_xgb.py \
        --train_start 2025-06-11 --train_end 2025-06-27 \
        --horizon 10
"""
from __future__ import annotations
import argparse, sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ml.train_forecast import _extract_day, FEATURE_NAMES   # reuse feature pipeline
from hft_market_maker.data.loader import DataLoader

DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/55_taker_feasibility/analysis")
TICK     = 0.01
LATENCY  = 0.10
SYMBOL   = "BTC"
PERP_FEE_BPS = 3.6


def drange(a, b):
    d, e = date.fromisoformat(a), date.fromisoformat(b)
    out = []
    while d <= e:
        out.append(d.isoformat()); d += timedelta(days=1)
    return out


def regime_of(ds):
    if ds.startswith("2025-05"): return "May2025(OOS)"
    if ds.startswith("2025-06") or ds.startswith("2025-07"):
        return "JunJul2025"
    return "other"


def load_raw_quotes(date_str):
    q = pd.read_parquet(DATA_DIR / f"quotes_{SYMBOL}_{date_str}.parquet",
                        columns=["time_exchange", "ask_price", "bid_price"])
    ts = q["time_exchange"].astype("int64").to_numpy() / 1e9
    return ts, q["bid_price"].to_numpy(), q["ask_price"].to_numpy()


def px_at(ts, arr, t):
    idx = np.searchsorted(ts, t, side="right") - 1
    valid = idx >= 0
    out = arr[np.clip(idx, 0, len(arr) - 1)].astype(float)
    out[~valid] = np.nan
    return out


def roundtrip_ticks(ts, bid, ask, t_eval, dirn, hold):
    te = t_eval + LATENCY; tx = te + hold
    ea = px_at(ts, ask, te); eb = px_at(ts, bid, te)
    xa = px_at(ts, ask, tx); xb = px_at(ts, bid, tx)
    return np.where(dirn > 0, xb - ea, np.where(dirn < 0, eb - xa, np.nan)) / TICK


def per_trade_bps(ts, bid, ask, g, dirn, sigabs, hold):
    """Top-decile-|signal| mean round-trip bps + win% + n for one day."""
    fin = np.isfinite(sigabs)
    thr = np.nanpercentile(sigabs[fin], 90)
    mask = fin & (sigabs >= thr) & (dirn != 0)
    pnl = roundtrip_ticks(ts, bid, ask, g[mask], dirn[mask], hold)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) == 0:
        return None
    mid_px = (np.nanmean(bid) + np.nanmean(ask)) / 2.0
    bps = pnl.mean() * TICK / mid_px * 1e4
    return float(bps), float((pnl > 0).mean() * 100), int(len(pnl))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train_start", default="2025-06-11")
    ap.add_argument("--train_end",   default="2025-06-27")
    ap.add_argument("--horizon", type=float, default=10.0)   # taker hold
    ap.add_argument("--quote_freq", type=float, default=0.5)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    H = args.horizon

    train_dates = drange(args.train_start, args.train_end)
    # OOS: Jul 2025 (later, same regime) + May 2025 (earlier, different regime)
    oos_dates = drange("2025-06-28", "2025-07-10") + drange("2025-05-13", "2025-05-24")

    print(f"=== Training XGBoost (horizon={H}s) on {args.train_start}..{args.train_end} ===")
    frames = []
    for d in train_dates:
        df = _extract_day(SYMBOL, str(DATA_DIR), d, H, args.quote_freq)
        if df is not None:
            frames.append(df); print(f"  train {d}: {len(df):,}")
    train_df = pd.concat(frames, ignore_index=True)
    X = train_df[FEATURE_NAMES].values.astype(np.float32)
    y = train_df["label"].values.astype(int)
    split = int(len(X) * 0.85)
    model = XGBClassifier(
        objective="multi:softprob", num_class=3, n_estimators=500, max_depth=4,
        learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=50,
        gamma=1.0, reg_alpha=0.1, reg_lambda=1.0, eval_metric="mlogloss",
        early_stopping_rounds=30, n_jobs=-1, random_state=42)
    model.fit(X[:split], y[:split], eval_set=[(X[split:], y[split:])], verbose=False)
    joblib.dump(model, OUT_DIR / f"xgb_taker_h{int(H)}.pkl")
    imp = dict(zip(FEATURE_NAMES, model.feature_importances_))
    print("  feature importance:",
          {k: round(float(v), 3) for k, v in sorted(imp.items(), key=lambda x: -x[1])})

    print(f"\n=== OOS evaluation (hold={H}s, latency={LATENCY*1000:.0f}ms) ===")
    rows = []
    for d in oos_dates:
        try:
            df = _extract_day(SYMBOL, str(DATA_DIR), d, H, args.quote_freq)
            if df is None:
                continue
            ts, bid, ask = load_raw_quotes(d)
            g = df["timestamp"].values
            proba = model.predict_proba(df[FEATURE_NAMES].values.astype(np.float32))
            sig = proba[:, 2] - proba[:, 0]              # p_up - p_down
            obi = df["obi"].values
            auc_up = roc_auc_score((df["label"].values == 2).astype(int), proba[:, 2])

            xgb_r = per_trade_bps(ts, bid, ask, g, np.sign(sig), np.abs(sig), H)
            obi_r = per_trade_bps(ts, bid, ask, g, np.sign(obi), np.abs(obi), H)
            if xgb_r and obi_r:
                rows.append({"date": d, "regime": regime_of(d), "auc_up": auc_up,
                             "xgb_bps": xgb_r[0], "xgb_win": xgb_r[1], "xgb_n": xgb_r[2],
                             "obi_bps": obi_r[0], "obi_win": obi_r[1], "obi_n": obi_r[2]})
                print(f"  OOS {d} ({regime_of(d)}): xgb={xgb_r[0]:+.3f}bps "
                      f"obi={obi_r[0]:+.3f}bps aucUp={auc_up:.3f}")
        except Exception as e:
            print(f"  OOS {d}: ERROR {e}")

    res = pd.DataFrame(rows)
    res.to_csv(OUT_DIR / f"btc_taker_xgb_h{int(H)}.csv", index=False)

    print("\n" + "=" * 70)
    print(f"OOS PER-TRADE EDGE (bps) — XGBoost vs OBI baseline | perp fee {PERP_FEE_BPS}bps")
    print("=" * 70)
    print(f"  {'regime':>14} | {'XGB bps':>8} {'win%':>5} | {'OBI bps':>8} {'win%':>5} | {'AUC up':>6} | days")
    for reg in ["JunJul2025", "May2025(OOS)"]:
        s = res[res.regime == reg]
        if s.empty:
            continue
        print(f"  {reg:>14} | {s.xgb_bps.mean():>+7.3f} {s.xgb_win.mean():>4.0f}% | "
              f"{s.obi_bps.mean():>+7.3f} {s.obi_win.mean():>4.0f}% | "
              f"{s.auc_up.mean():>6.3f} | {len(s)}")
    print(f"  {'ALL OOS':>14} | {res.xgb_bps.mean():>+7.3f} {res.xgb_win.mean():>4.0f}% | "
          f"{res.obi_bps.mean():>+7.3f} {res.obi_win.mean():>4.0f}% | "
          f"{res.auc_up.mean():>6.3f} | {len(res)}")
    print("\nVERDICT: XGB beats OBI ceiling?  "
          f"{'YES' if res.xgb_bps.mean() > res.obi_bps.mean() else 'NO'} "
          f"(XGB {res.xgb_bps.mean():+.3f} vs OBI {res.obi_bps.mean():+.3f} bps); "
          f"clears perp fee?  {'YES' if res.xgb_bps.mean() > PERP_FEE_BPS else 'NO'}")
    print(f"Saved -> {OUT_DIR / f'btc_taker_xgb_h{int(H)}.csv'}")


if __name__ == "__main__":
    main()
