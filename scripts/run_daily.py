"""
Daily Backtest Runner
----------------------
Runs the backtest day-by-day over a date range, driven by a config file.

Usage
-----
    python run_daily.py --config experiments/01_baseline_pure_as/config.json
    python run_daily.py --config experiments/01_baseline_pure_as/config.json --aggregate

Config file format (config.json)
---------------------------------
{
    "data_dir":         "data/real",
    "start":            "2025-05-13",
    "end":              "2025-05-20",
    "output_dir":       "experiments/01_baseline_pure_as/results",

    "strategy":         "pure_as",
    "gamma":            0.086,
    "t_scaling":        9702,
    "order_size":       0.001,
    "min_spread_bps":   0.05,
    "max_inventory":    0.02,
    "maker_fee":        0.0,
    "latency":          0.1,
    "quote_freq":       0.5,

    "vol_window":       120,
    "arrival_window":   60,
    "ewma_alpha":       0.9,

    "guardrail":        false,
    "vol_soft":         0.70,
    "vol_hard":         0.90,
    "min_size":         0.40,

    "short_gap":        2.0,
    "long_gap":         30.0,
    "timestamp":        "time_exchange",
    "max_rows":         null,
    "quiet":            false,
    "skip_existing":    false,
    "save_full":        false,

    "notes":            "baseline pure A-S before fixes"
}
"""

from __future__ import annotations

import argparse
import json
import traceback
import sys
import os
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from hft_market_maker.data.loader import DataLoader
from hft_market_maker import (
    AvellanedaStoikov,
    FullAggressivenessAS,
    RegimeDetector,
    RegimeAwareAS,
    TabularQLearning,
    DQNMarketMaker,
    Backtest,
    MarketState,
    OrderManager,
    VolRiskManager,
    OFIAsymmetricAS,
    GLFTMarketMaker,
    ShiftedGLFTMarketMaker,
    VolInventoryMarketMaker,
    RegimeFilter,
    OFIDirectedFilter,
    OBIDirectedFilter,
    VPINFilter,
    HourFilter,
    TradeSpikeFilter,
    DailyLossLimit,
    KyleLambdaFilter,
    DynamicSizeFilter,
    SpreadMultiplierFilter,
)


# ============================================================
# Config loading
# ============================================================

DEFAULTS = {
    "strategy":       "pure_as",
    "gamma":          0.086,
    "t_scaling":      9702.0,
    "order_size":     0.001,
    "min_spread_bps": 0.05,
    "max_inventory":  0.02,
    "maker_fee":      0.0,
    "latency":        0.1,
    "quote_freq":     0.5,

    "vol_window":     120,
    "arrival_window": 60,
    "ewma_alpha":     0.9,
    "kappa_as_window":     3600.0,
    "kappa_as_min_fills":  10,
    "kappa_as_min":        1.5,
    "regime_vol_threshold": 3.0,
    "regime_mom_threshold": 0.5,
    "regime_ofi_threshold": float("inf"),
    "ofi_directed_threshold": 0.3,
    "ofi_directed_mom_threshold": float("inf"),
    "vpin_threshold":       0.4,
    "vpin_bucket_volume":   0.5,
    "vpin_n_buckets":       50,
    "bad_hours":            [],
    "spike_multiplier":     3.0,
    "spike_cooldown":       5.0,
    "spike_min_baseline":   0.5,
    "spike_window":         5.0,
    "daily_loss_limit":     20.0,
    "liquidate_ticks":      None,
    "kyle_lambda_threshold": 0.01,
    "kyle_alpha":            0.01,
    "kyle_min_obs":          50,
    "dynsize_sensitivity":   0.5,
    "dynsize_min_mult":      0.2,
    "spread_mult_alpha":     2.0,
    "spread_mult_signal":    "spike",
    "spread_mult_lambda_scale": 0.01,
    "spread_mult_max":       5.0,
    "vi_alpha":            0.3,
    "vi_gamma_inv":        1.0,

    "guardrail":      False,
    "vol_soft":       0.70,
    "vol_hard":       0.90,
    "min_size":       0.40,

    "short_gap":      2.0,
    "long_gap":       30.0,
    "tolerance_ticks": 0.5,
    "kappa_force_interval": 60.0,
    "timestamp":      "time_exchange",
    "symbol":         "BTC",
    "max_rows":       None,
    "quiet":          False,
    "skip_existing":  False,
    "save_full":      False,
    "notes":          "",
}


def load_config(path: str) -> dict:
    with open(path) as f:
        user = json.load(f)
    cfg = {**DEFAULTS, **user}
    return cfg


# ============================================================
# Snapshot builder
# ============================================================

def build_snapshot(results) -> "pd.DataFrame | None":
    ql = results.quote_log
    if ql is None or ql.empty:
        return None

    df = ql.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp")
    elif not isinstance(df.index, pd.DatetimeIndex):
        return None

    df = df.sort_index()
    df = df.rename(columns={"mid": "close", "inventory": "inv"})

    if results.equity_curve is not None and len(results.equity_curve) > 0:
        eq = results.equity_curve.copy()
        if not isinstance(eq.index, pd.DatetimeIndex):
            eq.index = pd.to_datetime(eq.index, unit="s", utc=True)
        eq = eq[~eq.index.duplicated(keep="last")]
        eq_df = eq.reset_index()
        eq_df.columns = ["timestamp", "pnl"]
        df_reset = df.reset_index()

        # Strip timezone from both sides before merging
        df_reset["timestamp"] = pd.to_datetime(df_reset["timestamp"]).dt.tz_localize(None)
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"]).dt.tz_localize(None)

        merged = pd.merge_asof(
            df_reset.sort_values("timestamp"),
            eq_df.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )
        merged = merged.set_index("timestamp")
        df = merged

    keep = ["close", "pnl", "inv", "bid", "ask", "spread_bps",
            "sigma", "kappa", "A_hat", "ofi", "vol_percentile",
            "bid_size_mult", "ask_size_mult"]
    df = df[[c for c in keep if c in df.columns]]
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].astype("float32")

    return df


# ============================================================
# Strategy factory
# ============================================================

def make_strategy(cfg: dict, mid_price_estimate: float = 102000.0):
    tick_size = cfg.get("tick_size", 0.01)
    common = dict(
        T=cfg["t_scaling"],
        order_size=cfg["order_size"],
        min_spread_bps=cfg["min_spread_bps"],
        max_inventory=cfg["max_inventory"],
        tick_size=tick_size,
    )
    name = cfg["strategy"]
    gamma = cfg["gamma"]

    if name == "pure_as":
        return AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
    elif name == "pure_as_vpin":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return VPINFilter(base,
            vpin_threshold=cfg["vpin_threshold"])
    elif name == "pure_as_hour":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return HourFilter(base, bad_hours=cfg["bad_hours"])
    elif name == "pure_as_spike":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return TradeSpikeFilter(base,
            spike_multiplier=cfg["spike_multiplier"],
            spike_cooldown=cfg["spike_cooldown"],
            min_baseline=cfg["spike_min_baseline"])
    elif name == "pure_as_loss_limit":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"],
                              liquidate_ticks=cfg["liquidate_ticks"])
    elif name == "pure_as_spike_loss":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return DailyLossLimit(TradeSpikeFilter(base,
            spike_multiplier=cfg["spike_multiplier"],
            spike_cooldown=cfg["spike_cooldown"],
            min_baseline=cfg["spike_min_baseline"]),
            daily_limit=cfg["daily_loss_limit"],
            liquidate_ticks=cfg["liquidate_ticks"])
    elif name == "pure_as_kyle":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return KyleLambdaFilter(base, lambda_threshold=cfg["kyle_lambda_threshold"])
    elif name == "pure_as_dynsize":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return DynamicSizeFilter(base,
            sensitivity=cfg["dynsize_sensitivity"],
            min_mult=cfg["dynsize_min_mult"])
    elif name == "pure_as_spread_mult":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        return SpreadMultiplierFilter(base,
            alpha=cfg["spread_mult_alpha"],
            signal=cfg["spread_mult_signal"],
            lambda_scale=cfg["spread_mult_lambda_scale"],
            max_mult=cfg["spread_mult_max"])
    elif name == "pure_as_kitchen_sink":
        # All classical filters stacked: dynsize → spread_mult → loss_limit
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        base = DynamicSizeFilter(base,
            sensitivity=cfg["dynsize_sensitivity"],
            min_mult=cfg["dynsize_min_mult"])
        base = SpreadMultiplierFilter(base,
            alpha=cfg["spread_mult_alpha"],
            signal=cfg["spread_mult_signal"],
            lambda_scale=cfg["spread_mult_lambda_scale"],
            max_mult=cfg["spread_mult_max"])
        return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"],
                              liquidate_ticks=cfg["liquidate_ticks"])
    elif name == "as_ofi_directed":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        base = OFIDirectedFilter(base,
            ofi_threshold=cfg.get("ofi_directed_threshold", 0.3),
            mom_threshold=cfg.get("ofi_directed_mom_threshold", float("inf")))
        return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"],
                              liquidate_ticks=cfg["liquidate_ticks"])
    elif name == "as_mom_filter":
        base = AvellanedaStoikov(gamma=gamma, kappa_as_min=cfg["kappa_as_min"], **common)
        base = RegimeFilter(base,
            vol_threshold=float("inf"),
            mom_threshold=cfg["regime_mom_threshold"],
            ofi_threshold=float("inf"))
        return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"],
                              liquidate_ticks=cfg["liquidate_ticks"])
    elif name == "OFI":
        return OFIAsymmetricAS(
            gamma=gamma,
            ofi_sensitivity=cfg.get("ofi_sensitivity", 15.0),
            **common,
        )
    elif name == "aggressiveness":
        return FullAggressivenessAS(
            gamma_base=gamma, gamma_min=gamma * 0.1, gamma_max=gamma * 10,
            sensitivity=cfg.get("sensitivity", 1.5),
            ofi_sensitivity=cfg.get("ofi_sensitivity", 0.5),
            urgency_factor=cfg.get("urgency_factor", 3.0),
            **common,
        )
    elif name == "regime_aware":
        base = FullAggressivenessAS(
            gamma_base=gamma, gamma_min=gamma * 0.1, gamma_max=gamma * 10,
            sensitivity=cfg.get("sensitivity", 1.5),
            ofi_sensitivity=cfg.get("ofi_sensitivity", 0.5),
            urgency_factor=cfg.get("urgency_factor", 3.0),
            **common,
        )
        return RegimeAwareAS(base, RegimeDetector(
            update_interval=cfg.get("regime_update_interval", 30.0)))
    elif name == "tabular_rl":
        return TabularQLearning(
            tick_size       = tick_size,
            order_size      = cfg["order_size"],
            max_inventory   = cfg["max_inventory"],
            daily_loss_limit = cfg.get("daily_loss_limit", 9999.0),
            learning_rate   = cfg.get("lr", 0.05),
            discount        = cfg.get("discount", 0.99),
            epsilon_start   = cfg.get("epsilon_start", 1.0),
            epsilon_end     = cfg.get("epsilon_end", 0.05),
            epsilon_decay   = cfg.get("epsilon_decay", 0.99995),
            inventory_penalty = cfg.get("inventory_penalty", 0.05),
        )
    elif name == "dqn":
        return DQNMarketMaker(
            tick_size       = tick_size,
            order_size      = cfg["order_size"],
            max_inventory   = cfg["max_inventory"],
            daily_loss_limit = cfg.get("daily_loss_limit", 9999.0),
            hidden_dim      = cfg.get("hidden_dim", 128),
            lr              = cfg.get("lr", 3e-4),
            discount        = cfg.get("discount", 0.99),
            epsilon_start   = cfg.get("epsilon_start", 1.0),
            epsilon_end     = cfg.get("epsilon_end", 0.05),
            epsilon_decay   = cfg.get("epsilon_decay", 0.9999),
            batch_size      = cfg.get("batch_size", 128),
            target_update   = cfg.get("target_update", 50),
            replay_capacity = cfg.get("replay_capacity", 50_000),
            inventory_penalty = cfg.get("inventory_penalty", 0.05),
            train_mode      = cfg.get("rl_train_mode", False),
        )
    elif name in ("glft", "glft_regime", "glft_loss_limit", "glft_spike_loss"):
        base = GLFTMarketMaker(
            gamma=gamma,
            A=cfg.get("glft_A", None),
            kappa=cfg.get("glft_kappa", 1.5),
            order_size=cfg["order_size"],
            min_spread_bps=cfg["min_spread_bps"],
            max_inventory=cfg["max_inventory"],
            tick_size=tick_size,
            kappa_from_stats=cfg.get("kappa_from_stats", True),
        )
        if name == "glft_regime":
            return RegimeFilter(base,
                vol_threshold=cfg["regime_vol_threshold"],
                mom_threshold=cfg["regime_mom_threshold"],
                ofi_threshold=cfg.get("regime_ofi_threshold", float("inf")))
        if name == "glft_loss_limit":
            return DailyLossLimit(base, daily_limit=cfg["daily_loss_limit"],
                                  liquidate_ticks=cfg["liquidate_ticks"])
        if name == "glft_spike_loss":
            return DailyLossLimit(TradeSpikeFilter(base,
                spike_multiplier=cfg["spike_multiplier"],
                spike_cooldown=cfg["spike_cooldown"],
                min_baseline=cfg["spike_min_baseline"]),
                daily_limit=cfg["daily_loss_limit"],
                liquidate_ticks=cfg["liquidate_ticks"])
        return base
    elif name in ("shifted_glft", "shifted_glft_regime"):
        base = ShiftedGLFTMarketMaker(
            gamma=gamma,
            A_liq=cfg.get("glft_A_liq", 0.5),
            kappa=cfg.get("glft_kappa", 1.5),
            A_mom=cfg.get("glft_A_mom", 0.1),
            order_size=cfg["order_size"],
            min_spread_bps=cfg["min_spread_bps"],
            max_inventory=cfg["max_inventory"],
            tick_size=tick_size,
        )
        if name == "shifted_glft_regime":
            return RegimeFilter(base,
                vol_threshold=cfg["regime_vol_threshold"],
                mom_threshold=cfg["regime_mom_threshold"],
                ofi_threshold=cfg.get("regime_ofi_threshold", float("inf")))
        return base
    elif name in ("vol_inventory", "vol_inventory_regime", "vol_inventory_ofi_directed", "vol_inventory_obi_directed"):
        base = VolInventoryMarketMaker(
            alpha=cfg["vi_alpha"],
            gamma_inv=cfg["vi_gamma_inv"],
            quote_freq=cfg["quote_freq"],
            order_size=cfg["order_size"],
            min_spread_bps=cfg["min_spread_bps"],
            max_inventory=cfg["max_inventory"],
            tick_size=tick_size,
        )
        if name == "vol_inventory_regime":
            return RegimeFilter(base,
                vol_threshold=cfg["regime_vol_threshold"],
                mom_threshold=cfg["regime_mom_threshold"],
                ofi_threshold=cfg.get("regime_ofi_threshold", float("inf")))
        if name == "vol_inventory_ofi_directed":
            return OFIDirectedFilter(base,
                ofi_threshold=cfg.get("ofi_directed_threshold", 0.3),
                mom_threshold=cfg.get("ofi_directed_mom_threshold", float("inf")))
        if name == "vol_inventory_obi_directed":
            return OBIDirectedFilter(base,
                obi_threshold=cfg.get("obi_threshold", 0.3),
                mom_threshold=cfg.get("obi_mom_threshold", float("inf")))
        return base
    else:
        raise ValueError(f"Unknown strategy: {name}")


# ============================================================
# File discovery
# ============================================================

def find_daily_files(data_dir: Path, dt: date, symbol: str = "BTC"):
    date_str = dt.strftime("%Y-%m-%d")
    trades = data_dir / f"trades_{symbol}_{date_str}.parquet"
    quotes = data_dir / f"quotes_{symbol}_{date_str}.parquet"
    if not trades.exists() or not quotes.exists():
        return None, None
    return trades, quotes


def find_orderbook_file(data_dir: Path, dt: date, symbol: str = "LINK"):
    date_str = dt.strftime("%Y-%m-%d")
    path = data_dir / f"orderbooks_{symbol}_{date_str}.parquet"
    return path if path.exists() else None


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# ============================================================
# Single day runner
# ============================================================

def run_day(dt: date, trades_path: Path, quotes_path: Path,
            output_dir: Path, cfg: dict, orderbook_path: Path = None) -> dict:
    date_str = dt.strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  {date_str}")
    print(f"{'='*60}")

    loader = DataLoader()
    try:
        trades, quotes = loader.load_coinapi(
            trades_path=str(trades_path),
            quotes_path=str(quotes_path),
            max_rows=cfg["max_rows"],
            timestamp_col=cfg["timestamp"],
        )
    except Exception as e:
        print(f"  ERROR loading data: {e}")
        return {"date": date_str, "status": "load_error", "error": str(e)}

    if not trades or not quotes:
        print(f"  SKIP: no valid data after loading")
        return {"date": date_str, "status": "empty"}

    mid_est = (quotes[0].best_bid + quotes[0].best_ask) / 2
    strategy = make_strategy(cfg, mid_est)

    vol_rm = None
    if cfg["guardrail"]:
        vol_rm = VolRiskManager(
            soft_threshold=cfg["vol_soft"],
            hard_threshold=cfg["vol_hard"],
            min_size_multiplier=cfg["min_size"],
        )

    bt = Backtest(
        strategy=strategy,
        market_state=MarketState(
            vol_window=int(cfg["vol_window"]),
            arrival_window=int(cfg["arrival_window"]),
            ewma_alpha=cfg["ewma_alpha"],
            kappa_as_window=cfg["kappa_as_window"],
            kappa_as_min_fills=int(cfg["kappa_as_min_fills"]),
            vpin_bucket_volume=cfg["vpin_bucket_volume"],
            vpin_n_buckets=int(cfg["vpin_n_buckets"]),
            spike_window=cfg["spike_window"],
            kyle_alpha=cfg["kyle_alpha"],
            kyle_min_obs=int(cfg["kyle_min_obs"]),
        ),
        order_manager=OrderManager(
            maker_fee=cfg["maker_fee"],
            queue_model="none",
            queue_depth_estimate=0.3,
            latency=cfg["latency"],
        ),
        vol_risk_manager=vol_rm,
        requote_on_fill=True,
        requote_interval=cfg["quote_freq"],
        short_gap_threshold=cfg["short_gap"],
        long_gap_threshold=cfg["long_gap"],
        tolerance_ticks=cfg["tolerance_ticks"],
        kappa_force_interval=cfg["kappa_force_interval"],
        verbose=not cfg["quiet"],
        verbose_interval=400_000,
    )

    l2_tracker = None
    if orderbook_path is not None and orderbook_path.exists():
        try:
            from hft_market_maker.core.l2_features import L2BookTracker
            snaps = loader.load_orderbook(str(orderbook_path))
            l2_tracker = L2BookTracker(snaps)
            print(f"  L2: loaded {len(snaps):,} book snapshots")
        except Exception as e:
            print(f"  L2: skipped ({e})")

    try:
        results = bt.run(trades, quotes, l2_tracker=l2_tracker)
    except Exception as e:
        print(f"  ERROR during backtest: {e}")
        traceback.print_exc()
        return {"date": date_str, "status": "run_error", "error": str(e)}

    print(results.summary())

    # Save outputs
    prefix = output_dir / date_str
    metrics = {"date": date_str, "status": "ok", **results.metrics}

    with open(f"{prefix}_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    view_df = build_snapshot(results)
    if view_df is not None:
        view_df.to_parquet(f"{prefix}_view.parquet")

    with open(f"{prefix}_gaps.json", "w") as f:
        json.dump([], f)

    if cfg["save_full"]:
        if not results.trade_log.empty:
            results.trade_log.to_parquet(f"{prefix}_fills.parquet")
        if not results.quote_log.empty:
            results.quote_log.to_parquet(f"{prefix}_quotes.parquet")
        if len(results.equity_curve) > 0:
            results.equity_curve.to_frame("pnl").to_parquet(f"{prefix}_equity.parquet")

    summary_path = output_dir / "summary.csv"
    row = pd.DataFrame([metrics])
    row.to_csv(summary_path, mode="a",
               header=not summary_path.exists(), index=False)

    return metrics


# ============================================================
# Aggregation
# ============================================================

def aggregate_results(output_dir: Path):
    summary_path = output_dir / "summary.csv"
    if not summary_path.exists():
        print("No summary.csv found.")
        return

    df = pd.read_csv(summary_path)
    df = df[df["status"] == "ok"].copy()
    if df.empty:
        print("No successful days found.")
        return

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    print(f"\n{'='*65}")
    print(f"AGGREGATED RESULTS  ({df['date'].min().date()} → {df['date'].max().date()})")
    print(f"{'='*65}")
    print(f"Days run:              {len(df)}")
    print(f"Days profitable:       {(df['total_pnl'] > 0).sum()}  "
          f"({100*(df['total_pnl'] > 0).mean():.0f}%)")
    print(f"Total PnL:             {df['total_pnl'].sum():.4f}")
    print(f"Mean daily PnL:        {df['total_pnl'].mean():.4f}")
    print(f"Std daily PnL:         {df['total_pnl'].std():.4f}")
    print(f"Daily Sharpe:          "
          f"{df['total_pnl'].mean() / df['total_pnl'].std():.3f}")
    print(f"Total fills:           {df['total_fills'].sum():,}")
    print(f"Avg fill rate:         {df['fill_rate'].mean():.1%}")
    print(f"Avg spread quoted:     {df['avg_spread_bps'].mean():.2f} bps")
    print(f"Total fees:            {df['total_fees'].sum():.4f}")
    print(f"MM-only PnL:           {df['mm_only_pnl'].sum():.4f}")
    print(f"{'='*65}")

    print(f"\n{'Date':<14} {'PnL':>10} {'Cumulative':>12} {'Fills':>8} {'Gaps':>6}")
    print("-" * 55)
    cum = 0.0
    for _, row in df.iterrows():
        cum += row["total_pnl"]
        print(f"{str(row['date'].date()):<14} "
              f"{row['total_pnl']:>10.4f} "
              f"{cum:>12.4f} "
              f"{int(row['total_fills']):>8,} "
              f"{int(row.get('n_long_gaps', 0)):>6}")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Run daily HFT backtest from config file")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--aggregate", action="store_true",
                        help="Aggregate existing results and exit")
    parser.add_argument("--inspect", action="store_true",
                        help="Print file discovery only, no backtest")
    args = parser.parse_args()

    cfg = load_config(args.config)

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save config snapshot into output dir for reproducibility
    with open(output_dir / "config.json", "w") as f:
        json.dump(cfg, f, indent=2)

    if args.aggregate:
        aggregate_results(output_dir)
        return

    data_dir  = Path(cfg["data_dir"])
    start_date = date.fromisoformat(cfg["start"])
    end_date   = date.fromisoformat(cfg["end"])

    all_dates = list(date_range(start_date, end_date))
    available, missing = [], []
    for dt in all_dates:
        t, q = find_daily_files(data_dir, dt, cfg.get("symbol", "BTC"))
        if t is not None:
            available.append((dt, t, q))
        else:
            missing.append(dt)

    print(f"\nConfig:     {args.config}")
    print(f"Strategy:   {cfg['strategy']}  gamma={cfg['gamma']}  "
          f"T={cfg['t_scaling']}  quote_freq={cfg['quote_freq']}s")
    print(f"Date range: {start_date} → {end_date}  ({len(all_dates)} days)")
    print(f"Found: {len(available)}  |  Missing: {len(missing)}")
    if cfg.get("notes"):
        print(f"Notes: {cfg['notes']}")

    if args.inspect:
        return

    if not available:
        print("No files found.")
        return

    all_metrics, failed = [], []
    for dt, t_path, q_path in available:
        date_str = dt.strftime("%Y-%m-%d")
        if cfg["skip_existing"] and (output_dir / f"{date_str}_metrics.json").exists():
            print(f"  {date_str}  SKIP (exists)")
            continue
        ob_path = find_orderbook_file(data_dir, dt, cfg.get("symbol", "BTC"))
        metrics = run_day(dt, t_path, q_path, output_dir, cfg, orderbook_path=ob_path)
        all_metrics.append(metrics)
        if metrics.get("status") != "ok":
            failed.append((date_str, metrics.get("error", "unknown")))

    print(f"\n{'='*60}")
    print(f"RUN COMPLETE")
    print(f"{'='*60}")
    print(f"Attempted: {len(all_metrics)}  |  "
          f"OK: {sum(1 for m in all_metrics if m.get('status')=='ok')}  |  "
          f"Failed: {len(failed)}")
    if failed:
        for d, err in failed:
            print(f"  {d}: {err}")

    ok = [m for m in all_metrics if m.get("status") == "ok"]
    if ok:
        print(f"Total PnL:   {sum(m['total_pnl'] for m in ok):.4f}")
        print(f"MM-only PnL: {sum(m.get('mm_only_pnl',0) for m in ok):.4f}")


if __name__ == "__main__":
    main()