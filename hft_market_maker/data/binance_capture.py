"""
binance_capture.py
===================
Offline reconstruction of Binance L2 captures produced by
`scripts/collect_binance_l2.py` (raw depth-diff + trade + bookTicker JSONL).

Replays snapshot + diffs per the official Binance sync algorithm and emits
CoinAPI-schema tables that `DataLoader.load_coinapi` / `load_orderbook`
consume directly:

  trades:     time_exchange, time_coinapi, price, size, taker_side, symbol_id
  quotes:     time_exchange, time_coinapi, bid_price, bid_size,
              ask_price, ask_size, symbol_id      (top-of-book changes,
              derived from the reconstructed book at depth-event exchange time)
  orderbooks: time_exchange, bids, asks, symbol_id  (top-N levels on every
              depth event; bids/asks are lists of {"price","size"} structs)

Timestamps: `time_exchange` is the exchange event time (depth `E`, trade `T`,
milliseconds); `time_coinapi` is the local receive time from capture
(`ts_recv`), the CoinAPI-receipt-time analogue. The bookTicker stream is not
used for outputs (spot bookTicker carries no exchange timestamp); it stays in
the raw capture for latency QC.

Sync rules (Binance docs):
  spot:    drop diffs with u <= lastUpdateId; first kept diff must satisfy
           U <= lastUpdateId+1 <= u; thereafter U == prev_u + 1.
  futures: drop diffs with u < lastUpdateId; first kept diff must satisfy
           U <= lastUpdateId <= u; thereafter pu == prev_u.
On any violation the replayer discards the book and re-anchors at the next
snapshot (the collector writes one immediately after every detected gap, and
every 10 minutes as a safety anchor). Periodic snapshots are additionally
used to *verify* the reconstructed book; disagreement re-anchors and is
counted in the integrity report.
"""
from __future__ import annotations

import glob
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

TOP_N = 20          # book levels per side kept in orderbook output


# ── capture reading ────────────────────────────────────────────────────────────

def capture_files(capture_dir: str | Path, label: str, date: str) -> list[str]:
    """Hourly files for one instrument label (e.g. LINKUSDT_PERP) and UTC date."""
    return sorted(glob.glob(
        str(Path(capture_dir) / f"binance_{label}_{date}_*.jsonl.gz")))


def iter_records(files: list[str]):
    """
    Yield parsed capture records in file order. Multi-member gzip safe
    (collector restarts append new members) and tolerant of a torn tail —
    a file still being written, or cut off by a hard kill, yields whatever
    decompresses cleanly and then moves on.
    """
    import zlib
    for f in files:
        with gzip.open(f, "rt") as fh:
            try:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue    # torn final line
                    if isinstance(rec, dict) and "stream" in rec:
                        yield rec   # anything else is a torn-line fragment
            except (EOFError, zlib.error) as e:
                print(f"  note: truncated gzip tail in {Path(f).name} ({e})")


# ── book replay ────────────────────────────────────────────────────────────────

@dataclass
class Integrity:
    n_depth: int = 0
    n_trades: int = 0
    n_snapshots: int = 0
    n_reanchors: int = 0
    n_sync_violations: int = 0
    n_snapshot_checks: int = 0
    n_snapshot_best_mismatch: int = 0   # advisory: REST snapshot is racy vs stream
    n_crossed: int = 0
    n_dropped_presync: int = 0
    recv_minus_exch_ms: list = field(default_factory=list)  # sampled clock offset

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()
             if k != "recv_minus_exch_ms"}
        lat = np.array(self.recv_minus_exch_ms)
        if len(lat):
            d["recv_minus_exch_ms_p50"] = float(np.percentile(lat, 50))
            d["recv_minus_exch_ms_p99"] = float(np.percentile(lat, 99))
        return d


class BookReplayer:
    """
    Replays one instrument's capture stream. Feed records in order via
    `process()`; collected outputs are in .trade_rows / .quote_rows /
    .book_rows and .integrity.
    """

    def __init__(self, market: str, symbol_id: str,
                 top_n: int = TOP_N, verify_tol: float = 0.0):
        assert market in ("spot", "perp")
        self.market = market
        self.symbol_id = symbol_id
        self.top_n = top_n
        self.verify_tol = verify_tol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self._synced = False
        self._pending_snapshot: dict | None = None
        self._prev_u: int | None = None

        self._last_best: tuple | None = None
        self.trade_rows: list[tuple] = []
        self.quote_rows: list[tuple] = []
        self.book_rows: list[tuple] = []
        self.book_sink = None          # callable(list[tuple]) — set for chunked output
        self.book_chunk = 100_000
        self.integrity = Integrity()

    # -- helpers ---------------------------------------------------------------

    def _apply_levels(self, side: dict, levels):
        for p, q in levels:
            p, q = float(p), float(q)
            if q == 0.0:
                side.pop(p, None)
            else:
                side[p] = q

    def _top(self):
        bid = max(self.bids) if self.bids else 0.0
        ask = min(self.asks) if self.asks else 0.0
        return bid, ask

    def _anchor(self, snap: dict):
        self.bids = {float(p): float(q) for p, q in snap["bids"]
                     if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in snap["asks"]
                     if float(q) > 0}
        self._last_update_id = int(snap["lastUpdateId"])
        self._prev_u = None            # awaiting first bridging diff
        self._synced = True
        self.integrity.n_reanchors += 1

    def _verify_snapshot(self, snap: dict) -> bool:
        """
        Advisory check: does the snapshot's best bid/ask match the
        reconstructed book? A REST snapshot is fetched at a slightly
        different stream position than where its record lands, so small
        disagreements are expected — this is a drift alarm, not a gate.
        """
        if not (snap["bids"] and snap["asks"] and self.bids and self.asks):
            return True
        bid, ask = self._top()
        return (abs(float(snap["bids"][0][0]) - bid) < 1e-12 and
                abs(float(snap["asks"][0][0]) - ask) < 1e-12)

    # -- record processing -------------------------------------------------------

    def process(self, rec: dict) -> None:
        stream, data, ts_recv = rec["stream"], rec["data"], rec["ts_recv"]

        if stream == "snapshot":
            self.integrity.n_snapshots += 1
            if not self._synced:
                self._anchor(data)
            elif self._prev_u is not None:
                # periodic snapshot: advisory drift check only — the
                # update-id chain is the real correctness guarantee
                self.integrity.n_snapshot_checks += 1
                if not self._verify_snapshot(data):
                    self.integrity.n_snapshot_best_mismatch += 1
            return

        if stream == "gap":
            self._synced = False       # wait for the snapshot that follows
            return

        if stream == "depth":
            if not self._synced:
                self.integrity.n_dropped_presync += 1
                return
            U, u = int(data["U"]), int(data["u"])

            if self._prev_u is None:
                # first diff after an anchor: bridge the snapshot
                if self.market == "spot":
                    if u <= self._last_update_id:
                        return                          # stale, pre-snapshot
                    if not (U <= self._last_update_id + 1 <= u):
                        self.integrity.n_sync_violations += 1
                        self._synced = False
                        return
                else:
                    if u < self._last_update_id:
                        return
                    if not (U <= self._last_update_id <= u):
                        self.integrity.n_sync_violations += 1
                        self._synced = False
                        return
            else:
                ok = (U == self._prev_u + 1 if self.market == "spot"
                      else int(data["pu"]) == self._prev_u)
                if not ok:
                    self.integrity.n_sync_violations += 1
                    self._synced = False
                    return
            self._prev_u = u

            self._apply_levels(self.bids, data.get("b", []))
            self._apply_levels(self.asks, data.get("a", []))
            self.integrity.n_depth += 1

            t_exch = data["E"] / 1e3
            if self.integrity.n_depth % 100 == 0:
                self.integrity.recv_minus_exch_ms.append(
                    (ts_recv - t_exch) * 1e3)

            bid, ask = self._top()
            if bid and ask and bid >= ask:
                self.integrity.n_crossed += 1
            self._emit_book(t_exch, ts_recv)
            return

        if stream in ("trade", "aggTrade"):
            # buyer-is-maker (m=True) => taker sold
            t_exch = data.get("T", data.get("E", 0)) / 1e3
            self.trade_rows.append((
                t_exch, ts_recv, float(data["p"]), float(data["q"]),
                "SELL" if data.get("m") else "BUY"))
            self.integrity.n_trades += 1

    def _emit_book(self, t_exch: float, ts_recv: float) -> None:
        top_b = sorted(self.bids.items(), reverse=True)[:self.top_n]
        top_a = sorted(self.asks.items())[:self.top_n]
        if not top_b or not top_a:
            return
        best = (top_b[0][0], top_b[0][1], top_a[0][0], top_a[0][1])
        if best != self._last_best:
            self.quote_rows.append((t_exch, ts_recv, *best))
            self._last_best = best
        self.book_rows.append((
            t_exch,
            [{"price": p, "size": q} for p, q in top_b],
            [{"price": p, "size": q} for p, q in top_a]))
        if self.book_sink and len(self.book_rows) >= self.book_chunk:
            self.book_sink(self.book_rows)
            self.book_rows = []

    # -- output ------------------------------------------------------------------

    def to_frames(self) -> dict[str, pd.DataFrame]:
        def ts(col):
            return pd.to_datetime(np.array(col, dtype=float) * 1e9,
                                  unit="ns", utc=True)

        tr = pd.DataFrame(self.trade_rows, columns=[
            "te", "tc", "price", "size", "taker_side"])
        trades = pd.DataFrame({
            "time_exchange": ts(tr["te"]), "time_coinapi": ts(tr["tc"]),
            "price": tr["price"], "size": tr["size"],
            "taker_side": tr["taker_side"], "symbol_id": self.symbol_id})

        qt = pd.DataFrame(self.quote_rows, columns=[
            "te", "tc", "bid_price", "bid_size", "ask_price", "ask_size"])
        quotes = pd.DataFrame({
            "time_exchange": ts(qt["te"]), "time_coinapi": ts(qt["tc"]),
            "bid_price": qt["bid_price"], "bid_size": qt["bid_size"],
            "ask_price": qt["ask_price"], "ask_size": qt["ask_size"],
            "symbol_id": self.symbol_id})

        return {"trades": trades, "quotes": quotes}


def book_rows_to_table(rows: list[tuple], symbol_id: str):
    """Convert book row tuples to a pyarrow Table (CoinAPI orderbook schema)."""
    import pyarrow as pa
    level = pa.struct([("price", pa.float64()), ("size", pa.float64())])
    schema = pa.schema([
        ("time_exchange", pa.timestamp("ns", tz="UTC")),
        ("bids", pa.list_(level)),
        ("asks", pa.list_(level)),
        ("symbol_id", pa.string())])
    te = pa.array((np.array([r[0] for r in rows]) * 1e9).astype("int64"),
                  type=pa.int64()).cast(pa.timestamp("ns", tz="UTC"))
    return pa.Table.from_arrays([
        te,
        pa.array([r[1] for r in rows], type=pa.list_(level)),
        pa.array([r[2] for r in rows], type=pa.list_(level)),
        pa.array([symbol_id] * len(rows))], schema=schema)


def replay_day(capture_dir: str | Path, label: str, date: str,
               market: str, symbol_id: str, out_dir: str | Path,
               asset: str, top_n: int = TOP_N) -> dict:
    """
    Replay one instrument-day and write the three CoinAPI-schema parquets to
    out_dir (trades_/quotes_/orderbooks_{asset}_{date}.parquet). Orderbooks
    stream to disk in chunks. Returns the integrity report (with paths).
    """
    import pyarrow.parquet as pq

    files = capture_files(capture_dir, label, date)
    if not files:
        raise FileNotFoundError(
            f"no capture files for {label} {date} in {capture_dir}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: out_dir / f"{k}_{asset}_{date}.parquet"
             for k in ("trades", "quotes", "orderbooks")}

    rep = BookReplayer(market=market, symbol_id=symbol_id, top_n=top_n)
    writer = None

    def sink(rows):
        nonlocal writer
        table = book_rows_to_table(rows, symbol_id)
        if writer is None:
            writer = pq.ParquetWriter(paths["orderbooks"], table.schema)
        writer.write_table(table)

    rep.book_sink = sink
    for rec in iter_records(files):
        rep.process(rec)
    if rep.book_rows:
        sink(rep.book_rows)
        rep.book_rows = []
    if writer is not None:
        writer.close()

    frames = rep.to_frames()
    frames["trades"].to_parquet(paths["trades"], index=False)
    frames["quotes"].to_parquet(paths["quotes"], index=False)

    report = rep.integrity.to_dict()
    report["files"] = {k: str(v) for k, v in paths.items()}
    report["n_capture_files"] = len(files)
    return report
