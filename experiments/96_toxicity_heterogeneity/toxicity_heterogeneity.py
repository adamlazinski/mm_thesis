"""
toxicity_heterogeneity.py
=========================
Exp 96 — Is adverse selection homogeneous, or is there a selectable pocket of
benign flow a market maker can harvest? (Glosten-Milgrom escape route 2.)

C59 showed the *average* passive fill's realized half-spread is eaten within
100ms. But adverse selection is an average. A real MM makes money by NOT facing
the average — by quoting only into states whose flow is benign. This experiment
takes C59's markout and conditions it on state observable STRICTLY BEFORE the
fill (a maker posts passively and cannot pick who hits the order — only when to
be quoting), signed toward the maker's side:

    realized_half(t,h) = D * (price - mid_{t+h})       # what the maker keeps
    press_perp = D * dev            # perp-implied basis pressure (C56 lead)
    press_ofi  = D * signed_flow    # recent net taker flow (sweep in progress)
    press_obi  = D * obi            # top-of-book depth imbalance
    vol_recent                      # realized vol of mid, prior window
    intensity                       # trades/sec, prior window
    spread_ticks                    # compensation available at the fill

D=+1 taker-buy lifts ask => maker SOLD (hurt by mid up); D=-1 hits bid => maker
BOUGHT. press_* > 0 always means "predicts an adverse move against the maker."

Output per book: (1) univariate — realized_half by quintile of each press
feature; (2) a combined toxicity score, realized_half across its quintiles; (3)
the benign corner (all predictors favorable) vs the toxic corner — mean
realized_half, net of fee, and the % of flow that qualifies. If every selectable
bucket is negative net of realistic fees, lit MM is homogeneously dead; if a
selectable bucket clears the fee, that names the gate worth quoting.

Diagnostic, not a P&L claim: realized_half marks to mid, which C60 showed is not
directly bankable. A positive benign pocket here is a TARGET to verify in the
engine (exp 94-style gate), not a strategy on its own.

Run: python experiments/96_toxicity_heterogeneity/toxicity_heterogeneity.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
PROC = ROOT / "data" / "live" / "processed"

# spot book -> (tick, its perp for the dev feature)
BOOKS = {"LINK": (0.001, "LINK_PERP"), "BTC": (0.01, "BTC_PERP")}
HORIZONS = (0.1, 1.0, 5.0)
FLOW_WIN = 1.0        # seconds, recent-flow / vol / intensity lookback
EWMA_HL = 60.0        # basis EWMA half-life (matches exps 90/94)
QUOTE_TOL = pd.Timedelta("0.5s")
CAP_TICKS = 5.0
N_BUCKETS = 5
FEES_BPS = (0.0, 0.5, 1.0)   # maker fee scenarios (top-tier .. low-tier)

PRESS_COLS = ["press_perp", "press_ofi", "press_obi", "vol_recent",
              "intensity", "neg_spread"]


def _asof_mid(times, q):
    left = pd.DataFrame({"time_exchange": times.to_numpy()}).sort_values("time_exchange")
    m = pd.merge_asof(left, q, on="time_exchange", direction="backward",
                      tolerance=QUOTE_TOL)
    return m["mid"].to_numpy()[np.argsort(left.index.to_numpy(), kind="stable")]


def _asof_col(times, q, col):
    left = pd.DataFrame({"time_exchange": times.to_numpy()}).sort_values("time_exchange")
    m = pd.merge_asof(left, q, on="time_exchange", direction="backward",
                      tolerance=QUOTE_TOL)
    return m[col].to_numpy()[np.argsort(left.index.to_numpy(), kind="stable")]


def dev_at(t_tr, ts, ms, tp, mp):
    """Perp-spot basis deviation (EWMA-detrended), evaluated just before each trade."""
    t_all = np.concatenate([ts, tp])
    venue = np.concatenate([np.zeros(len(ts), int), np.ones(len(tp), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]
    out_t = np.empty(len(t_all)); out_d = np.empty(len(t_all))
    cur = [ms[0], mp[0]]; i_s = i_p = 0
    base = mp[0] - ms[0]; last_t = t_all[0]
    for k, (t, v) in enumerate(zip(t_all, venue)):
        if v == 0:
            cur[0] = ms[i_s]; i_s += 1
        else:
            cur[1] = mp[i_p]; i_p += 1
        B = cur[1] - cur[0]
        alpha = 1 - 0.5 ** (max(t - last_t, 0.0) / EWMA_HL)
        base += alpha * (B - base); last_t = t
        out_t[k] = t; out_d[k] = B - base
    # as-of backward onto trade times
    idx = np.searchsorted(out_t, t_tr, side="right") - 1
    idx = np.clip(idx, 0, len(out_d) - 1)
    return out_d[idx]


def load_quotes(book, date):
    df = pd.read_parquet(PROC / f"quotes_{book}_{date}.parquet")
    df["time_exchange"] = df["time_exchange"].values.astype("datetime64[ns]")
    df = df.sort_values("time_exchange").reset_index(drop=True)
    df["mid"] = (df["bid_price"] + df["ask_price"]) / 2.0
    df["obi"] = (df["bid_size"] - df["ask_size"]) / (df["bid_size"] + df["ask_size"])
    df["spread"] = df["ask_price"] - df["bid_price"]
    return df


def build(book, tick, perp, date):
    q = load_quotes(book, date)
    qt = q["time_exchange"].values.astype("int64") / 1e9
    t = pd.read_parquet(PROC / f"trades_{book}_{date}.parquet")
    t["time_exchange"] = t["time_exchange"].values.astype("datetime64[ns]")
    t = t.sort_values("time_exchange").reset_index(drop=True)
    tt = t["time_exchange"].values.astype("int64") / 1e9
    D = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    price = t["price"].to_numpy(); sz = t["size"].to_numpy()

    qm = q[["time_exchange", "mid"]]
    mid_t = _asof_mid(t["time_exchange"], qm)
    obi_t = _asof_col(t["time_exchange"], q[["time_exchange", "obi"]], "obi")
    spr_t = _asof_col(t["time_exchange"], q[["time_exchange", "spread"]], "spread")

    # recent signed flow & intensity over the prior FLOW_WIN seconds (strictly before t)
    signed = D * sz
    csum = np.concatenate([[0.0], np.cumsum(signed)])
    lo = np.searchsorted(tt, tt - FLOW_WIN, side="left")
    idx = np.arange(len(tt))
    recent_flow = csum[idx] - csum[lo]          # excludes current trade
    intensity = (idx - lo) / FLOW_WIN

    # recent realized vol of mid over prior window (from quotes), as-of to trades
    q_ret = np.diff(np.log(q["mid"].to_numpy()), prepend=np.log(q["mid"].iloc[0]))
    qser = pd.Series(q_ret, index=q["time_exchange"])
    vol = qser.rolling(f"{int(FLOW_WIN*1000)}ms").std().to_numpy()
    vol_t = _asof_col(t["time_exchange"],
                      pd.DataFrame({"time_exchange": q["time_exchange"], "vol": vol}),
                      "vol")

    # perp pressure
    ts_ = qt; ms_ = q["mid"].to_numpy()
    qp = load_quotes(perp, date)
    dev = dev_at(tt, ts_, ms_,
                 qp["time_exchange"].values.astype("int64") / 1e9,
                 qp["mid"].to_numpy())

    df = pd.DataFrame({
        "t": tt, "D": D, "price": price, "sz": sz, "mid_t": mid_t,
        "press_perp": D * dev,
        "press_ofi": D * recent_flow,
        "press_obi": D * obi_t,
        "vol_recent": vol_t,
        "intensity": intensity,
        "neg_spread": -(spr_t / tick),          # wider spread => less net-toxic
    })
    for h in HORIZONS:
        mid_h = _asof_mid(t["time_exchange"] + pd.to_timedelta(h, unit="s"), qm)
        df[f"rh_{h}"] = D * (price - mid_h)      # realized half-spread ($) at h
    df["mid_h_ok"] = ~np.isnan(df[f"rh_{HORIZONS[-1]}"])

    base = (~np.isnan(mid_t)) & (np.abs(D * (price - mid_t)) <= CAP_TICKS * tick) \
        & ~np.isnan(df["press_perp"]) & ~np.isnan(df["vol_recent"])
    return df[base].reset_index(drop=True), tick


def bps(x_dollars, mid):
    return 1e4 * np.nanmean(x_dollars / mid)


def summarize(df, tick, book):
    out = {"book": book, "n": int(len(df)),
           "mean_mid": float(np.nanmedian(df["mid_t"]))}
    mid = df["mid_t"].to_numpy()

    # univariate: realized_half by quintile of each press feature
    uni = {}
    for col in PRESS_COLS:
        v = df[col].to_numpy()
        if np.all(~np.isfinite(v)) or np.nanstd(v) == 0:
            continue
        try:
            qb = pd.qcut(v, N_BUCKETS, labels=False, duplicates="drop")
        except ValueError:
            continue
        buckets = []
        for b in range(int(np.nanmax(qb)) + 1):
            m = qb == b
            if m.sum() == 0:
                continue
            row = {"bucket": int(b), "frac": float(m.mean())}
            for h in HORIZONS:
                row[f"rh_{h}_ticks"] = float(np.nanmean(df[f"rh_{h}"].to_numpy()[m]) / tick)
                row[f"rh_{h}_bps"] = float(bps(df[f"rh_{h}"].to_numpy()[m], mid[m]))
            buckets.append(row)
        uni[col] = buckets
    out["univariate"] = uni

    # combined toxicity score = mean of z-scored press features (higher = toxic)
    Z = []
    for col in PRESS_COLS:
        v = df[col].to_numpy().astype(float)
        s = np.nanstd(v)
        Z.append((v - np.nanmean(v)) / s if s > 0 else np.zeros_like(v))
    score = np.nanmean(np.vstack(Z), axis=0)
    df = df.assign(tox=score)
    qb = pd.qcut(score, N_BUCKETS, labels=False, duplicates="drop")
    combo = []
    for b in range(int(np.nanmax(qb)) + 1):
        m = qb == b
        row = {"bucket": int(b), "frac": float(m.mean()),
               "score_mean": float(np.nanmean(score[m]))}
        for h in HORIZONS:
            row[f"rh_{h}_ticks"] = float(np.nanmean(df[f"rh_{h}"].to_numpy()[m]) / tick)
            row[f"rh_{h}_bps"] = float(bps(df[f"rh_{h}"].to_numpy()[m], mid[m]))
        combo.append(row)
    out["combined_score"] = combo

    # benign vs toxic corner: bottom vs top score quintile, net of fees @ 1s and 5s
    benign = qb == 0
    toxic = qb == (int(np.nanmax(qb)))
    corner = {}
    for name, m in [("benign", benign), ("toxic", toxic)]:
        c = {"frac": float(m.mean())}
        for h in (1.0, 5.0):
            rh_bps = float(bps(df[f"rh_{h}"].to_numpy()[m], mid[m]))
            c[f"rh_{h}_bps"] = rh_bps
            c[f"net_{h}_bps"] = {f"fee_{f}": round(rh_bps - f, 4) for f in FEES_BPS}
        corner[name] = c
    out["corner"] = corner
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    results = {}
    for book, (tick, perp) in BOOKS.items():
        if not (PROC / f"trades_{book}_{args.date}.parquet").exists():
            print(f"=== {book}: missing, skip"); continue
        print(f"=== {book} {args.date}")
        df, tk = build(book, tick, perp, args.date)
        r = summarize(df, tk, book)
        results[book] = r

        print(f"  n={r['n']:,}  benign frac={r['corner']['benign']['frac']:.2f}")
        print(f"  {'feature':12s}  rh@1s by quintile (bps, low->high toxicity)")
        for col in PRESS_COLS:
            if col not in r["univariate"]:
                continue
            vals = [f"{b['rh_1.0_bps']:+.2f}" for b in r["univariate"][col]]
            print(f"  {col:12s}  {'  '.join(vals)}")
        cb = r["combined_score"]
        print(f"  {'COMBINED':12s}  " +
              "  ".join(f"{b['rh_1.0_bps']:+.2f}" for b in cb))
        bn = r["corner"]["benign"]; tx = r["corner"]["toxic"]
        print(f"  benign corner: rh@1s={bn['rh_1.0_bps']:+.3f}bps "
              f"net@fee0={bn['net_1.0_bps']['fee_0.0']:+.3f}  "
              f"rh@5s={bn['rh_5.0_bps']:+.3f}bps")
        print(f"  toxic  corner: rh@1s={tx['rh_1.0_bps']:+.3f}bps  "
              f"rh@5s={tx['rh_5.0_bps']:+.3f}bps")

    with open(OUT / f"toxicity_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "flow_win": FLOW_WIN,
                   "horizons": list(HORIZONS), "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/toxicity_{args.date}.json")


if __name__ == "__main__":
    main()
