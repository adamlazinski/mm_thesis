"""
Analysis charts for exp 40 — LINK April 2026 zero-shot transfer.
Run from master2/: python experiments/40_link_apr2026_baseline/build_analysis.py
"""

import json, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

OUT     = Path("experiments/40_link_apr2026_baseline/analysis")
RESULTS = Path("experiments/40_link_apr2026_baseline/results")
OUT.mkdir(exist_ok=True)

COLOR   = "#1565C0"
COLOR2  = "#E65100"


def load_metrics():
    rows = []
    for f in sorted(glob.glob(str(RESULTS / "*_metrics.json"))):
        with open(f) as fh:
            m = json.load(fh)
        m["date"] = Path(f).stem.replace("_metrics", "")
        rows.append(m)
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def sharpe(pnls, ann=365):
    a = np.asarray(pnls, float)
    return 0.0 if a.std() < 1e-9 else float(a.mean() / a.std() * np.sqrt(ann))


def max_dd(pnls):
    eq = np.cumsum(pnls)
    return float(np.min(eq - np.maximum.accumulate(eq)))


df = load_metrics()
pnls  = df["total_pnl"].values
dates = df["date"].values


# ── fig1: cumulative equity + daily bars ──────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(16, 9))
fig.suptitle(
    "A-S Winner (γ≈0, max_inv=38, limit=$25) — Zero-Shot Transfer  Apr 2026",
    fontsize=13, fontweight="bold"
)

ax = axes[0]
cum = np.cumsum(pnls)
ax.plot(range(len(cum)), cum, color=COLOR, lw=2.5, zorder=3)
ax.fill_between(range(len(cum)), cum, alpha=0.12, color=COLOR)
ax.set_title(
    f"Cumulative PnL  |  Total: +${cum[-1]:,.0f}  |  "
    f"Sharpe: {sharpe(pnls):.1f}  |  Max DD: ${max_dd(pnls):.2f}  |  "
    f"Win rate: {int((pnls>0).sum())}/{len(pnls)}"
)
ax.set_ylabel("USD")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.grid(alpha=0.25)

ax2 = axes[1]
ax2.bar(range(len(pnls)), pnls, color=COLOR, edgecolor="white", linewidth=0.5)
ax2.axhline(0, color="black", lw=0.8)
ax2.axhline(np.mean(pnls), color=COLOR2, lw=1.4, ls="--",
            label=f"Mean: +${np.mean(pnls):.0f}/day")
ax2.set_title(f"Daily PnL — {int((pnls>0).sum())}/30 profitable  "
              f"(params unchanged from Jun-Jul 2025 IS winner)")
ax2.set_ylabel("USD")
ax2.set_xticks(range(len(dates)))
ax2.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax2.legend(fontsize=9)
ax2.grid(alpha=0.25, axis="y")

plt.tight_layout()
fig.savefig(OUT / "fig1_equity_daily.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig1_equity_daily.png")


# ── fig2: markout + adverse fills ─────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle("Adverse Selection Profile — April 2026", fontsize=13)

ax = axes[0]
ax.bar(range(len(df)), df["avg_markout_bps"].values, color=COLOR,
       edgecolor="white", lw=0.5)
ax.axhline(0, color="k", lw=0.8)
ax.axhline(df["avg_markout_bps"].mean(), color=COLOR2, ls="--", lw=1.5,
           label=f"Mean: +{df['avg_markout_bps'].mean():.3f} bps")
ax.set_title("Avg Markout per Day (bps)\n[Positive = fills are mean-reverting]")
ax.set_ylabel("bps")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9)
ax.grid(alpha=0.25, axis="y")

ax = axes[1]
ax.bar(range(len(df)), df["pct_adverse_fills"].values * 100, color=COLOR,
       edgecolor="white", lw=0.5)
ax.axhline(50, color="gray", ls="--", lw=1.2, label="50% (neutral)")
ax.axhline(df["pct_adverse_fills"].mean() * 100, color=COLOR2, ls="--", lw=1.5,
           label=f"Mean: {df['pct_adverse_fills'].mean()*100:.1f}%")
ax.set_title("% Adverse Fills per Day\n[Below 50% = positive selection]")
ax.set_ylabel("%")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9)
ax.grid(alpha=0.25, axis="y")
ax.set_ylim(0, 60)

plt.tight_layout()
fig.savefig(OUT / "fig2_markout.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig2_markout.png")


# ── fig3: fills + spread ──────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle("Volume and Spread — April 2026", fontsize=13)

ax = axes[0]
ax.bar(range(len(df)), df["total_fills"].values / 1000, color=COLOR,
       edgecolor="white", lw=0.5)
ax.axhline(df["total_fills"].mean() / 1000, color=COLOR2, ls="--", lw=1.5,
           label=f"Mean: {df['total_fills'].mean()/1000:.1f}k fills/day")
ax.set_title("Daily Fill Count (thousands)")
ax.set_ylabel("Fills (k)")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=9)
ax.grid(alpha=0.25, axis="y")

ax = axes[1]
ax.plot(range(len(df)), df["avg_spread_bps"].values, color=COLOR,
        lw=2, marker="o", ms=5)
ax.axhline(10, color="gray", ls=":", lw=1.2, label="Natural LINK spread (~10 bps at $9)")
ax.axhline(6.44, color="gray", ls="--", lw=1.0, label="min_spread floor (6.44 bps)")
ax.axhline(df["avg_spread_bps"].mean(), color=COLOR2, ls="--", lw=1.5,
           label=f"Mean: {df['avg_spread_bps'].mean():.2f} bps")
ax.set_title("Avg Quoted Half-Spread (bps)")
ax.set_ylabel("bps")
ax.set_xticks(range(len(dates)))
ax.set_xticklabels([d[5:] for d in dates], rotation=45, ha="right", fontsize=8)
ax.legend(fontsize=8)
ax.grid(alpha=0.25)

plt.tight_layout()
fig.savefig(OUT / "fig3_fills_spread.png", dpi=150, bbox_inches="tight")
plt.close()
print("Saved fig3_fills_spread.png")


# ── intraday helper ──────────────────────────────────────────────────────────
def intraday_chart(date_str, out_name, resample="1min"):
    path = RESULTS / f"{date_str}_view.parquet"
    if not path.exists():
        print(f"Skipped {date_str}: no view.parquet")
        return
    v = pd.read_parquet(path)
    v.index = pd.to_datetime(v.index)

    m = next(json.load(open(f)) for f in
             glob.glob(str(RESULTS / f"{date_str}_metrics.json")))

    pnl_r  = v["pnl"].resample(resample).last().dropna()
    inv_r  = v["inv"].resample(resample).mean().dropna()
    mid_r  = v["close"].resample(resample).last().dropna()
    spr_r  = v["spread_bps"].resample(resample).mean().dropna()

    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
    fig.suptitle(
        f"Intraday Detail — {date_str}  |  PnL: +${m['total_pnl']:.2f}  |  "
        f"Fills: {m['total_fills']:,}  |  Markout: {m['avg_markout_bps']:+.3f} bps  |  "
        f"Adverse: {m['pct_adverse_fills']*100:.1f}%",
        fontsize=12, fontweight="bold"
    )

    # PnL
    axes[0].plot(pnl_r.index, pnl_r.values, color=COLOR, lw=1.5)
    axes[0].axhline(0, color="k", lw=0.6)
    axes[0].fill_between(pnl_r.index, pnl_r.values, 0,
                         where=pnl_r.values >= 0, alpha=0.15, color=COLOR)
    axes[0].fill_between(pnl_r.index, pnl_r.values, 0,
                         where=pnl_r.values < 0, alpha=0.15, color="red")
    axes[0].set_ylabel("PnL (USD)")
    axes[0].set_title(f"Running PnL ({resample} bins)")
    axes[0].grid(alpha=0.25)

    # Inventory
    axes[1].plot(inv_r.index, inv_r.values, color=COLOR2, lw=1.2)
    axes[1].axhline(0, color="k", lw=0.6)
    axes[1].axhline( 38, color="gray", ls="--", lw=0.8, label="±max_inv (38 LINK)")
    axes[1].axhline(-38, color="gray", ls="--", lw=0.8)
    axes[1].fill_between(inv_r.index, inv_r.values, 0, alpha=0.12, color=COLOR2)
    axes[1].set_ylabel("Inventory (LINK)")
    axes[1].set_title(f"Inventory ({resample} avg)")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.25)

    # Mid price
    axes[2].plot(mid_r.index, mid_r.values, color="#333333", lw=1.2)
    axes[2].set_ylabel("USD")
    axes[2].set_title("LINK Mid Price")
    axes[2].grid(alpha=0.25)

    # Quoted spread
    axes[3].plot(spr_r.index, spr_r.values, color="#6A1B9A", lw=1.2)
    axes[3].axhline(6.44, color="gray", ls="--", lw=0.8, label="floor (6.44 bps)")
    axes[3].axhline(10.0, color="gray", ls=":",  lw=0.8, label="natural spread (~10 bps)")
    axes[3].set_ylabel("bps")
    axes[3].set_title(f"Quoted Half-Spread ({resample} avg)")
    axes[3].legend(fontsize=8)
    axes[3].grid(alpha=0.25)

    fig.autofmt_xdate(rotation=30, ha="right")
    plt.tight_layout()
    fig.savefig(OUT / out_name, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {out_name}")


# Apr 17 — best day ($121, 12k fills)
intraday_chart("2026-04-17", "fig4_intraday_apr17.png", resample="1min")

# Apr 10 — quiet day ($14, 7k fills)
intraday_chart("2026-04-10", "fig5_intraday_apr10.png", resample="1min")


# ── print summary ────────────────────────────────────────────────────────────
print(f"\nApril 2026 zero-shot transfer summary:")
print(f"  Days: {len(df)}  |  Wins: {int((pnls>0).sum())}/{len(df)}")
print(f"  Mean/day: +${pnls.mean():.2f}  |  Total: +${pnls.sum():.2f}")
print(f"  Sharpe: {sharpe(pnls):.2f}  |  Max DD: ${max_dd(pnls):.2f}")
print(f"  Avg markout: {df['avg_markout_bps'].mean():+.3f} bps")
print(f"  Avg adverse: {df['pct_adverse_fills'].mean()*100:.1f}%")
print(f"\nAll figures saved to {OUT}")
