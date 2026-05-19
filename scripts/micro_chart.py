"""
Interactive micro-level chart — inventory and PnL at raw quote-event resolution.
Outputs a self-contained HTML file viewable in any browser.

Features:
- Click legend entries to toggle any trace on/off
- Zoom/pan all panels together (shared x-axis)
- Hover for exact values at any point
- Compare multiple days by passing multiple --parquet paths

Usage (from master2/):
    # Single day, full session
    python scripts/micro_chart.py \\
        --parquet experiments/40_link_apr2026_baseline/results/2026-04-17_view.parquet \\
        --out experiments/40_link_apr2026_baseline/analysis/micro_apr17.html

    # Single day, specific window
    python scripts/micro_chart.py \\
        --parquet experiments/40_link_apr2026_baseline/results/2026-04-17_view.parquet \\
        --start 10:00 --end 12:00 \\
        --out experiments/40_link_apr2026_baseline/analysis/micro_apr17_10h.html

    # Compare two days
    python scripts/micro_chart.py \\
        --parquet experiments/40_link_apr2026_baseline/results/2026-04-17_view.parquet \\
                  experiments/40_link_apr2026_baseline/results/2026-04-10_view.parquet \\
        --out experiments/40_link_apr2026_baseline/analysis/micro_compare.html
"""

import argparse
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path


COLORS = ["#1565C0", "#E65100", "#2E7D32", "#6A1B9A", "#B71C1C", "#00838F"]


def load(parquet_path, start_time=None, end_time=None, resample_s=1):
    v = pd.read_parquet(parquet_path)
    v.index = pd.to_datetime(v.index)
    if start_time and end_time:
        v = v.between_time(start_time, end_time)
    if resample_s and resample_s > 0:
        rule = f"{resample_s}s"
        v = v.resample(rule).agg({
            "pnl":       "last",
            "inv":       "mean",
            "close":     "last",
            "spread_bps":"mean",
        }).dropna(how="all")
    # Mark gaps > 10s as NaN so lines break
    diffs = v.index.to_series().diff().dt.total_seconds()
    for col in ["pnl", "inv", "close", "spread_bps"]:
        if col in v.columns:
            v.loc[diffs > 10, col] = np.nan
    return v


def load_metrics(parquet_path):
    p = Path(parquet_path)
    date_str = p.stem.replace("_view", "")
    m_path = p.parent / f"{date_str}_metrics.json"
    if m_path.exists():
        with open(m_path) as f:
            return json.load(f)
    return {}


def build_figure(parquet_paths, start_time=None, end_time=None, resample_s=1):
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=["Running PnL (USD)", "Inventory (LINK)",
                        "Mid Price (USD)", "Quoted Half-Spread (bps)"],
        row_heights=[0.28, 0.28, 0.22, 0.22],
    )

    for i, path in enumerate(parquet_paths):
        color = COLORS[i % len(COLORS)]
        date_str = Path(path).stem.replace("_view", "")
        meta = load_metrics(path)

        label = (
            f"{date_str}  "
            f"PnL={meta.get('total_pnl', 0):+.0f}$  "
            f"fills={meta.get('total_fills', 0):,}  "
            f"mkout={meta.get('avg_markout_bps', 0):+.2f}bps"
        )

        v = load(path, start_time, end_time, resample_s)
        t = v.index

        show_legend = True

        # PnL
        fig.add_trace(go.Scatter(
            x=t, y=v["pnl"], name=label, legendgroup=date_str,
            line=dict(color=color, width=1.2),
            showlegend=show_legend, hovertemplate="%{y:.3f} USD<extra></extra>",
        ), row=1, col=1)

        # Inventory
        fig.add_trace(go.Scatter(
            x=t, y=v["inv"], name=label, legendgroup=date_str,
            line=dict(color=color, width=1.0),
            showlegend=False, hovertemplate="%{y:.1f} LINK<extra></extra>",
            fill="tozeroy", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
        ), row=2, col=1)

        # Mid price
        fig.add_trace(go.Scatter(
            x=t, y=v["close"], name=label, legendgroup=date_str,
            line=dict(color=color, width=1.0),
            showlegend=False, hovertemplate="%{y:.4f} USD<extra></extra>",
        ), row=3, col=1)

        # Spread
        fig.add_trace(go.Scatter(
            x=t, y=v["spread_bps"], name=label, legendgroup=date_str,
            line=dict(color=color, width=0.8),
            showlegend=False, hovertemplate="%{y:.2f} bps<extra></extra>",
        ), row=4, col=1)

    # Reference lines
    fig.add_hline(y=0, line_width=0.8, line_color="black", row=1, col=1)
    fig.add_hline(y=0, line_width=0.8, line_color="black", row=2, col=1)
    fig.add_hline(y=38,  line_width=0.8, line_dash="dash", line_color="gray",
                  annotation_text="max_inv", annotation_position="right", row=2, col=1)
    fig.add_hline(y=-38, line_width=0.8, line_dash="dash", line_color="gray", row=2, col=1)
    fig.add_hline(y=6.44, line_width=0.8, line_dash="dash", line_color="gray",
                  annotation_text="floor", annotation_position="right", row=4, col=1)

    window_str = f" | {start_time}–{end_time} UTC" if start_time else " | full session"
    res_str    = f"{resample_s}s bins" if resample_s > 0 else "raw"
    title = f"LINK micro view{window_str}  ({res_str})"

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=900,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        margin=dict(l=60, r=40, t=80, b=40),
        template="plotly_white",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#eeeeee")
    fig.update_yaxes(showgrid=True, gridcolor="#eeeeee")

    return fig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", nargs="+", required=True)
    ap.add_argument("--out",     required=True)
    ap.add_argument("--start",   default=None, help="HH:MM window start (UTC)")
    ap.add_argument("--end",     default=None, help="HH:MM window end (UTC)")
    ap.add_argument("--resample", type=int, default=1,
                    help="Resample to N seconds (default 1; 0 = raw)")
    args = ap.parse_args()

    fig = build_figure(args.parquet, args.start, args.end, args.resample)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out), include_plotlyjs="cdn")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
