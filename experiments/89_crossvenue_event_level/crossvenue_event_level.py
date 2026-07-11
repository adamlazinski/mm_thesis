"""
crossvenue_event_level.py
==========================
Exp 89 — Spot↔perp at event resolution (captured data): three measurements the
1Hz-book era could not make.

A. HY LEAD-LAG AT 10ms — Hayashi–Yoshida cross-correlation (exp 61 estimator,
   unchanged) on BBO *mid-change* event series from both venues, theta grid
   ±500ms in 10ms steps. Extends C36/exp 88 (100ms grid, trades) down an order
   of magnitude.

B. DIVERGENCE-CLOSURE — basis B(t) = mid_perp − mid_spot vs a 60s-halflife EWMA
   baseline. An episode opens when |B − base| exceeds a per-asset threshold and
   closes when it falls back under half of it. Recorded per episode: size,
   lifetime, trigger venue (whose move opened it), closure mode (laggard
   repriced toward vs trigger reverted). Quantifies "one trailing the other"
   where it actually lives.

C. QUOTE FADING — Kurth-et-al-style liquidity withdrawal, cross-venue: after a
   mid up-move on venue A, does venue B's best-ask *depth* shrink before venue
   B's price moves? Median relative depth D(t0+h)/D(t0−) at h ∈ {10..200}ms on
   the side an arbitrageur would lift, vs an unconditional random-time control.
   Episodes where B's price repriced within h are counted separately.

Caveat: cross-engine (spot vs futures) exchange-timestamp skew is unknown but
assumed ≤ few ms; capture path offset p50 ≈ 13ms is common-mode per venue.

Run: python experiments/89_crossvenue_event_level/crossvenue_event_level.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "hy61", ROOT / "experiments/61_link_spot_perp/hy_leadlag.py")
hy61 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hy61)

PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

PAIRS = {
    # divergence threshold in $ (open at |B-base|>thr, close at thr/2)
    "LINK": {"spot": "LINK", "perp": "LINK_PERP", "div_thr": 0.002},
    "BTC":  {"spot": "BTC",  "perp": "BTC_PERP",  "div_thr": 3.0},
}
FADE_HORIZONS_MS = [10, 20, 50, 100, 200]
EWMA_HALFLIFE_S = 60.0


def load_quotes(asset: str, date: str):
    df = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet",
                         columns=["time_exchange", "bid_price", "ask_price",
                                  "bid_size", "ask_size"])
    t = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bid = df["bid_price"].values.astype(float)
    ask = df["ask_price"].values.astype(float)
    keep = np.concatenate([[True], np.diff(t) > 0])
    return (t[keep], bid[keep], ask[keep],
            df["bid_size"].values.astype(float)[keep],
            df["ask_size"].values.astype(float)[keep])


def mid_changes(t, bid, ask):
    mid = (bid + ask) / 2
    chg = np.concatenate([[True], np.abs(np.diff(mid)) > 1e-12])
    return t[chg], mid[chg]


# ── A. HY at 10ms ──────────────────────────────────────────────────────────────

def part_a(ts, ms, tp, mp):
    thetas = np.round(np.arange(-0.5, 0.501, 0.01), 3)
    curve, _, _ = hy61.hy_curve(ts, ms, tp, mp, thetas)
    k = int(np.nanargmax(np.abs(curve)))
    return {"thetas": thetas.tolist(), "ccf": [float(x) for x in curve],
            "peak_theta_s": float(thetas[k]), "peak_rho": float(curve[k]),
            "n_spot_midchg": len(ts), "n_perp_midchg": len(tp)}


# ── B. divergence-closure ──────────────────────────────────────────────────────

def part_b(ts, ms, tp, mp, thr):
    # merged event stream of (t, venue, mid)
    t_all = np.concatenate([ts, tp])
    venue = np.concatenate([np.zeros(len(ts), int), np.ones(len(tp), int)])
    order = np.argsort(t_all, kind="stable")
    t_all, venue = t_all[order], venue[order]

    cur = [ms[0], mp[0]]
    i_s = i_p = 0
    base = mp[0] - ms[0]
    last_t = t_all[0]
    ep = None
    episodes = []

    for t, v in zip(t_all, venue):
        if v == 0:
            cur[0] = ms[i_s]; i_s += 1
        else:
            cur[1] = mp[i_p]; i_p += 1
        B = cur[1] - cur[0]
        dt = max(t - last_t, 0.0)
        last_t = t
        # baseline always tracks — a divergence the baseline absorbs is a
        # basis regime shift, closed out below as "absorbed", not a lag event
        alpha = 1 - 0.5 ** (dt / EWMA_HALFLIFE_S)
        base += alpha * (B - base)
        dev = B - base
        if ep is None:
            if abs(dev) > thr:
                ep = dict(t0=t, dev0=dev, trigger=v,
                          spot0=cur[0], perp0=cur[1])
        else:
            if t - ep["t0"] > 30.0:
                episodes.append(dict(size=abs(ep["dev0"]), dur=t - ep["t0"],
                                     trigger="spot" if ep["trigger"] == 0 else "perp",
                                     mode="absorbed"))
                ep = None
            elif abs(dev) < thr / 2:
                ds = cur[0] - ep["spot0"]; dp = cur[1] - ep["perp0"]
                # which venue's net move closed the gap? closing direction
                # reduces dev0: spot closing move has sign(dev0), perp has -sign
                s_close = ds * np.sign(ep["dev0"])
                p_close = -dp * np.sign(ep["dev0"])
                mode = ("laggard_repriced"
                        if (s_close if ep["trigger"] == 1 else p_close) >
                           (p_close if ep["trigger"] == 1 else s_close)
                        else "trigger_reverted")
                episodes.append(dict(size=abs(ep["dev0"]), dur=t - ep["t0"],
                                     trigger="spot" if ep["trigger"] == 0 else "perp",
                                     mode=mode))
                ep = None

    if not episodes:
        return {"n": 0}
    dur = np.array([e["dur"] for e in episodes])
    return {"n": len(episodes),
            "dur_ms_p50": float(np.median(dur) * 1e3),
            "dur_ms_p90": float(np.percentile(dur, 90) * 1e3),
            "size_p50": float(np.median([e["size"] for e in episodes])),
            "trigger": {s: sum(1 for e in episodes if e["trigger"] == s)
                        for s in ("spot", "perp")},
            "mode": {m: sum(1 for e in episodes if e["mode"] == m)
                     for m in ("laggard_repriced", "trigger_reverted", "absorbed")},
            "dur_ms_p50_lag_only": (float(np.median(
                [e["dur"] for e in episodes if e["mode"] != "absorbed"]) * 1e3)
                if any(e["mode"] != "absorbed" for e in episodes) else None)}


# ── C. quote fading ────────────────────────────────────────────────────────────

def fade(t_a, mid_a, t_b, ask_b_px, ask_b_sz, rng=None):
    """After up-moves of A's mid, track B's best-ask depth (price unchanged)."""
    up = np.where(np.diff(mid_a) > 1e-12)[0] + 1
    t_events = t_a[up] if rng is None else rng
    out = {h: [] for h in FADE_HORIZONS_MS}
    repriced = {h: 0 for h in FADE_HORIZONS_MS}
    for t0 in t_events:
        j0 = np.searchsorted(t_b, t0, side="right") - 1
        if j0 < 0:
            continue
        p0, d0 = ask_b_px[j0], ask_b_sz[j0]
        if d0 <= 0:
            continue
        for h in FADE_HORIZONS_MS:
            j1 = np.searchsorted(t_b, t0 + h / 1e3, side="right") - 1
            if j1 < 0:
                continue
            if abs(ask_b_px[j1] - p0) > 1e-12:
                repriced[h] += 1
            else:
                out[h].append(ask_b_sz[j1] / d0)
    res = {}
    for h in FADE_HORIZONS_MS:
        v = np.array(out[h])
        n_tot = len(v) + repriced[h]
        res[f"h{h}ms"] = {
            "n_price_unchanged": len(v),
            "repriced_pct": 100 * repriced[h] / n_tot if n_tot else None,
            "depth_ratio_p50": float(np.median(v)) if len(v) else None,
            "faded_pct": float(100 * (v < 0.75).mean()) if len(v) else None}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()
    rng = np.random.default_rng(7)

    results = {}
    for pair, cfg in PAIRS.items():
        print(f"=== {pair} {args.date}")
        t_s, bid_s, ask_s, bsz_s, asz_s = load_quotes(cfg["spot"], args.date)
        t_p, bid_p, ask_p, bsz_p, asz_p = load_quotes(cfg["perp"], args.date)
        ts_m, ms = mid_changes(t_s, bid_s, ask_s)
        tp_m, mp = mid_changes(t_p, bid_p, ask_p)

        a = part_a(ts_m, ms, tp_m, mp)
        print(f"  A: peak theta={a['peak_theta_s']*1e3:+.0f}ms rho={a['peak_rho']:.3f} "
              f"(mid-changes spot={a['n_spot_midchg']:,} perp={a['n_perp_midchg']:,})")

        b = part_b(ts_m, ms, tp_m, mp, cfg["div_thr"])
        print(f"  B: {b.get('n',0)} divergences, dur p50={b.get('dur_ms_p50',0):.0f}ms, "
              f"trigger={b.get('trigger')}, mode={b.get('mode')}")

        c = {
            "spot_moves_perp_book": fade(ts_m, ms, t_p, ask_p, asz_p),
            "spot_moves_perp_book_CONTROL": fade(
                ts_m, ms, t_p, ask_p, asz_p,
                rng=np.sort(rng.uniform(t_p[0] + 1, t_p[-1] - 1, 3000))),
            "perp_moves_spot_book": fade(tp_m, mp, t_s, ask_s, asz_s),
            "perp_moves_spot_book_CONTROL": fade(
                tp_m, mp, t_s, ask_s, asz_s,
                rng=np.sort(rng.uniform(t_s[0] + 1, t_s[-1] - 1, 3000))),
        }
        for k in ("spot_moves_perp_book", "perp_moves_spot_book"):
            h50 = c[k]["h50ms"]; ctl = c[k + "_CONTROL"]["h50ms"]
            print(f"  C {k}: 50ms depth ratio p50={h50['depth_ratio_p50']} "
                  f"(ctrl {ctl['depth_ratio_p50']}), repriced%={h50['repriced_pct']:.0f} "
                  f"(ctrl {ctl['repriced_pct']:.0f})")

        results[pair] = {"A_hy10ms": a, "B_divergence": b, "C_fading": c}

    with open(OUT / f"crossvenue_{args.date}.json", "w") as fh:
        json.dump({"date": args.date, "results": results}, fh, indent=2)
    print(f"\nSaved -> {OUT}/crossvenue_{args.date}.json")


if __name__ == "__main__":
    main()
