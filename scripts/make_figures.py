#!/usr/bin/env python3
"""
Thesis figures. Run from the repo root:
    .venv/bin/python3 scripts/make_figures.py

Writes thesis/figures/fN_*.png (slides, 150 dpi) and .pdf (thesis, vector).

Every number is either read from a committed experiment JSON or carried in a
TABLE_* constant transcribed from the contribution it cites. Nothing is
estimated, smoothed or interpolated; where a quantity was not measured the
figure leaves a gap rather than filling one.
"""
import json, glob, os, textwrap
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "thesis", "figures")
os.makedirs(OUT, exist_ok=True)

INK, MUTED, GRID = "#1a1a1a", "#6b7280", "#d9dce1"
BAD, GOOD, NEUTRAL, ACCENT = "#c0392b", "#1e7a4c", "#8a8f98", "#1f5c8b"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": INK, "axes.linewidth": 0.8, "axes.labelcolor": INK,
    "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.titlepad": 7, "figure.constrained_layout.use": True,
    "figure.constrained_layout.h_pad": 0.10, "figure.constrained_layout.w_pad": 0.10,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "xtick.color": INK, "ytick.color": INK, "legend.frameon": False,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.bbox": "tight",
})

def save(fig, name):
    _emit_caption(fig)
    for ext, kw in (("png", {"dpi": 150}), ("pdf", {})):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), **kw)
    plt.close(fig)
    print(f"  wrote thesis/figures/{name}.png + .pdf")

_CAPS = {}

def src(ax, text):
    """Queue a source note; emitted as one figure-level footnote by save()."""
    _CAPS.setdefault(ax.get_figure(), []).append(text)

def _emit_caption(fig):
    notes = _CAPS.pop(fig, [])
    if not notes:
        return
    # wrap to the figure's own width so a long note cannot stretch the saved bbox
    width = max(90, int(fig.get_size_inches()[0] * 20))
    lines = []
    for n in notes:
        for para in n.split("\n"):
            lines.extend(textwrap.wrap(para, width=width) or [""])
    fig.text(0.008, -0.012, "\n".join(lines), fontsize=6.6, color=MUTED,
             va="top", ha="left", linespacing=1.5)

def load(pattern):
    return {p: json.load(open(p)) for p in sorted(glob.glob(os.path.join(ROOT, pattern)))}

# ---------------------------------------------------------------- tables
# C30, LINK April 2026, 30 days, zero fees, flat A-S (Ch5 section 2).
REGIME = [  # label, fills/day, PnL/day, 1s markout bps, fill model honest?
    # half-spreads are exp 53's sweep configs in bps; LINK ~$9 on a true $0.01 tick => 1 tick = 11.1 bps
    ("deep inside\n4.5 bps (0.4t)",      7673, 35.37,  0.98, False),
    ("inside (optimum)\n8.9 bps (0.8t)", 7288, 94.13,  2.80, False),
    ("at touch\n11.1 bps (1.0t)",        2502, 33.23, -0.41, None),
    ("outside\n17.8 bps (1.6t)",          216,  2.52, -0.65, True),
    # NOTE: the bps are FULL quote-to-quote spreads (min_spread_bps, applied as
    # mid*bps/20000 per side), not half-spreads. One true $0.01 tick at LINK's
    # ~$9 is 11.1 bps, which is why the "at touch" row sits at 1.0t.
]
# C30, at-touch rerun under the L2 queue model (Ch5 section 2).
QUEUE = [(9, 11.8), (86, 2.8), (431, 0.4), (863, 0.9), (4313, 1.0)]
# (C33's breakeven sweep is read straight from exp 59 in f3_breakeven; the
#  earlier transcription rounded delta_be to 3.9 and so printed a ratio of 78.0
#  where the source and Ch5's table both carry 77.5.)
# C60 co-location addendum: whole latency stack 10 ms -> 1 ms, $/day.
SPEED = [("2026-07-10", -2.04, -1.94), ("2026-07-12", 1.91, 0.54)]
# Ch8 section 3: horizons that ran off the end of the 5 s measurement window.
TAIL_CENSORED = 10.0


# ---------------------------------------------------------------- F1
def f1_regime():
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.2, 4.0))
    lab = [r[0] for r in REGIME]
    x = np.arange(len(REGIME))
    colors = [BAD if r[4] is False else (GOOD if r[4] is True else NEUTRAL) for r in REGIME]

    a.bar(x, [r[2] for r in REGIME], color=colors, width=0.62)
    for i, r in enumerate(REGIME):
        a.text(i, r[2] + 3.0, f"${r[2]:,.1f}", ha="center", fontsize=9, fontweight="bold")
        inside = r[2] > 25
        a.text(i, r[2] / 2 if inside else r[2] + 13.5, f"{r[1]:,}\nfills/day", ha="center",
               fontsize=6.6, color="white" if inside else MUTED, fontweight="bold",
               va="center" if inside else "bottom")
    a.set_ylim(0, 132); a.set_xticks(x); a.set_xticklabels(lab, fontsize=7.5)
    a.set_ylabel("P&L  ($/day)")
    a.set_title("a.  Profit sits only where the fill could not have happened")
    a.axhline(0, color=INK, lw=0.8)

    b.bar(x, [r[3] for r in REGIME], color=colors, width=0.62)
    b.axhline(0, color=INK, lw=1.0)
    for i, r in enumerate(REGIME):
        off = 0.14 if r[3] > 0 else -0.30
        b.text(i, r[3] + off, f"{r[3]:+.2f}", ha="center", fontsize=8.5, fontweight="bold")
    b.set_xticks(x); b.set_xticklabels(lab, fontsize=7.5)
    b.set_ylabel("1 s markout  (bps)")
    b.set_title("b.  Markout inverts where it is honest")
    b.set_ylim(-1.15, 3.35)

    from matplotlib.patches import Patch
    a.legend(handles=[Patch(fc=BAD, label="price not on the $0.01 grid (C54)"),
                      Patch(fc=NEUTRAL, label="real price, unearned queue priority (C20)"),
                      Patch(fc=GOOD, label="honest — trades through the level")],
             loc="upper center", fontsize=7.0, ncol=1, bbox_to_anchor=(0.5, 1.0))
    src(a, "C30 \u2014 LINK, April 2026, 30 days, zero fees, flat A-S. Price-only fill model. Spreads are FULL quote-to-quote widths; one true 0.01 USD tick at ~9 USD is 11.1 bps.")
    src(b, "The two profitable regimes fail for different reasons \u2014 inside, the price does not exist; at the touch, the queue is not earned. Positive markout appears only where the fill model is wrong.")
    fig.suptitle("Figure 1   The quote-regime decomposition: every profitable regime is one the fill model misprices",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f1_quote_regime_decomposition")


# ---------------------------------------------------------------- F2
def f2_queue():
    fig, ax = plt.subplots(figsize=(6.6, 3.9))
    d = np.array([q[0] for q in QUEUE], float); p = np.array([q[1] for q in QUEUE], float)
    ax.plot(d, p, "-o", color=ACCENT, lw=1.6, ms=6, zorder=3)
    ax.axhspan(0, 1.0, color=GOOD, alpha=0.10, zorder=0)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xscale("log")
    ax.annotate("front of queue\n(~1 competing order)", xy=(9, 11.8), xytext=(13, 9.4),
                fontsize=7.5, color=INK,
                arrowprops=dict(arrowstyle="-", lw=0.7, color=MUTED))
    ax.annotate("mid-queue — the realistic retail position\n(4,313 LINK ahead of a 5-LINK order)",
                xy=(4313, 1.0), xytext=(300, 5.2), fontsize=7.5, color=INK,
                arrowprops=dict(arrowstyle="->", lw=0.7, color=MUTED))
    ax.text(1.55e4, 2.1, "sub-$1/day\nnoise floor", fontsize=7.2, color=GOOD,
            va="center", ha="right", fontweight="bold")
    ax.set_xlabel("LINK resting ahead of the order  (log scale)")
    ax.set_ylabel("P&L  ($/day)")
    ax.set_ylim(-1, 13.5); ax.set_xlim(6, 2.2e4)
    ax.set_title("Figure 2   The profit is queue rent: it decays to the noise floor by ~5% of visible depth")
    src(ax, "C30 — at-touch rerun under the L2 queue model, parameterised by share of visible depth resting ahead. "
            "Mid-queue markout: −2.9 bps.")
    save(fig, "f2_queue_position_collapse")


# ---------------------------------------------------------------- F3
def f3_breakeven():
    eq = json.load(open(os.path.join(
        ROOT, "experiments/59_synthetic_engine_validation/results/equilibrium_pinning.json")))["equilibrium"]
    eq.sort(key=lambda r: r["sigma"])
    fig, (a, b) = plt.subplots(1, 2, figsize=(10.0, 3.8), gridspec_kw={"width_ratios": [1.25, 1]})
    s     = np.array([r["sigma"] for r in eq])
    dbe   = np.array([r["delta_be_ticks"] for r in eq])
    ratio = np.array([r["delta_be_over_sigma"] for r in eq])
    free  = dbe > 2.0      # the sigma=0.02 cell is floored at the quoter's own 2-tick quote

    k = float(np.mean(ratio[free]))
    xs = np.linspace(0, 0.215, 50)
    a.plot(xs, k * xs, "--", color=MUTED, lw=1.1, zorder=1,
           label=f"$\\delta_{{be}} = {k:.1f}\\,\\sigma_\\$$   (fitted on the three unfloored points)")
    a.scatter(s[free], dbe[free], s=58, color=ACCENT, zorder=3, label="spread free to move")
    a.scatter(s[~free], dbe[~free], s=58, facecolor="white", edgecolor=ACCENT,
              lw=1.4, zorder=3, label="floored at the 2-tick quote")
    a.set_xlabel("dollar volatility  $\\sigma_\\$$"); a.set_ylabel("breakeven half-spread  $\\delta_{be}$  (ticks)")
    a.set_xlim(0, 0.215); a.set_ylim(0, 17)
    a.legend(loc="upper left", fontsize=7.2)
    a.set_title("a.  The breakeven spread is pinned to volatility")

    b.axhline(k, color=MUTED, ls="--", lw=1.1)
    b.scatter(s[free], ratio[free], s=58, color=ACCENT, zorder=3)
    b.scatter(s[~free], ratio[~free], s=58, facecolor="white", edgecolor=ACCENT, lw=1.4, zorder=3)
    for xi, yi, fr in zip(s, ratio, free):
        b.annotate(f"{yi:.1f}", xy=(xi, yi), xytext=(0, 8 if fr else -14),
                   textcoords="offset points", ha="center", fontsize=7.5,
                   color=INK if fr else MUTED)
    b.text(0.105, k + 14, f"ratio $\\approx$ {k:.0f} across a\ntenfold volatility range",
           ha="center", fontsize=7.8, color=INK, fontweight="bold")
    b.set_xlabel("dollar volatility  $\\sigma_\\$$"); b.set_ylabel("$\\delta_{be} / \\sigma_\\$$")
    b.set_ylim(60, 112); b.set_xlim(0, 0.215)
    b.set_title("b.  …at a constant ratio")

    src(a, "C33 — synthetic data, known ground truth. Open marker: the quoter cannot tighten below its 2-tick quote,")
    src(b, "so that point sits above the line by construction. This is a scaling property of the simulated market, "
           "not a measurement of a real competitive equilibrium: fill intensity is held fixed across the sweep.")
    fig.suptitle("Figure 3   The breakeven spread scales with volatility (synthetic engine check)",
                 fontsize=10.5, fontweight="bold", x=0.009, ha="left")
    save(fig, "f3_breakeven_equilibrium")


# ---------------------------------------------------------------- F4
def f4_instruments():
    ad = load("experiments/93_adverse_selection/results/adverse_selection_2026-07-1[012].json")
    tox = load("experiments/96_toxicity_heterogeneity/results/*.json")
    wal = load("experiments/97_wallet_toxicity/results/*.json")

    fig, axes = plt.subplots(1, 4, figsize=(14.0, 3.7))
    a, b, c, d = axes

    # 1. model-free markout
    one = list(ad.values())[0]
    hz = np.array(one["horizons"], float)
    for book, col, ls in (("LINK", ACCENT, "-"), ("LINK_PERP", "#67a9cf", "-"),
                          ("BTC", BAD, "-"), ("BTC_PERP", "#e08b7d", "-")):
        r = one["results"][book]["sample_rules"]["carry"]["realized_half"]
        a.plot(hz, [r[str(h)]["bps"] for h in hz], ls, color=col, lw=1.4, label=book, ms=3, marker="o")
    a.axhline(0, color=INK, lw=1.0); a.set_xscale("log")
    a.set_xlabel("horizon after the fill  (s)"); a.set_ylabel("realized half-spread  (bps)")
    a.set_ylim(-3.2, 1.6); a.legend(fontsize=6.6, loc="lower left")
    a.set_title("1.  Markout: the tape alone")
    src(a, "C59, 2026-07-10, carry-forward quote rule (Ch3 \u00a78). "
        "Gross edge gone within 100 ms on every book.")

    # 2. speed
    xs = np.arange(len(SPEED)); w = 0.34
    b.bar(xs - w/2, [s[1] for s in SPEED], w, color=NEUTRAL, label="10 ms (retail-reachable)")
    b.bar(xs + w/2, [s[2] for s in SPEED], w, color=ACCENT, label="1 ms (co-located limit)")
    b.axhline(0, color=INK, lw=1.0)
    for i, s in enumerate(SPEED):
        for off, v in ((-w/2, s[1]), (w/2, s[2])):
            b.text(i + off, v + (0.12 if v >= 0 else -0.30), f"{v:+.2f}", ha="center", fontsize=7)
    b.set_xticks(xs); b.set_xticklabels([s[0] for s in SPEED], fontsize=7.5)
    b.set_ylabel("P&L  ($/day)"); b.set_ylim(-3.1, 3.4); b.legend(fontsize=6.8, loc="upper left")
    b.set_title("2.  Speed: 1 ms vs 10 ms")
    src(b, "C60 colo addendum. Frozen tape, so this is rigged in the strategy's favour.")

    # 3. observable state: toxicity buckets, best signal, 5 s realized half
    one_t = list(tox.values())[0]["results"]["LINK"]["univariate"]
    sig = min(one_t, key=lambda k: min(x["rh_5.0_bps"] for x in one_t[k]))
    bk = one_t[sig]
    xs = [x["bucket"] for x in bk]; ys = [x["rh_5.0_bps"] for x in bk]
    cols = [GOOD if y >= 0 else BAD for y in ys]
    c.bar(xs, ys, color=cols, width=0.68)
    c.axhline(0, color=INK, lw=1.0)
    c.set_xticks(xs); c.set_xticklabels(["most\nbenign", "", "", "", "most\ntoxic"], fontsize=7)
    c.set_xlabel(f"quintile of  {sig}"); c.set_ylabel("realized half @ 5 s  (bps)")
    c.text(0.5, 0.055, "every quintile negative,\nat a zero fee", transform=c.transAxes,
           ha="center", fontsize=7.6, color=BAD, fontweight="bold")
    c.set_title("3.  Observable state")
    src(c, "C61. Toxicity is genuinely rankable; the cleanest quintile is still negative.")

    # 4. counterparty identity: every asset-day's benign and toxic pocket vs the fee floor
    pts = []
    for _wd in wal.values():
        for asset, r in _wd["results"].items():
            bp = r.get("benign_pocket_oos")
            if bp:
                pts.append((asset.replace("HL_", ""), bp["benign"]["rh5_bps"],
                            bp["toxic"]["rh5_bps"], r["uniq_takers"]))
    names = sorted({p[0] for p in pts})
    xmap = {n: i for i, n in enumerate(names)}
    bx = [xmap[p[0]] for p in pts]
    d.scatter([x - 0.11 for x in bx], [p[1] for p in pts], s=42, color=GOOD,
              zorder=3, label="benign-ranked wallets")
    d.scatter([x + 0.11 for x in bx], [p[2] for p in pts], s=42, color=BAD,
              marker="v", zorder=3, label="toxic-ranked wallets")
    mb = float(np.mean([p[1] for p in pts])); sb = float(np.std([p[1] for p in pts], ddof=1))
    d.axhspan(mb - sb, mb + sb, color=GOOD, alpha=0.11, zorder=0)
    d.axhline(mb, color=GOOD, lw=1.0, ls="-", zorder=1)
    d.axhline(0, color=INK, lw=1.0, zorder=2)
    for fee, lab in ((-1.0, "1.0 bps maker fee"), (-2.0, "2.0 bps maker fee")):
        d.axhline(fee, color=MUTED, ls=":", lw=1.0, zorder=1)
        d.text(len(names) - 0.45, fee + 0.07, lab, fontsize=6.6, color=MUTED, ha="right")
    d.text(len(names) - 0.42, mb + sb + 0.14,
           f"benign pocket  {mb:+.2f} \u00b1 {sb:.2f} bps\n\u2014 an order of magnitude\nbelow the cheapest fee",
           fontsize=7.0, color=INK, fontweight="bold", ha="right", va="bottom")
    d.set_xticks(range(len(names))); d.set_xticklabels(names, fontsize=7.5)
    d.set_xlim(-0.5, len(names) - 0.5); d.set_ylim(-3.1, 1.45)
    d.set_ylabel("realized half @ 5 s  (bps)")
    d.legend(fontsize=6.8, loc="lower left")
    d.set_title("4.  Identity: both wallets known")
    src(d, f"C62. {len(pts)} asset-days, out-of-sample split, wallet-shuffle placebo separating at the 100th percentile. "
           "Sorting works perfectly and still buys nothing a fee does not take back.")

    fig.suptitle("Figure 4   Four independent classes of information. All four terminate at zero, not below it.",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f4_four_instruments")


# ---------------------------------------------------------------- F5
def f5_venue_clock():
    ad = load("experiments/93_adverse_selection/results/*.json")
    rows = []
    for p, d in ad.items():
        for book, r in d["results"].items():
            rows.append((book, r.get("adverse_selection_horizon_s")))
    agg = defaultdict(list)
    for book, h in rows:
        agg[book].append(h)

    GROUP = {
        "BTC": ("Binance spot BTC", 0), "BTC_PERP": ("Binance perp BTC", 0),
        "LINK": ("Binance spot LINK", 1), "LINK_PERP": ("Binance perp LINK", 1),
        "CB_LINK_PERP": ("Coinbase perp LINK", 2), "HL_LINK": ("Hyperliquid LINK", 2),
        "HL_EIGEN": ("HL EIGEN  (tightest tail book)", 3),
        "HL_HMSTR": ("HL HMSTR", 3), "HL_CELO": ("HL CELO", 3),
        "HL_USUAL": ("HL USUAL", 3), "HL_VINE": ("HL VINE", 3), "HL_ZORA": ("HL ZORA", 3),
    }
    GCOL = {0: BAD, 1: "#b5651d", 2: ACCENT, 3: GOOD}
    GNAME = {0: "small relative tick", 1: "large relative tick", 2: "slower venues", 3: "thin tail books"}

    items = []
    for book, (label, g) in GROUP.items():
        hs = [h for h in agg.get(book, []) if h is not None]
        censored = book in agg and any(h is None for h in agg[book])
        items.append((label, g, np.mean(hs) if hs else None, censored))
    items.sort(key=lambda r: (r[1], r[2] if r[2] is not None else 1e9))

    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    for i, (label, g, h, cen) in enumerate(items):
        y = len(items) - i
        if h is not None:
            ax.plot([0.008, h], [y, y], color=GCOL[g], lw=1.2, alpha=0.5, zorder=1)
            ax.scatter([h], [y], s=52, color=GCOL[g], zorder=3)
            ax.text(h * 1.25, y, f"{h*1000:,.0f} ms" if h < 1 else f"{h:.2f} s",
                    va="center", fontsize=7.5, color=INK)
        else:
            ax.plot([0.008, TAIL_CENSORED], [y, y], color=GCOL[g], lw=1.2, alpha=0.5, zorder=1)
            ax.scatter([TAIL_CENSORED], [y], s=52, color=GCOL[g], marker=">", zorder=3)
            ax.text(TAIL_CENSORED * 1.3, y, "> 10 s  (never crossed)", va="center",
                    fontsize=7.5, color=GOOD, style="italic")
        ax.text(0.0072, y, label, ha="right", va="center", fontsize=8)

    ax.set_xscale("log"); ax.set_xlim(0.0009, 40); ax.set_ylim(0.3, len(items) + 0.7)
    ax.set_yticks([]); ax.spines[["left", "right", "top"]].set_visible(False)
    ax.set_xlabel("adverse-selection horizon — how long the maker's edge survives  (log seconds)")
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{v*1000:g} ms" if v < 1 else f"{v:g} s"))
    ax.grid(axis="y", visible=False)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=GCOL[g], label=GNAME[g])
                       for g in (0, 1, 2, 3)], loc="lower left", fontsize=7.5,
              bbox_to_anchor=(0.0, 1.005), ncol=4, columnspacing=1.6, handletextpad=0.4)
    ax.set_title("Figure 5   Part II's organising law: the adverse-selection horizon tracks the venue's clock",
                 pad=24)
    src(ax, "C59 (Binance books, 3 days) and C66 (Hyperliquid, 2026-07-16/18), identical model-free markout, "
            "carry-forward quote rule (Ch3 \u00a78). Nearly three orders of magnitude. EIGEN is the tail's tightest, "
            "most-competed book and behaves like the majors. The earlier freshness-gated rule retained as little as "
            "26% of the thin books' trades at 10 s and biased the slow books toward looking fast; redone with "
            "carry-forward quotes and 100% retention, every crossing moves later and none earlier, which widens the "
            "span rather than narrowing it.")
    save(fig, "f5_venue_clock_law")


# ---------------------------------------------------------------- F6
def f6_dislocation():
    """HL_BTC laggard only -- the claim Chapter 7 makes -- on the exchange clock,
    with the 07-16 common-receive-clock rerun overlaid as the robustness check.
    The HL_LINK runs in the same folder are a different laggard and are excluded."""
    allr = load("experiments/99_oracle_lag/results/*.json")
    base, recv = {}, {}
    for path, d in allr.items():
        if d["laggard"] != "HL_BTC":
            continue
        (recv if path.endswith("_recv.json") else base)[(d["leader"], d["date"])] = d
    base = {k: v for k, v in base.items() if not k[1].endswith("_x")}
    keys = sorted(base)
    thrs = [2, 5, 10]
    fees = [("fee_4.5", "4.5 bps  (base taker)", BAD),
            ("fee_3.0", "3.0 bps  (mid tier)", NEUTRAL),
            ("fee_1.4", "1.4 bps  (high-volume tier)", GOOD)]

    fig, (a, b) = plt.subplots(1, 2, figsize=(11.0, 4.1), gridspec_kw={"width_ratios": [1.1, 1]})

    xs = np.arange(len(thrs)); w = 0.26
    for j_, (fk, flab, col) in enumerate(fees):
        vals, errs = [], []
        for t in thrs:
            v = [base[k]["thresholds"][str(t)]["h5s"]["net_rt_bps"][fk]
                 for k in keys if str(t) in base[k]["thresholds"]]
            vals.append(np.mean(v)); errs.append(np.std(v))
        a.bar(xs + (j_ - 1) * w, vals, w, yerr=errs, color=col, label=flab,
              error_kw=dict(lw=0.8, capsize=2, ecolor=INK))
    a.axhline(0, color=INK, lw=1.0)
    a.set_xticks(xs); a.set_xticklabels([f"{t} bps" for t in thrs])
    a.set_xlabel("dislocation threshold"); a.set_ylabel("net round trip @ 5 s  (bps)")
    a.legend(fontsize=7.2, loc="upper left")
    a.set_title("a.  Two gates: threshold and fee tier")
    src(a, "C63 — Binance perp and Coinbase leading Hyperliquid BTC, 2026-07-15/16, exchange clock. "
           "Mean ± s.d. over the four runs; both legs priced at executable touches.")

    rows = []
    for k in keys:
        t = base[k]["thresholds"]["5"]["h5s"]
        rows.append((k, t["gross_rt_bps"], t["n"], t["hit_rate_rt"]))
    rows.sort(key=lambda r: r[1])
    lab = [f"{l.replace('BTC_PERP','Binance perp').replace('CB_BTC','Coinbase')}\n{d[5:]}"
           for (l, d), *_ in rows]
    yb = np.arange(len(rows))
    b.barh(yb, [r[1] for r in rows], color=ACCENT, height=0.58, zorder=2)
    b.axvline(2.8, color=BAD, ls="--", lw=1.2, zorder=3)
    b.text(2.68, -0.92, "round-trip toll\nat the good tier", fontsize=7, color=BAD, ha="right")
    rk = ("BTC_PERP", "2026-07-16")
    rt = recv[rk]["thresholds"]["5"]["h5s"] if rk in recv else None
    ri = next((i_ for i_, (k, *_) in enumerate(rows) if k == rk), None)
    for i_, (k, g, n, h) in enumerate(rows):
        # on the row carrying the common-clock diamond, start the label past it
        x = g + 0.14 if (rt is None or i_ != ri) else max(g + 0.14, rt["gross_rt_bps"] + 0.30)
        b.text(x, i_, f"{g:.2f} bps    n={n}, {h:.0%} hit", va="center", fontsize=7.4)
    if rt is not None and ri is not None:
        b.scatter([rt["gross_rt_bps"]], [ri], marker="D", s=46, color=GOOD, zorder=4)
        b.annotate(f"common-clock rerun: {rt['gross_rt_bps']:.2f} bps,\n"
                   f"{rt['hit_rate_rt']:.0%} hit — survives by improving",
                   xy=(rt["gross_rt_bps"], ri), xytext=(4.1, -1.05),
                   textcoords="data", fontsize=7, color=GOOD, fontweight="bold",
                   va="center", ha="left",
                   arrowprops=dict(arrowstyle="->", lw=0.8, color=GOOD,
                                   connectionstyle="arc3,rad=-0.25"))
    b.set_yticks(yb); b.set_yticklabels(lab, fontsize=7.4)
    b.set_xlabel("gross round trip @ 5 s  (bps)"); b.set_xlim(0, 9.6)
    b.set_ylim(-1.4, len(rows) - 0.4)
    b.set_title("b.  Leader-agnostic, at the 5 bps threshold")
    src(b, "Both leaders give the same answer, which identifies the signal as \"Hyperliquid is stretched from "
           "consensus\" rather than anything about one venue's feed. Own-venue momentum (exp 116) earns only "
           "+0.8 to +1.9 bps against the same toll.")

    fig.suptitle("Figure 6   The one surviving alpha: renting a slow venue's clock",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f6_dislocation")


# ---------------------------------------------------------------- F7
def f7_immediacy():
    """Panel a: the five-day per-coin round trip from exp 103 (config "none"; the
    "A+W" overlay is the one C64 retracted), ordered by the spread actually
    measured during the capture. Panel b: the bridge control as a slopegraph over
    every anchor x distance configuration in exp 111, which is where the
    spread-width claim's weight actually falls -- the six-point cross-section in
    panel a supports it only weakly (Spearman rho = 0.60)."""
    import glob as _g
    rt, spread = defaultdict(list), defaultdict(list)
    for f in _g.glob(os.path.join(ROOT, "experiments/103_defended_maker/results/*_inv_qf0.5.json")):
        j_ = json.load(open(f))
        a = j_["asset"].replace("HL_", "")
        if a == "LINK" or not j_["date"].startswith("2026-07"):
            continue
        v = j_["configs"]["none"].get("rt_bps_liq")   # residual liquidated (Ch8 §4)
        if v is not None:
            rt[a].append(v)
    for f in _g.glob(os.path.join(ROOT, "experiments/111_fair_value_wide/results/*.json")):
        j_ = json.load(open(f))
        if j_["date"].startswith("2026-07"):
            spread[j_["asset"].replace("HL_", "")].append(j_["spread_bps"])

    fig, (a, b) = plt.subplots(1, 2, figsize=(11.2, 4.2), gridspec_kw={"width_ratios": [1.1, 1]})

    BASE_FEE = 1.5
    names = sorted(rt, key=lambda n: -np.mean(spread[n]))
    means = [float(np.mean(rt[n])) for n in names]
    npos = [sum(1 for v in rt[n] if v > 0) for n in names]
    xs = np.arange(len(names))
    cols = [GOOD if m > BASE_FEE else (NEUTRAL if m > 0 else BAD) for m in means]
    a.bar(xs, means, color=cols, width=0.6, zorder=2)
    for x, n, m, k in zip(xs, names, means, npos):
        a.text(x, m + 0.55 if m >= 0 else m - 0.30, f"{m:+.2f}", ha="center",
               fontsize=8.5, fontweight="bold",
               va="bottom" if m >= 0 else "top")
        a.text(x, -2.7, f"{k}/5 days\n{np.mean(spread[n]):.0f} bps spread", ha="center",
               va="top", fontsize=6.6, color=MUTED)
    a.axhline(0, color=INK, lw=1.0, zorder=3)
    a.axhline(BASE_FEE, color=BAD, ls="--", lw=1.1, zorder=3)
    a.text(len(names) - 0.52, BASE_FEE + 0.4, "1.5 bps base maker fee",
           fontsize=7, color=BAD, ha="right", fontweight="bold")
    a.set_xticks(xs); a.set_xticklabels(names, fontsize=8.5, fontweight="bold")
    a.set_ylim(-5.2, 17.5)
    a.set_ylabel("gross round trip  (bps of notional)")
    a.set_title("a.  Four of six clear the base fee")
    src(a, "C66 / exp 103, config \"none\", qf=0.5, all 30 coin-days 2026-07-17..21, each day's residual "
           "liquidated across the closing spread rather than marked at the mid (Ch8 \u00a74; mid-marked bars "
           "average 0.3 bps higher and change no sign). Bars ordered by measured "
           "spread, widest left. ZORA is the tightest book in the screen and the third most profitable, so the "
           "six-point cross-section supports the spread-width reading only weakly (Spearman \u03c1 = 0.60).")

    runs = defaultdict(dict)
    for f in _g.glob(os.path.join(ROOT, "experiments/111_fair_value_wide/results/*USUAL*.json")):
        j_ = json.load(open(f))
        for k, r in j_["runs"].items():
            runs[k][j_["date"]] = r["rt_bps_liq"]     # residual liquidated (Ch8 §4)
    pairs = []
    for k, byd in runs.items():
        ju = [v for d, v in byd.items() if d.startswith("2026-07")]
        au = [v for d, v in byd.items() if d.startswith("2026-08")]
        if ju and au:
            pairs.append((k, float(np.mean(ju)), float(np.mean(au))))
    for k, ju, au in pairs:
        up = au > ju
        b.plot([0, 1], [ju, au], "-o", ms=3.4, lw=1.0,
               color=NEUTRAL if up else BAD, alpha=0.95 if not up else 0.6, zorder=2)
    mk = [p for p in pairs if p[0] == "micro_k1"][0]
    b.plot([0, 1], [mk[1], mk[2]], "-o", ms=7, lw=2.4, color=ACCENT, zorder=4,
           label="micro-price, k=1  (the anchor Ch. 8 adopts)")
    b.annotate(f"{mk[1]:+.1f} bps", xy=(0, mk[1]), xytext=(-8, 0), textcoords="offset points",
               ha="right", va="center", fontsize=8.5, fontweight="bold", color=ACCENT)
    b.annotate(f"{mk[2]:+.1f} bps", xy=(1, mk[2]), xytext=(8, 0), textcoords="offset points",
               ha="left", va="center", fontsize=8.5, fontweight="bold", color=ACCENT)
    b.axhline(0, color=INK, lw=1.0, zorder=1)
    fell = sum(1 for _, ju, au in pairs if au < ju)
    b.set_xticks([0, 1])
    b.set_xticklabels([f"July 17\u201321\nwidest tail spread 56 bps",
                       f"August 5\u20138\nwidest tail spread 14 bps"], fontsize=8)
    b.set_xlim(-0.42, 1.42)
    b.set_ylabel("gross round trip  (bps of notional)")
    b.legend(fontsize=7, loc="upper right")
    b.set_title("b.  The bridge control: USUAL, every configuration")
    src(b, f"C66 / exp 111 \u2014 all {len(pairs)} anchor \u00d7 distance configurations, same coin, two months "
           f"apart, residual liquidated. {fell} of {len(pairs)} fall, median "
           f"{np.median([ju - au for _, ju, au in pairs]):.0f} bps; the decay on the micro-price anchor is "
           "+23.4 bps, 95% CI [+7.2, +39.0] \u2014 the Part II quantity with the most room from zero. "
           "The within-instrument comparison, not the cross-section, is what prices the premium by competition.")

    fig.suptitle("Figure 7   The immediacy premium: paid where competition is thin, and only while it stays thin",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f7_immediacy_premium")


# ---------------------------------------------------------------- F8
def f8_fill_curve():
    """The premise A-S and GLFT share -- lambda(delta) = A exp(-kappa delta) --
    against what the two books actually do. BTC from the May 2025 calibration,
    LINK from exp 44's L2 fill curve."""
    btc = json.load(open(os.path.join(ROOT, "analysis/fill_intensity_calibration.json")))
    link = json.load(open(os.path.join(ROOT, "experiments/44_fill_curve_l2/results/fill_curve_summary.json")))

    fig, (a, b) = plt.subplots(1, 2, figsize=(10.6, 4.0))

    days = sorted(btc["per_day"])
    cur = {}
    for d in days:
        for pt in btc["per_day"][d]["curve"]:
            cur.setdefault(pt["delta"], []).append(pt["fill_prob"])
    dl = sorted(cur)
    md = np.array([np.mean(cur[x]) for x in dl])
    dl = np.array(dl, float)
    keep = dl <= 8
    a.plot(dl[keep], md[keep], "-o", color=ACCENT, lw=1.6, ms=5, zorder=3,
           label=f"measured ({len(days)} days)")
    sm = btc["summary"]
    A, k = sm["A_liq"]["median"], sm["kappa"]["median"]
    xs = np.linspace(0.5, 8, 200)
    a.plot(xs, A * np.exp(-k * xs), "--", color=BAD, lw=1.3, zorder=2,
           label=f"pure exponential  $A e^{{-\\kappa\\delta}}$  (A={A:.1f}, $\\kappa$={k:.2f})")
    floor = float(np.mean(md[(dl >= 1.5) & (dl <= 5.5)]))
    a.axhline(floor, color=GOOD, lw=1.1, ls="-", zorder=2)
    a.text(8.0, floor * 1.5, f"momentum floor  $A_{{mom}}$ \u2248 {floor:.2f} fills/s\n"
           "\u2014 fills that do not care how far out you quote",
           fontsize=7.4, color=GOOD, fontweight="bold", ha="right", va="bottom")
    a.set_yscale("log"); a.set_xlabel("half-spread $\\delta$  (ticks from mid)")
    a.set_ylabel("fill intensity  (fills/s, log)")
    a.set_xlim(0, 8.4); a.set_ylim(2e-3, 6)
    a.annotate("the exponential keeps falling;\nthe real book does not",
               xy=(5.2, A * np.exp(-k * 5.2)), xytext=(4.2, 6e-3),
               fontsize=7.2, color=BAD, fontweight="bold", ha="center",
               arrowprops=dict(arrowstyle="->", lw=0.8, color=BAD))
    a.legend(fontsize=7.2, loc="lower left", bbox_to_anchor=(0.0, 0.08))
    a.set_title("a.  BTC: a two-component curve, not an exponential")
    src(a, "C6 — BTC/USDT, May 2025. The exponential fits the touch and then runs out underneath the data: "
           "beyond ~1.5 ticks the intensity is flat, so quoting further out buys no protection.")

    fp = link["fill_curve_price"]; fq = link["fill_curve_queue"]
    ks = sorted(fp, key=int)
    x = np.array([int(v) for v in ks]) * 0.1          # $0.001 grid -> true $0.01 ticks
    yp = np.array([fp[v] for v in ks]) * 100
    yq = np.array([fq[v] for v in ks]) * 100
    b.step(x, yp, where="mid", color=BAD, lw=1.8, label="price-only fill model", zorder=3)
    b.step(x, yq, where="mid", color=ACCENT, lw=1.8, label="queue-aware (L2)", zorder=3)
    b.axvline(0.5, color=INK, ls=":", lw=1.1, zorder=1)
    b.text(0.52, 0.0022, "the natural bid\n(0.5 true ticks)", fontsize=7.2, color=INK)
    b.annotate("", xy=(0.5, yq[4]), xytext=(0.5, yp[4]),
               arrowprops=dict(arrowstyle="<->", lw=1.2, color=GOOD))
    b.text(0.58, 0.35, f"41\u00d7", fontsize=12, color=GOOD, fontweight="bold")
    b.set_yscale("log"); b.set_xlabel("distance from mid  (true $0.01 ticks)")
    b.set_ylabel("fill probability per quote  (%, log)")
    b.legend(fontsize=7.2, loc="lower left")
    b.set_title("b.  LINK: a step function, and where the model breaks")
    src(b, "C20 / exp 44 — LINK/USDT, April 2026, 30 days. The two models agree exactly inside the spread, "
           "where no queue exists, and differ by 41x at the touch, which is the whole of Chapter 5.")

    fig.suptitle("Figure 8   The fill-intensity premise both models share, against what the books actually do",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f8_fill_curve")


# ---------------------------------------------------------------- F9
def f9_carry():
    """Funding is a contractual cash flow; the basis is the risk. Both panels
    from exps 107 and 108."""
    fc = json.load(open(os.path.join(ROOT, "experiments/107_funding_carry/results/funding_carry.json")))
    books = {}
    for f in __import__("glob").glob(os.path.join(ROOT, "experiments/108_funding_book/results/*.json")):
        d = json.load(open(f)); books[d["hl"].replace("HL_", "")] = d

    fig, (a, b) = plt.subplots(1, 2, figsize=(10.8, 4.0), gridspec_kw={"width_ratios": [1, 1.12]})

    rows = [(k.replace("HL_", ""), v) for k, v in fc["rows"].items()]
    rows.sort(key=lambda r: -r[1]["net_carry_ann_pct"])
    xs = np.arange(len(rows)); w = 0.36
    a.bar(xs - w/2, [r[1]["hl_ann_pct"] for r in rows], w, color=ACCENT, label="Hyperliquid funding (received)")
    a.bar(xs + w/2, [r[1]["binance_ann_pct"] for r in rows], w, color=NEUTRAL, label="Binance funding (paid)")
    for i, (n, v) in enumerate(rows):
        a.text(i, max(v["hl_ann_pct"], v["binance_ann_pct"]) + 0.5,
               f"net {v['net_carry_ann_pct']:+.1f}%", ha="center", fontsize=8, fontweight="bold", color=GOOD)
    a.axhline(0, color=INK, lw=1.0)
    a.set_xticks(xs); a.set_xticklabels([r[0] for r in rows], fontsize=8.5, fontweight="bold")
    a.set_ylabel("annualised funding  (%)"); a.set_ylim(-3, 14.5)
    a.legend(fontsize=7.2, loc="lower left")
    a.set_title("a.  The differential is contractual, and positive on all four")
    src(a, "C67 / exp 107, 2026-07-19. Hyperliquid funding was positive on 72-100% of settlements (99.9-100% on BTC/ETH/LINK, 71.9% on SOL). "
           "This is a settled cash flow, not an estimated edge.")

    names = [n for n in ("BTC", "LINK") if n in books]
    xs = np.arange(len(names)); w = 0.3
    fund = [books[n]["funding_ann_pct"] for n in names]
    basis = [books[n]["basis_ann_pct"] for n in names]
    carry = [books[n]["carry_ann_pct"] for n in names]
    b.bar(xs - w, fund, w, color=GOOD, label="funding leg")
    b.bar(xs, basis, w, color=[GOOD if v >= 0 else BAD for v in basis], alpha=0.55, label="basis drift")
    b.bar(xs + w, carry, w, color=ACCENT, label="realised carry")
    b.axhline(0, color=INK, lw=1.0)
    for i, n in enumerate(names):
        bk = books[n]
        b.errorbar([i + w], [bk["carry_ann_pct"]], yerr=[bk["basis_vol_ann_pct"]],
                   fmt="none", ecolor=INK, elinewidth=1.0, capsize=3, zorder=4)
        win_bps = 1e4 * bk["carry_ann_pct"] / 100.0 * bk["hours"] / 8760.0
        b.text(i + w, bk["carry_ann_pct"] + bk["basis_vol_ann_pct"] + 0.7,
               f"{win_bps:+.1f} bps over the window\nvs a {bk['roundtrip_cost_bps']:.1f} bps round trip",
               ha="center", fontsize=7.0, fontweight="bold", color=BAD)
    b.set_xticks(xs); b.set_xticklabels([f"{n}\n{books[n]['hours']:.0f} h" for n in names],
                                        fontsize=8.5, fontweight="bold")
    b.set_ylabel("annualised  (%)"); b.set_ylim(-13, 19)
    b.legend(fontsize=7.2, loc="lower left", ncol=1)
    b.set_title("b.  The basis, not the funding, decides the outcome")
    src(b, "C67 / exp 108. Bars are ANNUALISED from 36 h and 12 h. Error bar = basis volatility, 7-12%/yr "
           "against a ~7% funding signal, so a short window measures the basis rather than the carry. Expressed as "
           "what was actually earned over each window, NEITHER clears the 5.6 bps round trip - the cash flow is "
           "real and collectible, but no window here paid for itself. Round-trip cost inverts the usual logic: "
           "0.68%/yr rebalanced monthly, 20.4%/yr daily.")

    fig.suptitle("Figure 9   Carry: the cash flow is contractual; the window is too short to pay for itself",
                 fontsize=10.5, fontweight="bold", x=0.008, ha="left")
    save(fig, "f9_carry")



if __name__ == "__main__":
    print("building figures ->", OUT)
    for fn in (f1_regime, f2_queue, f3_breakeven, f4_instruments,
               f5_venue_clock, f6_dislocation, f7_immediacy, f8_fill_curve, f9_carry):
        print(f"{fn.__name__}:")
        fn()
    print("\ndone.")
