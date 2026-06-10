"""
Conditional-reversion gate for the deep-limit MM strategy.
==========================================================
Deep-limit MM = short vol + short momentum: post a limit X ticks from mid, fill
only on a dislocation that reaches it, then bet the move REVERTS (profit) rather
than CONTINUES (loss). Viability hinges on two questions this study answers:

  Q1  Is there a depth where reversion dominates continuation?
  Q2  Can an EX-ANTE signal (vol regime, OFI alignment) separate the reverting
      fills from the continuing ones? — the precondition for risk guardrails to
      add value rather than just trade edge for tail symmetrically.

Event model (proxy, no backtest):
  At time t, displacement over the wait window DT:  disp = (mid(t)-mid(t-DT))/tick
  disp<0 = down-move => a LONG limit placed DT ago just filled (we bought the dip);
  disp>0 = up-move   => a SHORT limit filled. We FADE the move (dir = -sign(disp)).
  Reversion PnL over hold H:  pnl_ticks = dir * (mid(t+H)-mid(t))/tick
    >0 = move reverted (profit) ; <0 = move continued (loss).

State at fill (observable ex-ante):
  vol     : trailing-VOLWIN realized-vol tercile (low/med/high)
  ofi_align: sign(OFI over [t-DT,t]) == sign(disp)?  aligned+strong = informed
             continuation hypothesis; weak/opposed = noise/air-pocket => reversion.

Reports per depth bin (and cross-tab by vol / ofi_align): mean pnl, P(profit),
and the 5th-percentile pnl (the falling-knife tail) — tail is reported because
the whole strategy is a left-tail bet.

Usage:
    python experiments/57_deep_reversion/conditional_reversion.py --symbol LINK
    python experiments/57_deep_reversion/conditional_reversion.py --symbol BTC --tick 0.01
"""
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "real"
OUT_DIR  = Path("experiments/57_deep_reversion/analysis")

DT       = 30.0      # wait window (limit placed DT ago)
HOLD     = 60.0      # reversion holding horizon
VOLWIN   = 120.0
GRID_DT  = 1.0
DEPTH_BINS = [8, 20, 50, 100, 200, 500, 10**9]   # ticks from mid (|disp|)
OFI_THR  = 0.3       # |OFI| above this counts as "strong"


def dates_for(symbol):
    td = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / f"trades_{symbol}_*.parquet"))}
    qd = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA_DIR / f"quotes_{symbol}_*.parquet"))}
    return sorted(td & qd)


def load_day(symbol, date, tick):
    q = pd.read_parquet(DATA_DIR / f"quotes_{symbol}_{date}.parquet",
                        columns=["time_exchange", "ask_price", "bid_price"])
    qts = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qmid = (q["ask_price"].to_numpy() + q["bid_price"].to_numpy()) / 2.0
    t = pd.read_parquet(DATA_DIR / f"trades_{symbol}_{date}.parquet",
                        columns=["time_exchange", "size", "taker_side"])
    tts = t["time_exchange"].astype("int64").to_numpy() / 1e9
    tqty = t["size"].to_numpy()
    tside = t["taker_side"].astype(str).to_numpy()
    return qts, qmid, tts, tqty, tside


def day_events(symbol, date, tick):
    qts, qmid, tts, tqty, tside = load_day(symbol, date, tick)
    if len(qts) < 100:
        return None
    g = np.arange(np.ceil(qts[0]) + DT + 1, np.floor(qts[-1]) - HOLD - 1, GRID_DT)
    if len(g) < 50:
        return None

    def mid_at(t):
        idx = np.clip(np.searchsorted(qts, t, side="right") - 1, 0, len(qmid) - 1)
        return qmid[idx]

    m_now  = mid_at(g)
    m_prev = mid_at(g - DT)
    m_fut  = mid_at(g + HOLD)
    disp   = (m_now - m_prev) / tick               # signed displacement (ticks)
    dirn   = -np.sign(disp)                         # fade the move
    pnl    = dirn * (m_fut - m_now) / tick          # reversion pnl (ticks)

    # trailing realized vol on grid (tick-returns std)
    r = np.diff(m_now, prepend=m_now[0]) / tick
    vol = pd.Series(r).rolling(int(VOLWIN / GRID_DT), min_periods=10).std().to_numpy()

    # OFI over [t-DT, t] from trades (signed volume imbalance)
    buy = np.where(np.char.lower(tside.astype(str)) == "buy", tqty, 0.0)
    sell = np.where(np.char.lower(tside.astype(str)) == "sell", tqty, 0.0)
    cb = np.concatenate([[0.0], np.cumsum(buy)])
    cs = np.concatenate([[0.0], np.cumsum(sell)])
    hi = np.searchsorted(tts, g, side="right")
    lo = np.searchsorted(tts, g - DT, side="right")
    b = cb[hi] - cb[lo]; s = cs[hi] - cs[lo]
    ofi = (b - s) / (b + s + 1e-9)

    return pd.DataFrame({"disp": disp, "dirn": dirn, "pnl": pnl,
                         "absdepth": np.abs(disp), "vol": vol, "ofi": ofi})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="LINK")
    ap.add_argument("--tick", type=float, default=None)
    ap.add_argument("--days", type=int, default=999)
    args = ap.parse_args()
    tick = args.tick if args.tick is not None else (0.01 if args.symbol.startswith("BTC") else 0.001)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dates = dates_for(args.symbol)[: args.days]
    print(f"Conditional reversion — {args.symbol} (tick={tick}), {len(dates)} days, "
          f"DT={DT}s hold={HOLD}s")
    frames = []
    for d in dates:
        try:
            e = day_events(args.symbol, d, tick)
            if e is not None:
                frames.append(e); print(f"  {d}: {len(e):,} grid obs")
        except Exception as ex:
            print(f"  {d}: ERROR {ex}")
    df = pd.concat(frames, ignore_index=True)
    df = df[df["dirn"] != 0]
    # vol terciles (global)
    df["volb"] = pd.qcut(df["vol"].fillna(df["vol"].median()), 3,
                         labels=["loV", "medV", "hiV"], duplicates="drop")
    # OFI alignment with the move (informed-continuation hypothesis)
    aligned = np.sign(df["ofi"]) == np.sign(df["disp"])
    strong = df["ofi"].abs() >= OFI_THR
    df["ofi_state"] = np.where(aligned & strong, "aligned_strong",
                       np.where(~aligned & strong, "opposed_strong", "weak"))
    df["dbin"] = pd.cut(df["absdepth"], DEPTH_BINS, right=False,
                        labels=[f"{DEPTH_BINS[i]}-{DEPTH_BINS[i+1]}t"
                                for i in range(len(DEPTH_BINS)-1)])

    def tab(group_cols, title):
        print(f"\n{'='*78}\n{title}\n{'='*78}")
        g = df.groupby(group_cols, observed=True)["pnl"]
        out = g.agg(mean="mean", p_profit=lambda x: (x > 0).mean()*100,
                    p5=lambda x: np.percentile(x, 5), n="count")
        out = out[out["n"] >= 50]
        with pd.option_context("display.float_format", lambda v: f"{v:.1f}"):
            print(out.to_string())
        return out

    print("\nReversion PnL is in TICKS (mean>0 = reversion dominates; p5 = tail/knife).")
    t_depth = tab(["dbin"], "Q1 — BY DEPTH (does reversion dominate at some depth?)")
    t_dv = tab(["dbin", "volb"], "Q2a — DEPTH x VOL REGIME (separating signal?)")
    t_do = tab(["dbin", "ofi_state"], "Q2b — DEPTH x OFI-ALIGNMENT (informed vs noise?)")

    res = {"symbol": args.symbol, "tick": tick, "DT": DT, "HOLD": HOLD,
           "by_depth": json.loads(t_depth.reset_index().to_json(orient="records")),
           "by_depth_vol": json.loads(t_dv.reset_index().to_json(orient="records")),
           "by_depth_ofi": json.loads(t_do.reset_index().to_json(orient="records"))}
    with open(OUT_DIR / f"conditional_reversion_{args.symbol}.json", "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\nSaved -> {OUT_DIR / f'conditional_reversion_{args.symbol}.json'}")


if __name__ == "__main__":
    main()
