import unittest

import pandas as pd

from hft_market_maker.backtest import Backtest, DataGapError
from hft_market_maker.core.events import QuoteEvent
from hft_market_maker.core.order_manager import OrderManager


class TerminalMetricTests(unittest.TestCase):
    def test_total_pnl_marks_terminal_inventory_to_market(self):
        manager = OrderManager()
        manager.cash = 12.5
        manager.inventory = 2.0
        manager.update_mid(3.0)
        manager.update_book(2.5, 3.5, 0.0)
        backtest = Backtest(object(), order_manager=manager, verbose=False)

        metrics = backtest._compute_metrics(
            equity=pd.Series([1.0]),
            inventory=pd.Series([0.0]),
            fills_df=pd.DataFrame(),
            quotes_df=pd.DataFrame(),
            n_events=1,
        )

        self.assertEqual(metrics["total_pnl"], 18.5)
        self.assertEqual(metrics["terminal_inventory"], 2.0)

    def test_fill_metrics_include_exact_maker_notional(self):
        backtest = Backtest(
            object(), order_manager=OrderManager(), verbose=False
        )
        metrics = backtest._compute_metrics(
            fills_df=pd.DataFrame(
                [
                    {
                        "quantity": 2.0,
                        "price": 10.0,
                        "is_taker": False,
                    },
                    {
                        "quantity": 3.0,
                        "price": 11.0,
                        "is_taker": True,
                    },
                ]
            ),
            quotes_df=pd.DataFrame(),
            equity=pd.Series(dtype=float),
            inventory=pd.Series(dtype=float),
            n_events=2,
            n_short_gaps=0,
            n_long_gaps=0,
            gap_closures=[],
        )

        self.assertEqual(metrics["maker_notional"], 20.0)
        self.assertEqual(metrics["taker_notional"], 33.0)
        self.assertEqual(metrics["filled_quantity"], 5.0)


class GapPolicyTests(unittest.TestCase):
    def test_gap_fails_instead_of_retroactively_flattening(self):
        quotes = [
            QuoteEvent(0.0, 99.0, 101.0, 1.0, 1.0),
            QuoteEvent(3.0, 99.0, 101.0, 1.0, 1.0),
        ]
        backtest = Backtest(
            object(),
            short_gap_threshold=2.0,
            long_gap_threshold=30.0,
            data_gap_policy="error",
            verbose=False,
        )

        with self.assertRaises(DataGapError):
            backtest.run([], quotes)


if __name__ == "__main__":
    unittest.main()
