import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def load_views(folder: str, pattern: str = "*_view.parquet") -> pd.DataFrame:
    """
    Load all _view.parquet files from a folder and concatenate them.
    PnL is adjusted so each day continues from where the previous ended.
    Usage:
        df = load_views("results/")
        plot_backtest_stacked(df, view_rule="1min")
    """
    import glob
    import os
    
    paths = sorted(glob.glob(os.path.join(folder, pattern)))
    #paths=[paths[0],paths[1],paths[2],paths[3], paths[4], paths[5],paths[6]]
    paths=[paths[8]]
    if not paths:
        raise ValueError(f"No view parquets found in {folder}")
    
    dfs = []
    pnl_offset = 0.0
    
    for path in paths:
        df = load_view(path)
        if "pnl" in df.columns:
            df["pnl"] = df["pnl"] + pnl_offset
            pnl_offset = float(df["pnl"].iloc[-1])
        dfs.append(df)
    
    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    
    print(f"Loaded {len(paths)} days: {combined.index[0].date()} to {combined.index[-1].date()}")
    print(f"Total rows: {len(combined):,}")
    print(f"Cumulative PnL: {pnl_offset:.2f}")
    
    return combined
def load_view(path: str) -> pd.DataFrame:
    """
    Load a _view.parquet snapshot and return it with a DatetimeIndex.
    Usage:
        df = load_view("results/2025-05-13_view.parquet")
        plot_backtest_stacked(df)
    """
    df = pd.read_parquet(path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"Cannot build DatetimeIndex from {path}")
    return df.sort_index()

def plot_backtest(
    df: pd.DataFrame,
    price_col: str = "close",
    pnl_col: str = "pnl",
    inv_col: str = "inv",
    view_rule: str = "1s",
    title: str = "Backtest Viewer",
):
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex")

    cols = [c for c in [price_col, pnl_col, inv_col] if c in df.columns]
    view = df[cols].sort_index()

    if view_rule:
        view = view.resample(view_rule).last()

    view = view.dropna(how="all")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if price_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[price_col], name="Price", mode="lines"),
            secondary_y=False,
        )

    if pnl_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[pnl_col], name="PnL", mode="lines"),
            secondary_y=True,
        )

    if inv_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[inv_col], name="Inventory", mode="lines"),
            secondary_y=True,
        )

    fig.update_layout(
        title=f"{title} (view={view_rule})",
        height=600,
        xaxis=dict(rangeslider=dict(visible=True), type="date"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    

    # ---------- Toggle buttons (with axis re-mapping) ----------
    names = [t.name for t in fig.data]
    def _vis(*wanted): 
        return [n in wanted for n in names]

    def _axis_layout(left_title: str, right_title: str, show_right: bool = True):
        return {
            "yaxis": {"title": left_title, "side": "left"},
            "yaxis2": {"title": right_title, "side": "right", "overlaying": "y", "showgrid": False, "visible": show_right},
        }

    fig.update_layout(
        updatemenus=[
            dict(
                type="buttons",
                direction="right",
                x=0.0,
                y=1.18,
                buttons=[
                    # Price + PnL: Price left, PnL right
                    dict(
                        label="Price + PnL",
                        method="update",
                        args=[
                            {"visible": _vis("Price", "PnL")},
                            _axis_layout("Price", "PnL", True),
                        ],
                    ),
                    # Price + Inventory: Price left, Inventory right
                    dict(
                        label="Price + Inventory",
                        method="update",
                        args=[
                            {"visible": _vis("Price", "Inventory")},
                            _axis_layout("Price", "Inventory", True),
                        ],
                    ),
                    # PnL + Inventory: Inventory left, PnL right  ✅
                    dict(
                        label="PnL + Inventory",
                        method="update",
                        args=[
                            {"visible": _vis("PnL", "Inventory")},
                            _axis_layout("Inventory", "PnL", True),
                        ],
                    ),
                    # Inventory only: Inventory left, hide right axis ✅
                    dict(
                        label="Inventory only",
                        method="update",
                        args=[
                            {"visible": _vis("Inventory")},
                            _axis_layout("Inventory", "", False),
                        ],
                    ),
                    # PnL only: PnL left, hide right axis
                    dict(
                        label="PnL only",
                        method="update",
                        args=[
                            {"visible": _vis("PnL")},
                            _axis_layout("PnL", "", False),
                        ],
                    ),
                    # All: Price left, PnL+Inv right (still ok)
                    dict(
                        label="All",
                        method="update",
                        args=[
                            {"visible": _vis("Price", "PnL", "Inventory")},
                            _axis_layout("Price", "PnL / Inventory", True),
                        ],
                    ),
                ],
            )
        ]
    )
    fig.update_layout(**_axis_layout("Price", "PnL / Inventory", True))
    fig.show()

def plot_backtest_stacked(
    df: pd.DataFrame,
    price_col: str = "close",
    pnl_col: str = "pnl",
    inv_col: str = "inv",
    view_rule: str = "1s",
    title: str = "Backtest Viewer (Stacked)",
    height: int = 800,
):
    """
    Stacked interactive viewer:
      Row 1: Price
      Row 2: PnL
      Row 3: Inventory

    view_rule examples: "1s", "5s", "10s"
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex")

    cols = [c for c in [price_col, pnl_col, inv_col] if c in df.columns]
    view = df[cols].sort_index()

    # Downsample for display performance
    if view_rule:
        view = view.resample(view_rule).last()

    view = view.dropna(how="all")

    # Build stacked subplots with shared x
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.45, 0.35, 0.20],
        subplot_titles=("Price", "PnL", "Inventory"),
    )

    # Add traces (one per panel)
    trace_names = []

    if price_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[price_col], mode="lines", name="Price"),
            row=1, col=1
        )
        trace_names.append("Vol")

    if pnl_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[pnl_col], mode="lines", name="PnL"),
            row=2, col=1
        )
        trace_names.append("PnL")

    if inv_col in view.columns:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[inv_col], mode="lines", name="Inventory"),
            row=3, col=1
        )
        trace_names.append("Inventory")

    # Axes labels
    fig.update_yaxes(title_text="vol", row=1, col=1)
    fig.update_yaxes(title_text="PnL", row=2, col=1)
    fig.update_yaxes(title_text="Inv", row=3, col=1)

    # Range slider on the bottom x-axis only
    fig.update_layout(
        title=f"{title} (view={view_rule})",
        height=height,
        xaxis3=dict(rangeslider=dict(visible=True), type="date"),  # bottom subplot x-axis
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Button helpers: toggle trace visibility (3 traces max)
    names = [t.name for t in fig.data]
    def _vis(*wanted):
        return [n in wanted for n in names]

    fig.update_layout(
        updatemenus=[
            dict(
                type="buttons",
                direction="right",
                x=0.0,
                y=1.15,
                buttons=[
                    dict(label="Price + PnL", method="update", args=[{"visible": _vis("Price", "PnL")}]),
                    dict(label="Price + Inventory", method="update", args=[{"visible": _vis("Price", "Inventory")}]),
                    dict(label="PnL + Inventory", method="update", args=[{"visible": _vis("PnL", "Inventory")}]),
                    dict(label="Inventory only", method="update", args=[{"visible": _vis("Inventory")}]),
                    dict(label="PnL only", method="update", args=[{"visible": _vis("PnL")}]),
                    dict(label="All", method="update", args=[{"visible": _vis("Price", "PnL", "Inventory")}]),
                ],
            )
        ]
    )

    fig.show()

def plot_backtest_grid_2x2(
    df: pd.DataFrame,
    price_col: str = "close",
    pnl_col: str = "pnl",
    inv_col: str = "inv",
    vol_col: str = "sigma_gk_ann",
    vol_thr_off_col: str = "vol_gate_thr_off",
    vol_thr_on_col: str = "vol_gate_thr_on",
    gate_col: str = "vol_gate",
    view_rule: str | None = None,
    title: str = "Backtest Viewer",
    height: int = 750,
    shade_gate: bool = True,
):
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex")

    cols = [
        c for c in [
            price_col, pnl_col, inv_col,
            vol_col, vol_thr_off_col, vol_thr_on_col,
            gate_col
        ] if c in df.columns
    ]
    view = df[cols].sort_index()
    if view_rule:
        view = view.resample(view_rule).last()

    view = view.dropna(how="all")
    
    fig = make_subplots(
        rows=2,
        cols=2,
        shared_xaxes=True,
        vertical_spacing=0.08,
        horizontal_spacing=0.08,
        subplot_titles=("Price", "Volatility", "PnL", "Inventory"),
    )

    # --- Price ---
    if price_col in view:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[price_col], mode="lines", name="Price"),
            row=1, col=1
        )

    # --- Volatility ---
    if vol_col in view:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[vol_col], mode="lines", name="Vol"),
            row=1, col=2
        )
    if vol_thr_off_col in view:
        fig.add_trace(
            go.Scatter(
                x=view.index, y=view[vol_thr_off_col],
                mode="lines", line=dict(dash="dash"),
                name="Vol thr off"
            ),
            row=1, col=2
        )
    if vol_thr_on_col in view:
        fig.add_trace(
            go.Scatter(
                x=view.index, y=view[vol_thr_on_col],
                mode="lines", line=dict(dash="dash"),
                name="Vol thr on"
            ),
            row=1, col=2
        )

    # --- PnL ---
    if pnl_col in view:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[pnl_col], mode="lines", name="PnL"),
            row=2, col=1
        )

    # --- Inventory ---
    if inv_col in view:
        fig.add_trace(
            go.Scatter(x=view.index, y=view[inv_col], mode="lines", name="Inventory"),
            row=2, col=2
        )

    # Axis labels
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=1, col=2)
    fig.update_yaxes(title_text="PnL", row=2, col=1)
    fig.update_yaxes(title_text="Inv", row=2, col=2)

    # Layout + shared range slider
    fig.update_layout(
        title=title,
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    fig.update_xaxes(matches="x")

    # Put the range slider on the bottom-left axis (xaxis3 in a 2x2)
    fig.update_layout(xaxis3=dict(rangeslider=dict(visible=True), type="date"))

    # Optional: hide the duplicated range sliders / tick labels on the top row
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, row=1, col=2)

    # --- Shade risk_off / vol_gate periods ---
    '''if shade_gate and gate_col in view:
        g = view[gate_col].fillna(False).astype(bool)
        starts = view.index[g & ~g.shift(1, fill_value=False)]
        ends = view.index[(~g) & g.shift(1, fill_value=False)]

        if len(starts) and len(ends) < len(starts):
            ends = ends.append(pd.Index([view.index[-1]]))

        for s, e in zip(starts, ends):
            fig.add_vrect(
                x0=s, x1=e,
                fillcolor="gray",
                opacity=0.15,
                line_width=0,
                layer="below"
            )'''

    fig.show()