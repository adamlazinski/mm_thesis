"""
collect_coinbase_perp.py
========================
Live Coinbase perpetual collector — Advanced Trade public WS (no auth).

Companion to collect_coinbase_l2.py (spot). Coinbase perps live on Coinbase
International (INTX); their market data is exposed, unauthenticated, only via
the Advanced Trade feed (wss://advanced-trade-ws.coinbase.com) and only as
top-of-book (ticker) + trade tape (market_trades) — the level2 channel there
requires a signed JWT, so full-book perp L2 is not available. Top-of-book + tape
is sufficient for cross-venue lead-lag and the spot-perp basis (both use mid
changes and trades), matching how the Binance perp work (exps 88-90) treats it.

Raw-first, same as the other collectors: every message is appended verbatim
with a local receive timestamp. The Advanced Trade envelope bundles events for
multiple products in one message, so this writes a single combined per-feed
file; offline processing splits by product_id within events[].

Advanced Trade protocol note: one channel per subscribe message (not a list),
envelope = {"channel","timestamp","sequence_num","events":[...]}.

Output: {out}/coinbase_PERPINTX_{YYYY-MM-DD_HH}_r{RUNTAG}.jsonl.gz
        lines: {"ts_recv": <epoch float>, "stream":
                 "ticker|market_trades|heartbeats|subscriptions|error|gap",
                 "data": {...}}

Usage (requires: pip install websockets certifi):
    python scripts/collect_coinbase_perp.py \
        --product BTC-PERP-INTX --product LINK-PERP-INTX --out data/live --hours 72
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

WS_URL = "wss://advanced-trade-ws.coinbase.com"
CHANNELS = ["market_trades", "ticker", "heartbeats"]   # public (level2 needs auth)


class HourlyGzWriter:
    """Appends JSON lines to an hourly-rotated .jsonl.gz file."""

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
    writer = HourlyGzWriter(out_dir, "PERPINTX")
    backoff = [1, 2, 5, 10, 20, 30]
    backoff_i = 0
    try:
        while time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ssl=SSL_CTX,
                                               ping_interval=15, ping_timeout=15,
                                               max_size=None, max_queue=None) as ws:
                    for ch in CHANNELS:
                        await ws.send(json.dumps({"type": "subscribe",
                                                  "product_ids": products,
                                                  "channel": ch}))
                    writer.write(time.time(), "gap", {"reason": "connect/resubscribe"})
                    backoff_i = 0
                    while time.time() < stop_at:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        now = time.time()
                        msg = json.loads(raw)
                        stream = msg.get("channel", "other")
                        writer.write(now, stream, msg)
                        if stream == "error" or msg.get("type") == "error":
                            print(f"[error] {msg}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 — raw-first: log and reconnect
                wait = backoff[min(backoff_i, len(backoff) - 1)]
                backoff_i += 1
                print(f"[reconnect] {type(e).__name__}: {e} — retry in {wait}s",
                      file=sys.stderr)
                writer.write(time.time(), "gap", {"reason": f"{type(e).__name__}"})
                await asyncio.sleep(wait)
    finally:
        print(f"[PERPINTX] closing, {writer.n_lines:,} lines")
        writer.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", action="append", required=True,
                    help="Coinbase perp product, e.g. BTC-PERP-INTX (repeatable)")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--hours", type=float, default=72.0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_at = time.time() + args.hours * 3600.0
    print(f"Coinbase perp collector: {args.product} -> {out_dir} for {args.hours}h "
          f"(until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(stop_at))} UTC)")
    try:
        asyncio.run(collect(args.product, out_dir, stop_at))
    except KeyboardInterrupt:
        print("interrupted")


if __name__ == "__main__":
    main()
