"""
Adverse Selection Decomposition  (probe-simulation approach)
-------------------------------------------------------------
Simulates a market maker who posts at a fixed δ from mid every quote_freq
seconds and measures the adverse selection on the FIRST fill per interval.

Why "probe simulation" and not "all trades":
  During a sustained price cascade, thousands of trades occur at each price
  level. Treating each as an independent fill event inflates E[AS] by ~100×
  because it double-counts the continuation of the same move. A real market
  maker cancels after one fill and reposts — so each interval contributes at
  most ONE fill observation.

Method
------
  For each interval i = [t_i, t_i + quote_freq):
    1. Read mid_i = mid at t_i (the price we'd use when posting)
    2. Our hypothetical bid  = mid_i − δ·tick
       Our hypothetical ask  = mid_i + δ·tick
    3. Check if any sell-initiated trade at price ≤ bid occurred in the interval
       → first such trade = fill event; record (fill_time, mid_at_fill)
    4. Likewise for ask fills (buy-initiated trade ≥ ask)
    5. At fill_time + h, look up future mid and compute AS in ticks:
         bid fill: AS = (mid_at_fill − mid_future) / tick  [positive = price fell]
         ask fill: AS = (mid_future − mid_at_fill) / tick  [positive = price rose]

Results
-------
  fill_rate(δ)   : fraction of intervals where a fill occurs (both sides pooled)
  E[AS | δ, h]   : mean adverse selection ticks, conditional on getting filled
  net_pnl(δ, h)  : δ − E[AS | δ, h]  — expected tick PnL per fill

Usage
-----
    python scripts/adverse_selection_analysis.py \\
        --config experiments/48_adverse_selection/config.json

Output
------
    <output_dir>/
        fig1_as_vs_delta.png        E[AS|δ] for each horizon vs δ
        fig2_net_pnl_vs_delta.png   δ − E[AS|δ] per fill
        fig3_fill_rate.png          empirical fill_rate(δ)
        fig4_pnl_envelope.png       fill_rate(δ) × net_pnl(δ)
        fig5_win_rate.png           fraction of fills where net PnL > 0
        summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hft_market_maker.data.loader import DataLoader


# ---------------------------------------------------------------------------
# δ probe levels (in ticks) — covers action space of Exp 47 and beyond
# ---------------------------------------------------------------------------
DELTA_LEVELS = np.array([
    0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0,
    20.0, 30.0, 50.0, 70.0, 80.0, 100.0, 150.0, 200.0, 350.0, 500.0,
])

_PALETTE = ["#2196F3", "#FF9800", "#4CAF50", "#E91E63", "#9C27B0", "#00BCD4", "#FF5722", "#795548"]

def _horizon_color(h: int, all_horizons: list) -> str:
    idx = all_horizons.index(h) if h in all_horizons else 0
    return _PALETTE[idx % len(_PALETTE)]

def _horizon_label(h: int) -> str:
    if h < 60:
        return f"{h} s"
    elif h < 3600:
        return f"{h//60} min"
    return f"{h//3600} hr"


# ---------------------------------------------------------------------------
# Core: probe simulation for a single δ level and side
# ---------------------------------------------------------------------------

def probe_one_side(
    t_ts: np.ndarray,          # trade timestamps (sorted)
    t_price: np.ndarray,       # trade prices
    t_side: np.ndarray,        # 'buy' or 'sell'
    q_ts: np.ndarray,          # quote timestamps (sorted)
    q_mids: np.ndarray,        # mid prices from quotes
    delta_ticks: float,
    tick_size: float,
    quote_freq: float,
    horizons: list[int],
    side: str,                 # 'bid' or 'ask'
) -> dict:
    """
    Simulate posting one limit order per interval at mid ± δ·tick.
    Returns per-interval fill stats and adverse selection at each horizon.

    Fill condition uses the CONTEMPORANEOUS mid (most recent quote just before
    each trade), not the interval-start mid. Using a stale interval-start mid
    makes fill rates flat across all δ because it actually measures
    P(mid drifted ≥ δ within the interval), which is dominated by intra-interval
    volatility and nearly independent of δ for δ < ~100 ticks.

    Correct semantics: a trade fills our hypothetical order at δ if and only if
    the trade price is ≥ δ ticks through the mid *at the moment of that trade*.

    side='bid': order is below mid, filled by sell-initiated trades ≥ δ ticks below mid
    side='ask': order is above mid, filled by buy-initiated trades ≥ δ ticks above mid
    """
    day_start   = q_ts[0]
    day_end     = q_ts[-1]
    n_intervals = max(1, int((day_end - day_start) / quote_freq))

    # Contemporaneous mid: most recent quote at or before each trade
    pre_q_idx = np.searchsorted(q_ts, t_ts, side="right") - 1
    pre_q_idx = np.clip(pre_q_idx, 0, len(q_mids) - 1)
    pre_mids  = q_mids[pre_q_idx]

    # Fill condition: trade crossed our level relative to contemporaneous mid
    if side == "bid":
        delta_of_trade = (pre_mids - t_price) / tick_size   # ≥0 means below mid
        aggressor_fill = (t_side == "sell") & (delta_of_trade >= delta_ticks)
    else:
        delta_of_trade = (t_price - pre_mids) / tick_size   # ≥0 means above mid
        aggressor_fill = (t_side == "buy") & (delta_of_trade >= delta_ticks)

    # Map each filling trade to its 0.5 s interval
    trade_interval = np.floor((t_ts - day_start) / quote_freq).astype(int)
    trade_interval = np.clip(trade_interval, 0, n_intervals - 1)

    fill_intervals   = trade_interval[aggressor_fill]
    fill_ts_arr      = t_ts[aggressor_fill]
    fill_pre_mids    = pre_mids[aggressor_fill]

    if len(fill_intervals) == 0:
        return {"n_intervals": n_intervals, "n_filled": 0, "fill_rate": 0.0}

    # First fill per interval (trades are time-sorted → np.unique picks the earliest)
    unique_ivs, first_pos = np.unique(fill_intervals, return_index=True)
    first_fill_ts       = fill_ts_arr[first_pos]
    first_fill_pre_mids = fill_pre_mids[first_pos]
    n_filled            = len(unique_ivs)

    out = {
        "n_intervals": n_intervals,
        "n_filled":    n_filled,
        "fill_rate":   n_filled / n_intervals,
        # Return raw AS arrays for correct SE pooling across days
        "_raw": {},
    }

    for h in horizons:
        fut_q_idx = np.searchsorted(q_ts, first_fill_ts + h, side="right") - 1
        fut_valid = fut_q_idx < len(q_mids) - 1          # don't overshoot end-of-day
        fut_q_idx = np.clip(fut_q_idx, 0, len(q_mids) - 1)
        fut_mids  = q_mids[fut_q_idx]

        if fut_valid.sum() < 2:
            out[h] = None
            out["_raw"][h] = np.array([])
            continue

        mf = first_fill_pre_mids[fut_valid]
        fm = fut_mids[fut_valid]
        if side == "bid":
            as_h = (mf - fm) / tick_size   # positive = price fell further = adverse
        else:
            as_h = (fm - mf) / tick_size   # positive = price rose further = adverse

        n_h = len(as_h)
        out[h] = {
            "n":        n_h,
            "mean_as":  float(as_h.mean()),
            "std_as":   float(as_h.std()),
            "se_as":    float(as_h.std() / np.sqrt(n_h)),
            "net_pnl":  float(delta_ticks - as_h.mean()),
            "win_rate": float((as_h < delta_ticks).mean()),
            "p25_as":   float(np.percentile(as_h, 25)),
            "p75_as":   float(np.percentile(as_h, 75)),
        }
        out["_raw"][h] = as_h   # kept for cross-day pooled SE

    return out


def probe_day(trades, quotes, tick_size, horizons, delta_levels, quote_freq=0.5):
    """Run the probe simulation for both sides on one day."""
    if not trades or not quotes:
        return None

    q_ts   = np.array([q.timestamp for q in quotes], dtype=np.float64)
    q_mids = np.array([(q.best_bid + q.best_ask) / 2.0 for q in quotes],
                      dtype=np.float64)
    t_ts    = np.array([tr.timestamp for tr in trades], dtype=np.float64)
    t_price = np.array([tr.price     for tr in trades], dtype=np.float64)
    t_side  = np.array([tr.side      for tr in trades])

    day_results = {}
    for delta in delta_levels:
        bid_res = probe_one_side(t_ts, t_price, t_side, q_ts, q_mids,
                                 delta, tick_size, quote_freq, horizons, "bid")
        ask_res = probe_one_side(t_ts, t_price, t_side, q_ts, q_mids,
                                 delta, tick_size, quote_freq, horizons, "ask")
        day_results[float(delta)] = {"bid": bid_res, "ask": ask_res}

    return day_results


# ---------------------------------------------------------------------------
# Aggregate across days
# ---------------------------------------------------------------------------

def aggregate_days(all_day_results, horizons, delta_levels):
    """
    Pool bid + ask results across all days for each δ level.
    Uses raw per-fill AS observations (not replicated daily means) so that
    standard errors reflect actual observation-level variance.
    Returns: dict keyed by float(δ) → aggregate stats.
    """
    agg = {}
    for delta in delta_levels:
        d = float(delta)
        total_intervals = 0
        total_filled    = 0
        h_raw_as        = {h: [] for h in horizons}

        for day_res in all_day_results:
            if day_res is None or d not in day_res:
                continue
            for side_key in ("bid", "ask"):
                res = day_res[d][side_key]
                total_intervals += res["n_intervals"]
                total_filled    += res["n_filled"]
                for h in horizons:
                    raw = res.get("_raw", {}).get(h)
                    if raw is not None and len(raw) > 0:
                        h_raw_as[h].append(raw)

        fill_rate = total_filled / total_intervals if total_intervals > 0 else 0.0

        h_stats = {}
        for h in horizons:
            if not h_raw_as[h]:
                h_stats[h] = None
                continue
            vals = np.concatenate(h_raw_as[h])
            if len(vals) < 5:
                h_stats[h] = None
                continue
            mean_as = float(vals.mean())
            n_h     = len(vals)
            h_stats[h] = {
                "n":        n_h,
                "mean_as":  round(mean_as, 4),
                "se_as":    round(float(vals.std() / np.sqrt(n_h)), 4),
                "net_pnl":  round(float(d - mean_as), 4),
                "win_rate": round(float((vals < d).mean()), 4),
                "p25_as":   round(float(np.percentile(vals, 25)), 4),
                "p75_as":   round(float(np.percentile(vals, 75)), 4),
            }

        agg[d] = {
            "delta_ticks":    d,
            "fill_rate":      round(fill_rate, 6),
            "n_filled_total": total_filled,
            "by_horizon":     h_stats,
        }

    return agg


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _xy(agg, horizons, key, h=None):
    """Extract (xs, ys, ses) arrays from aggregate dict."""
    xs, ys, ses = [], [], []
    for d, stats in sorted(agg.items()):
        if h is not None:
            hr = stats["by_horizon"].get(h)
            if hr is None:
                continue
            xs.append(d)
            ys.append(hr.get(key, 0))
            ses.append(hr.get("se_as", 0))
        else:
            xs.append(d)
            ys.append(stats.get(key, 0))
    return np.array(xs), np.array(ys), np.array(ses)


def fig1_as_vs_delta(agg, horizons, out_path):
    fig, ax = plt.subplots(figsize=(10, 5))
    for h in horizons:
        xs, ys, ses = _xy(agg, horizons, "mean_as", h)
        c = _horizon_color(h, horizons)
        ax.fill_between(xs, ys - ses, ys + ses, alpha=0.15, color=c)
        ax.plot(xs, ys, "o-", color=c, lw=1.8, ms=5,
                label=f"h = {_horizon_label(h)}")
    # Reference line: AS = δ (zero net PnL)
    ref_x = np.array([min(agg), max(agg)])
    ax.plot(ref_x, ref_x, "--", color="#888", lw=1.2, label="AS = δ (breakeven)")
    ax.axhline(0, color="k", lw=0.5, ls=":")
    ax.set_xscale("log")
    ax.set_xlabel("Quote distance δ  (ticks from mid)", fontsize=11)
    ax.set_ylabel("E[Adverse selection | δ]  (ticks)", fontsize=11)
    ax.set_title("Adverse Selection vs. Spread Distance\n"
                 "Probe simulation — first fill per 0.5 s interval, bid + ask pooled",
                 fontsize=11)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.grid(True, which="both", ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def fig2_net_pnl(agg, horizons, out_path):
    fig, ax = plt.subplots(figsize=(10, 5))
    for h in horizons:
        xs, ys, ses = _xy(agg, horizons, "net_pnl", h)
        c = _horizon_color(h, horizons)
        ax.fill_between(xs, ys - ses, ys + ses, alpha=0.15, color=c)
        ax.plot(xs, ys, "o-", color=c, lw=1.8, ms=5,
                label=f"h = {_horizon_label(h)}")
    ax.axhline(0, color="k", lw=1.0, ls="--", label="Breakeven")
    ax.set_xscale("log")
    ax.set_xlabel("Quote distance δ  (ticks from mid)", fontsize=11)
    ax.set_ylabel("Net PnL per fill  (ticks)", fontsize=11)
    ax.set_title("Net Expected PnL per Fill  =  δ  −  E[AS | δ]\n"
                 "Positive = profitable after marking inventory to market",
                 fontsize=11)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.grid(True, which="both", ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def fig3_fill_rate(agg, out_path):
    xs, ys, _ = _xy(agg, [], "fill_rate")
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(xs, ys * 100, "o-", color="#9C27B0", lw=1.8, ms=5)
    ax.set_xscale("log")
    ax.set_xlabel("Quote distance δ  (ticks from mid)", fontsize=11)
    ax.set_ylabel("Fill rate  (% of intervals)", fontsize=11)
    ax.set_title("Empirical Fill Rate vs. Spread Distance\n"
                 "Each interval = 0.5 s; fill = at least one trade reached our level",
                 fontsize=11)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.grid(True, which="both", ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def fig4_pnl_envelope(agg, horizons, out_path):
    """fill_rate × net_pnl — shows the δ that maximises PnL per unit time."""
    fig, ax = plt.subplots(figsize=(10, 5))
    fr_xs, fr_ys, _ = _xy(agg, [], "fill_rate")
    fill_rate_map = dict(zip(fr_xs.tolist(), fr_ys.tolist()))

    for h in horizons:
        xs, nets, ses = _xy(agg, horizons, "net_pnl", h)
        if len(xs) == 0:
            continue
        frs = np.array([fill_rate_map.get(x, 0) for x in xs])
        envelope = frs * nets
        se_env   = frs * ses
        c = _horizon_color(h, horizons)
        ax.fill_between(xs, envelope - se_env, envelope + se_env, alpha=0.15, color=c)
        ax.plot(xs, envelope, "o-", color=c, lw=1.8, ms=5,
                label=f"h = {_horizon_label(h)}")

    ax.axhline(0, color="k", lw=1.0, ls="--")
    ax.set_xscale("log")
    ax.set_xlabel("Quote distance δ  (ticks from mid)", fontsize=11)
    ax.set_ylabel("fill_rate(δ) × net_pnl(δ)  [ticks / interval]", fontsize=11)
    ax.set_title("PnL Envelope  =  Fill Rate  ×  Net PnL per Fill\n"
                 "Peak = δ* that maximises expected PnL per unit time",
                 fontsize=11)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.grid(True, which="both", ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


def fig5_win_rate(agg, horizons, out_path):
    fig, ax = plt.subplots(figsize=(10, 4))
    for h in horizons:
        xs, ys, _ = _xy(agg, horizons, "win_rate", h)
        ax.plot(xs, ys * 100, "o-", color=_horizon_color(h, horizons),
                lw=1.8, ms=5, label=f"h = {_horizon_label(h)}")
    ax.axhline(50, color="#888", ls="--", lw=1.0, label="50%")
    ax.set_xscale("log")
    ax.set_ylim(0, 100)
    ax.set_xlabel("Quote distance δ  (ticks from mid)", fontsize=11)
    ax.set_ylabel("Fills where net PnL > 0  (%)", fontsize=11)
    ax.set_title("Per-Fill Win Rate  (AS < δ)\nBTC/USDT", fontsize=11)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter())
    ax.grid(True, which="both", ls=":", alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def compute_summary(agg, horizons, n_days):
    out = {"n_days": n_days, "by_horizon": {}}
    for h in horizons:
        xs, nets, _ = _xy(agg, horizons, "net_pnl", h)
        fr_xs, frs, _ = _xy(agg, [], "fill_rate")
        frs_map = dict(zip(fr_xs.tolist(), frs.tolist()))

        envelopes = np.array([frs_map.get(x, 0) * n for x, n in zip(xs, nets)])

        best_idx  = int(np.argmax(envelopes)) if len(envelopes) else -1
        best_delta = float(xs[best_idx]) if best_idx >= 0 else None

        # Breakeven: first δ where net_pnl < 0
        breakeven = None
        for i in range(len(nets) - 1):
            if nets[i] >= 0 and nets[i+1] < 0:
                frac = nets[i] / (nets[i] - nets[i+1])
                breakeven = float(xs[i] + frac * (xs[i+1] - xs[i]))
                break

        at_touch = agg.get(0.5, {}).get("by_horizon", {}).get(h) or \
                   agg.get(1.0, {}).get("by_horizon", {}).get(h)

        out["by_horizon"][str(h)] = {
            "delta_star_ticks":         round(best_delta, 1) if best_delta else None,
            "breakeven_delta_ticks":    round(breakeven, 1) if breakeven else None,
            "at_touch_mean_as_ticks":   round(at_touch["mean_as"], 3) if at_touch else None,
            "at_touch_net_pnl_ticks":   round(at_touch["net_pnl"], 3) if at_touch else None,
        }

    # Fill rates
    out["fill_rates"] = {
        str(d): round(stats["fill_rate"] * 100, 2)
        for d, stats in sorted(agg.items())
    }
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",  required=True)
    parser.add_argument("--start",   default=None)
    parser.add_argument("--end",     default=None)
    parser.add_argument("--symbol",  default=None)
    parser.add_argument("--quote_freq", type=float, default=None)
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    data_dir   = Path(cfg["data_dir"])
    symbol     = args.symbol or cfg.get("symbol", "BTC")
    tick_size  = float(cfg.get("tick_size", 0.01))
    horizons   = [int(h) for h in cfg.get("horizons", [1, 5, 30])]
    quote_freq = args.quote_freq or float(cfg.get("quote_freq", 0.5))
    out_dir    = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(args.start or cfg["start"])
    end   = date.fromisoformat(args.end   or cfg["end"])

    print(f"Adverse Selection Decomposition — {symbol}")
    print(f"Period: {start} → {end}   tick_size: ${tick_size}   "
          f"quote_freq: {quote_freq}s")
    print(f"δ levels: {DELTA_LEVELS.tolist()}")
    print(f"Horizons: {horizons} s")
    print(f"Output: {out_dir}\n")

    loader = DataLoader()
    all_day_results = []
    n_days = 0

    current = start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        current += timedelta(days=1)

        t_path = data_dir / f"trades_{symbol}_{ds}.parquet"
        q_path = data_dir / f"quotes_{symbol}_{ds}.parquet"
        if not t_path.exists() or not q_path.exists():
            continue

        trades, quotes = loader.load_coinapi(str(t_path), str(q_path))
        if len(trades) < 100 or len(quotes) < 100:
            continue

        day_res = probe_day(trades, quotes, tick_size, horizons,
                            DELTA_LEVELS, quote_freq=quote_freq)
        all_day_results.append(day_res)
        n_days += 1

        # Quick daily summary at a few key levels
        if day_res:
            line_parts = []
            for d in [0.5, 5.0, 50.0]:
                r = day_res.get(float(d), {})
                bid_fr = r.get("bid", {}).get("fill_rate", 0)
                ask_fr = r.get("ask", {}).get("fill_rate", 0)
                fr = (bid_fr + ask_fr) / 2
                line_parts.append(f"δ={d:.0f}:{fr*100:.1f}%")
            print(f"  {ds}  fill rates: {' | '.join(line_parts)}")

    print(f"\nAggregating {n_days} days...")
    agg = aggregate_days(all_day_results, horizons, DELTA_LEVELS)

    # Print full table
    print(f"\n{'δ (ticks)':>10}  {'fill%':>7}", end="")
    for h in horizons:
        print(f"  E[AS|{h:2d}s]  Net({h:2d}s)  Win%", end="")
    print()
    print("-" * (20 + 30 * len(horizons)))

    for d in DELTA_LEVELS:
        stats = agg.get(float(d))
        if stats is None:
            continue
        print(f"  {d:>8.1f}  {stats['fill_rate']*100:>6.2f}%", end="")
        for h in horizons:
            hr = stats["by_horizon"].get(h)
            if hr:
                print(f"  {hr['mean_as']:>8.3f}  {hr['net_pnl']:>7.3f}  "
                      f"{hr['win_rate']*100:>4.1f}%", end="")
            else:
                print(f"  {'—':>8}  {'—':>7}  {'—':>5}", end="")
        print()

    # Figures
    print(f"\nGenerating figures...")
    fig1_as_vs_delta(agg, horizons, str(out_dir / "fig1_as_vs_delta.png"))
    fig2_net_pnl(agg, horizons, str(out_dir / "fig2_net_pnl_vs_delta.png"))
    fig3_fill_rate(agg, str(out_dir / "fig3_fill_rate.png"))
    fig4_pnl_envelope(agg, horizons, str(out_dir / "fig4_pnl_envelope.png"))
    fig5_win_rate(agg, horizons, str(out_dir / "fig5_win_rate.png"))

    # Summary
    summary = compute_summary(agg, horizons, n_days)
    spath = out_dir / "summary.json"
    with open(spath, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*65}")
    print(f"  Key Findings  ({n_days} days, quote_freq={quote_freq}s)")
    print(f"{'='*65}")
    for h in horizons:
        s = summary["by_horizon"].get(str(h), {})
        print(f"  h={h:2d}s  δ*={str(s.get('delta_star_ticks','?')):>6} ticks  "
              f"breakeven={str(s.get('breakeven_delta_ticks','none')):>6}  "
              f"at-touch net={str(s.get('at_touch_net_pnl_ticks','?')):>7}")
    print(f"\n  Fill rates:")
    for d_str, fr in summary["fill_rates"].items():
        print(f"    δ={float(d_str):>6.1f} ticks → {fr:.2f}%")
    print(f"{'='*65}")
    print(f"  Summary: {spath}")


if __name__ == "__main__":
    main()
