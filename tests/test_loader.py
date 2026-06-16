import unittest

import pandas as pd

from hft_market_maker.data.loader import DataLoader


class SymbolValidationTests(unittest.TestCase):
    def test_multiple_symbols_are_rejected(self):
        frame = pd.DataFrame({"symbol_id": ["A", "B"]})
        with self.assertRaises(ValueError):
            DataLoader._validate_symbol_column(frame, "test data")

    def test_single_symbol_is_returned(self):
        frame = pd.DataFrame({"symbol_id": ["BINANCE_SPOT_LINK_USDT"]})
        self.assertEqual(
            DataLoader._validate_symbol_column(frame, "test data"),
            "BINANCE_SPOT_LINK_USDT",
        )


if __name__ == "__main__":
    unittest.main()
