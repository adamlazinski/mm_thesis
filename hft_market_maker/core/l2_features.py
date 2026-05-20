"""
L2 order book feature extractor.

Parses CoinAPI orderbook snapshot parquets and provides:
  - Queue depth at best bid/ask
  - Multi-level OBI (order book imbalance) at levels 1, 3, 5, 10
  - Queue-aware fill probability estimate
  - Book shape features

Snapshot format (from CoinAPI):
  columns: symbol_id, time_exchange, time_coinapi, asks, bids
  asks/bids: list of {'price': float, 'size': float} sorted best-first
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict


@dataclass
class BookSnapshot:
    timestamp: float
    best_bid_price: float
    best_ask_price: float
    best_bid_depth: float   # LINK at best bid
    best_ask_depth: float   # LINK at best ask
    obi_l1:  float          # (bid_d1 - ask_d1) / (bid_d1 + ask_d1)
    obi_l3:  float
    obi_l5:  float
    obi_l10: float
    total_bid_depth: float  # sum of top-10 bid levels
    total_ask_depth: float


def _depth_n(levels: list, n: int) -> float:
    return sum(l["size"] for l in levels[:n])


def _obi(bid_levels: list, ask_levels: list, n: int) -> float:
    b = _depth_n(bid_levels, n)
    a = _depth_n(ask_levels, n)
    denom = b + a
    return (b - a) / denom if denom > 1e-9 else 0.0


def parse_snapshot(row) -> BookSnapshot:
    bids = list(row["bids"]) if row["bids"] is not None else []
    asks = list(row["asks"]) if row["asks"] is not None else []
    ts = row["time_exchange"]
    if hasattr(ts, "timestamp"):
        ts = ts.timestamp()

    return BookSnapshot(
        timestamp=float(ts),
        best_bid_price=bids[0]["price"] if bids else 0.0,
        best_ask_price=asks[0]["price"] if asks else 0.0,
        best_bid_depth=bids[0]["size"]  if bids else 0.0,
        best_ask_depth=asks[0]["size"]  if asks else 0.0,
        obi_l1 =_obi(bids, asks, 1),
        obi_l3 =_obi(bids, asks, 3),
        obi_l5 =_obi(bids, asks, 5),
        obi_l10=_obi(bids, asks, 10),
        total_bid_depth=_depth_n(bids, 10),
        total_ask_depth=_depth_n(asks, 10),
    )


def load_snapshots(path: str) -> List[BookSnapshot]:
    """Load all snapshots from a single orderbook parquet file."""
    df = pd.read_parquet(path)
    return [parse_snapshot(row) for _, row in df.iterrows()]


class L2BookTracker:
    """
    Rolling L2 tracker for use inside the backtest event loop.

    Usage:
        tracker = L2BookTracker(snapshots)
        # At each event timestamp, call:
        snap = tracker.at(timestamp)
        # snap is the most recent BookSnapshot <= timestamp
    """

    def __init__(self, snapshots: List[BookSnapshot]):
        self._snaps = sorted(snapshots, key=lambda s: s.timestamp)
        self._timestamps = np.array([s.timestamp for s in self._snaps])
        self._idx = 0

    def at(self, timestamp: float) -> Optional[BookSnapshot]:
        """Return the most recent snapshot at or before timestamp."""
        if not self._snaps:
            return None
        idx = np.searchsorted(self._timestamps, timestamp, side="right") - 1
        if idx < 0:
            return None
        return self._snaps[idx]

    def advance(self, timestamp: float) -> Optional[BookSnapshot]:
        """Sequentially advance — faster than binary search in event loop."""
        snaps = self._snaps
        while self._idx + 1 < len(snaps) and snaps[self._idx + 1].timestamp <= timestamp:
            self._idx += 1
        return snaps[self._idx] if self._idx < len(snaps) else None


class QueueModel:
    """
    Estimates fill probability based on queue position.

    For inside-spread orders (new NBBO): queue_ahead = 0, always fills on
    any trade at the price level — consistent with price-only model.

    For at-touch or outside orders: fill only when cumulative trade volume
    since order posting exceeds queue_ahead.

    Parameters
    ----------
    tick_size : float
        Asset tick size ($0.001 for LINK)
    inside_spread_ticks : int
        If our order is this many ticks inside the natural spread, treat
        queue_ahead as 0. Default 1 (any inside-spread quote).
    """

    def __init__(self, tick_size: float = 0.001, inside_spread_ticks: int = 1):
        self.tick_size = tick_size
        self.inside_spread_ticks = inside_spread_ticks

    def queue_ahead(
        self,
        order_price: float,
        side: str,             # "bid" or "ask"
        natural_bid: float,
        natural_ask: float,
        bid_depth: float,      # queue at natural bid
        ask_depth: float,      # queue at natural ask
    ) -> float:
        """
        Estimate how much volume is ahead of our order in the queue.

        Returns 0 for inside-spread orders (we are the NBBO).
        Returns the natural touch depth for at-touch or outside orders.
        """
        eps = 1e-9  # float guard

        if side == "bid":
            # Strictly better than natural bid = inside spread, queue_ahead = 0
            if order_price > natural_bid + eps:
                return 0.0
            return bid_depth  # at touch or outside — behind natural queue

        else:  # ask
            # Strictly better than natural ask = inside spread, queue_ahead = 0
            if order_price < natural_ask - eps:
                return 0.0
            return ask_depth

    def fill_probability(
        self,
        queue_ahead: float,
        order_size: float,
        expected_trade_size: float,
        n_trades_per_sec: float,
        hold_sec: float,
    ) -> float:
        """
        Rough fill probability over the hold window given queue position.

        P(fill) ≈ P(cumulative volume in window > queue_ahead)
        Modelled as: expected_volume_in_window / (queue_ahead + order_size)
        Clamped to [0, 1].
        """
        if queue_ahead <= 0:
            return 1.0  # inside spread, always fills on any trade
        expected_volume = n_trades_per_sec * hold_sec * expected_trade_size
        return min(1.0, expected_volume / (queue_ahead + order_size + 1e-9))
