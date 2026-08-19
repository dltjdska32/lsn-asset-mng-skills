"""Portfolio total reconciliation that prevents overlapping balance double-counts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class ReconciliationStatus(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    version: str
    absolute_tolerance: Decimal
    relative_tolerance: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioReconciliationInput:
    reported_total: Decimal | None
    group_totals: Mapping[str, Decimal | None]
    group_components: Mapping[str, tuple[Decimal, ...]]


@dataclass(frozen=True, slots=True)
class PortfolioReconciliationResult:
    status: ReconciliationStatus
    authoritative_total: Decimal | None
    confirmed_group_total: Decimal | None
    naive_component_total: Decimal
    reported_difference: Decimal | None
    group_differences: Mapping[str, Decimal | None]
    reasons: tuple[str, ...]
    config_version: str


def _within(diff: Decimal, basis: Decimal, config: ReconciliationConfig) -> bool:
    allowed = max(config.absolute_tolerance, abs(basis) * config.relative_tolerance)
    return abs(diff) <= allowed


def reconcile_portfolio_total(
    data: PortfolioReconciliationInput,
    config: ReconciliationConfig,
) -> PortfolioReconciliationResult:
    naive = sum(
        (value for components in data.group_components.values() for value in components),
        Decimal("0"),
    )
    group_differences: dict[str, Decimal | None] = {}
    reasons: list[str] = []
    known_group_totals: list[Decimal] = []
    for name, components in data.group_components.items():
        reported_group = data.group_totals.get(name)
        component_sum = sum(components, Decimal("0"))
        if reported_group is None:
            group_differences[name] = None
            reasons.append(f"{name} reported total unavailable")
            continue
        known_group_totals.append(reported_group)
        difference = component_sum - reported_group
        group_differences[name] = difference
        if not _within(difference, reported_group, config):
            reasons.append(f"{name} components conflict with reported group total")

    confirmed_group_total = (
        sum(known_group_totals, Decimal("0"))
        if len(known_group_totals) == len(data.group_totals)
        else None
    )
    reported_difference = None
    if data.reported_total is None:
        reasons.append("portfolio reported total unavailable")
    elif confirmed_group_total is None:
        reasons.append("one or more reported group totals unavailable")
    else:
        reported_difference = confirmed_group_total - data.reported_total
        if not _within(reported_difference, data.reported_total, config):
            reasons.append("reported portfolio total conflicts with confirmed group totals")

    status = ReconciliationStatus.UNRESOLVED if reasons else ReconciliationStatus.RESOLVED
    return PortfolioReconciliationResult(
        status=status,
        authoritative_total=data.reported_total if status is ReconciliationStatus.RESOLVED else None,
        confirmed_group_total=confirmed_group_total,
        naive_component_total=naive,
        reported_difference=reported_difference,
        group_differences=group_differences,
        reasons=tuple(reasons),
        config_version=config.version,
    )


def load_reconciliation_config(path: Path) -> ReconciliationConfig:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"invalid flat YAML line in {path}: {raw_line!r}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    required = {"version", "absolute_tolerance_krw", "relative_tolerance"}
    if values.keys() != required:
        raise ValueError("reconciliation config must contain exactly the required keys")
    try:
        config = ReconciliationConfig(
            values["version"],
            Decimal(values["absolute_tolerance_krw"]),
            Decimal(values["relative_tolerance"]),
        )
    except InvalidOperation as exc:
        raise ValueError("reconciliation tolerances must be decimal strings") from exc
    if config.absolute_tolerance < 0 or not Decimal("0") <= config.relative_tolerance <= Decimal("1"):
        raise ValueError("reconciliation tolerances are out of range")
    return config
