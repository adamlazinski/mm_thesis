"""
Exp 59, Part F — joint sweep: does widen + speed restore latency tolerance?
============================================================================
Part E found each lever alone is limited at realistic latency: Lever 1 (widen
to 6-8t) cushions but is noisy at latency=0; Lever 3 (requote 0.05s) fixes the
staleness pick-off but ONLY at latency=0 (Lever 4: 20ms already -$95).

A single probe at (half=8t, requote=0.05s, latency=0.05s) gave +389.8 (70%
days>0) -- sharply better than Lever 4's -388.9 at (4t, 0.02s, 0.05s). This
script generalizes that probe into a 2D sweep over half-spread x latency at
the fast requote, to find where (if anywhere) the high-vol world crosses back
to breakeven under realistic latency.

Run:
    python experiments/59_synthetic_engine_validation/breakeven_sweep.py
"""
from __future__ import annotations
import importlib.util, sys, time, json
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "hvp", Path(__file__).resolve().parent / "high_vol_profit.py")
hvp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(hvp)

FIGS = Path("experiments/59_synthetic_engine_validation/figs")

HALVES = [6, 8, 12, 16]
LATENCIES = [0.0, 0.02, 0.05, 0.1, 0.2]
REQUOTE = 0.05


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    print(f"Part F — joint sweep: half-spread x latency, requote={REQUOTE}s, "
          f"beta=0, {hvp.N_SEEDS} seeds/cell\n")

    results = {}  # (half, lat) -> (mean, std, days_pct)
    print(f"  {'half(t)':>7} | " + " | ".join(f"lat={l:>5.2f}s" for l in LATENCIES))
    for half in HALVES:
        row = []
        for lat in LATENCIES:
            t0 = time.time()
            m, s, d = hvp.stats(half, 0.0, requote=REQUOTE, latency=lat)
            results[(half, lat)] = (m, s, d)
            row.append((m, s, d))
            print(f"    half={half:>3}t lat={lat:>5.2f}s -> mean={m:>8.1f}  "
                  f"std={s:>7.1f}  days>0={d:>5.0f}%  ({time.time()-t0:.1f}s)")
        print(f"  {half:>7} | " + " | ".join(f"{m:>9.1f}" for m, _, _ in row))

    # save raw results
    out_json = FIGS.parent / "results_breakeven_sweep.json"
    json.dump({f"{h},{l}": v for (h, l), v in results.items()},
              open(out_json, "w"), indent=2)
    print(f"\nSaved -> {out_json}")

    # figure: mean P&L vs latency, one line per half-spread
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.axhline(0, color="#888", lw=0.8)
    colors = plt.cm.viridis(np.linspace(0.1, 0.85, len(HALVES)))
    for half, c in zip(HALVES, colors):
        m = [results[(half, l)][0] for l in LATENCIES]
        se = [results[(half, l)][1] for l in LATENCIES]
        ax.errorbar(LATENCIES, m, yerr=se, marker="o", color=c, capsize=3,
                     lw=1.6, label=f"{half}t")
    ax.set_xlabel("latency (s)"); ax.set_ylabel(f"mean P&L ($) ± std ({hvp.N_SEEDS} seeds)")
    ax.set_title(f"Part F — widen + speed (requote={REQUOTE}s) vs latency, high-vol synthetic",
                  loc="left", fontweight="bold")
    ax.legend(title="half-spread")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_png = FIGS / "breakeven_sweep.png"
    fig.savefig(out_png, bbox_inches="tight"); plt.close(fig)
    print(f"Saved -> {out_png}")


if __name__ == "__main__":
    main()
