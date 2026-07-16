"""
collect_binance_liquidations.py
================================
Standalone Binance USDT-M futures liquidation collector — the all-market
forceOrder stream (`!forceOrder@arr`), raw-first, one hourly-rotated file.

Purpose: liquidations are the one flow that is price-insensitive by
construction (forced sellers/buyers), i.e. the benign counterparty a maker
wants. This stream labels them directly — the label exps 93/96 lacked when
proxying "forced" from OI/premium. Runs as its own process so the main
collect_binance_l2.py capture is not disturbed.

Payload per event (Binance docs): {"e":"forceOrder","E":<event ms>,
  "o":{"s":symbol,"S":side,"o":type,"q":qty,"p":price,"ap":avg price,
       "X":status,"T":trade ms, ...}}
Side "SELL" = a long was liquidated (forced sell), "BUY" = a short was.
Note: Binance throttles this stream to at most one order per symbol per
second — it undercounts within-second cascade intensity but timestamps and
prices every cascade.

Output: {out}/binance_LIQUIDATIONS_{YYYY-MM-DD_HH}_r{RUNTAG}.jsonl.gz
        lines: {"ts_recv": <epoch float>, "stream": "forceOrder|gap", "data": {...}}

Usage:
    python scripts/collect_binance_liquidations.py --out data/live --hours 168
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import ssl
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("pip install websockets certifi  (not in .venv yet)")

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"


class HourlyGzWriter:
    FLUSH_EVERY_S = 5.0
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
            self._fh.flush()
            self._last_flush = ts

    def close(self):
        if self._fh:
            self._fh.close()


async def collect(out_dir: Path, stop_at: float) -> None:
    writer = HourlyGzWriter(out_dir, "LIQUIDATIONS")
    backoff = [1, 2, 5, 10, 20, 30]
    backoff_i = 0
    try:
        while time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ssl=SSL_CTX,
                                               ping_interval=20, ping_timeout=20,
                                               max_size=None, max_queue=None) as ws:
                    writer.write(time.time(), "gap", {"reason": "connect"})
                    backoff_i = 0
                    while time.time() < stop_at:
                        raw = await asyncio.wait_for(ws.recv(), timeout=300)
                        writer.write(time.time(), "forceOrder", json.loads(raw))
            except asyncio.TimeoutError:
                continue          # quiet market: no liquidations for 5 min is normal
            except Exception as e:  # noqa: BLE001
                wait = backoff[min(backoff_i, len(backoff) - 1)]
                backoff_i += 1
                print(f"[reconnect] {type(e).__name__}: {e} — retry in {wait}s",
                      file=sys.stderr)
                writer.write(time.time(), "gap", {"reason": type(e).__name__})
                await asyncio.sleep(wait)
    finally:
        print(f"[LIQUIDATIONS] closing, {writer.n_lines:,} lines")
        writer.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--hours", type=float, default=168.0)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_at = time.time() + args.hours * 3600.0
    print(f"Binance liquidation collector -> {out_dir} for {args.hours}h "
          f"(until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(stop_at))} UTC)")
    try:
        asyncio.run(collect(out_dir, stop_at))
    except KeyboardInterrupt:
        print("interrupted")


if __name__ == "__main__":
    main()
