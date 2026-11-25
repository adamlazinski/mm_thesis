from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .domain import Instrument, decimal


def _clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid local time {value!r}; expected HH:MM[:SS]") from exc


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing configuration key: {key}")
    return mapping[key]


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"unknown {context} configuration keys: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class PairConfig:
    leg_a: str
    leg_b: str
    target_spread_b_minus_a: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_spread_b_minus_a", decimal(self.target_spread_b_minus_a))
        if not self.target_spread_b_minus_a.is_finite():
            raise ValueError("target spread must be finite")
        if not self.leg_a or not self.leg_b or self.leg_a == self.leg_b:
            raise ValueError("leg_a and leg_b must be distinct non-empty IDs")


@dataclass(frozen=True, slots=True)
class SessionConfig:
    timezone: str
    quote_start: time
    signal_start: time
    exit_time: time
    cancel_before_exit_ms: int
    max_quote_age_ms: int

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if self.signal_start >= self.exit_time:
            raise ValueError("signal_start must be earlier than exit_time")
        if self.quote_start >= self.exit_time:
            raise ValueError("quote_start must be earlier than exit_time")
        if self.cancel_before_exit_ms < 0 or self.max_quote_age_ms <= 0:
            raise ValueError("session millisecond settings must be positive")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    order_quantity: object
    half_width_a: object
    half_width_b: object
    quote_interval_ms: int
    target_weight_start: object
    target_weight_end: object
    convergence_gamma: object
    confidence_a: object
    confidence_b: object
    inventory_skew_common: object
    inventory_skew_spread: object
    refresh_ticks: int

    def __post_init__(self) -> None:
        for field_name in (
            "order_quantity",
            "half_width_a",
            "half_width_b",
            "confidence_a",
            "confidence_b",
            "inventory_skew_common",
            "inventory_skew_spread",
            "target_weight_start",
            "target_weight_end",
            "convergence_gamma",
        ):
            object.__setattr__(self, field_name, decimal(getattr(self, field_name)))
        numeric_fields = (
            "order_quantity",
            "half_width_a",
            "half_width_b",
            "confidence_a",
            "confidence_b",
            "inventory_skew_common",
            "inventory_skew_spread",
            "target_weight_start",
            "target_weight_end",
            "convergence_gamma",
        )
        if not all(getattr(self, name).is_finite() for name in numeric_fields):
            raise ValueError("strategy numerics must be finite")
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.half_width_a <= 0 or self.half_width_b <= 0:
            raise ValueError("half widths must be positive")
        if self.quote_interval_ms < 0 or self.refresh_ticks < 0:
            raise ValueError("quote_interval_ms and refresh_ticks cannot be negative")
        if not 0 <= self.target_weight_start <= 1:
            raise ValueError("target_weight_start must be in [0, 1]")
        if not 0 <= self.target_weight_end <= 1:
            raise ValueError("target_weight_end must be in [0, 1]")
        if self.target_weight_end < self.target_weight_start:
            raise ValueError("target weight must not decrease")
        if self.convergence_gamma <= 0:
            raise ValueError("convergence_gamma must be positive")
        if self.confidence_a <= 0 or self.confidence_b <= 0:
            raise ValueError("confidences must be positive")
        if self.inventory_skew_common < 0 or self.inventory_skew_spread < 0:
            raise ValueError("inventory skews cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_leg_mwh: object
    max_common_mwh: object
    max_spread_mwh: object
    max_gross_mwh: object

    def __post_init__(self) -> None:
        for field_name in (
            "max_leg_mwh",
            "max_common_mwh",
            "max_spread_mwh",
            "max_gross_mwh",
        ):
            object.__setattr__(self, field_name, decimal(getattr(self, field_name)))
            if not getattr(self, field_name).is_finite():
                raise ValueError(f"{field_name} must be finite")
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    new_order_latency_ms: int
    cancel_latency_ms: int
    fill_model: str
    queue_fraction: object
    maker_fee_per_mwh: object
    taker_fee_per_mwh: object
    maker_fee_rate: object
    taker_fee_rate: object
    exit_slippage_ticks: int

    def __post_init__(self) -> None:
        for field_name in (
            "queue_fraction",
            "maker_fee_per_mwh",
            "taker_fee_per_mwh",
            "maker_fee_rate",
            "taker_fee_rate",
        ):
            object.__setattr__(self, field_name, decimal(getattr(self, field_name)))
            if not getattr(self, field_name).is_finite():
                raise ValueError(f"{field_name} must be finite")
        if self.new_order_latency_ms < 0 or self.cancel_latency_ms < 0:
            raise ValueError("latencies cannot be negative")
        if self.fill_model not in {"trade_queue", "quote_through"}:
            raise ValueError("fill_model must be 'trade_queue' or 'quote_through'")
        if not 0 <= self.queue_fraction <= 1:
            raise ValueError("queue_fraction must be in [0, 1]")
        if self.exit_slippage_ticks < 0:
            raise ValueError("exit_slippage_ticks cannot be negative")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    pair: PairConfig
    instruments: dict[str, Instrument]
    session: SessionConfig
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig

    def __post_init__(self) -> None:
        required = {self.pair.leg_a, self.pair.leg_b}
        if set(self.instruments) != required:
            raise ValueError(f"instruments must contain exactly {sorted(required)}")
        if self.session.cancel_before_exit_ms < self.execution.cancel_latency_ms:
            raise ValueError(
                "cancel_before_exit_ms must be >= cancel_latency_ms so passive orders are "
                "gone before forced exit"
            )
        for instrument in self.instruments.values():
            if self.strategy.order_quantity % instrument.lot_size != 0:
                raise ValueError(
                    f"order_quantity must align with {instrument.contract_id} lot_size "
                    f"{instrument.lot_size}"
                )


def config_from_dict(raw: dict[str, Any]) -> BacktestConfig:
    _reject_unknown(
        raw,
        {"pair", "instruments", "session", "strategy", "risk", "execution"},
        "top-level",
    )
    pair_raw = _require(raw, "pair")
    _reject_unknown(pair_raw, {"leg_a", "leg_b", "target_spread_b_minus_a"}, "pair")
    pair = PairConfig(
        leg_a=_require(pair_raw, "leg_a"),
        leg_b=_require(pair_raw, "leg_b"),
        target_spread_b_minus_a=_require(pair_raw, "target_spread_b_minus_a"),
    )

    instruments_raw = _require(raw, "instruments")
    instruments: dict[str, Instrument] = {}
    for contract_id, item in instruments_raw.items():
        _reject_unknown(
            item,
            {"tick_size", "lot_size", "mwh_per_lot", "allow_negative_price"},
            f"instrument {contract_id}",
        )
        instruments[contract_id] = Instrument(
            contract_id=contract_id,
            tick_size=decimal(_require(item, "tick_size")),
            lot_size=decimal(item.get("lot_size", 1)),
            mwh_per_lot=decimal(item.get("mwh_per_lot", 1)),
            allow_negative_price=bool(item.get("allow_negative_price", True)),
        )

    session_raw = _require(raw, "session")
    _reject_unknown(
        session_raw,
        {
            "timezone",
            "quote_start",
            "signal_start",
            "exit_time",
            "cancel_before_exit_ms",
            "max_quote_age_ms",
        },
        "session",
    )
    session = SessionConfig(
        timezone=_require(session_raw, "timezone"),
        quote_start=_clock(_require(session_raw, "quote_start")),
        signal_start=_clock(_require(session_raw, "signal_start")),
        exit_time=_clock(_require(session_raw, "exit_time")),
        cancel_before_exit_ms=int(session_raw.get("cancel_before_exit_ms", 250)),
        max_quote_age_ms=int(session_raw.get("max_quote_age_ms", 5_000)),
    )

    strategy_raw = _require(raw, "strategy")
    _reject_unknown(
        strategy_raw,
        {
            "order_quantity",
            "half_width_a",
            "half_width_b",
            "quote_interval_ms",
            "target_weight_start",
            "target_weight_end",
            "convergence_gamma",
            "confidence_a",
            "confidence_b",
            "inventory_skew_common",
            "inventory_skew_spread",
            "refresh_ticks",
        },
        "strategy",
    )
    strategy = StrategyConfig(
        order_quantity=_require(strategy_raw, "order_quantity"),
        half_width_a=_require(strategy_raw, "half_width_a"),
        half_width_b=_require(strategy_raw, "half_width_b"),
        quote_interval_ms=int(strategy_raw.get("quote_interval_ms", 1_000)),
        target_weight_start=strategy_raw.get("target_weight_start", 0),
        target_weight_end=strategy_raw.get("target_weight_end", 1),
        convergence_gamma=strategy_raw.get("convergence_gamma", 1),
        confidence_a=strategy_raw.get("confidence_a", 1),
        confidence_b=strategy_raw.get("confidence_b", 1),
        inventory_skew_common=strategy_raw.get("inventory_skew_common", 0),
        inventory_skew_spread=strategy_raw.get("inventory_skew_spread", 0),
        refresh_ticks=int(strategy_raw.get("refresh_ticks", 1)),
    )

    risk_raw = _require(raw, "risk")
    _reject_unknown(
        risk_raw,
        {"max_leg_mwh", "max_common_mwh", "max_spread_mwh", "max_gross_mwh"},
        "risk",
    )
    risk = RiskConfig(
        max_leg_mwh=_require(risk_raw, "max_leg_mwh"),
        max_common_mwh=_require(risk_raw, "max_common_mwh"),
        max_spread_mwh=_require(risk_raw, "max_spread_mwh"),
        max_gross_mwh=_require(risk_raw, "max_gross_mwh"),
    )

    execution_raw = _require(raw, "execution")
    _reject_unknown(
        execution_raw,
        {
            "new_order_latency_ms",
            "cancel_latency_ms",
            "fill_model",
            "queue_fraction",
            "maker_fee_per_mwh",
            "taker_fee_per_mwh",
            "maker_fee_rate",
            "taker_fee_rate",
            "exit_slippage_ticks",
        },
        "execution",
    )
    execution = ExecutionConfig(
        new_order_latency_ms=int(execution_raw.get("new_order_latency_ms", 0)),
        cancel_latency_ms=int(execution_raw.get("cancel_latency_ms", 0)),
        fill_model=execution_raw.get("fill_model", "trade_queue"),
        queue_fraction=execution_raw.get("queue_fraction", 1),
        maker_fee_per_mwh=execution_raw.get("maker_fee_per_mwh", 0),
        taker_fee_per_mwh=execution_raw.get("taker_fee_per_mwh", 0),
        maker_fee_rate=execution_raw.get("maker_fee_rate", 0),
        taker_fee_rate=execution_raw.get("taker_fee_rate", 0),
        exit_slippage_ticks=int(execution_raw.get("exit_slippage_ticks", 0)),
    )
    return BacktestConfig(pair, instruments, session, strategy, risk, execution)


def load_config(path: str | Path) -> BacktestConfig:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a JSON object")
    return config_from_dict(raw)
