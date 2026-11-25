from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .config import BacktestConfig, PairConfig, SessionConfig, StrategyConfig
from .domain import BookQuote, decimal


ZERO = Decimal("0")
ONE = Decimal("1")
_MICROSECONDS_PER_DAY = 86_400_000_000
_MICROSECONDS_PER_SECOND = 1_000_000


@dataclass(frozen=True, slots=True)
class CoupledFairValues:
    """Auditable fair values for the two legs of the coupled relation."""

    leg_a: Decimal
    leg_b: Decimal
    observed_spread_b_minus_a: Decimal
    fair_spread_b_minus_a: Decimal
    target_weight: Decimal


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _microseconds(value: timedelta) -> Decimal:
    total = (
        value.days * _MICROSECONDS_PER_DAY
        + value.seconds * _MICROSECONDS_PER_SECOND
        + value.microseconds
    )
    return Decimal(total)


def causal_target_weight(
    timestamp: datetime,
    signal_start: datetime,
    exit_time: datetime,
    *,
    start_weight: object = ZERO,
    end_weight: object = ONE,
    gamma: object = ONE,
) -> Decimal:
    """Return a clamped, causal convergence weight for ``timestamp``.

    The calculation uses elapsed time only. It never inspects market observations,
    and it avoids ``timedelta.total_seconds()`` so no binary float enters the path.
    """

    _require_aware(timestamp, "timestamp")
    _require_aware(signal_start, "signal_start")
    _require_aware(exit_time, "exit_time")
    if exit_time <= signal_start:
        raise ValueError("exit_time must be later than signal_start")

    start = decimal(start_weight)
    end = decimal(end_weight)
    exponent = decimal(gamma)
    if not ZERO <= start <= ONE:
        raise ValueError("start_weight must be in [0, 1]")
    if not ZERO <= end <= ONE:
        raise ValueError("end_weight must be in [0, 1]")
    if end < start:
        raise ValueError("end_weight must not be smaller than start_weight")
    if exponent <= ZERO:
        raise ValueError("gamma must be positive")

    if timestamp <= signal_start:
        return start
    if timestamp >= exit_time:
        return end

    elapsed = _microseconds(timestamp - signal_start)
    duration = _microseconds(exit_time - signal_start)
    progress = elapsed / duration
    shaped_progress = progress**exponent
    return start + (end - start) * shaped_progress


def session_target_weight(
    timestamp: datetime,
    session: SessionConfig,
    strategy: StrategyConfig,
) -> Decimal:
    """Resolve the session's local signal/exit clocks for ``timestamp``'s date."""

    _require_aware(timestamp, "timestamp")
    local_timestamp = timestamp.astimezone(session.zone)
    local_date = local_timestamp.date()
    signal_start = datetime.combine(local_date, session.signal_start, tzinfo=session.zone)
    exit_time = datetime.combine(local_date, session.exit_time, tzinfo=session.zone)
    return causal_target_weight(
        timestamp,
        signal_start,
        exit_time,
        start_weight=strategy.target_weight_start,
        end_weight=strategy.target_weight_end,
        gamma=strategy.convergence_gamma,
    )


def coupled_fair_values(
    mid_a: object,
    mid_b: object,
    target_spread_b_minus_a: object,
    target_weight: object,
    *,
    confidence_a: object = ONE,
    confidence_b: object = ONE,
) -> CoupledFairValues:
    """Project two observed mids towards a weighted terminal relation.

    ``confidence_a`` and ``confidence_b`` are penalties for moving a leg away from
    its observed mid. Consequently, the leg with greater confidence moves less.
    """

    observed_a = decimal(mid_a)
    observed_b = decimal(mid_b)
    terminal_spread = decimal(target_spread_b_minus_a)
    weight = decimal(target_weight)
    penalty_a = decimal(confidence_a)
    penalty_b = decimal(confidence_b)

    if not ZERO <= weight <= ONE:
        raise ValueError("target_weight must be in [0, 1]")
    if penalty_a <= ZERO or penalty_b <= ZERO:
        raise ValueError("confidences must be positive")

    observed_spread = observed_b - observed_a
    spread_adjustment = weight * (terminal_spread - observed_spread)
    total_penalty = penalty_a + penalty_b

    fair_a = observed_a - (penalty_b / total_penalty) * spread_adjustment
    fair_b = observed_b + (penalty_a / total_penalty) * spread_adjustment
    fair_spread = observed_spread + spread_adjustment

    return CoupledFairValues(
        leg_a=fair_a,
        leg_b=fair_b,
        observed_spread_b_minus_a=observed_spread,
        fair_spread_b_minus_a=fair_spread,
        target_weight=weight,
    )


def fair_values_from_config(
    mid_a: object,
    mid_b: object,
    timestamp: datetime,
    pair: PairConfig,
    session: SessionConfig,
    strategy: StrategyConfig,
) -> CoupledFairValues:
    """Convenience adapter joining the causal schedule and pair configuration."""

    weight = session_target_weight(timestamp, session, strategy)
    return coupled_fair_values(
        mid_a,
        mid_b,
        pair.target_spread_b_minus_a,
        weight,
        confidence_a=strategy.confidence_a,
        confidence_b=strategy.confidence_b,
    )


class TerminalSpreadRelation:
    """State-free relation facade consumed by the quoting strategy."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def weight(self, timestamp: datetime) -> Decimal:
        return session_target_weight(timestamp, self.config.session, self.config.strategy)

    def evaluate(
        self,
        timestamp: datetime,
        book_a: BookQuote,
        book_b: BookQuote,
    ) -> CoupledFairValues:
        pair = self.config.pair
        if book_a.contract_id != pair.leg_a or book_b.contract_id != pair.leg_b:
            raise ValueError(
                "books must be ordered as the configured leg_a and leg_b contracts"
            )
        return fair_values_from_config(
            book_a.mid,
            book_b.mid,
            timestamp,
            pair,
            self.config.session,
            self.config.strategy,
        )

    def fair_values(
        self,
        timestamp: datetime,
        book_a: BookQuote,
        book_b: BookQuote,
    ) -> tuple[Decimal, Decimal]:
        values = self.evaluate(timestamp, book_a, book_b)
        return values.leg_a, values.leg_b
