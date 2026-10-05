"""Shared deterministic numeric primitives for Phase 5 asset analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Iterable, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class AnalysisStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class MetricResult:
    name: str
    value: Decimal | None
    unit: str | None = None
    formula: str | None = None
    status: AnalysisStatus = AnalysisStatus.COMPLETE
    reason: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    subject: str
    analysis_type: str
    status: AnalysisStatus
    metrics: tuple[MetricResult, ...] = ()
    findings: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


def decimal(value: Decimal | str | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("binary float is not accepted for deterministic financial calculations")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("financial values must be finite")
    return result


def safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == ZERO:
        return None
    return numerator / denominator


def pct_change(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    if current is None or prior is None or prior == ZERO:
        return None
    return (current / prior) - ONE


def simple_returns(prices: Iterable[Decimal]) -> tuple[Decimal, ...]:
    values = tuple(prices)
    returns: list[Decimal] = []
    for previous, current in zip(values, values[1:]):
        if previous <= ZERO:
            raise ValueError("price series must contain strictly positive values")
        returns.append((current / previous) - ONE)
    return tuple(returns)


def mean(values: Iterable[Decimal]) -> Decimal | None:
    series = tuple(values)
    if not series:
        return None
    return sum(series, ZERO) / Decimal(len(series))


def sample_stddev(values: Iterable[Decimal]) -> Decimal | None:
    series = tuple(values)
    if len(series) < 2:
        return None
    avg = mean(series)
    assert avg is not None
    variance = sum(((value - avg) ** 2 for value in series), ZERO) / Decimal(len(series) - 1)
    with localcontext() as ctx:
        ctx.prec = 34
        return variance.sqrt()


def max_drawdown(prices: Iterable[Decimal]) -> Decimal | None:
    values = tuple(prices)
    if not values:
        return None
    peak = values[0]
    if peak <= ZERO:
        raise ValueError("price series must contain strictly positive values")
    worst = ZERO
    for price in values:
        if price <= ZERO:
            raise ValueError("price series must contain strictly positive values")
        if price > peak:
            peak = price
        drawdown = (price / peak) - ONE
        if drawdown < worst:
            worst = drawdown
    return worst


def correlation(left: Iterable[Decimal], right: Iterable[Decimal]) -> Decimal | None:
    a = tuple(left)
    b = tuple(right)
    if len(a) != len(b) or len(a) < 2:
        return None
    ma = mean(a)
    mb = mean(b)
    assert ma is not None and mb is not None
    cov = sum(((x - ma) * (y - mb) for x, y in zip(a, b)), ZERO) / Decimal(len(a) - 1)
    sa = sample_stddev(a)
    sb = sample_stddev(b)
    if sa in (None, ZERO) or sb in (None, ZERO):
        return None
    return cov / (sa * sb)
