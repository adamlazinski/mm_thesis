"""
hyperliquid_capture.py
======================
Offline reconstruction of Hyperliquid captures (collect_hyperliquid.py) into
CoinAPI-schema parquets, plus the feature that makes this venue worth capturing:
per-trade counterparty wallet columns.

No book replay is needed — `bbo` already carries top-of-book and `l2Book` is a
periodic full snapshot, so this is a parsing pass with bulk time conversion.

Outputs per coin/date under out_dir:
  trades_{ASSET}_{DATE}.parquet   time_exchange, time_coinapi, price, size,
                                  taker_side, taker_wallet, maker_wallet, hash,
                                  tid, symbol_id
  quotes_{ASSET}_{DATE}.parquet   time_exchange, time_coinapi, bid_price,
                                  bid_size, ask_price, ask_size, symbol_id   (bbo)
  funding_{ASSET}_{DATE}.parquet  time_coinapi, funding, open_interest,
                                  oracle_px, mark_px, mid_px, premium, symbol_id
  orderbooks_{ASSET}_{DATE}.parquet  (l2Book snapshots, only with want_books)

taker_side / wallets: HL trade `side` is the taker side ("B"=taker bought,
"A"=taker sold); `users=[buyer, seller]`. So for side "B" the taker is the buyer
(users[0]) and the maker is the seller (users[1]); for "A" it is reversed. The
maker_wallet is the liquidity provider that was (potentially) adversely selected;
the taker_wallet is the aggressor whose flow toxicity we want to attribute.

ASSET naming: HL_BTC, HL_ETH, HL_SOL, HL_LINK, HL_HYPE — distinct from the
Binance/Coinbase assets so all venues coexist in the processed dir.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .binance_capture import iter_records

TOP_N = 20


def capture_files(capture_dir: str | Path, coin: str, date: str) -> list[str]:
    return sorted(glob.glob(
        str(Path(capture_dir) / f"hyperliquid_{coin}_{date}_*.jsonl.gz")))


def _ms(series) -> pd.Series:
    return pd.to_datetime(np.asarray(series, dtype="float64"), unit="ms", utc=True)


def _epoch(series) -> pd.Series:
    return pd.to_datetime(np.asarray(series, dtype="float64") * 1e9, unit="ns", utc=True)


def replay_coin_day(capture_dir, coin, date, symbol_id, out_dir, asset,
                    top_n=TOP_N, want_books=False) -> dict:
    files = capture_files(capture_dir, coin, date)
    if not files:
        raise FileNotFoundError(f"no capture files for hyperliquid {coin} {date}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    trade_rows, quote_rows, fund_rows, book_rows = [], [], [], []
    n = {"trades": 0, "bbo": 0, "l2Book": 0, "ctx": 0, "gaps": 0}

    for rec in iter_records(files):
        stream, data, ts = rec["stream"], rec["data"], rec["ts_recv"]

        if stream == "trades":
            for t in data:
                side = t.get("side")
                users = t.get("users") or [None, None]
                buyer, seller = (users + [None, None])[:2]
                if side == "B":
                    taker_side, taker_w, maker_w = "BUY", buyer, seller
                else:
                    taker_side, taker_w, maker_w = "SELL", seller, buyer
                trade_rows.append((t.get("time"), ts, float(t["px"]), float(t["sz"]),
                                   taker_side, taker_w, maker_w,
                                   t.get("hash"), t.get("tid")))
                n["trades"] += 1

        elif stream == "bbo":
            bb = data.get("bbo")
            if bb and bb[0] and bb[1]:
                quote_rows.append((data.get("time"), ts,
                                   float(bb[0]["px"]), float(bb[0]["sz"]),
                                   float(bb[1]["px"]), float(bb[1]["sz"])))
                n["bbo"] += 1

        elif stream == "activeAssetCtx":
            c = data.get("ctx", {})
            fund_rows.append((ts, _f(c.get("funding")), _f(c.get("openInterest")),
                              _f(c.get("oraclePx")), _f(c.get("markPx")),
                              _f(c.get("midPx")), _f(c.get("premium"))))
            n["ctx"] += 1

        elif stream == "l2Book":
            n["l2Book"] += 1
            if want_books:
                lv = data.get("levels") or [[], []]
                bids = [{"price": float(x["px"]), "size": float(x["sz"])}
                        for x in lv[0][:top_n]]
                asks = [{"price": float(x["px"]), "size": float(x["sz"])}
                        for x in lv[1][:top_n]]
                if bids and asks:
                    book_rows.append((data.get("time"), bids, asks))

        elif stream == "gap":
            n["gaps"] += 1

    # trades
    tr = pd.DataFrame(trade_rows, columns=[
        "te", "tc", "price", "size", "taker_side", "taker_wallet",
        "maker_wallet", "hash", "tid"])
    trades = pd.DataFrame({
        "time_exchange": _ms(tr["te"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
        "time_coinapi": _epoch(tr["tc"]) if len(tr) else pd.Series([], dtype="datetime64[ns, UTC]"),
        "price": tr["price"] if len(tr) else [], "size": tr["size"] if len(tr) else [],
        "taker_side": tr["taker_side"] if len(tr) else [],
        "taker_wallet": tr["taker_wallet"] if len(tr) else [],
        "maker_wallet": tr["maker_wallet"] if len(tr) else [],
        "hash": tr["hash"] if len(tr) else [], "tid": tr["tid"] if len(tr) else [],
        "symbol_id": symbol_id})
    trades.to_parquet(out_dir / f"trades_{asset}_{date}.parquet", index=False)

    qt = pd.DataFrame(quote_rows, columns=[
        "te", "tc", "bid_price", "bid_size", "ask_price", "ask_size"])
    quotes = pd.DataFrame({
        "time_exchange": _ms(qt["te"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
        "time_coinapi": _epoch(qt["tc"]) if len(qt) else pd.Series([], dtype="datetime64[ns, UTC]"),
        "bid_price": qt["bid_price"] if len(qt) else [], "bid_size": qt["bid_size"] if len(qt) else [],
        "ask_price": qt["ask_price"] if len(qt) else [], "ask_size": qt["ask_size"] if len(qt) else [],
        "symbol_id": symbol_id})
    quotes.to_parquet(out_dir / f"quotes_{asset}_{date}.parquet", index=False)

    if fund_rows:
        fr = pd.DataFrame(fund_rows, columns=[
            "tc", "funding", "open_interest", "oracle_px", "mark_px", "mid_px", "premium"])
        pd.DataFrame({
            "time_coinapi": _epoch(fr["tc"]), "funding": fr["funding"],
            "open_interest": fr["open_interest"], "oracle_px": fr["oracle_px"],
            "mark_px": fr["mark_px"], "mid_px": fr["mid_px"], "premium": fr["premium"],
            "symbol_id": symbol_id}).to_parquet(
                out_dir / f"funding_{asset}_{date}.parquet", index=False)

    if want_books and book_rows:
        _write_books(book_rows, symbol_id, out_dir / f"orderbooks_{asset}_{date}.parquet")

    uniq_makers = trades["maker_wallet"].nunique() if len(trades) else 0
    uniq_takers = trades["taker_wallet"].nunique() if len(trades) else 0
    return {"asset": asset, "n_trades": len(trades), "n_quotes": len(quotes),
            "n_funding": len(fund_rows), "n_l2Book": n["l2Book"], "n_gaps": n["gaps"],
            "uniq_maker_wallets": int(uniq_makers),
            "uniq_taker_wallets": int(uniq_takers),
            "n_capture_files": len(files), "wrote_orderbooks": bool(want_books)}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _write_books(rows, symbol_id, path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    level = pa.struct([("price", pa.float64()), ("size", pa.float64())])
    schema = pa.schema([
        ("time_exchange", pa.timestamp("ns", tz="UTC")),
        ("bids", pa.list_(level)), ("asks", pa.list_(level)),
        ("symbol_id", pa.string())])
    te = pa.array((np.asarray([r[0] for r in rows], dtype="float64") * 1e6).astype("int64"),
                  type=pa.int64()).cast(pa.timestamp("ns", tz="UTC"))
    table = pa.Table.from_arrays([
        te, pa.array([r[1] for r in rows], type=pa.list_(level)),
        pa.array([r[2] for r in rows], type=pa.list_(level)),
        pa.array([symbol_id] * len(rows))], schema=schema)
    pq.write_table(table, path)
