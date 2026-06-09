#!/usr/bin/env python3
"""
Train a short-horizon mid-price direction classifier for BTC/USDT.

Features (computed at each 0.5s quote interval, matching MarketState):
  ofi              rolling 60s signed volume imbalance [-1, 1]
  momentum         5s log-return / (σ√5) clipped to [-1, 1]
  obi              instantaneous order-book imbalance [-1, 1]
  sigma_norm       σ_t / rolling-mean(σ), div 4, clipped [0, 1]
  spike_ratio      trades-per-sec (5s) / trades-per-sec (60s), div 5
  lambda_imbalance (buy_count - sell_count) / total over 60s
  mid_ret_lag1     previous-interval normalised return (momentum lag)
  spread_norm      current exchange spread / tick_size

Target: 1 if mid[t + horizon_s] > mid[t], else 0.

Usage:
    python ml/train_forecast.py \
        --data_dir data/real \
        --symbol BTC \
        --train_start 2025-06-11 --train_end 2025-06-22 \
        --test_start  2025-06-23 --test_end  2025-06-27 \
        --horizon 1.0 \
        --out ml/models/forecast_1s_btc.pkl
"""

import argparse
import sys
from pathlib import Path
from collections import deque

import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report

sys.path.insert(0, str(Path(__file__).parent.parent))
from hft_market_maker.data.loader import DataLoader

FEATURE_NAMES = [
    "ofi", "momentum", "obi", "sigma_norm", "spike_ratio",
    "lambda_imbalance", "mid_ret_lag1", "spread_norm",
]


# ---------------------------------------------------------------------------
# Vectorised feature extraction (one day at a time)
# ---------------------------------------------------------------------------

def _extract_day(
    symbol: str,
    data_dir: str,
    date: str,
    horizon: float,
    quote_freq: float,
) -> pd.DataFrame | None:
    loader = DataLoader()
    t_path = f"{data_dir}/trades_{symbol}_{date}.parquet"
    q_path = f"{data_dir}/quotes_{symbol}_{date}.parquet"

    try:
        trades, quotes = loader.load_coinapi(t_path, q_path)
    except Exception as e:
        print(f"  [{date}] load error: {e}")
        return None

    if len(trades) < 500 or len(quotes) < 500:
        return None

    # ------------------------------------------------------------------
    # Arrays
    # ------------------------------------------------------------------
    q_ts  = np.array([q.timestamp  for q in quotes])
    q_bid = np.array([q.best_bid   for q in quotes])
    q_ask = np.array([q.best_ask   for q in quotes])
    q_mid = (q_bid + q_ask) / 2.0
    q_bsz = np.array([q.bid_size   for q in quotes])
    q_asz = np.array([q.ask_size   for q in quotes])

    t_ts   = np.array([t.timestamp for t in trades])
    t_qty  = np.array([t.quantity  for t in trades])
    t_side = np.array([t.side      for t in trades])
    t_buy  = np.where(t_side == "buy",  t_qty, 0.0)
    t_sell = np.where(t_side == "sell", t_qty, 0.0)

    # ------------------------------------------------------------------
    # Quote grid
    # ------------------------------------------------------------------
    t0 = max(q_ts[0], t_ts[0]) + 60.0   # warmup
    t1 = min(q_ts[-1], t_ts[-1]) - horizon
    if t1 <= t0:
        return None
    grid_ts = np.arange(t0, t1, quote_freq)
    N = len(grid_ts)

    # Index of most recent quote at or before each grid point
    gi = np.searchsorted(q_ts, grid_ts, side="right") - 1
    gi = np.clip(gi, 0, len(q_ts) - 1)

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------
    fi = np.searchsorted(q_ts, grid_ts + horizon, side="right") - 1
    fi = np.clip(fi, 0, len(q_ts) - 1)
    cur_mid = q_mid[gi]
    fut_mid = q_mid[fi]
    # 3-class label: 0=down, 1=flat, 2=up
    # Mid = X.005 in BTC (fixed 1-tick spread), so changes are in discrete ticks.
    label = np.where(fut_mid > cur_mid, 2, np.where(fut_mid < cur_mid, 0, 1)).astype(np.int8)

    # ------------------------------------------------------------------
    # OBI
    # ------------------------------------------------------------------
    bid_sz  = q_bsz[gi]
    ask_sz  = q_asz[gi]
    tot_sz  = bid_sz + ask_sz
    obi = np.where(tot_sz > 0, (bid_sz - ask_sz) / tot_sz, 0.0)

    # ------------------------------------------------------------------
    # Spread (normalised by tick_size=0.01)
    # ------------------------------------------------------------------
    spread_norm = (q_ask[gi] - q_bid[gi]) / 0.01

    # ------------------------------------------------------------------
    # Sigma (EWMA of log-return² / dt on quote grid, alpha=0.06 = 1−0.94)
    # ------------------------------------------------------------------
    log_ret_q = np.diff(np.log(np.maximum(q_mid, 1e-9)))
    dt_q      = np.diff(q_ts).clip(1e-6)
    var_inst  = log_ret_q ** 2 / dt_q

    alpha_ewma = 0.06   # 1 - 0.94
    var_ewma = np.zeros(len(q_ts))
    var_ewma[1] = var_inst[0]
    for k in range(2, len(q_ts)):
        var_ewma[k] = alpha_ewma * var_inst[k-1] + (1 - alpha_ewma) * var_ewma[k-1]
    sigma_q = np.sqrt(np.maximum(var_ewma, 0.0))
    sigma_grid = sigma_q[gi]

    # sigma_norm: normalised by rolling mean over last 120 quote-grid points
    win = 120
    sigma_cum = np.cumsum(sigma_grid)
    sigma_cum_shifted = np.concatenate([[0.0], sigma_cum[:-1]])
    start_idx = np.maximum(np.arange(N) - win, 0)
    sigma_roll_mean = (sigma_cum - sigma_cum[start_idx]) / np.maximum(np.arange(N) - start_idx, 1)
    sigma_norm = np.clip(sigma_grid / (sigma_roll_mean + 1e-10) / 4.0, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Momentum (5s log-return normalised by σ√5)
    # ------------------------------------------------------------------
    mom_win = 5.0
    mi = np.searchsorted(q_ts, grid_ts - mom_win, side="right") - 1
    mi = np.clip(mi, 0, len(q_ts) - 1)
    ref_mid = q_mid[mi]
    log_mom  = np.log(np.maximum(cur_mid, 1e-9) / np.maximum(ref_mid, 1e-9))
    exp_move = sigma_grid * np.sqrt(mom_win)
    momentum = np.clip(log_mom / (exp_move + 1e-9) / 3.0, -1.0, 1.0)

    # ------------------------------------------------------------------
    # Lagged mid return (previous grid interval)
    # ------------------------------------------------------------------
    prev_gi = np.searchsorted(q_ts, grid_ts - quote_freq, side="right") - 1
    prev_gi = np.clip(prev_gi, 0, len(q_ts) - 1)
    prev_mid = q_mid[prev_gi]
    mid_ret_lag1 = np.log(np.maximum(cur_mid, 1e-9) / np.maximum(prev_mid, 1e-9))
    exp_move1 = sigma_grid * np.sqrt(quote_freq)
    mid_ret_lag1 = np.clip(mid_ret_lag1 / (exp_move1 + 1e-9) / 3.0, -1.0, 1.0)

    # ------------------------------------------------------------------
    # OFI and lambda imbalance (cumsum + searchsorted)
    # ------------------------------------------------------------------
    cum_buy  = np.concatenate([[0.0], np.cumsum(t_buy)])
    cum_sell = np.concatenate([[0.0], np.cumsum(t_sell)])

    lo60 = np.searchsorted(t_ts, grid_ts - 60.0, side="right")
    hi   = np.searchsorted(t_ts, grid_ts,         side="right")

    b60 = cum_buy[hi]  - cum_buy[lo60]
    s60 = cum_sell[hi] - cum_sell[lo60]
    ofi = (b60 - s60) / (b60 + s60 + 1e-9)

    # Lambda imbalance: trade count ratio
    cum_cnt = np.arange(len(t_ts) + 1, dtype=float)
    cum_buy_cnt  = np.concatenate([[0.0], np.cumsum(t_side == "buy").astype(float)])
    cnt_total = cum_cnt[hi] - cum_cnt[lo60]
    cnt_buy   = cum_buy_cnt[hi] - cum_buy_cnt[lo60]
    cnt_sell  = cnt_total - cnt_buy
    lambda_imbalance = (cnt_buy - cnt_sell) / (cnt_total + 1e-9)

    # ------------------------------------------------------------------
    # Spike ratio: 5s trade rate / 60s trade rate
    # ------------------------------------------------------------------
    lo5  = np.searchsorted(t_ts, grid_ts - 5.0, side="right")
    cnt5 = (cum_cnt[hi] - cum_cnt[lo5]) / 5.0
    cnt60 = (cum_cnt[hi] - cum_cnt[lo60]) / 60.0
    spike_ratio = np.clip(cnt5 / (cnt60 + 1e-6) / 5.0, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    df = pd.DataFrame({
        "date":            date,
        "timestamp":       grid_ts,
        "ofi":             ofi,
        "momentum":        momentum,
        "obi":             obi,
        "sigma_norm":      sigma_norm,
        "spike_ratio":     spike_ratio,
        "lambda_imbalance": lambda_imbalance,
        "mid_ret_lag1":    mid_ret_lag1,
        "spread_norm":     spread_norm,
        "label":           label,   # 0=down, 1=flat, 2=up
        "forward_ret":     (fut_mid - cur_mid) / (cur_mid + 1e-9),
    })
    df = df.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return df


def build_dataset(
    symbol: str,
    data_dir: str,
    dates: list,
    horizon: float,
    quote_freq: float = 0.5,
) -> pd.DataFrame:
    frames = []
    for date in dates:
        print(f"  {date} ...", end=" ", flush=True)
        df = _extract_day(symbol, data_dir, date, horizon, quote_freq)
        if df is not None:
            frames.append(df)
            print(f"{len(df):,} rows")
        else:
            print("skipped")
    if not frames:
        raise ValueError("No data loaded.")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args):
    from datetime import date, timedelta

    def date_range(start, end):
        d = date.fromisoformat(start)
        e = date.fromisoformat(end)
        out = []
        while d <= e:
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out

    train_dates = date_range(args.train_start, args.train_end)
    test_dates  = date_range(args.test_start,  args.test_end)

    print(f"\nBuilding training set ({len(train_dates)} days)...")
    train_df = build_dataset(args.symbol, args.data_dir, train_dates,
                              args.horizon, args.quote_freq)
    print(f"\nBuilding test set ({len(test_dates)} days)...")
    test_df  = build_dataset(args.symbol, args.data_dir, test_dates,
                              args.horizon, args.quote_freq)

    X_train = train_df[FEATURE_NAMES].values.astype(np.float32)
    y_train = train_df["label"].values.astype(int)
    X_test  = test_df[FEATURE_NAMES].values.astype(np.float32)
    y_test  = test_df["label"].values.astype(int)

    # 15% of training for early stopping (temporal — last 15%)
    split = int(len(X_train) * 0.85)
    X_val, y_val = X_train[split:], y_train[split:]
    X_tr,  y_tr  = X_train[:split],  y_train[:split]

    print(f"\nTrain: {len(X_tr):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
    print(f"Train class balance: {y_tr.mean():.3f} up")

    # 3-class model: 0=down, 1=flat, 2=up
    # predict_proba returns [p_down, p_flat, p_up]; signal = p_up - p_down
    model = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        n_estimators=500,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=50,
        gamma=1.0,
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="mlogloss",
        early_stopping_rounds=30,
        n_jobs=-1,
        random_state=42,
    )

    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    proba_train = model.predict_proba(X_train)   # (N, 3)  cols: down, flat, up
    proba_test  = model.predict_proba(X_test)

    signal_train = proba_train[:, 2] - proba_train[:, 0]   # p_up - p_down ∈ [-1, 1]
    signal_test  = proba_test[:, 2]  - proba_test[:, 0]

    # For AUC treat up vs not-up and down vs not-down
    auc_up_train = roc_auc_score((y_train == 2).astype(int), proba_train[:, 2])
    auc_up_test  = roc_auc_score((y_test  == 2).astype(int), proba_test[:, 2])
    auc_dn_train = roc_auc_score((y_train == 0).astype(int), proba_train[:, 0])
    auc_dn_test  = roc_auc_score((y_test  == 0).astype(int), proba_test[:, 0])

    acc_train = accuracy_score(y_train, proba_train.argmax(axis=1))
    acc_test  = accuracy_score(y_test,  proba_test.argmax(axis=1))

    print("\n" + "=" * 60)
    print(f"TRAIN  Acc={acc_train:.4f}  AUC(up)={auc_up_train:.4f}  AUC(down)={auc_dn_train:.4f}")
    print(f"TEST   Acc={acc_test:.4f}  AUC(up)={auc_up_test:.4f}  AUC(down)={auc_dn_test:.4f}")
    print("=" * 60)

    # Class distribution
    for split, y_s in [("Train", y_train), ("Test", y_test)]:
        n = len(y_s)
        print(f"  {split}: down={( y_s==0).sum()/n:.1%}  "
              f"flat={(y_s==1).sum()/n:.1%}  up={(y_s==2).sum()/n:.1%}")

    print("\nTest classification report:")
    print(classification_report(y_test, proba_test.argmax(axis=1),
                                 target_names=["down", "flat", "up"]))

    # Feature importances
    print("Feature importances (gain):")
    fi = dict(zip(FEATURE_NAMES, model.feature_importances_))
    for name, imp in sorted(fi.items(), key=lambda x: -x[1]):
        bar = "█" * int(imp * 300)
        print(f"  {name:20s} {imp:.4f}  {bar}")

    # Signal sharpness: when |signal| is large, are we right?
    print("\nSignal sharpness (p_up - p_down):")
    for thresh in [0.1, 0.2, 0.3]:
        mask_up   = signal_test >  thresh
        mask_down = signal_test < -thresh
        if mask_up.sum() > 50:
            acc_up = (y_test[mask_up] == 2).mean()
            print(f"  signal> {thresh:.1f}: n={mask_up.sum():,}  p(actually_up)={acc_up:.3f}")
        if mask_down.sum() > 50:
            acc_down = (y_test[mask_down] == 0).mean()
            print(f"  signal<-{thresh:.1f}: n={mask_down.sum():,}  p(actually_down)={acc_down:.3f}")

    print(f"\n  Signal mean={signal_test.mean():.4f}  std={signal_test.std():.4f}  "
          f"range=[{signal_test.min():.3f}, {signal_test.max():.3f}]")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_path)
    print(f"\nModel saved to {out_path}")

    # Also save metadata alongside model
    meta = {
        "symbol": args.symbol,
        "horizon": args.horizon,
        "train_start": args.train_start,
        "train_end": args.train_end,
        "test_start": args.test_start,
        "test_end": args.test_end,
        "features": FEATURE_NAMES,
        "n_train": int(len(X_train)),
        "n_test":  int(len(X_test)),
        "test_auc_up":   float(auc_up_test),
        "test_auc_down": float(auc_dn_test),
        "test_acc": float(acc_test),
        "n_classes": 3,
        "label_map": {"0": "down", "1": "flat", "2": "up"},
    }
    import json
    meta_path = out_path.with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved to {meta_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir",    default="data/real")
    parser.add_argument("--symbol",      default="BTC")
    parser.add_argument("--train_start", default="2025-06-11")
    parser.add_argument("--train_end",   default="2025-06-22")
    parser.add_argument("--test_start",  default="2025-06-23")
    parser.add_argument("--test_end",    default="2025-06-27")
    parser.add_argument("--horizon",     type=float, default=1.0)
    parser.add_argument("--quote_freq",  type=float, default=0.5)
    parser.add_argument("--out",         default="ml/models/forecast_1s_btc.pkl")
    args = parser.parse_args()
    train(args)
