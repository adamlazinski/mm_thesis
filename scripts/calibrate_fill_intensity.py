"""
calibrate_fill_intensity.py
============================
Calibrate the two-component fill intensity model

    lambda(delta) = A_liq * exp(-kappa * delta) + max(a - b * delta, 0)

across multiple days, using survival-based hazard MLE (correctly handles
right-censored orders) over a wide spread-distance grid.

Compares against the constant-floor model

    lambda(delta) = A_liq * exp(-kappa * delta) + A_floor

via AIC, and reports per-day and aggregate (A_liq, kappa, a, b) plus the
implied cutoff delta = a/b beyond which the toxic/momentum flow vanishes.

Run from master2/ root with .venv activated:
    python scripts/calibrate_fill_intensity.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hft_market_maker.core.fill_analysis import (
    load_day,
    hazard_curve,
    compare_fits,
)

DATA_DIR = Path("data/real")
OUT_PATH = Path("analysis/fill_intensity_calibration.json")

TICK            = 0.01
LATENCY         = 0.10
MAX_LIFETIME    = 10.0
RECOMPUTE_FREQ  = 0.20   # 200ms -- 2x coarser than survival_analysis.ipynb for speed
TOLERANCE_TICKS = 1.0

# Dense near the touch (where the decay happens), sparse out to 100 ticks
# (~$10 on a ~$100k BTC mid) to characterise the slow toxic-flow tail.
DELTAS = np.array([
    0.5, 1.5, 2.5, 3.5, 4.5, 5.5,
    7.5, 10.0, 15.0, 20.0, 30.0, 50.0, 75.0, 100.0,
])

DAYS = ["2025-05-13", "2025-05-20", "2025-06-15", "2025-07-05"]


def main():
    per_day = {}

    for date_str in DAYS:
        print(f"\n=== {date_str} ===")
        trades, quotes = load_day(date_str, DATA_DIR)
        curve = hazard_curve(
            trades, quotes, DELTAS,
            latency=LATENCY,
            max_lifetime=MAX_LIFETIME,
            recompute_freq=RECOMPUTE_FREQ,
            tolerance_ticks=TOLERANCE_TICKS,
            tick=TICK,
        )
        print(curve.to_string(index=False))

        comp = compare_fits(curve, min_delta=0.5, include_linear_decay=True)

        ex = comp["exponential"] or {}
        sh = comp["shifted"] or {}
        ld = comp["linear_decay"] or {}

        print(f"  exponential:  kappa={ex.get('kappa'):.4f}  A={ex.get('A'):.4f}  "
              f"r2={ex.get('r2'):.4f}  aic={ex.get('aic'):.2f}")
        if sh:
            print(f"  shifted:      A_liq={sh['A_liq']:.4f}  kappa={sh['kappa']:.4f}  "
                  f"A_floor={sh['A_floor']:.4f}  r2={sh['r2']:.4f}  aic={sh['aic']:.2f}")
        if ld:
            print(f"  linear_decay: A_liq={ld['A_liq']:.4f}  kappa={ld['kappa']:.4f}  "
                  f"a={ld['a']:.4f}  b={ld['b']:.6f}  cutoff(a/b)={ld['cutoff']:.1f} ticks  "
                  f"r2={ld['r2']:.4f}  aic={ld['aic']:.2f}")
        print(f"  preferred: {comp['preferred']}  (delta_aic={comp['delta_aic']:.2f})")

        per_day[date_str] = {
            "curve": curve.to_dict(orient="records"),
            "exponential": ex,
            "shifted": sh,
            "linear_decay": ld,
            "preferred": comp["preferred"],
            "delta_aic": comp["delta_aic"],
        }

    # ---- Aggregate linear-decay params across days ----
    ld_rows = [d["linear_decay"] for d in per_day.values() if d["linear_decay"]]
    summary = {}
    if ld_rows:
        for key in ("A_liq", "kappa", "a", "b", "cutoff", "r2"):
            vals = np.array([row[key] for row in ld_rows], dtype=float)
            summary[key] = {
                "mean": float(np.mean(vals)),
                "median": float(np.median(vals)),
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }

        print("\n=== Aggregate linear-decay calibration across days ===")
        for key, stats in summary.items():
            print(f"  {key:>8}: mean={stats['mean']:.5f}  median={stats['median']:.5f}  "
                  f"range=[{stats['min']:.5f}, {stats['max']:.5f}]")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"per_day": per_day, "summary": summary}, f, indent=2)
    print(f"\nSaved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
