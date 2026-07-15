"""
collect_coinbase_l2.py
======================
Live Coinbase (Exchange/Pro) L2 collector — raw ticker + matches + level2
capture, mirroring collect_binance_l2.py so the same offline pipeline and
lead-lag analyses apply cross-venue.

Purpose: capture Coinbase BTC-USD / LINK-USD concurrently with the Binance
collector to (a) measure the Binance->Coinbase price-discovery lead (a
cross-exchange C56 analog), and (b) test whether Coinbase's wider spread /
less-toxic US-retail flow is a book on which lit spread capture clears its
adverse selection (the wide-book hope).

Capture design (raw-first, identical to the Binance collector): every
websocket message is appended verbatim with a local receive timestamp to
hourly-rotated gzipped JSONL files, one per product. Book reconstruction
happens offline from the level2 snapshot + l2update replay (Coinbase sends a
fresh snapshot on every (re)subscribe, so a reconnect re-anchors). Nothing is
interpreted at capture time.

Coinbase feed (public, no auth): wss://ws-feed.exchange.coinbase.com
  channels: ticker    -> best_bid/best_ask/sizes + last match (exchange time)
            matches   -> individual trades (side/size/price, exchange time)
            level2_batch -> snapshot (full book) + l2update (changes, 50ms)
            heartbeat -> keepalive + sequence, for gap detection

Output: {out}/coinbase_{LABEL}_{YYYY-MM-DD_HH}_r{RUNTAG}.jsonl.gz
        LABEL = product with '-' stripped (LINK-USD -> LINKUSD)
        lines: {"ts_recv": <epoch float>, "stream":
                 "ticker|match|snapshot|l2update|heartbeat|subscriptions|error|gap",
                 "data": {...}}

Usage (requires: pip install websockets certifi):
    python scripts/collect_coinbase_l2.py \
        --product LINK-USD --product BTC-USD --out data/live --hours 168

On macOS, prevent sleep for the duration:
    caffeinate -i python scripts/collect_coinbase_l2.py ...
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

WS_URL = "wss://ws-feed.exchange.coinbase.com"
CHANNELS = ["ticker", "matches", "level2_batch", "heartbeat"]
# per-message type -> the stream label we record it under
TYPE_STREAM = {
    "ticker": "ticker", "match": "match", "last_match": "match",
    "snapshot": "snapshot", "l2update": "l2update", "heartbeat": "heartbeat",
    "subscriptions": "subscriptions", "error": "error",
}


class HourlyGzWriter:
    """Appends JSON lines to an hourly-rotated .jsonl.gz file per product."""

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
                    f"coinbase_{self.label}_{hour_key}_r{self.RUN_TAG}.jsonl.gz")
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


async def collect(products: list[str], out_dir: Path, stop_at: float) -> None:
    label = {p: p.replace("-", "") for p in products}
    writers = {p: HourlyGzWriter(out_dir, label[p]) for p in products}
    sub = {"type": "subscribe", "product_ids": products, "channels": CHANNELS}
    backoff_i = 0
    backoff = [1, 2, 5, 10, 20, 30]

    try:
        while time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ssl=SSL_CTX,
                                               ping_interval=20, ping_timeout=20,
                                               max_size=None, max_queue=None) as ws:
                    await ws.send(json.dumps(sub))
                    # a reconnect re-anchors via the fresh level2 snapshot;
                    # mark it in-band on every product stream
                    for p in products:
                        writers[p].write(time.time(), "gap",
                                         {"reason": "connect/resubscribe"})
                    backoff_i = 0
                    while time.time() < stop_at:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        now = time.time()
                        msg = json.loads(raw)
                        typ = msg.get("type", "other")
                        stream = TYPE_STREAM.get(typ, "other")
                        pid = msg.get("product_id")
                        if pid in writers:
                            writers[pid].write(now, stream, msg)
                        else:
                            # subscriptions/error/other: no product_id -> log to all
                            for p in products:
                                writers[p].write(now, stream, msg)
                        if typ == "error":
                            print(f"[error] {msg.get('message')} "
                                  f"{msg.get('reason')}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 — raw-first: log and reconnect
                wait = backoff[min(backoff_i, len(backoff) - 1)]
                backoff_i += 1
                print(f"[reconnect] {type(e).__name__}: {e} — retry in {wait}s",
                      file=sys.stderr)
                for p in products:
                    writers[p].write(time.time(), "gap",
                                     {"reason": f"{type(e).__name__}"})
                await asyncio.sleep(wait)
    finally:
        for w in writers.values():
            print(f"[{w.label}] closing, {w.n_lines:,} lines")
            w.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", action="append", required=True,
                    help="Coinbase product id, e.g. LINK-USD (repeatable)")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--hours", type=float, default=168.0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_at = time.time() + args.hours * 3600.0
    print(f"Coinbase collector: {args.product} -> {out_dir} "
          f"for {args.hours}h (until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(stop_at))} UTC)")
    try:
        asyncio.run(collect(args.product, out_dir, stop_at))
    except KeyboardInterrupt:
        print("interrupted")


if __name__ == "__main__":
    main()
