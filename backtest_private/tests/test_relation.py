from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from coupled_mm.config import (
    BacktestConfig,
    ExecutionConfig,
    PairConfig,
    RiskConfig,
    SessionConfig,
    StrategyConfig,
)
from coupled_mm.domain import BookQuote, Instrument
from coupled_mm.relation import (
    TerminalSpreadRelation,
    causal_target_weight,
    coupled_fair_values,
    fair_values_from_config,
)


def _strategy(**overrides: object) -> StrategyConfig:
    values: dict[str, object] = {
        "order_quantity": "1",
        "half_width_a": "0.5",
        "half_width_b": "0.5",
        "quote_interval_ms": 1000,
        "target_weight_start": 0.0,
        "target_weight_end": 1.0,
        "convergence_gamma": 1.0,
        "confidence_a": "1",
        "confidence_b": "1",
        "inventory_skew_common": "0",
        "inventory_skew_spread": "0",
        "refresh_ticks": 1,
    }
    values.update(overrides)
    return StrategyConfig(**values)


def test_causal_weight_is_clamped_and_uses_only_elapsed_time() -> None:
    start = datetime(2026, 1, 2, 10, 45, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, 11, 45, tzinfo=timezone.utc)

    assert causal_target_weight(start, start, end) == Decimal("0")
    assert causal_target_weight(
        datetime(2026, 1, 2, 11, 15, tzinfo=timezone.utc), start, end
    ) == Decimal("0.5")
    assert causal_target_weight(end, start, end) == Decimal("1")
    assert causal_target_weight(
        datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc), start, end
    ) == Decimal("1")


def test_causal_weight_applies_gamma_and_configured_endpoints() -> None:
    start = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    halfway = datetime(2026, 1, 2, 11, 0, tzinfo=timezone.utc)

    weight = causal_target_weight(
        halfway,
        start,
        end,
        start_weight="0.1",
        end_weight="0.9",
        gamma="2",
    )
    assert weight == Decimal("0.3")


def test_coupled_fair_values_reach_terminal_relation() -> None:
    fair = coupled_fair_values("100", "100", "-5", "1")

    assert fair.leg_a == Decimal("102.5")
    assert fair.leg_b == Decimal("97.5")
    assert fair.observed_spread_b_minus_a == Decimal("0")
    assert fair.fair_spread_b_minus_a == Decimal("-5")
    assert fair.leg_b - fair.leg_a == Decimal("-5")


def test_fair_projection_respects_confidence_and_partial_weight() -> None:
    fair = coupled_fair_values(
        "100",
        "98",
        "-5",
        "0.5",
        confidence_a="3",
        confidence_b="1",
    )

    assert fair.fair_spread_b_minus_a == Decimal("-3.5")
    assert fair.leg_a == Decimal("100.375")
    assert fair.leg_b == Decimal("96.875")


def test_config_adapter_uses_local_session_clocks() -> None:
    session = SessionConfig(
        timezone="Europe/Warsaw",
        quote_start=time(10, 0),
        signal_start=time(10, 45),
        exit_time=time(11, 45),
        cancel_before_exit_ms=250,
        max_quote_age_ms=5000,
    )
    pair = PairConfig("A", "B", "-5")
    strategy = _strategy()
    # 10:15 UTC is 11:15 local time in Warsaw in January: halfway through.
    timestamp = datetime(2026, 1, 2, 10, 15, tzinfo=timezone.utc)

    fair = fair_values_from_config("100", "100", timestamp, pair, session, strategy)

    assert fair.target_weight == Decimal("0.5")
    assert fair.fair_spread_b_minus_a == Decimal("-2.5")


def test_terminal_relation_facade_returns_values_for_strategy() -> None:
    session = SessionConfig(
        timezone="UTC",
        quote_start=time(10, 0),
        signal_start=time(10, 45),
        exit_time=time(11, 45),
        cancel_before_exit_ms=250,
        max_quote_age_ms=5000,
    )
    pair = PairConfig("A", "B", "-5")
    config = BacktestConfig(
        pair=pair,
        instruments={
            "A": Instrument("A", Decimal("0.1")),
            "B": Instrument("B", Decimal("0.1")),
        },
        session=session,
        strategy=_strategy(),
        risk=RiskConfig("10", "10", "10", "10"),
        execution=ExecutionConfig(0, 0, "trade_queue", "1", "0", "0", "0", "0", 0),
    )
    timestamp = datetime(2026, 1, 2, 11, 45, tzinfo=timezone.utc)
    book_a = BookQuote(timestamp, "A", Decimal("99"), Decimal("101"), 1, 1)
    book_b = BookQuote(timestamp, "B", Decimal("99"), Decimal("101"), 1, 1)

    assert TerminalSpreadRelation(config).fair_values(timestamp, book_a, book_b) == (
        Decimal("102.5"),
        Decimal("97.5"),
    )


def test_relation_rejects_naive_times_and_invalid_parameters() -> None:
    aware = datetime(2026, 1, 2, 11, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone-aware"):
        causal_target_weight(aware.replace(tzinfo=None), aware, aware.replace(hour=12))
    with pytest.raises(ValueError, match="target_weight"):
        coupled_fair_values("1", "2", "-5", "1.01")
    with pytest.raises(ValueError, match="confidences"):
        coupled_fair_values("1", "2", "-5", "1", confidence_a="0")
