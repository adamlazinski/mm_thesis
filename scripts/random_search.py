"""
Random Parameter Search
-----------------------
Config-driven random search over A-S parameters using multiprocessing.

Usage
-----
    python random_search.py --config experiments/02_ofi_asymmetric/search_config.json

Search config format
--------------------
{
    "data_dir":       "data/real",
    "start":          "2025-05-13",
    "end":            "2025-05-17",
    "output":         "search/02_ofi_search.csv",

    "strategy":       "pure_as",
    "order_size":     0.001,
    "tick_size":      0.01,
    "maker_fee":      0.0,
    "timestamp":      "time_exchange",

    "fixed": {
        "latency":          0.1,
        "quote_freq":       0.5,
        "min_spread_bps":   0.05,
        "max_inventory":    0.02,
        "vol_window":       120,
        "arrival_window":   60,
        "ewma_alpha":       0.9,
        "guardrail":        false
    },

    "search": {
        "gamma":      ["log_uniform", 0.001, 0.015],
        "t_scaling":  ["log_uniform", 4000, 18000]
    },

    "scoring": {
        "metric":           "mean_pnl",
        "min_fills":        10,
        "min_fill_rate":    0.001
    },

    "n_trials":   100,
    "n_workers":  7,
    "seed":       42,
    "top_n":      10,
    "notes":      "baseline gamma/T search"
}

Fixed params are used as-is every trial.
Search params are sampled randomly each trial.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import List, Optional
import warnings
import sys, os
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

from hft_market_maker.data.loader import DataLoader
from hft_market_maker import (
    AvellanedaStoikov,
    Backtest,
    MarketState,
    OrderManager,
    OFIAsymmetricAS,
    FullAggressivenessAS,
    VolRiskManager,
    GLFTMarketMaker,
    ShiftedGLFTMarketMaker,
    VolInventoryMarketMaker,
    RegimeFilter,
)


# ============================================================
# Config
# ============================================================

SEARCH_DEFAULTS = {
    "strategy":     "pure_as",
    "order_size":   0.001,
    "tick_size":    0.01,
    "maker_fee":    0.0,
    "timestamp":    "time_exchange",
    "n_trials":     100,
    "n_workers":    None,
    "seed":         42,
    "top_n":        10,
    "notes":        "",
    "fixed": {
        "latency":          0.1,
        "quote_freq":       0.5,
        "min_spread_bps":   0.05,
        "max_inventory":    0.02,
        "vol_window":       120,
        "arrival_window":   60,
        "ewma_alpha":       0.9,
        "guardrail":        False,
        "vol_soft":         0.70,
        "vol_hard":         0.90,
        "min_size":         0.40,
    },
    "search": {
        "gamma":     ["log_uniform", 0.001, 0.015],
        "t_scaling": ["log_uniform", 4000, 18000],
    },
    "scoring": {
        "metric":        "mean_pnl",
        "min_fills":     10,
        "min_fill_rate": 0.001,
    },
}


def load_config(path: str) -> dict:
    with open(path) as f:
        user = json.load(f)
    cfg = {**SEARCH_DEFAULTS}
    for k, v in user.items():
        if k == "search":
            cfg[k] = v  # user's search space fully replaces defaults — no gamma/t_scaling bleed-in
        elif k in ("fixed", "scoring") and k in cfg:
            cfg[k] = {**cfg[k], **v}
        else:
            cfg[k] = v
    return cfg


# ============================================================
# Parameter sampling
# ============================================================

def sample_params(search_space: dict, seed: int) -> dict:
    rng = random.Random(seed)
    params = {}
    for name, spec in search_space.items():
        kind = spec[0]
        if kind == "uniform":
            params[name] = rng.uniform(spec[1], spec[2])
        elif kind == "log_uniform":
            params[name] = np.exp(rng.uniform(np.log(spec[1]), np.log(spec[2])))
        elif kind == "choice":
            params[name] = rng.choice(spec[1:])
        elif kind == "fixed":
            params[name] = spec[1]
    return params


# ============================================================
# Strategy factory
# ============================================================

def make_strategy(cfg: dict, all_params: dict, mid_est: float = 102000.0):
    name = cfg["strategy"]
    tick_size = cfg["tick_size"]
    order_size = cfg["order_size"]
    min_spread_bps = all_params.get("min_spread_bps", 0.0)
    max_inventory = all_params.get("max_inventory", 0.02)

    if name in ("pure_as", "OFI", "aggressiveness"):
        common = dict(
            T=all_params.get("t_scaling", 3600.0),
            order_size=order_size,
            min_spread_bps=min_spread_bps,
            max_inventory=max_inventory,
            tick_size=tick_size,
        )
        gamma = all_params["gamma"]
        if name == "pure_as":
            return AvellanedaStoikov(gamma=gamma, **common)
        elif name == "OFI":
            return OFIAsymmetricAS(
                gamma=gamma,
                ofi_sensitivity=all_params.get("ofi_sensitivity", 15.0),
                **common,
            )
        elif name == "aggressiveness":
            return FullAggressivenessAS(
                gamma_base=gamma, gamma_min=gamma * 0.1, gamma_max=gamma * 10,
                sensitivity=all_params.get("sensitivity", 1.5),
                ofi_sensitivity=all_params.get("ofi_sensitivity", 0.5),
                urgency_factor=all_params.get("urgency_factor", 3.0),
                **common,
            )

    elif name in ("glft", "glft_regime"):
        base = GLFTMarketMaker(
            gamma=all_params["gamma"],
            A=all_params.get("glft_A", None),
            kappa=all_params.get("glft_kappa", 1.5),
            order_size=order_size,
            min_spread_bps=min_spread_bps,
            max_inventory=max_inventory,
            tick_size=tick_size,
            kappa_from_stats=all_params.get("kappa_from_stats", True),
        )
        if name == "glft_regime":
            return RegimeFilter(base,
                vol_threshold=all_params.get("regime_vol_threshold", 3.0),
                mom_threshold=all_params.get("regime_mom_threshold", 0.5))
        return base

    elif name in ("shifted_glft", "shifted_glft_regime"):
        base = ShiftedGLFTMarketMaker(
            gamma=all_params["gamma"],
            A_liq=all_params.get("glft_A_liq", 0.5),
            kappa=all_params.get("glft_kappa", 1.5),
            A_mom=all_params.get("glft_A_mom", 0.1),
            order_size=order_size,
            min_spread_bps=min_spread_bps,
            max_inventory=max_inventory,
            tick_size=tick_size,
        )
        if name == "shifted_glft_regime":
            return RegimeFilter(base,
                vol_threshold=all_params.get("regime_vol_threshold", 3.0),
                mom_threshold=all_params.get("regime_mom_threshold", 0.5))
        return base

    elif name in ("vol_inventory", "vol_inventory_regime"):
        base = VolInventoryMarketMaker(
            alpha=all_params["vi_alpha"],
            gamma_inv=all_params["vi_gamma_inv"],
            quote_freq=all_params.get("quote_freq", 0.5),
            order_size=order_size,
            min_spread_bps=min_spread_bps,
            max_inventory=max_inventory,
            tick_size=tick_size,
        )
        if name == "vol_inventory_regime":
            return RegimeFilter(base,
                vol_threshold=all_params.get("regime_vol_threshold", 3.0),
                mom_threshold=all_params.get("regime_mom_threshold", 0.5))
        return base

    else:
        raise ValueError(f"Unknown strategy: {name}")


# ============================================================
# Single trial
# ============================================================

@dataclass
class TrialResult:
    trial_id:      int
    params:        dict
    mean_pnl:      float
    total_pnl:     float
    mean_sharpe:   float
    mean_fills:    float
    mean_fill_rate: float
    n_days:        int
    n_errors:      int
    score:         float


def run_single_day(
    trades_path: str,
    quotes_path: str,
    all_params: dict,
    cfg: dict,
) -> Optional[dict]:
    try:
        loader = DataLoader()
        trades, quotes = loader.load_coinapi(
            trades_path=trades_path,
            quotes_path=quotes_path,
            timestamp_col=cfg["timestamp"],
        )
        if not trades or not quotes:
            return None

        mid_est = (quotes[0].best_bid + quotes[0].best_ask) / 2
        strategy = make_strategy(cfg, all_params, mid_est)

        fixed = all_params  # fixed params already merged in

        vol_rm = None
        if fixed.get("guardrail", False):
            vol_rm = VolRiskManager(
                soft_threshold=fixed.get("vol_soft", 0.70),
                hard_threshold=fixed.get("vol_hard", 0.90),
                min_size_multiplier=fixed.get("min_size", 0.40),
            )

        bt = Backtest(
            strategy=strategy,
            market_state=MarketState(
                vol_window=int(fixed["vol_window"]),
                arrival_window=int(fixed["arrival_window"]),
                ewma_alpha=fixed["ewma_alpha"],
            ),
            order_manager=OrderManager(
                maker_fee=cfg["maker_fee"],
                queue_model="none",
                queue_depth_estimate=0.3,
                latency=fixed["latency"],
            ),
            vol_risk_manager=vol_rm,
            requote_on_fill=True,
            requote_interval=fixed["quote_freq"],
            short_gap_threshold=fixed.get("short_gap", 2.0),
            long_gap_threshold=fixed.get("long_gap", 30.0),
            tolerance_ticks=fixed.get("tolerance_ticks", 0.5),
            kappa_force_interval=fixed.get("kappa_force_interval", 60.0),
            verbose=False,
        )

        results = bt.run(trades, quotes)
        return results.metrics

    except Exception:
        return None


def run_trial(args_tuple) -> TrialResult:
    trial_id, sampled_params, day_files, cfg = args_tuple

    # Merge fixed + sampled
    all_params = {**cfg["fixed"], **sampled_params}

    day_metrics, n_errors = [], 0
    for trades_path, quotes_path in day_files:
        m = run_single_day(trades_path, quotes_path, all_params, cfg)
        if m is None:
            n_errors += 1
        else:
            day_metrics.append(m)

    if not day_metrics:
        return TrialResult(trial_id=trial_id, params=sampled_params,
                           mean_pnl=0.0, total_pnl=0.0, mean_sharpe=-999.0,
                           mean_fills=0.0, mean_fill_rate=0.0,
                           n_days=0, n_errors=n_errors, score=-999.0)

    pnls       = [m.get("total_pnl", 0.0)   for m in day_metrics]
    sharpes    = [m.get("sharpe", 0.0)       for m in day_metrics]
    fills      = [m.get("total_fills", 0)    for m in day_metrics]
    fill_rates = [m.get("fill_rate", 0.0)    for m in day_metrics]

    mean_pnl       = float(np.mean(pnls))
    total_pnl      = float(np.sum(pnls))
    mean_sharpe    = float(np.mean(sharpes))
    mean_fills     = float(np.mean(fills))
    mean_fill_rate = float(np.mean(fill_rates))

    scoring = cfg.get("scoring", {})
    metric  = scoring.get("metric", "mean_pnl")
    score   = mean_pnl if metric == "mean_pnl" else mean_sharpe

    if mean_fill_rate < scoring.get("min_fill_rate", 0.001):
        score -= 100.0
    if mean_fills < scoring.get("min_fills", 10):
        score -= 100.0

    return TrialResult(
        trial_id=trial_id, params=sampled_params,
        mean_pnl=mean_pnl, total_pnl=total_pnl,
        mean_sharpe=mean_sharpe, mean_fills=mean_fills,
        mean_fill_rate=mean_fill_rate,
        n_days=len(day_metrics), n_errors=n_errors, score=score,
    )


# ============================================================
# File discovery
# ============================================================

def find_daily_files(data_dir: Path, start: date, end: date) -> List[tuple]:
    files = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        t = data_dir / f"trades_BTC_{date_str}.parquet"
        q = data_dir / f"quotes_BTC_{date_str}.parquet"
        if t.exists() and q.exists():
            files.append((str(t), str(q)))
        current += timedelta(days=1)
    return files


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Random search from config file")
    parser.add_argument("--config", required=True, help="Path to search config JSON")
    args = parser.parse_args()

    cfg = load_config(args.config)

    data_dir   = Path(cfg["data_dir"])
    start      = date.fromisoformat(cfg["start"])
    end        = date.fromisoformat(cfg["end"])
    output     = Path(cfg["output"])
    n_trials   = cfg["n_trials"]
    n_workers  = cfg["n_workers"] or max(1, cpu_count() - 1)
    seed       = cfg["seed"]
    top_n      = cfg["top_n"]

    output.parent.mkdir(parents=True, exist_ok=True)

    day_files = find_daily_files(data_dir, start, end)
    if not day_files:
        print(f"ERROR: No data files found in {data_dir} for {start}→{end}")
        return

    print(f"Random search: {n_trials} trials × {len(day_files)} days")
    print(f"Strategy:  {cfg['strategy']}")
    print(f"Workers:   {n_workers}  |  Output: {output}")
    print(f"Fixed params: {cfg['fixed']}")
    print(f"Search space:")
    for name, spec in cfg["search"].items():
        print(f"  {name:<20} {spec}")
    if cfg.get("notes"):
        print(f"Notes: {cfg['notes']}")
    print()

    work = [
        (trial_id, sample_params(cfg["search"], seed + trial_id), day_files, cfg)
        for trial_id in range(n_trials)
    ]

    results = []
    with Pool(processes=n_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(run_trial, work)):
            results.append(result)
            if (i + 1) % 10 == 0 or (i + 1) == n_trials:
                best = max(results, key=lambda r: r.score)
                print(f"  [{i+1:>4}/{n_trials}]  "
                      f"best score={best.score:.3f}  "
                      f"pnl={best.mean_pnl:.4f}  "
                      f"fills={best.mean_fills:.0f}  "
                      f"trial={best.trial_id}")

    results.sort(key=lambda r: r.score, reverse=True)

    rows = []
    for r in results:
        row = {"trial_id": r.trial_id, "score": r.score,
               "mean_pnl": r.mean_pnl, "total_pnl": r.total_pnl,
               "mean_sharpe": r.mean_sharpe, "mean_fills": r.mean_fills,
               "mean_fill_rate": r.mean_fill_rate,
               "n_days": r.n_days, "n_errors": r.n_errors}
        row.update({f"param_{k}": v for k, v in r.params.items()})
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(output, index=False)
    print(f"\nSaved {len(df)} results to {output}")

    print(f"\nTop {top_n} trials:")
    print("-" * 80)
    param_cols = [f"param_{k}" for k in cfg["search"]]
    top_cols = ["trial_id", "score", "mean_pnl", "mean_fills",
                "mean_fill_rate"] + param_cols
    top_cols = [c for c in top_cols if c in df.columns]
    print(df.head(top_n)[top_cols].to_string(index=False, float_format="%.5f"))


if __name__ == "__main__":
    main()