"""
collect_hyperliquid.py
======================
Live Hyperliquid perp collector — raw trades + bbo + l2Book + funding/OI capture
via the public WebSocket (wss://api.hyperliquid.xyz/ws, no auth), mirroring the
Binance/Coinbase collectors.

Why Hyperliquid: its trade feed carries BOTH counterparty wallet addresses
(`users: [buyer, seller]`), so adverse selection can be attributed per wallet
rather than inferred from anonymous state (the instrument exp 96 lacked). This
is the venue on which the flow-sorting escape route (C61) can actually be tested.

Streams per coin (Hyperliquid subscription types):
  trades         {coin, side "B"/"A" (taker buy/sell), px, sz, time(ms), hash,
                  tid, users:[buyer,seller]}
  bbo            {coin, time, bbo:[{px,sz,n} bid, {px,sz,n} ask]}   (~5-10 Hz)
  l2Book         {coin, time, levels:[[bids],[asks]]} (each {px,sz,n}, ~7-8 s)
  activeAssetCtx {coin, ctx:{funding, openInterest, oraclePx, markPx, midPx,...}}

Raw-first, same as the other collectors: every message is appended verbatim with
a local receive timestamp to hourly-rotated gzipped JSONL, one file per coin.
An application-level ping is sent every 30s (HL closes idle sockets).

Output: {out}/hyperliquid_{COIN}_{YYYY-MM-DD_HH}_r{RUNTAG}.jsonl.gz
        lines: {"ts_recv": <epoch float>, "stream":
                 "trades|bbo|l2Book|activeAssetCtx|gap", "data": {...}}

Usage (requires: pip install websockets certifi):
    python scripts/collect_hyperliquid.py \
        --coin BTC --coin ETH --coin SOL --coin LINK --coin HYPE \
        --out data/live --hours 72
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

WS_URL = "wss://api.hyperliquid.xyz/ws"
STREAMS = ["trades", "bbo", "l2Book", "activeAssetCtx"]
PING_EVERY_S = 30.0


class HourlyGzWriter:
    """Appends JSON lines to an hourly-rotated .jsonl.gz file per coin."""

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
                    f"hyperliquid_{self.label}_{hour_key}_r{self.RUN_TAG}.jsonl.gz")
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


async def collect(coins: list[str], out_dir: Path, stop_at: float) -> None:
    writers = {c: HourlyGzWriter(out_dir, c) for c in coins}
    backoff = [1, 2, 5, 10, 20, 30]
    backoff_i = 0
    try:
        while time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ssl=SSL_CTX,
                                               ping_interval=20, ping_timeout=20,
                                               max_size=None, max_queue=None) as ws:
                    for c in coins:
                        for typ in STREAMS:
                            await ws.send(json.dumps({
                                "method": "subscribe",
                                "subscription": {"type": typ, "coin": c}}))
                    for c in coins:
                        writers[c].write(time.time(), "gap",
                                         {"reason": "connect/resubscribe"})
                    backoff_i = 0
                    last_ping = time.time()
                    while time.time() < stop_at:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=PING_EVERY_S)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"method": "ping"}))
                            last_ping = time.time()
                            continue
                        now = time.time()
                        msg = json.loads(raw)
                        ch = msg.get("channel", "")
                        data = msg.get("data")
                        if ch in ("subscriptionResponse", "pong"):
                            pass
                        elif ch == "trades" and isinstance(data, list):
                            # a trades message is a list; all share one coin
                            if data:
                                c = data[0].get("coin")
                                if c in writers:
                                    writers[c].write(now, "trades", data)
                        elif isinstance(data, dict) and data.get("coin") in writers:
                            writers[data["coin"]].write(now, ch, data)
                        if now - last_ping > PING_EVERY_S:
                            await ws.send(json.dumps({"method": "ping"}))
                            last_ping = now
            except Exception as e:  # noqa: BLE001 — raw-first: log and reconnect
                wait = backoff[min(backoff_i, len(backoff) - 1)]
                backoff_i += 1
                print(f"[reconnect] {type(e).__name__}: {e} — retry in {wait}s",
                      file=sys.stderr)
                for c in coins:
                    writers[c].write(time.time(), "gap", {"reason": type(e).__name__})
                await asyncio.sleep(wait)
    finally:
        for w in writers.values():
            print(f"[{w.label}] closing, {w.n_lines:,} lines")
            w.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", action="append", required=True,
                    help="Hyperliquid coin symbol, e.g. BTC (repeatable)")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--hours", type=float, default=72.0)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_at = time.time() + args.hours * 3600.0
    print(f"Hyperliquid collector: {args.coin} -> {out_dir} for {args.hours}h "
          f"(until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(stop_at))} UTC)")
    try:
        asyncio.run(collect(args.coin, out_dir, stop_at))
    except KeyboardInterrupt:
        print("interrupted")


if __name__ == "__main__":
    main()
