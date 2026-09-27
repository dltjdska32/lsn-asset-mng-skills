"""Portfolio comparison across consecutive periods with split adjustment, absence distinction, and incomparability safeguards."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import calendar
from decimal import Decimal

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
)
from investment_stack.contracts.institutional import (
    Holding13F,
    HoldingSet13F,
    NoticeStatus,
    PutCall,
    QuantityType,
)
from investment_stack.institutional.models import (
    EffectiveHoldingSet,
    HoldingChange13F,
    HoldingChangeStatus,
    InstitutionalPortfolioComparison,
)
from investment_stack.institutional.normalize import apply_split_adjustment


def is_consecutive_quarter_periods(prior_period: str, current_period: str) -> bool:
    """True only for ordered, adjacent calendar-quarter end dates."""
    try:
        prior = date.fromisoformat(prior_period)
        current = date.fromisoformat(current_period)
    except (TypeError, ValueError):
        return False

    def quarter_index(period: date) -> int | None:
        quarter = (period.month - 1) // 3
        end_month = (quarter + 1) * 3
        if period.month != end_month or period.day != calendar.monthrange(period.year, end_month)[1]:
            return None
        return period.year * 4 + quarter

    prior_index = quarter_index(prior)
    current_index = quarter_index(current)
    return prior_index is not None and current_index == prior_index + 1


def compare_portfolios(
    prior_set: HoldingSet13F | EffectiveHoldingSet,
    current_set: HoldingSet13F | EffectiveHoldingSet,
    *,
    split_factors: Mapping[str, Decimal] | None = None,
    is_confidential_omission: bool = False,
    coverage_uncertain: bool = False,
    prior_public_availability: PublicAvailability | None = None,
    current_public_availability: PublicAvailability | None = None,
) -> InstitutionalPortfolioComparison:
    """Compare holdings of a manager between prior and current observation periods.

    Strict Invariants (REQ R12):
    - Absence != Sold: An absence of a holding in 13F must NOT be asserted as an actual sale fact.
      Under confidential omission or uncertain coverage, absent positions are NOT_REPORTED.
    - Strict Comparability Checks:
      - Manager mismatch -> is_comparable = False
    - Reversed, non-quarter-end, identical, or non-adjacent observation periods -> is_comparable = False
      - Notice-only filing -> is_comparable = False
      - Instrument kind / unit mismatch (e.g. PRN vs SH, Put/Call option vs equity, class mismatch)
        for the same CUSIP -> classified as INCOMPARABLE, never assumed sold.
    - QuantityType purity: SH compared with SH, PRN compared with PRN.
    - Split adjustment applied to prior shares for accurate delta calculation.
    """
    incomparable_reasons: list[str] = []
    is_comparable = True

    # 1. Manager check
    if prior_set.manager_cik != current_set.manager_cik:
        is_comparable = False
        incomparable_reasons.append(
            f"Manager mismatch: {prior_set.manager_cik} vs {current_set.manager_cik}"
        )

    # 2. Period check: a quarter-over-quarter change must use adjacent quarter ends.
    if not is_consecutive_quarter_periods(prior_set.report_period, current_set.report_period):
        is_comparable = False
        if prior_set.report_period == current_set.report_period:
            incomparable_reasons.append(
                f"Observation periods must be distinct, got identical period: {prior_set.report_period}"
            )
        else:
            incomparable_reasons.append(
                "Observation periods must be ordered adjacent calendar quarter ends: "
                f"{prior_set.report_period} -> {current_set.report_period}"
            )

    # 3. Empty holdings check
    if not prior_set.holdings and not current_set.holdings:
        is_comparable = False
        incomparable_reasons.append("Both observation periods have empty holdings")

    # 4. Notice status check on effective holding sets
    if isinstance(prior_set, EffectiveHoldingSet) and prior_set.has_unresolved_amendments:
        is_comparable = False
        incomparable_reasons.append(
            f"Prior period has unresolved amendments: {prior_set.unresolved_reasons}"
        )
    if isinstance(current_set, EffectiveHoldingSet) and current_set.has_unresolved_amendments:
        is_comparable = False
        incomparable_reasons.append(
            f"Current period has unresolved amendments: {current_set.unresolved_reasons}"
        )

    if not is_comparable:
        prior_filing_id = prior_set.base_filing_id if isinstance(prior_set, EffectiveHoldingSet) else prior_set.filing_id
        current_filing_id = current_set.base_filing_id if isinstance(current_set, EffectiveHoldingSet) else current_set.filing_id
        return InstitutionalPortfolioComparison(
            manager_cik=prior_set.manager_cik,
            prior_period=prior_set.report_period,
            current_period=current_set.report_period,
            prior_filing_id=prior_filing_id,
            current_filing_id=current_filing_id,
            changes=(),
            total_eligible_value_prior=prior_set.total_eligible_value,
            total_eligible_value_current=current_set.total_eligible_value,
            is_comparable=False,
            incomparable_reasons=tuple(incomparable_reasons),
            is_value_comparable=False,
            coverage_status="INCOMPARABLE",
            comparison_warnings=("No position deltas or portfolio weights were calculated because the filing sets are not comparable.",),
            prior_public_availability=prior_public_availability,
            current_public_availability=current_public_availability,
        )

    factors = split_factors or {}

    prior_cov = getattr(prior_set, "coverage_status", "COMPLETE")
    curr_cov = getattr(current_set, "coverage_status", "COMPLETE")
    prior_missing = getattr(prior_set, "missing_row_count", 0)
    curr_missing = getattr(current_set, "missing_row_count", 0)
    incomplete_coverage = (
        coverage_uncertain
        or is_confidential_omission
        or prior_cov != "COMPLETE"
        or curr_cov != "COMPLETE"
        or prior_missing > 0
        or curr_missing > 0
    )

    prior_scale_unc = getattr(prior_set, "scale_uncertain", False) or any(
        h.value_scale is None for h in prior_set.holdings
    )
    curr_scale_unc = getattr(current_set, "scale_uncertain", False) or any(
        h.value_scale is None for h in current_set.holdings
    )
    # Reported weights use the reported portfolio total as denominator. If any
    # rows are missing or confidentially omitted, that denominator is incomplete.
    is_val_comparable = not (prior_scale_unc or curr_scale_unc or incomplete_coverage)
    comparison_warnings: list[str] = []
    if not is_val_comparable:
        comparison_warnings.append(
            "Reported values and weights unavailable: value scale or complete portfolio coverage is not established"
        )

    has_partial_coverage = incomplete_coverage
    overall_coverage_status = "PARTIAL" if has_partial_coverage else "COMPLETE"
    if prior_missing > 0:
        comparison_warnings.append(f"Prior period has {prior_missing} missing/skipped rows")
    if curr_missing > 0:
        comparison_warnings.append(f"Current period has {curr_missing} missing/skipped rows")

    # Build prior dictionary: key -> (Holding13F, adjusted_shares)
    prior_map: dict[tuple[str, str, PutCall, QuantityType], tuple[Holding13F, Decimal]] = {}
    prior_cusips: dict[str, list[tuple[str, str, PutCall, QuantityType]]] = {}
    for h in prior_set.holdings:
        factor = factors.get(h.cusip, Decimal("1"))
        if h.quantity_type == QuantityType.SH and factor != Decimal("1"):
            adj_shares = h.normalized_shares * factor
        else:
            adj_shares = h.normalized_shares

        key = (h.cusip, h.security_class or "", h.put_call, h.quantity_type)
        prior_map[key] = (h, adj_shares)
        prior_cusips.setdefault(h.cusip, []).append(key)

    # Build current dictionary: key -> Holding13F
    current_map: dict[tuple[str, str, PutCall, QuantityType], Holding13F] = {}
    current_cusips: dict[str, list[tuple[str, str, PutCall, QuantityType]]] = {}
    for h in current_set.holdings:
        key = (h.cusip, h.security_class or "", h.put_call, h.quantity_type)
        current_map[key] = h
        current_cusips.setdefault(h.cusip, []).append(key)

    all_keys = set(prior_map.keys()) | set(current_map.keys())
    changes: list[HoldingChange13F] = []

    prior_tot_val = prior_set.total_eligible_value
    curr_tot_val = current_set.total_eligible_value

    prior_filing_id = (
        prior_set.base_filing_id if isinstance(prior_set, EffectiveHoldingSet) else prior_set.filing_id
    )
    current_filing_id = (
        current_set.base_filing_id if isinstance(current_set, EffectiveHoldingSet) else current_set.filing_id
    )

    for key in sorted(all_keys, key=lambda k: (k[0], k[1], str(k[2]), str(k[3]))):
        cusip, sec_class, put_call, qty_type = key

        in_prior = key in prior_map
        in_curr = key in current_map

        if in_prior and in_curr:
            h_prior, prior_shares = prior_map[key]
            h_curr = current_map[key]
            curr_shares = h_curr.normalized_shares

            issuer_name = h_curr.issuer_name or h_prior.issuer_name
            delta_shares = curr_shares - prior_shares
            if prior_shares > Decimal("0"):
                delta_pct = delta_shares / prior_shares
            else:
                delta_pct = None

            if is_val_comparable:
                prior_val = h_prior.normalized_value
                curr_val = h_curr.normalized_value
                prior_wt = prior_val / prior_tot_val if prior_tot_val > Decimal("0") else Decimal("0")
                curr_wt = curr_val / curr_tot_val if curr_tot_val > Decimal("0") else Decimal("0")
                delta_wt = curr_wt - prior_wt
            else:
                prior_val = None
                curr_val = None
                prior_wt = None
                curr_wt = None
                delta_wt = None

            if delta_shares > Decimal("0"):
                status = HoldingChangeStatus.INCREASED
            elif delta_shares < Decimal("0"):
                status = HoldingChangeStatus.DECREASED
            else:
                status = HoldingChangeStatus.UNCHANGED

            is_split_adj = factors.get(cusip, Decimal("1")) != Decimal("1")
            changes.append(
                HoldingChange13F(
                    manager_cik=prior_set.manager_cik,
                    cusip=cusip,
                    issuer_name=issuer_name,
                    security_class=sec_class or None,
                    quantity_type=qty_type,
                    put_call=put_call,
                    prior_shares=prior_shares,
                    current_shares=curr_shares,
                    share_change=delta_shares,
                    share_change_pct=delta_pct,
                    prior_value=prior_val,
                    current_value=curr_val,
                    prior_weight=prior_wt,
                    current_weight=curr_wt,
                    weight_change=delta_wt,
                    status=status,
                    is_split_adjusted=is_split_adj,
                    notice_status=NoticeStatus.COMPLETE,
                )
            )

        elif in_curr and not in_prior:
            h_curr = current_map[key]
            curr_shares = h_curr.normalized_shares

            if is_val_comparable:
                curr_val = h_curr.normalized_value
                curr_wt = curr_val / curr_tot_val if curr_tot_val > Decimal("0") else Decimal("0")
                prior_wt = Decimal("0")
                delta_wt = curr_wt
            else:
                curr_val = None
                curr_wt = None
                prior_wt = None
                delta_wt = None

            # Check if this CUSIP existed in prior under a different class, option, or PRN/SH
            other_prior_keys = prior_cusips.get(cusip, [])
            if other_prior_keys:
                status = HoldingChangeStatus.INCOMPARABLE
            else:
                status = HoldingChangeStatus.NEW_POSITION

            changes.append(
                HoldingChange13F(
                    manager_cik=current_set.manager_cik,
                    cusip=cusip,
                    issuer_name=h_curr.issuer_name,
                    security_class=sec_class or None,
                    quantity_type=qty_type,
                    put_call=put_call,
                    prior_shares=None,
                    current_shares=curr_shares,
                    share_change=curr_shares,
                    share_change_pct=None,
                    prior_value=None,
                    current_value=curr_val,
                    prior_weight=prior_wt,
                    current_weight=curr_wt,
                    weight_change=delta_wt,
                    status=status,
                    is_split_adjusted=False,
                    notice_status=NoticeStatus.COMPLETE,
                )
            )

        elif in_prior and not in_curr:
            h_prior, prior_shares = prior_map[key]

            if is_val_comparable:
                prior_val = h_prior.normalized_value
                prior_wt = prior_val / prior_tot_val if prior_tot_val > Decimal("0") else Decimal("0")
                curr_wt = Decimal("0")
                delta_wt = -prior_wt
            else:
                prior_val = None
                prior_wt = None
                curr_wt = None
                delta_wt = None

            delta_shares = -prior_shares

            # Check if this CUSIP still exists in current under a different class, option, or PRN/SH
            other_curr_keys = current_cusips.get(cusip, [])
            if other_curr_keys:
                status = HoldingChangeStatus.INCOMPARABLE
                notice_st = NoticeStatus.COMPLETE
            elif has_partial_coverage:
                # Absence != Sold: Under confidential omission, uncertain coverage, or missing rows,
                # absent position cannot be asserted as sold!
                status = HoldingChangeStatus.NOT_REPORTED
                notice_st = (
                    NoticeStatus.CONFIDENTIAL_OMISSION if is_confidential_omission else NoticeStatus.COMPLETE
                )
            else:
                # Closed position in complete 13F report
                status = HoldingChangeStatus.CLOSED_POSITION
                notice_st = NoticeStatus.COMPLETE

            is_split_adj = factors.get(cusip, Decimal("1")) != Decimal("1")
            changes.append(
                HoldingChange13F(
                    manager_cik=prior_set.manager_cik,
                    cusip=cusip,
                    issuer_name=h_prior.issuer_name,
                    security_class=sec_class or None,
                    quantity_type=qty_type,
                    put_call=put_call,
                    prior_shares=prior_shares,
                    current_shares=None,
                    share_change=delta_shares if status == HoldingChangeStatus.CLOSED_POSITION else None,
                    share_change_pct=Decimal("-1.0") if status == HoldingChangeStatus.CLOSED_POSITION else None,
                    prior_value=prior_val,
                    current_value=None,
                    prior_weight=prior_wt,
                    current_weight=curr_wt,
                    weight_change=delta_wt,
                    status=status,
                    is_split_adjusted=is_split_adj,
                    notice_status=notice_st,
                )
            )

    return InstitutionalPortfolioComparison(
        manager_cik=prior_set.manager_cik,
        prior_period=prior_set.report_period,
        current_period=current_set.report_period,
        prior_filing_id=prior_filing_id,
        current_filing_id=current_filing_id,
        changes=tuple(changes),
        total_eligible_value_prior=prior_tot_val,
        total_eligible_value_current=curr_tot_val,
        is_comparable=is_comparable,
        incomparable_reasons=tuple(incomparable_reasons),
        is_value_comparable=is_val_comparable,
        coverage_status=overall_coverage_status,
        comparison_warnings=tuple(comparison_warnings),
        prior_public_availability=prior_public_availability,
        current_public_availability=current_public_availability,
    )


__all__ = ["compare_portfolios", "is_consecutive_quarter_periods"]
