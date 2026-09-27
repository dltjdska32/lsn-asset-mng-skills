"""Corporate actions normalization, split adjustments, and effective 13F amendment chain synthesis."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    PointInTimeError,
    TimezoneValidationError,
)
from investment_stack.contracts.institutional import (
    AmendmentType,
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingSet13F,
    PutCall,
    QuantityType,
)
from investment_stack.institutional.models import EffectiveHoldingSet


def apply_split_adjustment(
    holdings: Iterable[Holding13F],
    split_factor: Decimal,
) -> tuple[Holding13F, ...]:
    """Adjust holding share quantities for corporate actions (splits/reverse splits).

    Multiplies normalized_shares by split_factor. Raw historical values and reported
    total market value are preserved.
    """
    factor = parse_finite_decimal(split_factor)
    if factor <= Decimal("0"):
        raise DecimalValidationError(f"Split factor must be strictly positive, got: {split_factor}")

    adjusted: list[Holding13F] = []
    for h in holdings:
        # Only adjust share quantities, principal amounts are not share-split
        if h.quantity_type == QuantityType.SH:
            new_norm_shares = h.normalized_shares * factor
        else:
            new_norm_shares = h.normalized_shares

        adj_holding = Holding13F(
            holding_id=h.holding_id,
            filing_id=h.filing_id,
            cusip=h.cusip,
            issuer_name=h.issuer_name,
            raw_quantity=h.raw_quantity,
            raw_value=h.raw_value,
            normalized_value=h.normalized_value,
            normalized_shares=new_norm_shares,
            security_class=h.security_class,
            put_call=h.put_call,
            quantity_type=h.quantity_type,
            value_currency=h.value_currency,
            value_scale=h.value_scale,
            mapped_instrument_id=h.mapped_instrument_id,
            discretion=h.discretion,
            voting_sole=h.voting_sole,
            voting_shared=h.voting_shared,
            voting_none=h.voting_none,
        )
        adjusted.append(adj_holding)
    return tuple(adjusted)


def synthesize_effective_holdings(
    manager_cik: str,
    report_period: str,
    filings_with_holdings: Sequence[tuple[Filing13F, HoldingSet13F]],
    cutoff: datetime,
) -> EffectiveHoldingSet | None:
    """Synthesize effective 13F holdings up to cutoff by resolving amendment chains.

    Rules:
    - Only filings where public_availability.is_point_in_time_available(cutoff) are considered.
    - Process chronologically by acceptance / filing date.
    - Original 13F-HR establishes base portfolio.
    - 13F-HR/A with RESTATED completely replaces the active holding set.
    - 13F-HR/A with ADD_NEW_HOLDINGS adds previously omitted/confidential positions.
    - Unknown or conflicting amendment types are flagged as unresolved.
    """
    if cutoff.tzinfo is None:
        raise TimezoneValidationError("Cutoff datetime must be timezone-aware")

    # Filter to matching manager, report_period, and point-in-time eligible
    eligible: list[tuple[Filing13F, HoldingSet13F]] = []
    for filing, h_set in filings_with_holdings:
        if filing.manager_cik != manager_cik:
            continue
        if filing.report_period != report_period:
            continue
        if filing.public_availability.is_point_in_time_available(cutoff):
            eligible.append((filing, h_set))

    if not eligible:
        return None

    # Sort chronologically by acceptance timestamp, then filed date, then amendment number
    eligible.sort(
        key=lambda pair: (
            pair[0].public_availability.public_available_at or datetime.min.replace(tzinfo=timezone.utc),
            pair[0].filed_date,
            pair[0].amendment_number or 0,
            pair[0].accession,
        )
    )

    # Filing metadata controls the point-in-time selection; the attached holding
    # table must independently identify that same filing, manager, and period.
    # Reject mismatched payloads instead of letting rows cross filing boundaries.
    valid_eligible: list[tuple[Filing13F, HoldingSet13F]] = []
    input_integrity_errors: list[str] = []
    for filing, h_set in eligible:
        problems: list[str] = []
        if h_set.filing_id != filing.filing_id:
            problems.append("holding-set filing_id does not match filing")
        if h_set.manager_cik != filing.manager_cik:
            problems.append("holding-set manager_cik does not match filing")
        if h_set.report_period != filing.report_period:
            problems.append("holding-set report_period does not match filing")
        if any(h.filing_id != filing.filing_id for h in h_set.holdings):
            problems.append("one or more holding rows belong to a different filing")
        if problems:
            input_integrity_errors.append(
                f"Rejected filing {filing.accession}: " + "; ".join(problems)
            )
        else:
            valid_eligible.append((filing, h_set))

    if not valid_eligible:
        return None

    base_filing_id = ""
    contributing_accessions: list[str] = []
    active_holdings: dict[tuple[str, str, str, str], Holding13F] = {}
    has_restatements = False
    has_additions = False
    has_unresolved = bool(input_integrity_errors)
    unresolved_reasons: list[str] = list(input_integrity_errors)
    synth_warnings: list[str] = []
    used_pairs: list[tuple[Filing13F, HoldingSet13F]] = []
    base_accession: str | None = None

    for filing, h_set in valid_eligible:

        if filing.form == Form13FKind.HR or (
            filing.form == Form13FKind.HR_A and filing.amendment_type == AmendmentType.RESTATED
        ):
            if filing.form == Form13FKind.HR_A and filing.base_accession and base_accession and filing.base_accession != base_accession:
                has_unresolved = True
                unresolved_reasons.append(
                    f"Restatement {filing.accession} references unexpected base accession {filing.base_accession}"
                )
                continue
            if filing.form == Form13FKind.HR_A:
                has_restatements = True
            if not base_filing_id:
                base_filing_id = filing.filing_id
                base_accession = filing.accession
            # Complete replacement of holdings
            active_holdings.clear()
            for h in h_set.holdings:
                key = (h.cusip, h.security_class or "", str(h.put_call), str(h.quantity_type))
                active_holdings[key] = h
            contributing_accessions.append(filing.accession)
            used_pairs.append((filing, h_set))

        elif filing.form == Form13FKind.HR_A and filing.amendment_type == AmendmentType.ADD_NEW_HOLDINGS:
            if filing.base_accession and base_accession and filing.base_accession != base_accession:
                has_unresolved = True
                unresolved_reasons.append(
                    f"Addition {filing.accession} references unexpected base accession {filing.base_accession}"
                )
                continue
            if not base_filing_id:
                has_unresolved = True
                unresolved_reasons.append(
                    f"Addition {filing.accession} has no prior complete holdings filing to extend"
                )
                continue
            has_additions = True
            # Additive merge
            for h in h_set.holdings:
                key = (h.cusip, h.security_class or "", str(h.put_call), str(h.quantity_type))
                if key in active_holdings:
                    existing = active_holdings[key]
                    if (
                        existing.normalized_shares != h.normalized_shares
                        or existing.normalized_value != h.normalized_value
                    ):
                        has_unresolved = True
                        unresolved_reasons.append(
                            f"Duplicate conflicting key {key} in ADD_NEW_HOLDINGS accession {filing.accession}"
                        )
                    # An additive amendment cannot overwrite an already reported row.
                    # Identical duplicates are redundant; conflicting duplicates stay unresolved.
                    continue
                active_holdings[key] = h
            contributing_accessions.append(filing.accession)
            used_pairs.append((filing, h_set))

        elif filing.form == Form13FKind.HR_A and filing.amendment_type is None:
            # Ambiguous amendment without explicit restatement vs addition designation
            has_unresolved = True
            unresolved_reasons.append(
                f"Amendment {filing.accession} lacks explicit amendment_type (neither RESTATED nor ADD_NEW_HOLDINGS)"
            )
            # Do not guess whether a partial amendment replaces or adds rows.
            # Keep the last unambiguous snapshot and block downstream comparison.

        elif filing.form == Form13FKind.NT:
            # A notice-only filing contains no replacement holdings table.
            # Preserve the last holdings report; the notice is not a liquidation.
            has_unresolved = True
            unresolved_reasons.append(
                f"Notice-only filing {filing.accession} has no holdings table and cannot establish an effective snapshot"
            )
            synth_warnings.append(
                f"Notice-only filing {filing.accession} did not replace reported holdings"
            )

    has_missing_rows = False
    total_missing_rows = 0
    scale_uncertain = False
    for filing, h_set in used_pairs:
        if getattr(h_set, "missing_row_count", 0) > 0:
            has_missing_rows = True
            total_missing_rows += getattr(h_set, "missing_row_count", 0)
        if getattr(h_set, "scale_uncertain", False) or any(h.value_scale is None for h in h_set.holdings):
            scale_uncertain = True
        for w in getattr(h_set, "parsing_warnings", ()):
            synth_warnings.append(w)

    cov_status = "COMPLETE"
    if has_missing_rows:
        cov_status = "PARTIAL_MISSING_ROWS"
    elif scale_uncertain:
        cov_status = "UNCERTAIN_SCALE"

    sorted_holdings = tuple(
        sorted(
            active_holdings.values(),
            key=lambda h: (h.cusip, h.security_class or "", str(h.put_call), h.holding_id),
        )
    )
    if not base_filing_id:
        # A notice or unattached amendment alone is not a holdings snapshot.
        return None
    if scale_uncertain:
        total_val = Decimal("0")
    else:
        total_val = sum((h.normalized_value for h in sorted_holdings), Decimal("0"))

    return EffectiveHoldingSet(
        manager_cik=manager_cik,
        report_period=report_period,
        as_of=cutoff,
        base_filing_id=base_filing_id,
        contributing_accessions=tuple(contributing_accessions),
        holdings=sorted_holdings,
        total_eligible_value=total_val,
        has_restatements=has_restatements,
        has_additions=has_additions,
        has_unresolved_amendments=has_unresolved,
        unresolved_reasons=tuple(unresolved_reasons),
        parsing_warnings=tuple(synth_warnings),
        missing_row_count=total_missing_rows,
        coverage_status=cov_status,
        scale_uncertain=scale_uncertain,
    )


__all__ = [
    "apply_split_adjustment",
    "synthesize_effective_holdings",
]
