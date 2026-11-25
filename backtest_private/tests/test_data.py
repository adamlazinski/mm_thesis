from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from coupled_mm.data import load_quotes, parse_timestamp
from coupled_mm.domain import Instrument


def _instruments() -> dict[str, Instrument]:
    return {"A": Instrument("A", tick_size=Decimal("0.5"))}


def _write_quotes(tmp_path: Path, row: str) -> Path:
    path = tmp_path / "quotes.csv"
    path.write_text(
        "timestamp,contract_id,bid_price,bid_size,ask_price,ask_size\n" + row + "\n",
        encoding="utf-8",
    )
    return path


def test_timestamp_requires_an_explicit_utc_offset() -> None:
    timestamp = parse_timestamp("2026-01-15T11:42:03.125000+01:00")

    assert timestamp.utcoffset() == timedelta(hours=1)
    assert parse_timestamp("2026-01-15T10:42:03.125000Z").utcoffset() == timedelta(0)
    with pytest.raises(ValueError, match="has no UTC offset"):
        parse_timestamp("2026-01-15T11:42:03.125000")


def test_load_quotes_preserves_offset_aware_timestamp(tmp_path: Path) -> None:
    path = _write_quotes(
        tmp_path,
        "2026-01-15T11:42:03.125000+01:00,A,99.5,8,100.0,10",
    )

    quote = load_quotes(path, _instruments())[0]

    assert quote.timestamp.utcoffset() == timedelta(hours=1)
    assert quote.bid_price == Decimal("99.5")


def test_off_grid_quote_is_rejected(tmp_path: Path) -> None:
    path = _write_quotes(
        tmp_path,
        "2026-01-15T11:42:03+01:00,A,99.25,8,100.0,10",
    )

    with pytest.raises(ValueError, match="off the 0.5 tick grid"):
        load_quotes(path, _instruments())


def test_crossed_book_is_rejected(tmp_path: Path) -> None:
    path = _write_quotes(
        tmp_path,
        "2026-01-15T11:42:03+01:00,A,100.0,8,99.5,10",
    )

    with pytest.raises(ValueError, match="ask_price > bid_price"):
        load_quotes(path, _instruments())

