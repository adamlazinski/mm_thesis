"""
collect_binance_l2.py
======================
Live Binance L2 collector — raw depth-diff + trade + bookTicker capture, for
spot and USDT-M perpetual markets.

Purpose: build a true historical orderbook evolution (event-level, not 1Hz
snapshots) so backtests can (a) reconstruct real queue depth through any price
level, (b) validate the quote-proxy L2 tracker against the full book on the
same day, and (c) calibrate the queue_fraction heuristic.

Capture design (raw-first): every websocket message is appended verbatim, with
a local receive timestamp, to hourly-rotated gzipped JSONL files. A REST depth
snapshot is written into the same file at start, on every reconnect/gap, and
every SNAPSHOT_EVERY_S as a safety anchor. Book reconstruction happens offline
(snapshot + diff replay, official sync algorithm) — nothing is interpreted at
capture time, so a collector bug cannot corrupt the record.

Continuity rules differ per market and both are checked:
  spot: each depth diff carries U/u; gap if U != prev_u + 1
  perp: each depth diff carries pu (previous stream u); gap if pu != prev_u
A gap is logged in-band and triggers a fresh snapshot so offline
reconstruction can re-anchor.

Trade streams: raw @trade on both markets (futures @aggTrade is documented but
was observed silent on fstream as of 2026-07; raw @trade delivers there).

Output: {out}/binance_{LABEL}_{YYYY-MM-DD_HH}.jsonl.gz   (LABEL = SYMBOL or SYMBOL_PERP)
        lines: {"ts_recv": <epoch float>, "stream": "depth|trade|aggTrade|bookTicker|snapshot|gap", "data": {...}}

Usage (requires: pip install websockets):
    python scripts/collect_binance_l2.py \
        --symbol LINKUSDT --symbol BTCUSDT \
        --perp LINKUSDT --perp BTCUSDT \
        --out data/live --hours 25

On macOS, prevent sleep for the duration:
    caffeinate -i python scripts/collect_binance_l2.py ...
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import signal
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("pip install websockets certifi  (not in .venv yet)")

# This Python install has no default CA bundle (macOS python.org framework
# without Install Certificates.command) — use certifi's bundle if present.
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

SNAPSHOT_EVERY_S = 600          # periodic safety snapshot
RECONNECT_BACKOFF_S = [1, 2, 5, 10, 30]

MARKETS = {
    "spot": {
        "ws_base": "wss://stream.binance.com:9443/stream?streams=",
        "rest_depth": "https://api.binance.com/api/v3/depth?symbol={symbol}&limit=5000",
        "trade_stream": "trade",
    },
    "perp": {
        "ws_base": "wss://fstream.binance.com/stream?streams=",
        "rest_depth": "https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit=1000",
        # NB: docs say futures only has @aggTrade, but as of 2026-07 the
        # fstream @aggTrade stream is silent while raw @trade delivers.
        "trade_stream": "trade",
    },
}


@dataclass
class Instrument:
    symbol: str          # e.g. LINKUSDT
    market: str          # "spot" | "perp"

    @property
    def label(self) -> str:
        return self.symbol + ("_PERP" if self.market == "perp" else "")

    @property
    def streams(self) -> str:
        s = self.symbol.lower()
        trade = MARKETS[self.market]["trade_stream"]
        return f"{s}@depth@100ms/{s}@{trade}/{s}@bookTicker"

    @property
    def ws_url(self) -> str:
        return MARKETS[self.market]["ws_base"] + self.streams

    @property
    def rest_depth_url(self) -> str:
        return MARKETS[self.market]["rest_depth"].format(symbol=self.symbol)

    def is_gap(self, prev_u: int | None, data: dict) -> bool:
        if prev_u is None:
            return False
        if self.market == "spot":
            return data.get("U") != prev_u + 1
        return data.get("pu") != prev_u


class HourlyGzWriter:
    """Appends JSON lines to an hourly-rotated .jsonl.gz file per instrument."""

    FLUSH_EVERY_S = 5.0
    # Per-launch tag in the filename so a restart never appends to a file
    # another process created (concurrent/interleaved gzip members corrupt
    # the archive; observed on the 2026-07-10 restart boundary).
    RUN_TAG = time.strftime("%H%M%S", time.gmtime())

    def __init__(self, out_dir: Path, label: str):
        self.out_dir = out_dir
        self.label = label
        self._fh = None
        self._hour_key = None
        self._last_flush = 0.0
        self.n_lines = 0

    def _rotate_if_needed(self, ts: float):
        hour_key = time.strftime("%Y-%m-%d_%H", time.gmtime(ts))
        if hour_key != self._hour_key:
            if self._fh:
                self._fh.close()
            path = (self.out_dir /
                    f"binance_{self.label}_{hour_key}_r{self.RUN_TAG}.jsonl.gz")
            self._fh = gzip.open(path, "at")
            self._hour_key = hour_key
            print(f"[{self.label}] writing -> {path}")

    def write(self, ts: float, stream: str, data) -> None:
        self._rotate_if_needed(ts)
        self._fh.write(json.dumps(
            {"ts_recv": ts, "stream": stream, "data": data},
            separators=(",", ":")) + "\n")
        self.n_lines += 1
        if ts - self._last_flush > self.FLUSH_EVERY_S:
            self._fh.flush()          # Z_SYNC_FLUSH: pending bytes hit disk
            self._last_flush = ts

    def close(self):
        if self._fh:
            self._fh.close()


def fetch_snapshot(inst: Instrument) -> dict:
    req = urllib.request.Request(inst.rest_depth_url,
                                 headers={"User-Agent": "l2-collector/1.0"})
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
        return json.load(r)


async def collect_instrument(inst: Instrument, out_dir: Path,
                             stop_at: float) -> None:
    writer = HourlyGzWriter(out_dir, inst.label)
    backoff_i = 0
    prev_u = None          # last depth final-update-id seen
    last_snapshot_t = 0.0
    n_gaps = 0

    def snapshot(reason: str):
        nonlocal last_snapshot_t
        try:
            snap = fetch_snapshot(inst)
            writer.write(time.time(), "snapshot", {"reason": reason, **snap})
            last_snapshot_t = time.time()
            print(f"[{inst.label}] snapshot ({reason}) "
                  f"lastUpdateId={snap['lastUpdateId']}")
        except Exception as e:
            print(f"[{inst.label}] snapshot FAILED ({reason}): {e}")

    while time.time() < stop_at:
        try:
            async with websockets.connect(inst.ws_url, ssl=SSL_CTX,
                                          ping_interval=20,
                                          max_size=2**23) as ws:
                print(f"[{inst.label}] connected ({inst.market})")
                backoff_i = 0
                snapshot("connect")
                prev_u = None      # re-anchor continuity after reconnect
                async for raw in ws:
                    now = time.time()
                    msg = json.loads(raw)
                    stream = msg.get("stream", "")
                    data = msg.get("data", msg)

                    if "@depth" in stream:
                        if inst.is_gap(prev_u, data):
                            n_gaps += 1
                            print(f"[{inst.label}] depth GAP #{n_gaps}: "
                                  f"prev_u={prev_u} U={data.get('U')} "
                                  f"pu={data.get('pu')}")
                            writer.write(now, "gap",
                                         {"prev_u": prev_u,
                                          "U": data.get("U"),
                                          "pu": data.get("pu")})
                            snapshot("gap")
                        prev_u = data.get("u")
                        writer.write(now, "depth", data)
                    elif "@trade" in stream:
                        writer.write(now, "trade", data)
                    elif "@aggTrade" in stream:
                        writer.write(now, "aggTrade", data)
                    elif "@bookTicker" in stream:
                        writer.write(now, "bookTicker", data)
                    else:
                        writer.write(now, "other", msg)

                    if now - last_snapshot_t > SNAPSHOT_EVERY_S:
                        snapshot("periodic")
                    if now >= stop_at:
                        break
        except asyncio.CancelledError:
            break
        except Exception as e:
            wait = RECONNECT_BACKOFF_S[min(backoff_i,
                                           len(RECONNECT_BACKOFF_S) - 1)]
            backoff_i += 1
            print(f"[{inst.label}] ws error: {e} — reconnect in {wait}s")
            await asyncio.sleep(wait)

    writer.close()
    print(f"[{inst.label}] done: {writer.n_lines} lines, {n_gaps} depth gaps")


async def main_async(args) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    instruments = ([Instrument(s.upper(), "spot") for s in args.symbol or []] +
                   [Instrument(s.upper(), "perp") for s in args.perp or []])
    if not instruments:
        sys.exit("nothing to collect: pass --symbol and/or --perp")
    stop_at = time.time() + args.hours * 3600
    print(f"Collecting {[i.label for i in instruments]} for {args.hours}h "
          f"-> {out_dir}/  (ctrl-C to stop early)")
    tasks = [asyncio.create_task(collect_instrument(i, out_dir, stop_at))
             for i in instruments]
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: [t.cancel() for t in tasks])
    await asyncio.gather(*tasks, return_exceptions=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", action="append",
                   help="spot symbol, e.g. LINKUSDT (repeatable)")
    p.add_argument("--perp", action="append",
                   help="USDT-M perpetual symbol, e.g. LINKUSDT (repeatable)")
    p.add_argument("--out", default="data/live",
                   help="output directory (default data/live)")
    p.add_argument("--hours", type=float, default=25.0,
                   help="capture duration in hours (default 25 = 1 full UTC day + margin)")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
