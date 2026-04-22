"""
Complete Example — HFT Market Making Backtest
==============================================

This script demonstrates all four strategy variants:
  1. Pure Avellaneda-Stoikov (baseline)
  2. Full Aggressiveness model (dynamic gamma + OFI asymmetry + inventory urgency)
  3. Regime-Aware A-S (regime detection layered on top)
  4. DQN Market Maker (RL-based)

Run with:
    python run_example.py

Or with your own data:
    python run_example.py --trades path/to/trades.csv --quotes path/to/quotes.csv
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import time
import numpy as np

from hft_market_maker import (
    Backtest,
    AvellanedaStoikov,
    FullAggressivenessAS,
    RegimeDetector,
    RegimeAwareAS,
    DQNMarketMaker,
    TabularQLearning,
    MarketState,
    OrderManager,
    DataLoader,
    generate_synthetic_data,
)


# ===========================================================================
# Strategy factory
# ===========================================================================

def make_strategy(name: str, **kwargs):
    """Factory for all strategy variants."""

    common = dict(
        gamma=0.1,
        T=3600.0,
        order_size=0.01,
        min_spread_bps=5.0,
        max_inventory=0.5,
        tick_size=0.5,
        **kwargs,
    )

    if name == "pure_as":
        return AvellanedaStoikov(**common)

    elif name == "aggressiveness":
        return FullAggressivenessAS(
            gamma_base=0.1,
            gamma_min=0.01,
            gamma_max=1.0,
            sensitivity=1.5,
            ofi_sensitivity=0.5,
            urgency_factor=3.0,
            **{k: v for k, v in common.items()
               if k not in ("gamma",)},
        )

    elif name == "regime_aware":
        base = FullAggressivenessAS(
            gamma_base=0.1,
            gamma_min=0.01,
            gamma_max=1.0,
            **{k: v for k, v in common.items()
               if k not in ("gamma",)},
        )
        detector = RegimeDetector(
            hurst_window=200,
            vol_window=100,
            update_interval=30.0,
        )
        return RegimeAwareAS(base, detector)

    elif name == "tabular_rl":
        base = AvellanedaStoikov(**common)
        return TabularQLearning(
            base_strategy=base,
            learning_rate=0.1,
            discount=0.99,
            epsilon_start=1.0,
            epsilon_end=0.05,
            epsilon_decay=0.9999,
            inventory_penalty=0.05,
        )

    elif name == "dqn":
        base = AvellanedaStoikov(**common)
        return DQNMarketMaker(
            base_strategy=base,
            hidden_dim=64,
            lr=1e-3,
            discount=0.99,
            epsilon_start=0.8,  # less exploration since we have A-S baseline
            epsilon_end=0.05,
            epsilon_decay=0.9998,
            batch_size=64,
            target_update=100,
            inventory_penalty=0.1,
        )

    else:
        raise ValueError(f"Unknown strategy: {name}")


# ===========================================================================
# Main
# ===========================================================================

def run_backtest(
    strategy_name: str,
    trades,
    quotes,
    verbose: bool = True,
) -> dict:
    print(f"\n{'='*60}")
    print(f"Running: {strategy_name.upper()}")
    print(f"{'='*60}")

    strategy = make_strategy(strategy_name)
    market_state = MarketState(vol_window=100, arrival_window=60.0)
    order_manager = OrderManager(maker_fee=0.001, queue_model="partial",
                                 queue_depth_estimate=0.3)

    bt = Backtest(
        strategy=strategy,
        market_state=market_state,
        order_manager=order_manager,
        requote_on_fill=True,
        requote_interval=0.1,
        verbose=verbose,
        verbose_interval=5_000,
    )

    t0 = time.time()
    results = bt.run(trades, quotes)
    elapsed = time.time() - t0

    print(f"\n{results.summary()}")
    print(f"Elapsed: {elapsed:.2f}s")

    return {"name": strategy_name, "results": results, "elapsed": elapsed}


def compare_strategies(all_results: list) -> None:
    print("\n" + "=" * 70)
    print("STRATEGY COMPARISON")
    print("=" * 70)
    print(f"{'Strategy':<25} {'PnL':>10} {'Sharpe':>10} {'Max DD':>12} {'Fills':>8} {'Fees':>10}")
    print("-" * 70)
    for r in all_results:
        m = r["results"].metrics
        name = r["name"]
        print(
            f"{name:<25} "
            f"{m['total_pnl']:>10.4f} "
            f"{m['sharpe']:>10.3f} "
            f"{m['max_drawdown']:>12.4f} "
            f"{m['total_fills']:>8} "
            f"{m['total_fees']:>10.6f}"
        )
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", default=None)
    parser.add_argument("--quotes", default=None)
    parser.add_argument("--minutes", type=int, default=120)
    parser.add_argument("--strategy", default="all",
                        choices=["all", "pure_as", "aggressiveness",
                                 "regime_aware", "tabular_rl", "dqn"])
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    # Load data
    if args.trades and args.quotes:
        loader = DataLoader()
        trades, quotes = loader.load_csv(args.trades, args.quotes)
    else:
        print(f"No data provided. Generating {args.minutes} minutes of synthetic data...")
        trades, quotes = generate_synthetic_data(
            n_minutes=args.minutes,
            tick_interval=0.1,
            mid_start=50_000.0,
            vol_per_second=0.0005,
            trade_rate=8.0,
            spread=5.0,
            seed=42,
        )

    # Run strategies
    strategies_to_run = (
        ["pure_as", "aggressiveness", "regime_aware", "tabular_rl", "dqn"]
        if args.strategy == "all"
        else [args.strategy]
    )

    all_results = []
    for name in strategies_to_run:
        try:
            result = run_backtest(name, trades, quotes, verbose=True)
            all_results.append(result)
        except Exception as e:
            print(f"ERROR running {name}: {e}")
            import traceback
            traceback.print_exc()

    if len(all_results) > 1:
        compare_strategies(all_results)

    # Plot best strategy
    if not args.no_plot and all_results:
        best = max(all_results, key=lambda r: r["results"].metrics["total_pnl"])
        print(f"\nPlotting results for: {best['name']}")
        try:
            best["results"].plot()
        except Exception as e:
            print(f"Could not plot: {e}")


if __name__ == "__main__":
    main()
