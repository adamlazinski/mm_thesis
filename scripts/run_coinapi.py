"""
Run Backtest on Your CoinAPI Data
===================================

Usage:
    python run_coinapi.py --trades trades.parquet --quotes quotes.parquet

Optional flags:
    --strategy      pure_as | aggressiveness | regime_aware | tabular_rl | dqn | all
    --gamma         Risk aversion (default: 0.1)
    --max-rows      Limit rows loaded (useful for quick testing)
    --timestamp     time_exchange (default) | time_coinapi
    --no-plot       Skip the matplotlib chart
    --inspect       Just print data summary and exit (no backtest)

Example — quick sanity check on first 50k rows:
    python run_coinapi.py --trades trades.parquet --quotes quotes.parquet --max-rows 50000 --inspect

Example — run all strategies:
    python run_coinapi.py --trades trades.parquet --quotes quotes.parquet --strategy all
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from hft_market_maker.data.loader import DataLoader
from hft_market_maker import (
    VolRiskManager,
    AvellanedaStoikov,
    FullAggressivenessAS,
    RegimeDetector,
    RegimeAwareAS,
    TabularQLearning,
    DQNMarketMaker,
    Backtest,
    MarketState,
    OrderManager,
)


def inspect_data(trades_path: str, quotes_path: str, timestamp_col: str) -> None:
    """Print a summary of your data without running anything."""
    print("\n=== DATA INSPECTION ===\n")

    print("TRADES:")
    t_df = pd.read_parquet(trades_path)
    print(f"  Rows:    {len(t_df):,}")
    print(f"  Columns: {list(t_df.columns)}")
    print(f"  dtypes:\n{t_df.dtypes}")
    print(f"\n  First row:\n{t_df.iloc[0]}")
    print(f"\n  Last row:\n{t_df.iloc[-1]}")
    print(f"\n  Price range: {t_df['price'].min():.4f} — {t_df['price'].max():.4f}")
    print(f"  Size range:  {t_df['size'].min():.6f} — {t_df['size'].max():.6f}")
    print(f"  taker_side counts:\n{t_df['taker_side'].value_counts()}")

    print("\nQUOTES:")
    q_df = pd.read_parquet(quotes_path)
    print(f"  Rows:    {len(q_df):,}")
    print(f"  Columns: {list(q_df.columns)}")
    print(f"\n  First row:\n{q_df.iloc[0]}")
    print(f"\n  Last row:\n{q_df.iloc[-1]}")
    print(f"\n  Bid range: {q_df['bid_price'].min():.4f} — {q_df['bid_price'].max():.4f}")
    print(f"  Ask range: {q_df['ask_price'].min():.4f} — {q_df['ask_price'].max():.4f}")
    spread = q_df['ask_price'] - q_df['bid_price']
    print(f"  Spread: min={spread.min():.4f}  mean={spread.mean():.4f}  max={spread.max():.4f}")

    print("\nTIMESTAMPS:")
    loader = DataLoader()
    ts = loader._parse_coinapi_timestamps(q_df[timestamp_col])
    duration_hours = (ts[-1] - ts[0]) / 3600
    print(f"  Start:    {pd.to_datetime(ts[0], unit='s', utc=True)}")
    print(f"  End:      {pd.to_datetime(ts[-1], unit='s', utc=True)}")
    print(f"  Duration: {duration_hours:.2f} hours  ({duration_hours/24:.2f} days)")
    print(f"  Quote interval: {np.diff(ts).mean()*1000:.1f}ms average")


def make_strategy(name: str, gamma: float, mid_price_estimate: float = 50000.0):
    """
    Build a strategy. mid_price_estimate is used to set a sensible
    tick_size — adjust if your asset is not BTC.
    """
    # Tick size heuristic: 1 pip = 0.01% of mid price
    tick_size = round(mid_price_estimate * 0.0001, 2)

    common = dict(
        T=3600.0,           # 1-hour rolling horizon
        order_size=0.001,   # Small default — adjust to your asset
        min_spread_bps=3.0, # 3 bps minimum (covers fees)
        max_inventory=0.1,  # Max 0.1 BTC position
        tick_size=tick_size,
    )

    if name == "pure_as":
        return AvellanedaStoikov(gamma=gamma, **common)

    elif name == "aggressiveness":
        return FullAggressivenessAS(
            gamma_base=gamma,
            gamma_min=gamma * 0.1,
            gamma_max=gamma * 10,
            sensitivity=1.5,
            ofi_sensitivity=0.5,
            urgency_factor=3.0,
            **common,
        )

    elif name == "regime_aware":
        base = FullAggressivenessAS(
            gamma_base=gamma, gamma_min=gamma * 0.1, gamma_max=gamma * 10,
            sensitivity=1.5, ofi_sensitivity=0.5, urgency_factor=3.0, **common,
        )
        return RegimeAwareAS(base, RegimeDetector(update_interval=30.0))

    elif name == "tabular_rl":
        base = AvellanedaStoikov(gamma=gamma, **common)
        return TabularQLearning(
            base_strategy=base,
            learning_rate=0.05,
            discount=0.99,
            epsilon_start=0.5,   # Start with some exploration
            epsilon_end=0.02,
            epsilon_decay=0.99999,
            inventory_penalty=0.05,
        )

    elif name == "dqn":
        base = AvellanedaStoikov(gamma=gamma, **common)
        return DQNMarketMaker(
            base_strategy=base,
            hidden_dim=64,
            lr=5e-4,
            epsilon_start=0.5,
            epsilon_end=0.02,
            epsilon_decay=0.99999,
            inventory_penalty=0.1,
        )

    else:
        raise ValueError(f"Unknown strategy: {name}")


def run_one(name, trades, quotes, gamma, verbose, maker_fee=0.00075, 
            use_guardrail=True, vol_soft=0.60, vol_hard=0.90, min_size=0.20):
    print(f"\n{'='*60}")
    print(f"  Strategy: {name.upper()}  |  gamma={gamma}")
    print(f"{'='*60}")

    # Estimate mid price from first few quotes for tick_size calc
    mid_est = (quotes[0].best_bid + quotes[0].best_ask) / 2

    strategy = make_strategy(name, gamma=gamma, mid_price_estimate=mid_est)

    bt = Backtest(
        strategy=strategy,
        market_state=MarketState(
            vol_window=200,
            arrival_window=60.0,
            ewma_alpha=0.94,
        ),
        order_manager=OrderManager(
            maker_fee=maker_fee,
            queue_model="partial",
            queue_depth_estimate=0.3,
        ),
        vol_risk_manager=VolRiskManager(
            soft_threshold=vol_soft,
            hard_threshold=vol_hard,
            min_size_multiplier=min_size,
        ) if use_guardrail else None,
        requote_on_fill=True,
        requote_interval=0.05,        # 50ms min between requotes (matches your 100ms quotes)
        verbose=verbose,
        verbose_interval=50_000,
    )

    import time
    t0 = time.time()
    results = bt.run(trades, quotes)
    elapsed = time.time() - t0

    print(results.summary())
    print(f"Wall time: {elapsed:.1f}s")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run HFT market making backtest on CoinAPI data")
    parser.add_argument("--trades", required=True, help="Path to trades parquet file")
    parser.add_argument("--quotes", required=True, help="Path to quotes parquet file")
    parser.add_argument("--strategy", default="pure_as",
                        choices=["pure_as", "aggressiveness", "regime_aware",
                                 "tabular_rl", "dqn", "all"])
    parser.add_argument("--gamma", type=float, default=0.1,
                        help="Risk aversion parameter (default: 0.1)")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="Limit number of rows (for quick testing)")
    parser.add_argument("--timestamp", default="time_exchange",
                        choices=["time_exchange", "time_coinapi"],
                        help="Which timestamp column to use (default: time_exchange)")
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--inspect", action="store_true",
                        help="Just print data summary, no backtest")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-event progress output")
    parser.add_argument("--maker-fee", type=float, default=0.00075,
                        help="Maker fee fraction (default: 0.00075 = Binance with BNB)")
    parser.add_argument("--no-guardrail", action="store_true",
                        help="Disable the volatility guardrail")
    parser.add_argument("--vol-soft", type=float, default=0.60,
                        help="Vol percentile for soft scaling start (default: 0.60)")
    parser.add_argument("--vol-hard", type=float, default=0.90,
                        help="Vol percentile for hard floor (default: 0.90)")
    parser.add_argument("--min-size", type=float, default=0.20,
                        help="Minimum size multiplier at hard threshold (default: 0.20)")
    args = parser.parse_args()

    if args.inspect:
        inspect_data(args.trades, args.quotes, args.timestamp)
        return

    # Load data
    loader = DataLoader()
    trades, quotes = loader.load_coinapi(
        trades_path=args.trades,
        quotes_path=args.quotes,
        max_rows=args.max_rows,
        timestamp_col=args.timestamp,
    )

    if not trades or not quotes:
        print("ERROR: No valid data loaded. Check your file paths and column names.")
        return

    # Run strategies
    strategies_to_run = (
        ["pure_as", "aggressiveness", "regime_aware", "tabular_rl", "dqn"]
        if args.strategy == "all"
        else [args.strategy]
    )

    all_results = []
    for name in strategies_to_run:
        try:
            r = run_one(name, trades, quotes, args.gamma, verbose=not args.quiet,
                        maker_fee=args.maker_fee,
                        use_guardrail=not args.no_guardrail,
                        vol_soft=args.vol_soft, vol_hard=args.vol_hard,
                        min_size=args.min_size)
            all_results.append((name, r))
        except Exception as e:
            print(f"\nERROR running {name}: {e}")
            import traceback; traceback.print_exc()

    # Comparison table
    if len(all_results) > 1:
        print("\n" + "=" * 72)
        print("COMPARISON")
        print("=" * 72)
        print(f"{'Strategy':<22} {'PnL':>10} {'Sharpe':>8} {'MaxDD':>10} {'Fills':>7} {'AvgSpd':>8}")
        print("-" * 72)
        for name, r in all_results:
            m = r.metrics
            print(f"{name:<22} {m['total_pnl']:>10.4f} {m['sharpe']:>8.3f} "
                  f"{m['max_drawdown']:>10.4f} {m['total_fills']:>7} "
                  f"{m['avg_spread_bps']:>8.2f}bps")
        print("=" * 72)

    # Plot best result
    if not args.no_plot and all_results:
        best_name, best_results = max(all_results, key=lambda x: x[1].metrics["total_pnl"])
        print(f"\nPlotting: {best_name}")
        try:
            best_results.plot()
        except Exception as e:
            print(f"Plot failed: {e}")


if __name__ == "__main__":
    main()
