"""
collect_deribit_options.py
==========================
Live Deribit option-tape collector — raw-first, mirroring the other collectors.

Motivation: Deribit's public REST history serves only ~24h of option trades, and
one day per currency was not enough to settle exp 112 (BTC and ETH disagreed at
zero fees). This accumulates the tape forward so the delta-hedged markout can be
run over multiple days.

Two channels carry everything exp 112 needs, without subscribing to hundreds of
instruments: the per-currency option trade tape (each trade carries its own IV,
index price and mark, and the instrument name encodes strike/expiry/right), and
the underlying index. Greeks are computed offline from (F, K, T, sigma), and the
index and ATM-IV series are reconstructed from the tape itself.

  trades.option.{CCY}.100ms   every option trade for the currency
  deribit_price_index.{ccy}_usd   the underlying index

Output: {out}/deribit_{CCY}_{YYYY-MM-DD_HH}_r{RUNTAG}.jsonl.gz
        lines: {"ts_recv": <epoch float>, "stream": "trades|index|gap", "data": {...}}

Usage:
    python scripts/collect_deribit_options.py --currency BTC --currency ETH \
        --out data/live --hours 168
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

WS_URL = "wss://www.deribit.com/ws/api/v2"


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
                    f"deribit_{self.label}_{hour_key}_r{self.RUN_TAG}.jsonl.gz")
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


async def collect(currencies: list[str], out_dir: Path, stop_at: float) -> None:
    writers = {c: HourlyGzWriter(out_dir, c) for c in currencies}
    channels = ([f"trades.option.{c}.100ms" for c in currencies] +
                [f"deribit_price_index.{c.lower()}_usd" for c in currencies])
    backoff = [1, 2, 5, 10, 20, 30]
    backoff_i = 0
    try:
        while time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ssl=SSL_CTX,
                                               ping_interval=20, ping_timeout=20,
                                               max_size=None, max_queue=None) as ws:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "public/subscribe",
                        "params": {"channels": channels}}))
                    for c in currencies:
                        writers[c].write(time.time(), "gap",
                                         {"reason": "connect/resubscribe"})
                    backoff_i = 0
                    while time.time() < stop_at:
                        raw = await asyncio.wait_for(ws.recv(), timeout=120)
                        now = time.time()
                        msg = json.loads(raw)
                        p = msg.get("params") or {}
                        ch = p.get("channel", "")
                        data = p.get("data")
                        if ch.startswith("trades.option."):
                            c = ch.split(".")[2]
                            if c in writers and data:
                                writers[c].write(now, "trades", data)
                        elif ch.startswith("deribit_price_index."):
                            c = ch.split(".")[1].split("_")[0].upper()
                            if c in writers:
                                writers[c].write(now, "index", data)
            except asyncio.TimeoutError:
                continue          # quiet tape is normal overnight
            except Exception as e:  # noqa: BLE001 — raw-first: log and reconnect
                wait = backoff[min(backoff_i, len(backoff) - 1)]
                backoff_i += 1
                print(f"[reconnect] {type(e).__name__}: {e} — retry in {wait}s",
                      file=sys.stderr)
                for c in currencies:
                    writers[c].write(time.time(), "gap", {"reason": type(e).__name__})
                await asyncio.sleep(wait)
    finally:
        for w in writers.values():
            print(f"[{w.label}] closing, {w.n_lines:,} lines")
            w.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--currency", action="append", required=True)
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--hours", type=float, default=168.0)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_at = time.time() + args.hours * 3600.0
    print(f"Deribit option collector: {args.currency} -> {out_dir} for {args.hours}h "
          f"(until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(stop_at))} UTC)")
    try:
        asyncio.run(collect(args.currency, out_dir, stop_at))
    except KeyboardInterrupt:
        print("interrupted")


if __name__ == "__main__":
    main()
