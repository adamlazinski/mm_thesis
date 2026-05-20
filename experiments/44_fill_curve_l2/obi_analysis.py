"""
Experiment 44b: OBI Predictive Power Analysis

Questions:
  1. Does OBI (L1/L3/L5/L10) predict the direction of future price moves?
     → Correlation and Spearman IC at horizons 0.5s to 120s
  2. Does the signal decay or strengthen with horizon?
  3. Does OBI predict fill quality (markout)?
     → Compare adverse fill rate for fills preceded by high vs low OBI
  4. L1 vs L3 vs L5 vs L10 — which level gives the strongest signal?
  5. Nonlinearity: extreme OBI vs neutral OBI

Run from master2/:
    python experiments/44_fill_curve_l2/obi_analysis.py
"""

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr, pearsonr

DATA_DIR     = Path("data/real")
OUT_DIR      = Path("experiments/44_fill_curve_l2/results")
ANALYSIS_DIR = Path("experiments/44_fill_curve_l2/analysis")
TICK         = 0.001
HORIZONS     = [0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
SAMPLE_EVERY = 5   # seconds between samples
OBI_LEVELS   = ["obi_l1", "obi_l3", "obi_l5", "obi_l10"]


# ── Data loading ───────────────────────────────────────────────────────────────

def load_day_ob(date_str):
    path = DATA_DIR / f"orderbooks_LINK_{date_str}.parquet"
    if not path.exists():
        return None
    ob = pd.read_parquet(path)
    ob["ts"]  = pd.to_datetime(ob["time_exchange"]).astype("int64") / 1e9

    def _d(col, n):
        return ob[col].apply(lambda x: sum(l["size"] for l in list(x)[:n]))

    for n, suffix in [(1,"l1"),(3,"l3"),(5,"l5"),(10,"l10")]:
        b = _d("bids", n); a = _d("asks", n)
        ob[f"obi_{suffix}"] = (b - a) / (b + a + 1e-9)

    ob["mid"] = (ob["bids"].apply(lambda x: list(x)[0]["price"]) +
                 ob["asks"].apply(lambda x: list(x)[0]["price"])) / 2
    return ob.sort_values("ts").reset_index(drop=True)


def load_day_trades(date_str):
    path = DATA_DIR / f"trades_LINK_{date_str}.parquet"
    if not path.exists():
        return None
    tr = pd.read_parquet(path)
    tr["ts"] = pd.to_datetime(tr["time_exchange"]).astype("int64") / 1e9
    return tr.sort_values("ts").reset_index(drop=True)


# ── Predictive power ───────────────────────────────────────────────────────────

def compute_predictive_power(ob, horizon_list=HORIZONS, sample_every=SAMPLE_EVERY):
    """
    For each snapshot sampled every `sample_every` seconds, compute:
      - Return from t to t + horizon (in bps)
      - OBI at L1, L3, L5, L10 at time t

    Returns DataFrame with columns: ts, obi_l1..l10, ret_0.5..120
    """
    ts  = ob["ts"].values
    mid = ob["mid"].values

    records = []
    i = 0
    while i < len(ts):
        t0 = ts[i]
        row = {"ts": t0}
        for lvl in OBI_LEVELS:
            row[lvl] = float(ob[lvl].iloc[i])

        valid = True
        for h in horizon_list:
            idx = np.searchsorted(ts, t0 + h, side="right") - 1
            if idx <= i or idx >= len(ts):
                valid = False
                break
            row[f"ret_{h}"] = (mid[idx] - mid[i]) / mid[i] * 10000  # bps

        if valid:
            records.append(row)

        # Advance by sample_every seconds
        next_t = t0 + sample_every
        i = np.searchsorted(ts, next_t, side="left")

    return pd.DataFrame(records)


def ic_table(df, horizons=HORIZONS):
    """Compute Pearson corr and Spearman IC for each OBI level × horizon."""
    results = []
    ret_cols = [f"ret_{h}" for h in horizons if f"ret_{h}" in df.columns]
    for lvl in OBI_LEVELS:
        for rc in ret_cols:
            h = float(rc.replace("ret_", ""))
            x = df[lvl].values
            y = df[rc].values
            mask = ~np.isnan(x) & ~np.isnan(y) & (y != 0)  # exclude zero returns
            if mask.sum() < 30:
                continue
            corr, _  = pearsonr(x[mask], y[mask])
            ic,   _  = spearmanr(x[mask], y[mask])
            # Hit rate: sign(OBI) == sign(return) on non-zero returns
            nz = mask & (x != 0)
            hit = float(np.mean(np.sign(x[nz]) == np.sign(y[nz]))) if nz.sum() > 0 else np.nan
            results.append({"level": lvl, "horizon": h,
                             "pearson": corr, "ic": ic, "hit_rate": hit,
                             "n": int(mask.sum())})
    return pd.DataFrame(results)


# ── Fill quality conditioned on OBI ───────────────────────────────────────────

def fill_quality_by_obi(ob, tr, markout_horizon=1.0, n_quantiles=5):
    """
    For each trade at the natural bid/ask, look up OBI from the most recent
    snapshot and compute 1s markout. Returns markout statistics by OBI quantile.
    """
    ts_ob  = ob["ts"].values
    ts_tr  = tr["ts"].values
    obi_ob = ob["obi_l1"].values
    mid_ob = ob["mid"].values

    records = []
    for i in range(len(tr)):
        t_fill = ts_tr[i]
        side   = tr["taker_side"].iloc[i]
        price  = float(tr["price"].iloc[i])

        # Most recent snapshot before this trade
        snap_idx = np.searchsorted(ts_ob, t_fill, side="left") - 1
        if snap_idx < 0:
            continue

        obi_at_fill = obi_ob[snap_idx]

        # Markout: mid 1s after fill vs fill price
        fut_idx = np.searchsorted(ts_ob, t_fill + markout_horizon, side="right") - 1
        if fut_idx <= snap_idx:
            continue

        fut_mid = mid_ob[fut_idx]
        if side == "SELL":   # market sell → we have a bid fill
            markout = (fut_mid - price) / price * 10000  # positive = good for us
        else:                # market buy → we have an ask fill
            markout = (price - fut_mid) / price * 10000

        records.append({"obi": obi_at_fill, "markout": markout, "side": side})

    df = pd.DataFrame(records)
    if len(df) < 50:
        return df, None

    df["obi_q"] = pd.qcut(df["obi"], n_quantiles, labels=False, duplicates="drop")
    summary = df.groupby("obi_q").agg(
        mean_markout=("markout", "mean"),
        pct_adverse=("markout", lambda x: (x < 0).mean()),
        n=("markout", "count"),
        obi_mean=("obi", "mean"),
    ).reset_index()
    return df, summary


# ── Main ───────────────────────────────────────────────────────────────────────

def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ob_files = sorted(glob.glob(str(DATA_DIR / "orderbooks_LINK_2026-04-*.parquet")))
    dates = [Path(f).stem.replace("orderbooks_LINK_", "") for f in ob_files]
    print(f"Running OBI analysis on {len(dates)} days")

    all_pred   = []
    all_fill   = []

    for date_str in dates:
        ob = load_day_ob(date_str)
        tr = load_day_trades(date_str)
        if ob is None or tr is None:
            continue
        print(f"  {date_str}: {len(ob):,} snapshots  {len(tr):,} trades", end=" ... ")

        pred = compute_predictive_power(ob)
        pred["date"] = date_str
        all_pred.append(pred)

        raw_fills, _ = fill_quality_by_obi(ob, tr)
        if len(raw_fills) > 0:
            raw_fills["date"] = date_str
            all_fill.append(raw_fills)

        ic = ic_table(pred)
        best = ic[ic.level == "obi_l1"].sort_values("ic", ascending=False).iloc[0]
        print(f"best IC={best['ic']:.3f} @ {best['horizon']:.0f}s")

    pred_all = pd.concat(all_pred, ignore_index=True)
    fill_all = pd.concat(all_fill, ignore_index=True) if all_fill else None

    # Aggregate IC table
    ic_agg = ic_table(pred_all)
    ic_pivot = ic_agg.pivot_table(index="level", columns="horizon",
                                   values="ic", aggfunc="mean")
    print("\n=== Spearman IC (OBI level × horizon) ===")
    print(ic_pivot.round(4).to_string())

    ic_agg.to_csv(OUT_DIR / "obi_ic_table.csv", index=False)

    # ── Figures ───────────────────────────────────────────────────────────────

    colors = {"obi_l1": "#1565C0", "obi_l3": "#E65100",
              "obi_l5": "#2E7D32", "obi_l10": "#6A1B9A"}
    labels = {"obi_l1": "OBI L1 (touch)", "obi_l3": "OBI L3",
              "obi_l5": "OBI L5", "obi_l10": "OBI L10"}

    # fig5: IC decay / growth curve
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("OBI Predictive Power — LINK Apr 2026 (30 days)", fontsize=13, fontweight="bold")

    for lvl in OBI_LEVELS:
        sub = ic_agg[ic_agg.level == lvl].sort_values("horizon")
        axes[0].plot(sub["horizon"], sub["ic"], "o-", color=colors[lvl],
                     lw=2, ms=7, label=labels[lvl])
        axes[0].plot(sub["horizon"], sub["pearson"], "--", color=colors[lvl],
                     lw=1.2, alpha=0.5)

    axes[0].axhline(0, color="k", lw=0.8)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("Horizon (seconds, log scale)")
    axes[0].set_ylabel("IC (Spearman, solid) / Pearson (dashed)")
    axes[0].set_title("Signal Strength vs Horizon\n[Does OBI predict price direction?]")
    axes[0].legend(fontsize=9); axes[0].grid(alpha=0.25)
    axes[0].set_xticks(HORIZONS)
    axes[0].set_xticklabels([str(h) for h in HORIZONS], fontsize=8)

    # Hit rate
    for lvl in OBI_LEVELS:
        sub = ic_agg[ic_agg.level == lvl].sort_values("horizon")
        axes[1].plot(sub["horizon"], sub["hit_rate"], "o-", color=colors[lvl],
                     lw=2, ms=7, label=labels[lvl])
    axes[1].axhline(0.5, color="k", lw=0.8, ls="--", label="Random (50%)")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Horizon (seconds, log scale)")
    axes[1].set_ylabel("Directional Hit Rate")
    axes[1].set_title("Hit Rate vs Horizon\n[P(sign(OBI) == sign(return))]")
    axes[1].legend(fontsize=9); axes[1].grid(alpha=0.25)
    axes[1].set_xticks(HORIZONS)
    axes[1].set_xticklabels([str(h) for h in HORIZONS], fontsize=8)

    plt.tight_layout()
    fig.savefig(ANALYSIS_DIR / "fig5_obi_ic.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("Saved fig5_obi_ic.png")

    # fig6: OBI quantile vs markout
    if fill_all is not None:
        fill_all["obi_q5"] = pd.qcut(fill_all["obi"], 5,
                                      labels=["Q1\n(strong sell)", "Q2", "Q3\n(neutral)",
                                              "Q4", "Q5\n(strong buy)"],
                                      duplicates="drop")
        summary = fill_all.groupby("obi_q5").agg(
            mean_markout=("markout", "mean"),
            pct_adverse=("markout", lambda x: (x < 0).mean()),
            n=("markout", "count"),
            obi_mean=("obi", "mean"),
        ).reset_index()

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle("Fill Quality Conditioned on OBI — 30 Days", fontsize=13)

        ax = axes[0]
        colors_q = ["#B71C1C", "#E65100", "#757575", "#1565C0", "#0D47A1"]
        bars = ax.bar(range(len(summary)), summary["mean_markout"],
                      color=colors_q, edgecolor="white")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xticks(range(len(summary)))
        ax.set_xticklabels(summary["obi_q5"].astype(str), fontsize=9)
        ax.set_ylabel("Avg markout (bps)\n[Positive = price moved our way after fill]")
        ax.set_title("Avg Fill Markout by OBI Quintile")
        ax.grid(alpha=0.25, axis="y")

        ax = axes[1]
        ax.bar(range(len(summary)), summary["pct_adverse"] * 100,
               color=colors_q, edgecolor="white")
        ax.axhline(50, color="k", lw=0.8, ls="--", label="50% neutral")
        ax.set_xticks(range(len(summary)))
        ax.set_xticklabels(summary["obi_q5"].astype(str), fontsize=9)
        ax.set_ylabel("% Adverse fills")
        ax.set_title("Adverse Fill Rate by OBI Quintile\n[Does OBI predict fill quality?]")
        ax.set_ylim(0, 70)
        ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

        plt.tight_layout()
        fig.savefig(ANALYSIS_DIR / "fig6_obi_fill_quality.png", dpi=150, bbox_inches="tight")
        plt.close()
        print("Saved fig6_obi_fill_quality.png")

    # fig7: OBI return scatter at best horizon
    best_h = ic_agg[ic_agg.level == "obi_l1"].sort_values("ic", ascending=False).iloc[0]["horizon"]
    ret_col = f"ret_{best_h}"
    if ret_col in pred_all.columns:
        sample = pred_all[["obi_l1", ret_col]].dropna().sample(min(5000, len(pred_all)))
        fig, ax = plt.subplots(figsize=(9, 7))
        ax.scatter(sample["obi_l1"], sample[ret_col], alpha=0.15, s=8, color="#1565C0")
        # Regression line
        x = sample["obi_l1"].values; y = sample[ret_col].values
        m, b = np.polyfit(x, y, 1)
        xr = np.linspace(x.min(), x.max(), 100)
        ax.plot(xr, m * xr + b, color="#B71C1C", lw=2,
                label=f"OLS: slope={m:.2f} bps/unit OBI")
        ax.axhline(0, color="k", lw=0.5); ax.axvline(0, color="k", lw=0.5)
        ic_val = ic_agg[(ic_agg.level=="obi_l1") & (ic_agg.horizon==best_h)]["ic"].iloc[0]
        ax.set_xlabel("OBI L1 (order book imbalance at touch)")
        ax.set_ylabel(f"Price return at t+{best_h:.0f}s (bps)")
        ax.set_title(f"OBI L1 vs {best_h:.0f}s Return — IC={ic_val:.3f}\n"
                     f"[Positive OBI = bid-heavy = price tends to rise]")
        ax.legend(fontsize=10); ax.grid(alpha=0.2)
        plt.tight_layout()
        fig.savefig(ANALYSIS_DIR / "fig7_obi_scatter.png", dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved fig7_obi_scatter.png  (horizon={best_h:.0f}s)")

    # Save summary
    summary_out = {
        "ic_by_level_horizon": ic_agg.to_dict(orient="records"),
        "best_level": ic_agg.sort_values("ic", ascending=False).iloc[0]["level"],
        "best_horizon": float(ic_agg.sort_values("ic", ascending=False).iloc[0]["horizon"]),
        "best_ic": float(ic_agg.sort_values("ic", ascending=False).iloc[0]["ic"]),
    }
    with open(OUT_DIR / "obi_summary.json", "w") as f:
        json.dump(summary_out, f, indent=2)
    print("Saved obi_summary.json")


if __name__ == "__main__":
    run()
