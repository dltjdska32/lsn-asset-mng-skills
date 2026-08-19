"""Typed Phase 6 report contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class ReportAsOf:
    analysis_as_of: str
    analysis_timezone: str
    market_data_as_of: str | None
    financial_data_as_of: str | None
    macro_data_as_of: str | None
    portfolio_data_as_of: str | None


@dataclass(frozen=True, slots=True)
class ReportSectionInput:
    name: str
    title: str
    lines: tuple[str, ...]
    status: Availability = Availability.AVAILABLE
    evidence_ids: tuple[str, ...] = ()
    calculation_ids: tuple[str, ...] = ()
    base_case: bool = False
    current_value_claim: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportSection:
    name: str
    title: str
    lines: tuple[str, ...]
    status: Availability
    evidence_ids: tuple[str, ...]
    calculation_ids: tuple[str, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvestmentReport:
    title: str
    availability: Availability
    confidence: Confidence
    as_of: ReportAsOf
    sections: tuple[ReportSection, ...]
    review_required: bool
    review_triggers: tuple[str, ...]
    unknowns: tuple[str, ...]
    markdown: str
