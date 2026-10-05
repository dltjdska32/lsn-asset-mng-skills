"""Point-in-time validation harness, lookahead leak detection, and governance audit reports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from investment_stack.contracts.errors import (
    PointInTimeError,
    TimezoneValidationError,
)
from investment_stack.contracts.institutional import (
    Filing13F,
    Holding13F,
    HoldingSet13F,
    NoticeStatus,
    QuantityType,
)
from investment_stack.institutional.models import (
    EffectiveHoldingSet,
    HoldingChangeStatus,
    InstitutionalPortfolioComparison,
    ValidationReport,
)
from investment_stack.institutional.normalize import synthesize_effective_holdings


def validate_lookahead_leak(
    filings: Iterable[Filing13F],
    as_of: datetime,
) -> tuple[bool, list[str]]:
    """Audit filings for future information leaks relative to as_of cutoff.

    Returns (has_leak, leak_details).
    """
    if as_of.tzinfo is None:
        raise TimezoneValidationError("as_of must be timezone-aware")

    leaks: list[str] = []
    for f in filings:
        if not f.public_availability.is_point_in_time_available(as_of):
            pub_at = f.public_availability.public_available_at or f.filed_date
            leaks.append(
                f"Filing {f.accession} (accepted/available at {pub_at}) is NOT point-in-time available at cutoff {as_of.isoformat()}"
            )

    return (len(leaks) > 0, leaks)


def validate_amendment_cutoff_invariance(
    manager_cik: str,
    report_period: str,
    filings_with_holdings: Sequence[tuple[Filing13F, HoldingSet13F]],
    as_of: datetime,
) -> tuple[bool, list[str]]:
    """Verify that future restatements/amendments do not leak into as_of effective holdings."""
    if as_of.tzinfo is None:
        raise TimezoneValidationError("as_of must be timezone-aware")

    errors: list[str] = []
    effective_at_cutoff = synthesize_effective_holdings(
        manager_cik, report_period, filings_with_holdings, as_of
    )

    if effective_at_cutoff is None:
        return (False, errors)

    # Check contributing accessions: none should have public_availability > as_of
    filing_map = {f.accession: f for f, _ in filings_with_holdings}
    for acc in effective_at_cutoff.contributing_accessions:
        f = filing_map.get(acc)
        if f is not None and not f.public_availability.is_point_in_time_available(as_of):
            errors.append(
                f"Effective holdings at {as_of.isoformat()} improperly consumed future amendment {acc}"
            )

    return (len(errors) > 0, errors)


def validate_absence_not_sold_under_confidential_omission(
    comparison: InstitutionalPortfolioComparison,
) -> tuple[bool, list[str]]:
    """Ensure that under confidential omission, missing holdings are NOT coded as liquidated/sold."""
    violations: list[str] = []
    for ch in comparison.changes:
        if ch.notice_status == NoticeStatus.CONFIDENTIAL_OMISSION:
            if ch.status == HoldingChangeStatus.CLOSED_POSITION:
                violations.append(
                    f"CUSIP {ch.cusip}: Position omitted under confidential treatment was incorrectly marked CLOSED_POSITION (Absence != Sold)"
                )
    return (len(violations) > 0, violations)


def validate_quantity_type_purity(
    holding_set: HoldingSet13F | EffectiveHoldingSet,
) -> tuple[bool, list[str]]:
    """Verify that SH (shares) and PRN (principal amount) holdings are kept distinct."""
    violations: list[str] = []
    seen_keys: set[tuple[str, str | None, Any, QuantityType]] = set()

    for h in holding_set.holdings:
        key = (h.cusip, h.security_class, h.put_call, h.quantity_type)
        if key in seen_keys:
            violations.append(f"Duplicate holding key with mixed or duplicate quantities: {key}")
        seen_keys.add(key)

    return (len(violations) > 0, violations)


def run_point_in_time_audit(
    validation_id: str,
    as_of: datetime,
    universe_size: int,
    filings: Iterable[Filing13F],
    comparisons: Sequence[InstitutionalPortfolioComparison],
    *,
    period_start: str = "",
    period_end: str = "",
    pre_registered_baseline: str | None = None,
) -> ValidationReport:
    """Execute complete Point-in-Time validation protocol and generate governance report."""
    if as_of.tzinfo is None:
        raise TimezoneValidationError("as_of must be timezone-aware")

    reasons: list[str] = []
    metric_results: dict[str, Any] = {}

    # Check 1: Lookahead leak test
    filings_list = list(filings)
    has_leak, leak_details = validate_lookahead_leak(filings_list, as_of)
    metric_results["lookahead_leak_detected"] = has_leak
    metric_results["leaked_filing_count"] = len(leak_details)
    if has_leak:
        reasons.extend(leak_details)

    # Check 2: Pre-registered baseline verification
    if not pre_registered_baseline:
        reasons.append(
            "Pre-registered benchmark baseline is missing; model improvement cannot be assessed per REQ R13"
        )
        metric_results["baseline_registered"] = False
    else:
        metric_results["baseline_registered"] = True
        metric_results["baseline_name"] = pre_registered_baseline

    # Check 3: Confidential omission absence audit
    conf_violations: list[str] = []
    for comp in comparisons:
        has_viol, viols = validate_absence_not_sold_under_confidential_omission(comp)
        if has_viol:
            conf_violations.extend(viols)
    metric_results["confidential_absence_violations"] = len(conf_violations)
    if conf_violations:
        reasons.extend(conf_violations)

    # Final score status determination
    if has_leak or conf_violations:
        score_status = "REJECTED"
    else:
        # Strict R13 rule: Without full out-of-sample backtest & independent review, status is UNVALIDATED
        score_status = "UNVALIDATED"
        reasons.append("13F model point-in-time audit complete; status is UNVALIDATED until independent review approval")

    return ValidationReport(
        validation_id=validation_id,
        as_of=as_of,
        universe_size=universe_size,
        period_start=period_start or (filings_list[0].report_period if filings_list else ""),
        period_end=period_end or (filings_list[-1].report_period if filings_list else ""),
        lookahead_leak_detected=has_leak,
        score_status=score_status,
        reasons=tuple(reasons),
        metric_results=metric_results,
    )


__all__ = [
    "run_point_in_time_audit",
    "validate_absence_not_sold_under_confidential_omission",
    "validate_amendment_cutoff_invariance",
    "validate_lookahead_leak",
    "validate_quantity_type_purity",
]
