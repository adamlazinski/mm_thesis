from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .domain import AggressorSide, BookQuote, Instrument, Trade, decimal


QUOTE_COLUMNS = {
    "timestamp",
    "contract_id",
    "bid_price",
    "ask_price",
    "bid_size",
    "ask_size",
}
TRADE_COLUMNS = {
    "timestamp",
    "contract_id",
    "price",
    "size",
    "aggressor_side",
}


def parse_timestamp(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {raw!r}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(
            f"timestamp {raw!r} has no UTC offset; provide e.g. +01:00 or Z to avoid DST ambiguity"
        )
    return timestamp


def _headers(path: Path, fieldnames: list[str] | None, required: set[str]) -> None:
    present = set(fieldnames or [])
    missing = required - present
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")


def _sequence(row: dict[str, str], row_number: int) -> int:
    raw = (row.get("sequence") or "").strip()
    return int(raw) if raw else row_number


def _validate_price(price: Decimal, instrument: Instrument, label: str, row_number: int) -> None:
    if not instrument.allow_negative_price and price < 0:
        raise ValueError(f"row {row_number}: {label} cannot be negative")
    if price % instrument.tick_size != 0:
        raise ValueError(
            f"row {row_number}: {label}={price} is off the {instrument.tick_size} tick grid"
        )


def _validate_ordering(events: Iterable[BookQuote | Trade], path: Path) -> None:
    previous_timestamp: datetime | None = None
    previous_sequence: dict[str, int] = {}
    seen_sequences: set[tuple[str, int]] = set()
    for event in events:
        if previous_timestamp is not None and event.timestamp < previous_timestamp:
            raise ValueError(f"{path}: rows are not sorted by timestamp")
        previous_timestamp = event.timestamp
        prior = previous_sequence.get(event.contract_id)
        if prior is not None and event.sequence <= prior:
            raise ValueError(
                f"{path}: sequence must increase within contract {event.contract_id!r}"
            )
        previous_sequence[event.contract_id] = event.sequence
        key = (event.contract_id, event.sequence)
        if key in seen_sequences:
            raise ValueError(f"{path}: duplicate contract/sequence key {key}")
        seen_sequences.add(key)


def load_quotes(path: str | Path, instruments: dict[str, Instrument]) -> list[BookQuote]:
    csv_path = Path(path)
    events: list[BookQuote] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _headers(csv_path, reader.fieldnames, QUOTE_COLUMNS)
        for row_number, row in enumerate(reader, start=2):
            contract_id = row["contract_id"].strip()
            if contract_id not in instruments:
                raise ValueError(f"row {row_number}: unknown contract_id {contract_id!r}")
            instrument = instruments[contract_id]
            bid = decimal(row["bid_price"].strip())
            ask = decimal(row["ask_price"].strip())
            _validate_price(bid, instrument, "bid_price", row_number)
            _validate_price(ask, instrument, "ask_price", row_number)
            try:
                event = BookQuote(
                    timestamp=parse_timestamp(row["timestamp"]),
                    contract_id=contract_id,
                    bid_price=bid,
                    ask_price=ask,
                    bid_size=decimal(row["bid_size"].strip()),
                    ask_size=decimal(row["ask_size"].strip()),
                    sequence=_sequence(row, row_number),
                    source_row=row_number,
                )
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f"{csv_path}: invalid quote row {row_number}: {exc}") from exc
            events.append(event)
    _validate_ordering(events, csv_path)
    return events


def load_trades(path: str | Path, instruments: dict[str, Instrument]) -> list[Trade]:
    csv_path = Path(path)
    events: list[Trade] = []
    seen_trade_ids: set[str] = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _headers(csv_path, reader.fieldnames, TRADE_COLUMNS)
        for row_number, row in enumerate(reader, start=2):
            trade_id = (row.get("trade_id") or "").strip()
            if trade_id:
                if trade_id in seen_trade_ids:
                    raise ValueError(f"{csv_path}: duplicate trade_id {trade_id!r}")
                seen_trade_ids.add(trade_id)
            contract_id = row["contract_id"].strip()
            if contract_id not in instruments:
                raise ValueError(f"row {row_number}: unknown contract_id {contract_id!r}")
            instrument = instruments[contract_id]
            price = decimal(row["price"].strip())
            _validate_price(price, instrument, "price", row_number)
            side_raw = row["aggressor_side"].strip().lower()
            try:
                side = AggressorSide(side_raw)
            except ValueError as exc:
                raise ValueError(
                    f"row {row_number}: aggressor_side must be exactly 'buy' or 'sell'"
                ) from exc
            try:
                event = Trade(
                    timestamp=parse_timestamp(row["timestamp"]),
                    contract_id=contract_id,
                    price=price,
                    size=decimal(row["size"].strip()),
                    aggressor_side=side,
                    sequence=_sequence(row, row_number),
                    source_row=row_number,
                )
            except (ValueError, ArithmeticError) as exc:
                raise ValueError(f"{csv_path}: invalid trade row {row_number}: {exc}") from exc
            events.append(event)
    _validate_ordering(events, csv_path)
    return events
