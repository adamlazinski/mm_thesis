"""
Generate analysis charts and risk metrics for the GLFT winner vs A-S control.
Run from master2/ root: python experiments/37_link_glft_control/build_analysis.py
"""

import json, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

OUT  = Path("experiments/37_link_glft_control/analysis")
GLFT = Path("experiments/34_link_glft_search/results_oos_best")
ASC  = Path("experiments/37_link_glft_control/results_as_control")
IS   = Path("experiments/33_link_glft/results_loss_limit")  # calibrated IS for reference

STYLE = {"glft_winner": ("#2196F3", "GLFT search-opt"),
         "as_control":  ("#FF5722", "A-S control (γ≈0)"),
         "glft_calib":  ("#9C27B0", "GLFT calibrated")}


def load_metrics(directory):
    files = sorted(glob.glob(str(directory / "*_metrics.json")))
    rows = []
    for f in files:
        with open(f) as fh:
            m = json.load(fh)
        m["date"] = Path(f).stem.replace("_metrics", "")
        rows.append(m)
    return pd.DataFrame(rows).set_index("date")


def sharpe(pnls, annualise=365):
    a = np.array(pnls)
    if a.std() < 1e-9: return 0.0
    return float(a.mean() / a.std() * np.sqrt(annualise))


def max_dd(pnls):
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity - peak))


def risk_table(df, label):
    pnls = df["total_pnl"].values
    wins = int((pnls > 0).sum())
    return {
        "Strategy":        label,
        "Mean PnL/day":    f"${np.mean(pnls):+.2f}",
        "Total PnL":       f"${np.sum(pnls):+.2f}",
        "Win rate":        f"{wins}/{len(pnls)}  ({100*wins/len(pnls):.0f}%)",
        "Sharpe (daily)":  f"{sharpe(pnls):.2f}",
        "Max drawdown":    f"${max_dd(pnls):.2f}",
        "Avg spread":      f"{df['avg_spread_bps'].mean():.2f} bps",
        "Avg markout":     f"{df['avg_markout_bps'].mean():+.3f} bps",
        "Pct adverse":     f"{df['pct_adverse_fills'].mean()*100:.1f}%",
        "Avg fills/day":   f"{df['total_fills'].mean():.0f}",
        "Avg |inventory|": f"{df['avg_abs_inventory'].mean():.1f} LINK",
    }


# ─────────────────────────────────────────────
# 1. Load data
# ─────────────────────────────────────────────
g = load_metrics(GLFT)
a = load_metrics(ASC)
g_is = load_metrics(IS)

dates_oos = g.index.tolist()
dates_is  = g_is.index.tolist()


# ─────────────────────────────────────────────
# 2. Cumulative equity (OOS)
# ─────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("GLFT Search-Opt vs A-S Control — OOS (Jun 28 – Jul 10)", fontsize=14, fontweight="bold")

ax = axes[0, 0]
for df, key in [(g, "glft_winner"), (a, "as_control")]:
    c, lbl = STYLE[key]
    cum = np.cumsum(df["total_pnl"].values)
    ax.plot(range(len(cum)), cum, color=c, lw=2, label=lbl, marker="o", ms=5)
ax.set_title("Cumulative PnL (OOS)")
ax.set_ylabel("USD")
ax.set_xticks(range(len(dates_oos)))
ax.set_xticklabels([d[5:] for d in dates_oos], rotation=45, ha="right", fontsize=8)
ax.legend(); ax.grid(alpha=0.3); ax.axhline(0, color="k", lw=0.5)


# ─────────────────────────────────────────────
# 3. Daily PnL bar chart (OOS)
# ─────────────────────────────────────────────
ax = axes[0, 1]
x = np.arange(len(dates_oos))
w = 0.38
for df, key, dx in [(g, "glft_winner", -w/2), (a, "as_control", w/2)]:
    c, lbl = STYLE[key]
    vals = df["total_pnl"].values
    ax.bar(x + dx, vals, width=w, color=c, alpha=0.8, label=lbl)
ax.set_title("Daily PnL (OOS)")
ax.set_ylabel("USD")
ax.set_xticks(x)
ax.set_xticklabels([d[5:] for d in dates_oos], rotation=45, ha="right", fontsize=8)
ax.legend(); ax.grid(alpha=0.3, axis="y"); ax.axhline(0, color="k", lw=0.5)


# ─────────────────────────────────────────────
# 4. Avg spread bps (OOS) — shows GLFT dynamic vs A-S fixed
# ─────────────────────────────────────────────
ax = axes[1, 0]
for df, key in [(g, "glft_winner"), (a, "as_control")]:
    c, lbl = STYLE[key]
    ax.plot(range(len(df)), df["avg_spread_bps"].values, color=c, lw=2, label=lbl, marker="s", ms=5)
ax.axhline(6.44, color="gray", lw=1, ls="--", label="min_spread floor (6.44 bps)")
ax.axhline(10.0, color="k", lw=0.8, ls=":", label="Natural LINK spread (10 bps)")
ax.set_title("Avg Quoted Spread (OOS)")
ax.set_ylabel("bps")
ax.set_xticks(range(len(dates_oos)))
ax.set_xticklabels([d[5:] for d in dates_oos], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=8); ax.grid(alpha=0.3)


# ─────────────────────────────────────────────
# 5. Adverse fill rate & markout (OOS)
# ─────────────────────────────────────────────
ax = axes[1, 1]
for df, key in [(g, "glft_winner"), (a, "as_control")]:
    c, lbl = STYLE[key]
    ax.scatter(df["pct_adverse_fills"].values * 100,
               df["avg_markout_bps"].values,
               color=c, s=80, alpha=0.85, label=lbl, zorder=3)
ax.axvline(50, color="gray", lw=1, ls="--", label="50% adverse (neutral)")
ax.axhline(0,  color="gray", lw=1, ls="--")
ax.set_xlabel("% Adverse Fills")
ax.set_ylabel("Avg Markout (bps)")
ax.set_title("Adverse Selection Profile (OOS)")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "fig1_oos_comparison.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig1_oos_comparison.png")


# ─────────────────────────────────────────────
# 6. Jul 3 intraday: equity + inventory (view.parquet)
# ─────────────────────────────────────────────
try:
    vg = pd.read_parquet(GLFT / "2025-07-03_view.parquet")
    va = pd.read_parquet(ASC  / "2025-07-03_view.parquet")
    vg.index = pd.to_datetime(vg.index)
    va.index = pd.to_datetime(va.index)

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
    fig.suptitle("Intraday Detail — Jul 3 2025 (GLFT winner +$152.94, A-S control +$189.07)", fontsize=13)

    # Resample to 10-minute bars for clarity
    for df, key, ax_pnl in [(vg, "glft_winner", 0), (va, "as_control", 0)]:
        c, lbl = STYLE[key]
        pnl10 = df["pnl"].resample("10min").last()
        axes[0].plot(pnl10.index, pnl10.values, color=c, lw=1.5, label=lbl)
    axes[0].set_title("Running PnL (10-min bins)")
    axes[0].set_ylabel("USD"); axes[0].legend(); axes[0].grid(alpha=0.3)
    axes[0].axhline(0, color="k", lw=0.5)

    for df, key in [(vg, "glft_winner"), (va, "as_control")]:
        c, lbl = STYLE[key]
        inv10 = df["inv"].resample("10min").mean()
        axes[1].plot(inv10.index, inv10.values, color=c, lw=1.2, label=lbl, alpha=0.85)
    axes[1].axhline(38,  color="gray", ls="--", lw=0.8, label="max_inv +38")
    axes[1].axhline(-38, color="gray", ls="--", lw=0.8, label="max_inv -38")
    axes[1].axhline(0, color="k", lw=0.5)
    axes[1].set_title("Inventory (10-min avg)")
    axes[1].set_ylabel("LINK"); axes[1].legend(fontsize=8); axes[1].grid(alpha=0.3)

    # Mid price
    mid10 = ((vg["bid"] + vg["ask"]) / 2).resample("10min").last()
    axes[2].plot(mid10.index, mid10.values, color="#333", lw=1.2, label="Mid price")
    axes[2].set_title("LINK Mid Price")
    axes[2].set_ylabel("USD"); axes[2].legend(); axes[2].grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT / "fig2_intraday_jul3.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("Saved fig2_intraday_jul3.png")
except Exception as e:
    print(f"Skipped intraday chart: {e}")


# ─────────────────────────────────────────────
# 7. Risk metrics table
# ─────────────────────────────────────────────
r_g = risk_table(g, "GLFT search-opt")
r_a = risk_table(a, "A-S control (γ≈0)")
metrics_df = pd.DataFrame([r_g, r_a]).set_index("Strategy")
print("\nRisk metrics table:")
print(metrics_df.to_string())
metrics_df.to_csv(OUT / "risk_metrics.csv")
print("Saved risk_metrics.csv")


# ─────────────────────────────────────────────
# 8. Fill volume distribution (OOS)
# ─────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(dates_oos))
w = 0.38
for df, key, dx in [(g, "glft_winner", -w/2), (a, "as_control", w/2)]:
    c, lbl = STYLE[key]
    ax.bar(x + dx, df["total_fills"].values, width=w, color=c, alpha=0.8, label=lbl)
ax.set_title("Daily Fill Count (OOS) — higher fills → more spread captured")
ax.set_ylabel("Fills"); ax.set_xticks(x)
ax.set_xticklabels([d[5:] for d in dates_oos], rotation=45, ha="right", fontsize=9)
ax.legend(); ax.grid(alpha=0.3, axis="y")
plt.tight_layout()
fig.savefig(OUT / "fig3_fill_volume.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig3_fill_volume.png")

print("\nAll outputs written to", OUT)
