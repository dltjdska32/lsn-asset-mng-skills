"""Institutional 13F domain models, comparison structures, feature sets, and validation types."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    TimezoneValidationError,
)
from investment_stack.contracts.institutional import (
    AmendmentType,
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingSet13F,
    NoticeStatus,
    PutCall,
    QuantityType,
)


class HoldingChangeStatus(StrEnum):
    """Categorization of position change between two observation periods."""

    NEW_POSITION = "NEW_POSITION"
    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    UNCHANGED = "UNCHANGED"
    CLOSED_POSITION = "CLOSED_POSITION"
    NOT_REPORTED = "NOT_REPORTED"
    INCOMPARABLE = "INCOMPARABLE"


@dataclass(frozen=True, slots=True)
class HoldingChange13F:
    """Detailed position change metrics for a single security between two periods."""

    manager_cik: str
    cusip: str
    issuer_name: str
    security_class: str | None
    quantity_type: QuantityType
    put_call: PutCall
    prior_shares: Decimal | None
    current_shares: Decimal | None
    share_change: Decimal | None
    share_change_pct: Decimal | None
    prior_value: Decimal | None
    current_value: Decimal | None
    prior_weight: Decimal | None
    current_weight: Decimal | None
    weight_change: Decimal | None
    status: HoldingChangeStatus
    is_split_adjusted: bool = False
    notice_status: NoticeStatus = NoticeStatus.COMPLETE

    def __post_init__(self) -> None:
        if not self.manager_cik or not self.cusip:
            raise ContractValidationError("manager_cik and cusip must be non-empty strings")


@dataclass(frozen=True, slots=True)
class InstitutionalPortfolioComparison:
    """Comparison of reported holdings for a manager across two periods."""

    manager_cik: str
    prior_period: str
    current_period: str
    prior_filing_id: str
    current_filing_id: str
    changes: tuple[HoldingChange13F, ...]
    total_eligible_value_prior: Decimal
    total_eligible_value_current: Decimal
    is_comparable: bool
    incomparable_reasons: tuple[str, ...] = ()
    is_value_comparable: bool = True
    coverage_status: str = "COMPLETE"
    comparison_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.manager_cik:
            raise ContractValidationError("manager_cik must be non-empty")
        p_val = parse_finite_decimal(self.total_eligible_value_prior)
        c_val = parse_finite_decimal(self.total_eligible_value_current)
        if p_val < 0 or c_val < 0:
            raise DecimalValidationError("Portfolio total values must be non-negative")
        if p_val != self.total_eligible_value_prior:
            object.__setattr__(self, "total_eligible_value_prior", p_val)
        if c_val != self.total_eligible_value_current:
            object.__setattr__(self, "total_eligible_value_current", c_val)


@dataclass(frozen=True, slots=True)
class EffectiveHoldingSet:
    """Synthesized effective portfolio holdings up to a point-in-time cutoff."""

    manager_cik: str
    report_period: str
    as_of: datetime
    base_filing_id: str
    contributing_accessions: tuple[str, ...]
    holdings: tuple[Holding13F, ...]
    total_eligible_value: Decimal
    has_restatements: bool = False
    has_additions: bool = False
    has_unresolved_amendments: bool = False
    unresolved_reasons: tuple[str, ...] = ()
    parsing_warnings: tuple[str, ...] = ()
    missing_row_count: int = 0
    coverage_status: str = "COMPLETE"
    scale_uncertain: bool = False

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise TimezoneValidationError("as_of must be timezone-aware")
        if not self.manager_cik or not self.report_period:
            raise ContractValidationError("manager_cik and report_period must be non-empty")
        val = parse_finite_decimal(self.total_eligible_value)
        if val < 0:
            raise DecimalValidationError("total_eligible_value must be non-negative")
        if val != self.total_eligible_value:
            object.__setattr__(self, "total_eligible_value", val)


@dataclass(frozen=True, slots=True)
class ParsedHoldingSet13F(HoldingSet13F):
    """Subclass of HoldingSet13F preserving XML parsing quality, row skips, and coverage status."""

    parsing_warnings: tuple[str, ...] = ()
    missing_row_count: int = 0
    total_rows_observed: int = 0
    coverage_status: str = "COMPLETE"
    scale_uncertain: bool = False
    source_vintage: str = "UNKNOWN"

    @classmethod
    def create_parsed(
        cls,
        filing_id: str,
        manager_cik: str,
        report_period: str,
        holdings: Iterable[Holding13F],
        *,
        total_eligible_value: Decimal,
        is_amended: bool = False,
        parsing_warnings: tuple[str, ...] = (),
        missing_row_count: int = 0,
        total_rows_observed: int = 0,
        coverage_status: str = "COMPLETE",
        scale_uncertain: bool = False,
        source_vintage: str = "UNKNOWN",
    ) -> ParsedHoldingSet13F:
        h_list = list(holdings)
        for h in h_list:
            if h.filing_id != filing_id:
                raise ContractValidationError(
                    f"Holding {h.holding_id} filing_id ({h.filing_id}) does not match HoldingSet ({filing_id})"
                )
        sorted_holdings = tuple(
            sorted(
                h_list,
                key=lambda h: (h.cusip, h.security_class or "", str(h.put_call), h.holding_id),
            )
        )
        t_val = parse_finite_decimal(total_eligible_value)
        if t_val < 0:
            raise DecimalValidationError("total_eligible_value must be non-negative")
        return cls(
            filing_id=filing_id,
            manager_cik=manager_cik,
            report_period=report_period,
            holdings=sorted_holdings,
            total_eligible_value=t_val,
            is_amended=is_amended,
            parsing_warnings=parsing_warnings,
            missing_row_count=missing_row_count,
            total_rows_observed=total_rows_observed,
            coverage_status=coverage_status,
            scale_uncertain=scale_uncertain,
            source_vintage=source_vintage,
        )


@dataclass(frozen=True, slots=True)
class InstitutionalFeatureSet:
    """Extracted point-in-time institutional signal features with strict UNVALIDATED gate."""

    manager_cik: str
    target_cusip: str
    as_of: datetime
    holding_period: str
    quarterly_share_change_pct: Decimal | None
    portfolio_weight_current: Decimal | None
    portfolio_weight_change: Decimal | None
    institutional_consensus_direction: int | None
    consecutive_quarters_held: int
    information_lag_days: int | None
    coverage_quality_score: Decimal | None
    is_point_in_time: bool = True
    score_status: str = "UNVALIDATED"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise TimezoneValidationError("as_of must be timezone-aware")
        if not self.manager_cik or not self.target_cusip:
            raise ContractValidationError("manager_cik and target_cusip must be non-empty")
        if self.score_status != "UNVALIDATED" and not self.is_point_in_time:
            raise ContractValidationError("Cannot validate non-point-in-time features")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Formal audit report produced by the point-in-time validation harness."""

    validation_id: str
    as_of: datetime
    universe_size: int
    period_start: str
    period_end: str
    lookahead_leak_detected: bool
    score_status: str = "UNVALIDATED"
    reasons: tuple[str, ...] = ()
    metric_results: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise TimezoneValidationError("as_of must be timezone-aware")
        if self.universe_size < 0:
            raise ContractValidationError("universe_size must be non-negative")


__all__ = [
    "AmendmentType",
    "EffectiveHoldingSet",
    "Filing13F",
    "Form13FKind",
    "Holding13F",
    "HoldingChange13F",
    "HoldingChangeStatus",
    "HoldingSet13F",
    "InstitutionalFeatureSet",
    "InstitutionalPortfolioComparison",
    "NoticeStatus",
    "ParsedHoldingSet13F",
    "PutCall",
    "QuantityType",
    "ValidationReport",
]
