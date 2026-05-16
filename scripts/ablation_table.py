"""
Multi-day ablation table for thesis.
Reads summary CSVs from the three experiment directories and prints
a clean comparison across all available days plus aggregate stats.

Usage:
    python scripts/ablation_table.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from pathlib import Path


EXPERIMENTS = [
    ("A-S",              "experiments/01_baseline_pure_as/results"),
    ("ShiftedGLFT",      "experiments/08_shifted_glft/results"),
    ("ShiftedGLFT+Regime","experiments/09_shifted_glft_regime/results"),
]


def load(result_dir: str) -> pd.DataFrame:
    """Load results from per-day JSON files — robust to CSV schema drift."""
    import json
    rows = []
    for p in sorted(Path(result_dir).glob("*_metrics.json")):
        try:
            m = json.loads(p.read_text())
            if m.get("status") == "ok":
                rows.append(m)
        except Exception:
            pass
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # Keep only the latest result per date (in case of duplicate runs)
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
    return df.set_index("date")


def aggregate(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    pnl = df["total_pnl"]
    return {
        "n_days":       len(df),
        "profitable":   (pnl > 0).sum(),
        "total_pnl":    pnl.sum(),
        "mean_pnl":     pnl.mean(),
        "std_pnl":      pnl.std(),
        "daily_sharpe": pnl.mean() / pnl.std() if pnl.std() > 0 else 0,
        "max_dd":       df["max_drawdown"].min(),
        "total_fills":  df["total_fills"].sum(),
        "fill_rate":    df["fill_rate"].mean(),
        "avg_spread":   df["avg_spread_bps"].mean(),
        "hyst_rate":    df.get("hysteresis_skip_rate", pd.Series([0]*len(df))).mean(),
    }


def main():
    dfs = {name: load(d) for name, d in EXPERIMENTS}

    # ── Per-day PnL table ─────────────────────────────────────────────────────
    all_dates = sorted(set(
        date for df in dfs.values() if not df.empty for date in df.index
    ))

    print("\n=== Daily PnL ===")
    header = f"{'Date':<12}" + "".join(f"{n:>20}" for n in dfs)
    print(header)
    print("-" * (12 + 20 * len(dfs)))
    for d in all_dates:
        row = f"{str(d):<12}"
        for name, df in dfs.items():
            if d in df.index:
                row += f"{df.loc[d,'total_pnl']:>20.2f}"
            else:
                row += f"{'—':>20}"
        print(row)

    # ── Aggregate comparison ───────────────────────────────────────────────────
    aggs = {name: aggregate(df) for name, df in dfs.items()}

    print("\n=== Aggregate (10-day) ===")
    metrics = [
        ("Days run",        "n_days",       "{:.0f}"),
        ("Profitable days", "profitable",   "{:.0f}"),
        ("Total PnL ($)",   "total_pnl",    "{:.2f}"),
        ("Mean daily PnL",  "mean_pnl",     "{:.2f}"),
        ("Std daily PnL",   "std_pnl",      "{:.2f}"),
        ("Daily Sharpe",    "daily_sharpe", "{:.3f}"),
        ("Max drawdown ($)","max_dd",        "{:.2f}"),
        ("Total fills",     "total_fills",  "{:,.0f}"),
        ("Avg fill rate",   "fill_rate",    "{:.1%}"),
        ("Avg spread (bps)","avg_spread",   "{:.2f}"),
        ("Hysteresis skip", "hyst_rate",    "{:.1%}"),
    ]

    col_w = 22
    print(f"{'Metric':<24}" + "".join(f"{n:>{col_w}}" for n in dfs))
    print("-" * (24 + col_w * len(dfs)))
    for label, key, fmt in metrics:
        row = f"{label:<24}"
        for name, a in aggs.items():
            if key in a:
                row += f"{fmt.format(a[key]):>{col_w}}"
            else:
                row += f"{'—':>{col_w}}"
        print(row)

    # ── Regime filter: % of day quoting ───────────────────────────────────────
    regime_df = dfs.get("ShiftedGLFT+Regime")
    base_df   = dfs.get("ShiftedGLFT")
    if regime_df is not None and base_df is not None and not regime_df.empty:
        print("\n=== Regime filter activity ===")
        print(f"{'Date':<12} {'Regime fills':>14} {'Base fills':>12} {'Fill reduction':>16}")
        print("-" * 58)
        for d in all_dates:
            rf = regime_df.loc[d, "total_fills"] if d in regime_df.index else None
            bf = base_df.loc[d, "total_fills"]   if d in base_df.index   else None
            if rf is not None and bf is not None and bf > 0:
                red = 1 - rf / bf
                print(f"{str(d):<12} {rf:>14,.0f} {bf:>12,.0f} {red:>16.1%}")


if __name__ == "__main__":
    main()
