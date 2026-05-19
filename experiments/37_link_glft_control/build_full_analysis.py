"""
Extended analysis: full 30-day view + updated report section.
Run from master2/: python experiments/37_link_glft_control/build_full_analysis.py
"""

import json, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

OUT  = Path("experiments/37_link_glft_control/analysis")
IS   = Path("experiments/37_link_glft_control/results_as_full_is")
OOS  = Path("experiments/37_link_glft_control/results_as_control")


def load_metrics(directory, period_label):
    rows = []
    for f in sorted(glob.glob(str(directory / "*_metrics.json"))):
        with open(f) as fh:
            m = json.load(fh)
        m["date"]   = Path(f).stem.replace("_metrics", "")
        m["period"] = period_label
        rows.append(m)
    return pd.DataFrame(rows)


def sharpe(pnls, ann=365):
    a = np.asarray(pnls)
    return 0.0 if a.std() < 1e-9 else float(a.mean() / a.std() * np.sqrt(ann))


def max_dd(pnls):
    eq = np.cumsum(pnls)
    return float(np.min(eq - np.maximum.accumulate(eq)))


# ─── load ──────────────────────────────────────────────────────────────────
df_is  = load_metrics(IS,  "IS")
df_oos = load_metrics(OOS, "OOS")
df     = pd.concat([df_is, df_oos], ignore_index=True).sort_values("date").reset_index(drop=True)

pnls    = df["total_pnl"].values
dates   = df["date"].values
periods = df["period"].values
colors  = ["#1565C0" if p == "IS" else "#E65100" for p in periods]


# ─── fig4: 30-day equity + daily PnL ──────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(16, 9))
fig.suptitle(
    "A-S Winner (γ≈0, max_inv=38, limit=$25) — Full 30-Day View  "
    "Jun 11 – Jul 10 2025",
    fontsize=13, fontweight="bold"
)

# Equity
ax = axes[0]
cum = np.cumsum(pnls)
ax.plot(range(len(cum)), cum, color="#1565C0", lw=2.5, zorder=3)
ax.fill_between(range(len(cum)), cum, alpha=0.12, color="#1565C0")
# Shade OOS
oos_start = next(i for i,p in enumerate(periods) if p=="OOS")
ax.axvspan(oos_start - 0.5, len(cum) - 0.5, alpha=0.08, color="#E65100",
           label="OOS period (Jun 28–Jul 10)")
ax.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax.set_title(f"Cumulative PnL  |  Total: +${cum[-1]:,.0f}  |  "
             f"Sharpe: {sharpe(pnls):.1f}  |  Max DD: ${max_dd(pnls):.2f}  |  "
             f"Win rate: {int((pnls>0).sum())}/{len(pnls)}")
ax.set_ylabel("USD")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9); ax.grid(alpha=0.25)
ax.text(oos_start/2, cum.max()*0.05, "In-Sample\n(Jun 11–27)", ha="center",
        color="#1565C0", fontsize=9, fontweight="bold")
ax.text(oos_start + (len(cum)-oos_start)/2, cum.max()*0.05, "Out-of-Sample\n(Jun 28–Jul 10)",
        ha="center", color="#E65100", fontsize=9, fontweight="bold")

# Daily bars
ax2 = axes[1]
bars = ax2.bar(range(len(pnls)), pnls, color=colors, edgecolor="white", linewidth=0.5)
ax2.axhline(0, color="black", lw=0.8)
ax2.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax2.axhline(np.mean(pnls), color="#1565C0", lw=1.2, ls=":", alpha=0.6,
            label=f"Mean: +${np.mean(pnls):.0f}/day")
ax2.set_title("Daily PnL — all 30 days profitable  (Jun 22: -4.3% trend, Jun 23: +10% trend)")
ax2.set_ylabel("USD")
ax2.set_xticks(range(len(dates)))
ax2.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax2.legend(fontsize=9); ax2.grid(alpha=0.25, axis="y")
# Annotate Jun 22 and 23
for d, label in [("2025-06-22", "Jun 22\n-4.3%"), ("2025-06-23", "Jun 23\n+10%")]:
    idx = list(dates).index(d)
    ax2.annotate(label, xy=(idx, pnls[idx]+5), fontsize=7.5, ha="center",
                 color="#B71C1C", fontweight="bold",
                 arrowprops=dict(arrowstyle="-", color="#B71C1C", lw=0.8),
                 xytext=(idx, pnls[idx]+35))

is_patch  = mpatches.Patch(color="#1565C0", label="In-Sample (Jun 11–27)")
oos_patch = mpatches.Patch(color="#E65100", label="Out-of-Sample (Jun 28–Jul 10)")
ax2.legend(handles=[is_patch, oos_patch], fontsize=9)

plt.tight_layout()
fig.savefig(OUT / "fig4_full_30day.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig4_full_30day.png")


# ─── fig5: markout and adverse fills across 30 days ───────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle("Adverse Selection Profile — 30 Days", fontsize=13)

ax = axes[0]
ax.bar(range(len(df)), df["avg_markout_bps"].values, color=colors, edgecolor="white", lw=0.5)
ax.axhline(0, color="k", lw=0.8)
ax.axhline(df["avg_markout_bps"].mean(), color="purple", ls="--", lw=1.5,
           label=f"Mean: +{df['avg_markout_bps'].mean():.3f} bps")
ax.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax.set_title("Avg Markout per Day (bps)\n[Positive = fills are mean-reverting]")
ax.set_ylabel("bps"); ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

ax = axes[1]
ax.bar(range(len(df)), df["pct_adverse_fills"].values * 100, color=colors,
       edgecolor="white", lw=0.5)
ax.axhline(50, color="gray", ls="--", lw=1.2, label="50% (neutral)")
ax.axhline(df["pct_adverse_fills"].mean()*100, color="purple", ls="--", lw=1.5,
           label=f"Mean: {df['pct_adverse_fills'].mean()*100:.1f}%")
ax.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax.set_title("% Adverse Fills per Day\n[All well below 50% neutral]")
ax.set_ylabel("%"); ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")
ax.set_ylim(0, 60)

is_patch  = mpatches.Patch(color="#1565C0", label="In-Sample")
oos_patch = mpatches.Patch(color="#E65100", label="Out-of-Sample")
for a in axes:
    a.legend(handles=[is_patch, oos_patch] + a.get_legend_handles_labels()[0][
        len([is_patch,oos_patch]):], fontsize=8)

plt.tight_layout()
fig.savefig(OUT / "fig5_markout_30day.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig5_markout_30day.png")


# ─── fig6: fills and spread ──────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle("Volume and Spread — 30 Days", fontsize=13)

ax = axes[0]
ax.bar(range(len(df)), df["total_fills"].values / 1000, color=colors, edgecolor="white", lw=0.5)
ax.axhline(df["total_fills"].mean()/1000, color="purple", ls="--", lw=1.5,
           label=f"Mean: {df['total_fills'].mean()/1000:.1f}k fills/day")
ax.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax.set_title("Daily Fill Count (thousands)")
ax.set_ylabel("Fills (k)"); ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

ax = axes[1]
ax.plot(range(len(df)), df["avg_spread_bps"].values, color="#1565C0",
        lw=2, marker="o", ms=5)
ax.axhline(10, color="gray", ls=":", lw=1.2, label="Natural LINK spread (10 bps)")
ax.axhline(6.44, color="gray", ls="--", lw=1.0, label="min_spread floor (6.44 bps)")
ax.axhline(df["avg_spread_bps"].mean(), color="purple", ls="--", lw=1.5,
           label=f"Mean: {df['avg_spread_bps'].mean():.2f} bps")
ax.axvline(oos_start - 0.5, color="#E65100", lw=1.5, ls="--", alpha=0.7)
ax.set_title("Avg Quoted Half-Spread (bps)")
ax.set_ylabel("bps"); ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=8); ax.grid(alpha=0.25)

plt.tight_layout()
fig.savefig(OUT / "fig6_fills_spread_30day.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig6_fills_spread_30day.png")


# ─── print stats ─────────────────────────────────────────────────────────
def stats_block(pnls, label):
    p = np.asarray(pnls)
    wins = int((p>0).sum())
    return (f"  {label}: mean={p.mean():+.1f}/d  total={p.sum():+,.0f}  "
            f"wins={wins}/{len(p)}  Sharpe={sharpe(p):.1f}  MaxDD=${max_dd(p):.2f}")

print("\nSummary:")
print(stats_block(df_is["total_pnl"],  "IS  (Jun 11-27, 17d)"))
print(stats_block(df_oos["total_pnl"], "OOS (Jun 28-Jul10, 13d)"))
print(stats_block(pnls,                "ALL (Jun 11-Jul10, 30d)"))
