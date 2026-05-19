"""
Data Loader
-----------

Loads raw tick data from CSV or Parquet files into typed event objects.

Expected CSV schemas
--------------------

Trades CSV:
  timestamp, price, quantity, side
  - timestamp: Unix epoch (seconds or milliseconds — auto-detected)
  - price: float
  - quantity: float
  - side: 'buy' or 'sell' (or 'BUY'/'SELL', '1'/'0', etc.)

Quotes CSV (top-of-book snapshots):
  timestamp, best_bid, best_ask, bid_size, ask_size
  - All floats

Binance format support:
  Binance trade exports use slightly different column names;
  use load_binance_trades() and load_binance_orderbook() for those.

You can also synthesise data for testing with generate_synthetic_data().
"""

from __future__ import annotations
from typing import List, Tuple, Optional
import numpy as np
import pandas as pd

from ..core.events import TradeEvent, QuoteEvent


class DataLoader:

    def load_csv(
        self,
        trades_path: str,
        quotes_path: str,
        timestamp_unit: Optional[str] = None,  # 's', 'ms', 'us' — auto if None
        trade_side_col: str = "side",
        max_rows: Optional[int] = None,
    ) -> Tuple[List[TradeEvent], List[QuoteEvent]]:
        """
        Load trades and quotes from standard CSV files.
        """
        trades_df = pd.read_csv(trades_path, nrows=max_rows)
        quotes_df = pd.read_csv(quotes_path, nrows=max_rows)

        trades = self._parse_trades(trades_df, timestamp_unit)
        quotes = self._parse_quotes(quotes_df, timestamp_unit)

        print(f"Loaded {len(trades):,} trades and {len(quotes):,} quotes.")
        return trades, quotes

    def load_parquet(
        self,
        trades_path: str,
        quotes_path: str,
        max_rows: Optional[int] = None,
    ) -> Tuple[List[TradeEvent], List[QuoteEvent]]:
        trades_df = pd.read_parquet(trades_path)
        quotes_df = pd.read_parquet(quotes_path)
        if max_rows:
            trades_df = trades_df.head(max_rows)
            quotes_df = quotes_df.head(max_rows)
        trades = self._parse_trades(trades_df)
        quotes = self._parse_quotes(quotes_df)
        print(f"Loaded {len(trades):,} trades and {len(quotes):,} quotes.")
        return trades, quotes

    # ------------------------------------------------------------------
    # CoinAPI format (your data)
    # ------------------------------------------------------------------

    def load_coinapi(
        self,
        trades_path: str,
        quotes_path: str,
        max_rows=None,
        timestamp_col: str = "time_exchange",
    ):
        """
        Load CoinAPI parquet files with your exact schema.

        Trades columns:  time_exchange, time_coinapi, price, size, taker_side
        Quotes columns:  time_exchange, time_coinapi, ask_price, ask_size, bid_price, bid_size

        Parameters
        ----------
        timestamp_col : str
            Which timestamp to use. 'time_exchange' is preferred (exchange matching
            engine time). 'time_coinapi' is CoinAPI receipt time.
        """
        import os
        print(f"Loading trades from: {trades_path}")
        trades_df = pd.read_parquet(trades_path)
        if max_rows:
            trades_df = trades_df.head(max_rows)

        print(f"Loading quotes from: {quotes_path}")
        quotes_df = pd.read_parquet(quotes_path)
        if max_rows:
            quotes_df = quotes_df.head(max_rows)

        trades = self._parse_coinapi_trades(trades_df, timestamp_col)
        quotes = self._parse_coinapi_quotes(quotes_df, timestamp_col)

        print(f"Loaded {len(trades):,} trades and {len(quotes):,} quotes.")
        if trades:
            print(f"  Trades: {trades[0].timestamp:.3f} to {trades[-1].timestamp:.3f}")
        if quotes:
            print(f"  Quotes: {quotes[0].timestamp:.3f} to {quotes[-1].timestamp:.3f}")
        if trades:
            prices = [t.price for t in trades]
            print(f"  Price range: {min(prices):.2f} to {max(prices):.2f}")

        return trades, quotes

    def load_coinapi_trades(self, path: str, timestamp_col: str = "time_exchange",
                             max_rows=None):
        """Load just the trades parquet file."""
        df = pd.read_parquet(path)
        if max_rows:
            df = df.head(max_rows)
        return self._parse_coinapi_trades(df, timestamp_col)

    def load_coinapi_quotes(self, path: str, timestamp_col: str = "time_exchange",
                             max_rows=None):
        """Load just the quotes parquet file."""
        df = pd.read_parquet(path)
        if max_rows:
            df = df.head(max_rows)
        return self._parse_coinapi_quotes(df, timestamp_col)

    def _parse_coinapi_trades(self, df, timestamp_col):
        ts = self._parse_coinapi_timestamps(df[timestamp_col])
        sides = self._normalise_sides(df["taker_side"].values)
        qty_col = "size" if "size" in df.columns else "quantity"
        trades = []
        for i in range(len(df)):
            price = float(df["price"].iloc[i])
            qty = float(df[qty_col].iloc[i])
            if price <= 0 or qty <= 0 or np.isnan(price) or np.isnan(qty):
                continue
            trades.append(TradeEvent(
                timestamp=float(ts[i]),
                price=price,
                quantity=qty,
                side=str(sides[i]),
            ))
        return trades

    def _parse_coinapi_quotes(self, df, timestamp_col):
        ts = self._parse_coinapi_timestamps(df[timestamp_col])
        quotes = []
        for i in range(len(df)):
            bid = float(df["bid_price"].iloc[i])
            ask = float(df["ask_price"].iloc[i])
            bid_sz = float(df["bid_size"].iloc[i])
            ask_sz = float(df["ask_size"].iloc[i])
            if bid <= 0 or ask <= 0 or bid >= ask or np.isnan(bid) or np.isnan(ask):
                continue
            quotes.append(QuoteEvent(
                timestamp=float(ts[i]),
                best_bid=bid,
                best_ask=ask,
                bid_size=bid_sz,
                ask_size=ask_sz,
            ))
        return quotes

    def _parse_coinapi_timestamps(self, ts_series):
        """
        CoinAPI timestamps are ISO8601 strings like '2024-01-15T10:30:00.123456Z'
        or pandas Timestamps. Converts to Unix epoch seconds (float).

        Pandas 2.0+ stores datetime64 as microseconds (us) so we divide by 1e6.
        Older pandas used nanoseconds (ns) — we detect which is in use.
        """
        if not pd.api.types.is_datetime64_any_dtype(ts_series):
            ts_series = pd.to_datetime(ts_series, utc=True)

        int_vals = ts_series.astype("int64").values
        # Detect unit: microseconds give ~1.7e15 for 2024, nanoseconds ~1.7e18
        if int_vals[0] > 1e17:
            return int_vals / 1e9   # nanoseconds
        elif int_vals[0] > 1e14:
            return int_vals / 1e6   # microseconds
        else:
            return int_vals.astype(float)  # already seconds

    def load_binance_trades(self, path: str) -> List[TradeEvent]:
        """
        Binance aggTrades CSV columns:
          agg_trade_id, price, quantity, first_trade_id, last_trade_id,
          transact_time, is_buyer_maker
        """
        df = pd.read_csv(path)
        df.columns = [c.lower().strip() for c in df.columns]

        # Normalise column names
        col_map = {
            "transact_time": "timestamp",
            "price": "price",
            "quantity": "qty",
            "is_buyer_maker": "is_buyer_maker",
        }
        for old, new in col_map.items():
            if old in df.columns:
                df.rename(columns={old: new}, inplace=True)

        ts = self._normalise_timestamps(df["timestamp"].values)

        events = []
        for i in range(len(df)):
            is_buyer_maker = bool(df["is_buyer_maker"].iloc[i])
            # If buyer is maker, aggressor is seller
            side = "sell" if is_buyer_maker else "buy"
            events.append(TradeEvent(
                timestamp=float(ts[i]),
                price=float(df["price"].iloc[i]),
                quantity=float(df["qty"].iloc[i]),
                side=side,
            ))
        return events

    def load_binance_orderbook(self, path: str) -> List[QuoteEvent]:
        """
        Binance order book snapshot CSV:
          timestamp, asks[0][0], asks[0][1], bids[0][0], bids[0][1]
          (or similar)
        """
        df = pd.read_csv(path)
        df.columns = [c.lower().strip() for c in df.columns]
        ts = self._normalise_timestamps(df["timestamp"].values)

        # Try to find bid/ask columns
        ask_price_col = next((c for c in df.columns if "ask" in c and "price" in c), None) or \
                        next((c for c in df.columns if c.startswith("ask")), None)
        bid_price_col = next((c for c in df.columns if "bid" in c and "price" in c), None) or \
                        next((c for c in df.columns if c.startswith("bid")), None)

        events = []
        for i in range(len(df)):
            row = df.iloc[i]
            events.append(QuoteEvent(
                timestamp=float(ts[i]),
                best_bid=float(row[bid_price_col]),
                best_ask=float(row[ask_price_col]),
                bid_size=1.0,  # Default if not available
                ask_size=1.0,
            ))
        return events

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_trades(self, df: pd.DataFrame,
                      timestamp_unit: Optional[str] = None) -> List[TradeEvent]:
        df.columns = [c.lower().strip() for c in df.columns]
        ts = self._normalise_timestamps(df["timestamp"].values, timestamp_unit)
        sides = self._normalise_sides(df["side"].values if "side" in df.columns
                                      else np.full(len(df), "buy"))
        qty_col = next((c for c in ["quantity", "qty", "size", "amount", "vol"]
                        if c in df.columns), None)
        qtys = df[qty_col].values if qty_col else np.ones(len(df))

        return [
            TradeEvent(
                timestamp=float(ts[i]),
                price=float(df["price"].iloc[i]),
                quantity=float(qtys[i]),
                side=str(sides[i]),
            )
            for i in range(len(df))
        ]

    def _parse_quotes(self, df: pd.DataFrame,
                      timestamp_unit: Optional[str] = None) -> List[QuoteEvent]:
        df.columns = [c.lower().strip() for c in df.columns]
        ts = self._normalise_timestamps(df["timestamp"].values, timestamp_unit)

        bid_col = next((c for c in ["best_bid", "bid", "bid_price"] if c in df.columns), None)
        ask_col = next((c for c in ["best_ask", "ask", "ask_price"] if c in df.columns), None)
        bid_sz = df["bid_size"].values if "bid_size" in df.columns else np.ones(len(df))
        ask_sz = df["ask_size"].values if "ask_size" in df.columns else np.ones(len(df))

        return [
            QuoteEvent(
                timestamp=float(ts[i]),
                best_bid=float(df[bid_col].iloc[i]),
                best_ask=float(df[ask_col].iloc[i]),
                bid_size=float(bid_sz[i]),
                ask_size=float(ask_sz[i]),
            )
            for i in range(len(df))
        ]

    def _normalise_timestamps(self, ts: np.ndarray,
                               unit: Optional[str] = None) -> np.ndarray:
        """Convert milliseconds or microseconds to seconds."""
        ts = ts.astype(float)
        if unit == "ms" or (unit is None and ts.mean() > 1e12):
            ts /= 1000.0
        elif unit == "us" or (unit is None and ts.mean() > 1e15):
            ts /= 1e6
        return ts

    def _normalise_sides(self, sides: np.ndarray) -> np.ndarray:
        result = []
        for s in sides:
            s_str = str(s).lower().strip()
            if s_str in ("buy", "b", "1", "true", "long"):
                result.append("buy")
            else:
                result.append("sell")
        return np.array(result)


# ===========================================================================
# Synthetic data generator (for testing without real data)
# ===========================================================================

def generate_synthetic_data(
    n_minutes: int = 60,
    tick_interval: float = 0.1,
    mid_start: float = 50_000.0,
    vol_per_second: float = 0.001,
    trade_rate: float = 5.0,
    spread: float = 5.0,
    seed: int = 42,
) -> Tuple[List[TradeEvent], List[QuoteEvent]]:
    """
    Generates synthetic BTC-like tick data for testing.

    Parameters
    ----------
    n_minutes : int
        Length of the simulation.
    tick_interval : float
        Seconds between quote ticks.
    mid_start : float
        Starting mid price.
    vol_per_second : float
        Price vol per second (as fraction of mid).
    trade_rate : float
        Average trades per second.
    spread : float
        Exchange spread in quote currency.
    """
    rng = np.random.default_rng(seed)
    T = n_minutes * 60
    timestamps = np.arange(0.0, T, tick_interval)

    # Generate mid price path (GBM)
    n = len(timestamps)
    dt = tick_interval
    log_rets = rng.normal(0, vol_per_second * np.sqrt(dt), size=n)
    mid_prices = mid_start * np.exp(np.cumsum(log_rets))

    # Quotes
    quotes = []
    for i, t in enumerate(timestamps):
        mid = mid_prices[i]
        quotes.append(QuoteEvent(
            timestamp=t,
            best_bid=mid - spread / 2,
            best_ask=mid + spread / 2,
            bid_size=rng.exponential(1.0),
            ask_size=rng.exponential(1.0),
        ))

    # Trades (Poisson arrivals)
    trades = []
    t = 0.0
    while t < T:
        inter_arrival = rng.exponential(1.0 / trade_rate)
        t += inter_arrival
        if t >= T:
            break

        # Interpolate mid price
        idx = min(int(t / tick_interval), n - 1)
        mid = mid_prices[idx]

        side = "buy" if rng.random() < 0.5 else "sell"
        # Trade at best bid or ask + noise
        if side == "buy":
            price = mid + spread / 2 + rng.normal(0, spread * 0.1)
        else:
            price = mid - spread / 2 + rng.normal(0, spread * 0.1)

        qty = rng.exponential(0.05)  # ~0.05 BTC average

        trades.append(TradeEvent(
            timestamp=t,
            price=abs(price),
            quantity=qty,
            side=side,
        ))

    print(f"Generated {len(trades):,} trades and {len(quotes):,} quotes "
          f"over {n_minutes} minutes.")
    return trades, quotes
