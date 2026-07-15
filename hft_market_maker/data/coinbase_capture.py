"""
coinbase_capture.py
===================
Offline reconstruction of Coinbase captures into the same CoinAPI-schema
parquets as binance_capture.py, so DataLoader and every experiment script
consume them unchanged.

Two feeds, two reconstructions:

SPOT (collect_coinbase_l2.py, Exchange feed — full L2):
  snapshot sets the book; each l2update applies [side, price, size] changes
  (size 0 removes the level). Continuity is per-connection; a reconnect writes
  a `gap` and Coinbase re-sends a fresh snapshot, which re-anchors. Best
  bid/ask is tracked incrementally (a full min/max only when the touch level is
  removed) so a 6k-level book stays cheap. Emits trades + quotes; top-20
  orderbooks only with want_books=True (heavier).

PERP (collect_coinbase_perp.py, Advanced Trade feed — top-of-book only):
  ticker -> quotes (best_bid/ask + sizes); market_trades -> trades. No L2 there
  (that channel needs auth). One combined capture file carries both products;
  split by product_id inside events[].

taker_side:
  spot match `side` is the MAKER side => taker is the opposite (side=sell means
  the maker sold, so the taker BOUGHT).
  perp market_trades side is convention-ambiguous, so taker_side is inferred by
  price vs the prevailing ticker mid (>= mid => BUY), matching the project's
  price-only fill convention; the reported side is the fallback before the first
  quote is seen.

Output assets: CB_LINK, CB_BTC (spot); CB_LINK_PERP, CB_BTC_PERP (perp) — kept
distinct from the Binance assets so both venues coexist in the processed dir.
"""
from __future__ import annotations

import glob
import heapq
from pathlib import Path

import numpy as np
import pandas as pd

from .binance_capture import iter_records   # generic {"stream",...} line reader

TOP_N = 20


def capture_files(capture_dir: str | Path, label: str, date: str) -> list[str]:
    """Hourly files for one Coinbase label (LINKUSD, BTCUSD, PERPINTX) + UTC date."""
    return sorted(glob.glob(
        str(Path(capture_dir) / f"coinbase_{label}_{date}_*.jsonl.gz")))


def _iso(series) -> pd.Series:
    return pd.to_datetime(pd.Series(list(series), dtype="object"),
                          utc=True, format="ISO8601")


def _epoch(series) -> pd.Series:
    return pd.to_datetime(np.asarray(series, dtype=float) * 1e9, unit="ns", utc=True)


# ── spot: full-book reconstruction ────────────────────────────────────────────

class SpotReplayer:
    def __init__(self, symbol_id: str, top_n: int = TOP_N, want_books: bool = False):
        self.symbol_id = symbol_id
        self.top_n = top_n
        self.want_books = want_books
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.best_bid = 0.0
        self.best_ask = 0.0
        self._synced = False
        self._last_best = None
        self.trade_rows: list[tuple] = []
        self.quote_rows: list[tuple] = []
        self.book_rows: list[tuple] = []
        self.book_sink = None
        self.book_chunk = 100_000
        self.n_l2 = self.n_trades = self.n_snapshots = 0
        self.n_gaps = self.n_crossed = 0
        self.recv_minus_exch_ms: list[float] = []

    def _recompute_bid(self):
        self.best_bid = max(self.bids) if self.bids else 0.0

    def _recompute_ask(self):
        self.best_ask = min(self.asks) if self.asks else 0.0

    def process(self, rec: dict) -> None:
        stream, data, ts = rec["stream"], rec["data"], rec["ts_recv"]

        if stream == "snapshot":
            self.n_snapshots += 1
            self.bids = {float(p): float(s) for p, s in data["bids"] if float(s) > 0}
            self.asks = {float(p): float(s) for p, s in data["asks"] if float(s) > 0}
            self._recompute_bid()
            self._recompute_ask()
            self._synced = True
            self._last_best = None
            return

        if stream == "gap":
            self._synced = False
            self.n_gaps += 1
            return

        if stream == "l2update":
            if not self._synced:
                return
            t_exch = data.get("time")
            for ch in data.get("changes", []):
                side, price, size = ch[0], float(ch[1]), float(ch[2])
                if side == "buy":
                    if size == 0.0:
                        self.bids.pop(price, None)
                        if price >= self.best_bid:
                            self._recompute_bid()
                    else:
                        self.bids[price] = size
                        if price > self.best_bid:
                            self.best_bid = price
                else:
                    if size == 0.0:
                        self.asks.pop(price, None)
                        if self.best_ask and price <= self.best_ask:
                            self._recompute_ask()
                    else:
                        self.asks[price] = size
                        if not self.best_ask or price < self.best_ask:
                            self.best_ask = price
            self.n_l2 += 1
            if self.n_l2 % 100 == 0 and t_exch:
                try:
                    te = pd.Timestamp(t_exch).timestamp()
                    self.recv_minus_exch_ms.append((ts - te) * 1e3)
                except Exception:
                    pass

            b, a = self.best_bid, self.best_ask
            if not (b and a):
                return
            if b >= a:
                self.n_crossed += 1
            best = (b, self.bids.get(b, 0.0), a, self.asks.get(a, 0.0))
            if best != self._last_best:
                self.quote_rows.append((t_exch, ts, *best))
                self._last_best = best
            if self.want_books:
                tb = heapq.nlargest(self.top_n, self.bids.items())
                ta = heapq.nsmallest(self.top_n, self.asks.items())
                self.book_rows.append((
                    t_exch,
                    [{"price": p, "size": q} for p, q in tb],
                    [{"price": p, "size": q} for p, q in ta]))
                if self.book_sink and len(self.book_rows) >= self.book_chunk:
                    self.book_sink(self.book_rows)
                    self.book_rows = []
            return

        if stream == "match" and data.get("type") == "match":
            # skip the one-shot "last_match" snapshot; take live matches only
            price, size = float(data["price"]), float(data["size"])
            taker = "BUY" if data.get("side") == "sell" else "SELL"
            self.trade_rows.append((data.get("time"), ts, price, size, taker))
            self.n_trades += 1

    def to_frames(self) -> dict[str, pd.DataFrame]:
        tr = pd.DataFrame(self.trade_rows,
                          columns=["te", "tc", "price", "size", "taker_side"])
        trades = pd.DataFrame({
            "time_exchange": _iso(tr["te"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "time_coinapi": _epoch(tr["tc"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "price": tr["price"] if len(tr) else [],
            "size": tr["size"] if len(tr) else [],
            "taker_side": tr["taker_side"] if len(tr) else [],
            "symbol_id": self.symbol_id})
        qt = pd.DataFrame(self.quote_rows,
                          columns=["te", "tc", "bid_price", "bid_size",
                                   "ask_price", "ask_size"])
        quotes = pd.DataFrame({
            "time_exchange": _iso(qt["te"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "time_coinapi": _epoch(qt["tc"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "bid_price": qt["bid_price"] if len(qt) else [],
            "bid_size": qt["bid_size"] if len(qt) else [],
            "ask_price": qt["ask_price"] if len(qt) else [],
            "ask_size": qt["ask_size"] if len(qt) else [],
            "symbol_id": self.symbol_id})
        return {"trades": trades.dropna(subset=["time_exchange"]),
                "quotes": quotes.dropna(subset=["time_exchange"])}


# ── perp: top-of-book from ticker, trades from market_trades ───────────────────

class PerpReplayer:
    def __init__(self, product_symbol: dict[str, str]):
        # product_symbol: {"BTC-PERP-INTX": "CB_BTC_PERP", ...}
        self.map = product_symbol
        self.trade_rows = {p: [] for p in product_symbol}
        self.quote_rows = {p: [] for p in product_symbol}
        self.last_quote = {p: None for p in product_symbol}
        self.n_trades = {p: 0 for p in product_symbol}
        self.n_quotes = {p: 0 for p in product_symbol}

    def process(self, rec: dict) -> None:
        stream, data = rec["stream"], rec["data"]
        ts = rec["ts_recv"]
        if stream == "ticker":
            env_t = data.get("timestamp")
            for ev in data.get("events", []):
                for tk in ev.get("tickers", []):
                    pid = tk.get("product_id")
                    if pid not in self.map:
                        continue
                    bb, ba = tk.get("best_bid"), tk.get("best_ask")
                    if bb is None or ba is None:
                        continue
                    bb, ba = float(bb), float(ba)
                    self.quote_rows[pid].append((
                        env_t, ts, bb, float(tk.get("best_bid_quantity", 0) or 0),
                        ba, float(tk.get("best_ask_quantity", 0) or 0)))
                    self.last_quote[pid] = (bb, ba)
                    self.n_quotes[pid] += 1
        elif stream == "market_trades":
            for ev in data.get("events", []):
                for t in ev.get("trades", []):
                    pid = t.get("product_id")
                    if pid not in self.map:
                        continue
                    price, size = float(t["price"]), float(t["size"])
                    q = self.last_quote.get(pid)
                    if q:
                        taker = "BUY" if price >= (q[0] + q[1]) / 2 else "SELL"
                    else:
                        taker = (t.get("side") or "BUY").upper()
                    self.trade_rows[pid].append((t.get("time"), ts, price, size, taker))
                    self.n_trades[pid] += 1

    def frames_for(self, pid: str) -> dict[str, pd.DataFrame]:
        sym = self.map[pid]
        tr = pd.DataFrame(self.trade_rows[pid],
                          columns=["te", "tc", "price", "size", "taker_side"])
        trades = pd.DataFrame({
            "time_exchange": _iso(tr["te"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "time_coinapi": _epoch(tr["tc"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "price": tr["price"] if len(tr) else [],
            "size": tr["size"] if len(tr) else [],
            "taker_side": tr["taker_side"] if len(tr) else [],
            "symbol_id": sym})
        qt = pd.DataFrame(self.quote_rows[pid],
                          columns=["te", "tc", "bid_price", "bid_size",
                                   "ask_price", "ask_size"])
        quotes = pd.DataFrame({
            "time_exchange": _iso(qt["te"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "time_coinapi": _epoch(qt["tc"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
            "bid_price": qt["bid_price"] if len(qt) else [],
            "bid_size": qt["bid_size"] if len(qt) else [],
            "ask_price": qt["ask_price"] if len(qt) else [],
            "ask_size": qt["ask_size"] if len(qt) else [],
            "symbol_id": sym})
        return {"trades": trades.dropna(subset=["time_exchange"]),
                "quotes": quotes.dropna(subset=["time_exchange"])}


# ── drivers ────────────────────────────────────────────────────────────────────

def _book_table(rows, symbol_id):
    import pyarrow as pa
    level = pa.struct([("price", pa.float64()), ("size", pa.float64())])
    schema = pa.schema([
        ("time_exchange", pa.timestamp("ns", tz="UTC")),
        ("bids", pa.list_(level)), ("asks", pa.list_(level)),
        ("symbol_id", pa.string())])
    te = pa.array(_iso([r[0] for r in rows]).view("int64"),
                  type=pa.int64()).cast(pa.timestamp("ns", tz="UTC"))
    return pa.Table.from_arrays([
        te, pa.array([r[1] for r in rows], type=pa.list_(level)),
        pa.array([r[2] for r in rows], type=pa.list_(level)),
        pa.array([symbol_id] * len(rows))], schema=schema)


def replay_spot_day(capture_dir, label, date, symbol_id, out_dir, asset,
                    top_n=TOP_N, want_books=False) -> dict:
    import pyarrow.parquet as pq
    files = capture_files(capture_dir, label, date)
    if not files:
        raise FileNotFoundError(f"no capture files for coinbase {label} {date}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: out_dir / f"{k}_{asset}_{date}.parquet"
             for k in ("trades", "quotes", "orderbooks")}

    rep = SpotReplayer(symbol_id, top_n=top_n, want_books=want_books)
    writer = None

    def sink(rows):
        nonlocal writer
        table = _book_table(rows, symbol_id)
        if writer is None:
            writer = pq.ParquetWriter(paths["orderbooks"], table.schema)
        writer.write_table(table)

    rep.book_sink = sink
    for rec in iter_records(files):
        rep.process(rec)
    if want_books and rep.book_rows:
        sink(rep.book_rows)
    if writer is not None:
        writer.close()

    frames = rep.to_frames()
    frames["trades"].to_parquet(paths["trades"], index=False)
    frames["quotes"].to_parquet(paths["quotes"], index=False)
    lat = np.array(rep.recv_minus_exch_ms)
    return {"asset": asset, "n_l2": rep.n_l2, "n_trades": rep.n_trades,
            "n_snapshots": rep.n_snapshots, "n_gaps": rep.n_gaps,
            "n_crossed": rep.n_crossed, "n_quotes": len(frames["quotes"]),
            "n_capture_files": len(files),
            "recv_minus_exch_ms_p50": float(np.percentile(lat, 50)) if len(lat) else None,
            "wrote_orderbooks": bool(want_books),
            "files": {k: str(v) for k, v in paths.items()
                      if k != "orderbooks" or want_books}}


def replay_perp_day(capture_dir, date, product_asset, out_dir) -> dict:
    # product_asset: {"BTC-PERP-INTX": "CB_BTC_PERP", "LINK-PERP-INTX": "CB_LINK_PERP"}
    files = capture_files(capture_dir, "PERPINTX", date)
    if not files:
        raise FileNotFoundError(f"no capture files for coinbase PERPINTX {date}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    product_symbol = {p: a for p, a in product_asset.items()}
    rep = PerpReplayer(product_symbol)
    for rec in iter_records(files):
        rep.process(rec)
    report = {"n_capture_files": len(files), "products": {}}
    for pid, asset in product_asset.items():
        frames = rep.frames_for(pid)
        for k in ("trades", "quotes"):
            frames[k].to_parquet(out_dir / f"{k}_{asset}_{date}.parquet", index=False)
        report["products"][asset] = {"n_trades": len(frames["trades"]),
                                     "n_quotes": len(frames["quotes"])}
    return report
