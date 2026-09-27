"""Non-posting judgements and 5-section Korean briefing contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import re
from typing import Mapping

from investment_stack.contracts.calculation import (
    CalculationRecord,
    CalculationStatus,
    DataAvailabilityStatus,
    FormulaRequirement,
    GateDecision,
    InvestmentDecision,
    OutputKind,
    validate_calculation_for_use,
)
from investment_stack.contracts.codec import format_decimal
from investment_stack.contracts.context import PublicAvailabilityKind
from investment_stack.contracts.errors import ContractValidationError
from investment_stack.contracts.institutional import Filing13F
from investment_stack.contracts.slots import EligibilityDecision, EligibilityStatus, SelectedInputSet
from investment_stack.institutional.models import EffectiveHoldingSet, ValidationReport


@dataclass(frozen=True, slots=True)
class InstitutionalBriefingContext:
    """Source-bound, non-scoring 13F summary for a user-facing briefing."""

    report_period: str
    publication_label: str
    validation_status: str
    accessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NumericBinding:
    """Typed output rendered from one calculation and its eligible selected evidence."""

    key: str
    value: Decimal
    unit: str
    currency: str
    calculation_id: str
    evidence_ids: tuple[str, ...]
    public_available_at: str
    conditional: bool = False


def _collect_numeric_bindings(
    inputs: SelectedInputSet,
    calculations: Mapping[str, CalculationRecord],
    eligibility_decisions: Mapping[str, EligibilityDecision] | None,
    analysis_as_of: datetime | None,
    registered_gates: tuple[GateDecision, ...],
) -> tuple[NumericBinding, ...]:
    """Fail closed unless semantic output and every source input are explicitly bound."""
    if analysis_as_of is None or analysis_as_of.tzinfo is None or eligibility_decisions is None:
        return ()
    selected_by_slot = {slot.slot_id: slot for slot in inputs.slots}
    candidates: dict[str, list[NumericBinding]] = {"current_price": [], "valuation": []}
    allowed_units = {"currency/share", "price/share", "money/share"}

    for calc_key, record in calculations.items():
        if (
            calc_key != record.calculation_id
            or not record.bound_inputs
            or not record.verify_lineage()
            or record.run_id != inputs.run_id
            or record.selection_snapshot_hash != inputs.snapshot_hash
        ):
            continue
        purpose = (record.purpose or "").upper()
        if purpose == "CURRENT_PRICE":
            output_kind = OutputKind.PRICE
            binding_key = "current_price"
            if record.status != CalculationStatus.CALCULATED:
                continue
        elif purpose == "VALUATION_MODEL":
            output_kind = OutputKind.VALUATION
            binding_key = "valuation"
            if record.requirement != FormulaRequirement.ANALYST_SCENARIO:
                continue
            if record.status not in {CalculationStatus.CALCULATED, CalculationStatus.CONDITIONAL}:
                continue
        else:
            continue

        evidence_ids: set[str] = set()
        public_times: list[datetime] = []
        lineage_ok = True
        for bound in record.bound_inputs:
            selected = selected_by_slot.get(bound.slot_id)
            decision = eligibility_decisions.get(bound.eligibility_id)
            if (
                selected is None
                or selected.canonical_value != bound.canonical_value
                or selected.canonical_unit != bound.canonical_unit
                or selected.canonical_currency != bound.canonical_currency
                or selected.evidence_id != bound.evidence_id
                or selected.input_fingerprint != bound.input_fingerprint
                or selected.eligibility_id != bound.eligibility_id
                or selected.public_available_at != bound.public_available_at
                or not bound.eligibility_id
                or decision is None
                or decision.eligibility_id != bound.eligibility_id
                or decision.status != EligibilityStatus.ELIGIBLE
                or decision.input_fingerprint != bound.input_fingerprint
                or not bound.public_available_at
                or (
                    purpose == "CURRENT_PRICE"
                    and decision.purpose.upper() != "CURRENT_PRICE"
                )
                or (
                    purpose == "VALUATION_MODEL"
                    and decision.purpose.upper() not in {"FINANCIAL_CALC", "VALUATION_MODEL"}
                )
            ):
                lineage_ok = False
                break
            try:
                available_at = datetime.fromisoformat(bound.public_available_at.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                lineage_ok = False
                break
            if available_at.tzinfo is None or available_at > analysis_as_of:
                lineage_ok = False
                break
            public_times.append(available_at)
            evidence_ids.add(bound.evidence_id)
        if not lineage_ok or not evidence_ids:
            continue

        try:
            validated = validate_calculation_for_use(record, registered_gates=registered_gates)
        except ContractValidationError:
            continue
        if not validated.is_consumable:
            continue
        matches = [output for output in validated.outputs if output.kind == output_kind]
        # No scenario-name field exists, so a scenario value cannot be assigned to
        # conservative/base/optimistic by tuple order.
        if len(matches) != 1:
            continue
        output = matches[0]
        unit = output.unit.strip().casefold()
        currency = (output.currency or "").strip().upper()
        currency_unit = f"{currency.casefold()}/share"
        valid_per_share_unit = unit in allowed_units or unit == currency_unit
        if not valid_per_share_unit or not re.fullmatch(r"[A-Z]{3}", currency) or output.value <= 0:
            continue
        candidates[binding_key].append(
            NumericBinding(
                key=binding_key,
                value=output.value,
                unit=output.unit,
                currency=currency,
                calculation_id=record.calculation_id,
                evidence_ids=tuple(sorted(evidence_ids)),
                public_available_at=max(public_times).isoformat(),
                # Analyst scenario outputs are assumptions-based estimates, not a
                # definitive fair price, even when their calculation status is
                # CALCULATED. Preserve that distinction in the user-facing label.
                conditional=(
                    record.status == CalculationStatus.CONDITIONAL
                    or purpose == "VALUATION_MODEL"
                    and record.requirement == FormulaRequirement.ANALYST_SCENARIO
                ),
            )
        )

    # Conflicting eligible calculations are not averaged or selected by input order.
    return tuple(bindings[0] for bindings in candidates.values() if len(bindings) == 1)


def _display_numeric_bindings(table: dict[str, str], details: list[str], bindings: tuple[NumericBinding, ...]) -> None:
    """Show only lineage-checked facts; displaying a fact never authorizes an action."""
    for binding in bindings:
        value_text = f"{format_decimal(binding.value)} {binding.currency}/주"
        if binding.conditional:
            value_text += " (조건부 산출값)"
        table["현재가" if binding.key == "current_price" else "적정가 산출값"] = value_text
        details.append(
            f"수치 근거 — calculation `{binding.calculation_id}`; evidence "
            + ", ".join(f"`{evidence_id}`" for evidence_id in binding.evidence_ids)
            + f"; 공개시점 {binding.public_available_at}."
        )


def make_institutional_briefing_context(
    effective: EffectiveHoldingSet,
    selected_filings: tuple[Filing13F, ...],
    validation: ValidationReport,
) -> InstitutionalBriefingContext:
    """Bind an effective 13F snapshot to its selected public filings and audit cutoff."""
    if effective.as_of != validation.as_of:
        raise ContractValidationError("13F effective holdings and validation report must share the same cutoff")
    filing_by_accession = {filing.accession: filing for filing in selected_filings}
    if len(filing_by_accession) != len(selected_filings):
        raise ContractValidationError("selected 13F accessions must be unique")
    missing = [accession for accession in effective.contributing_accessions if accession not in filing_by_accession]
    if missing:
        raise ContractValidationError("effective 13F holdings reference missing selected filings")

    bound = [filing_by_accession[accession] for accession in effective.contributing_accessions]
    for filing in bound:
        if filing.manager_cik != effective.manager_cik or filing.report_period != effective.report_period:
            raise ContractValidationError("13F contributing filing identity does not match effective holdings")
        if not filing.public_availability.is_point_in_time_available(effective.as_of):
            raise ContractValidationError("13F contributing filing was not public at the pinned cutoff")

    exact_times = [
        filing.public_availability.public_available_at
        for filing in bound
        if filing.public_availability.kind == PublicAvailabilityKind.EXACT
    ]
    date_bounds = [
        filing.public_availability.interval_end
        for filing in bound
        if filing.public_availability.kind == PublicAvailabilityKind.DATE_INTERVAL
    ]
    has_unknown = any(
        filing.public_availability.kind == PublicAvailabilityKind.UNKNOWN for filing in bound
    )
    if has_unknown or not bound:
        publication_label = "공개시각 확인 불가"
    elif date_bounds and (not exact_times or max(date_bounds) >= max(exact_times)):
        publication_label = f"날짜만 확인; 보수적 공개 경계 {max(date_bounds).isoformat()}"
    else:
        publication_label = f"공개 확인 {max(exact_times).isoformat()}"

    if validation.score_status == "REJECTED":
        validation_status = "검증 실패"
    elif effective.has_unresolved_amendments or effective.coverage_status != "COMPLETE":
        validation_status = "불완전·미검증"
    else:
        validation_status = "미검증"
    return InstitutionalBriefingContext(
        report_period=effective.report_period,
        publication_label=publication_label,
        validation_status=validation_status,
        accessions=tuple(effective.contributing_accessions),
    )


@dataclass(frozen=True, slots=True)
class NonPostingBriefing:
    """Non-posting judgement briefing contract with 5 fixed sections."""

    status: DataAvailabilityStatus
    decision: InvestmentDecision

    # 5 Sections
    section_judgement: str
    section_table: Mapping[str, str]
    section_core: tuple[str, ...]
    section_conditions: tuple[str, ...]
    section_details: tuple[str, ...]

    reasons: tuple[str, ...]
    verified_hash: str
    numeric_bindings: tuple[NumericBinding, ...] = ()

    def __post_init__(self) -> None:
        if self.status in (DataAvailabilityStatus.PARTIAL, DataAvailabilityStatus.UNAVAILABLE):
            if self.decision not in (InvestmentDecision.WAIT, InvestmentDecision.INCONCLUSIVE):
                raise ContractValidationError(
                    f"Briefing status is {self.status}, decision must be WAIT or INCONCLUSIVE"
                )


def generate_briefing(
    inputs: SelectedInputSet,
    calculations: Mapping[str, CalculationRecord],
    has_price: bool,
    has_policy: bool,
    has_personal_snapshot: bool,
    institutional_context: InstitutionalBriefingContext | None = None,
    *,
    eligibility_decisions: Mapping[str, EligibilityDecision] | None = None,
    analysis_as_of: datetime | None = None,
    registered_gates: tuple[GateDecision, ...] = (),
) -> NonPostingBriefing:
    """Generate a 5-section Korean briefing without posting any trades."""
    reasons = []

    # 1. Integrity checks
    hash_ok = inputs.verify_hash()
    if not hash_ok:
        reasons.append("SelectedInputSet hash verification failed.")

    lineage_errors = []

    input_slots_by_id = {s.slot_id: s for s in inputs.slots}

    for calc_id, calc in calculations.items():
        if not calc.verify_lineage():
            lineage_errors.append(f"CalculationRecord {calc_id} lineage failed.")
        if calc.run_id != inputs.run_id:
            lineage_errors.append(f"CalculationRecord {calc_id} run_id mismatch.")
        if calc.selection_snapshot_hash != inputs.snapshot_hash:
            lineage_errors.append(f"CalculationRecord {calc_id} selection_snapshot_hash mismatch.")

        for bound in calc.bound_inputs:
            ref_slot = input_slots_by_id.get(bound.slot_id)
            if not ref_slot:
                lineage_errors.append(f"CalculationRecord {calc_id} has unbounded slot {bound.slot_id}.")
                continue
            if bound.canonical_value != ref_slot.canonical_value:
                lineage_errors.append(f"CalculationRecord {calc_id} slot {bound.slot_id} value mismatch.")
            if bound.canonical_unit != ref_slot.canonical_unit:
                lineage_errors.append(f"CalculationRecord {calc_id} slot {bound.slot_id} unit mismatch.")
            if bound.canonical_currency != ref_slot.canonical_currency:
                lineage_errors.append(f"CalculationRecord {calc_id} slot {bound.slot_id} currency mismatch.")
            if bound.evidence_id != ref_slot.evidence_id:
                lineage_errors.append(f"CalculationRecord {calc_id} slot {bound.slot_id} evidence_id mismatch.")
            if bound.input_fingerprint != ref_slot.input_fingerprint:
                lineage_errors.append(f"CalculationRecord {calc_id} slot {bound.slot_id} fingerprint mismatch.")

    if lineage_errors:
        reasons.extend(lineage_errors)

    if not hash_ok or lineage_errors:
        return NonPostingBriefing(
            status=DataAvailabilityStatus.UNAVAILABLE,
            decision=InvestmentDecision.INCONCLUSIVE,
            section_judgement="판단 보류 (데이터 무결성 검증 실패)",
            section_table={"현재가": "계산 불가: 무결성 실패", "적정가": "계산 불가: 무결성 실패", "행동규모": "계산 불가: 무결성 실패"},
            section_core=(),
            section_conditions=(),
            section_details=tuple(reasons),
            reasons=tuple(reasons),
            verified_hash=""
        )

    numeric_bindings = _collect_numeric_bindings(
        inputs, calculations, eligibility_decisions, analysis_as_of, registered_gates
    )

    # 2. Completeness checks
    if not calculations:
        reasons.append("A 도메인 결과 부재 (계산 내역 없음).")
    if not has_price:
        reasons.append("시장 가격 데이터 부재.")
    if not has_policy:
        reasons.append("승인된 정책 한도 데이터 부재.")
    if not has_personal_snapshot:
        reasons.append("개인 포트폴리오 스냅샷 부재.")

    if reasons:
        status = DataAvailabilityStatus.UNAVAILABLE

        table = {
            "현재가": "계산 불가: 적격 가격 근거 미연결" if has_price else "계산 불가: 가격 누락",
            "적정가 산출값": "계산 불가: 적격 가치평가 근거 미연결" if calculations else "계산 불가: A결과 부재",
            "정책한도": "대기" if has_policy else "계산 불가: 정책 누락",
            "개인비중": "대기" if has_personal_snapshot else "계산 불가: 스냅샷 누락",
            "실행규모": "계산 불가: 판단 보류",
        }
        details = list(reasons)
        visible_bindings = tuple(
            binding for binding in numeric_bindings
            if binding.key != "current_price" or has_price
        )
        _display_numeric_bindings(table, details, visible_bindings)

        return NonPostingBriefing(
            status=status,
            decision=InvestmentDecision.INCONCLUSIVE,
            section_judgement="판단 보류 (핵심 입력 부재)",
            section_table=table,
            section_core=(),
            section_conditions=(),
            section_details=tuple(details),
            reasons=tuple(reasons),
            verified_hash=inputs.snapshot_hash,
            numeric_bindings=visible_bindings,
        )

    # Numeric market/valuation outputs may be displayed only through typed bindings.
    # They do not authorize any action or sizing policy.
    reasons.append("안전마진·개인 위험·축소 정책 provenance가 확인되지 않아 행동 판단과 규모 산출을 보류합니다.")
    core_lines = [
        "13F 자료는 공개 지연이 있는 보조 근거이며, UNVALIDATED 점수는 판단 가중치나 거래 신호로 쓰지 않습니다."
    ]
    detail_lines = list(reasons)
    table = {
        "현재가": "계산 불가: 적격 가격 근거 미연결",
        "적정가 산출값": "계산 불가: 적격 가치평가 근거 미연결",
        "진입·추가매수 구간": "계산 불가: 승인된 안전마진 정책 미확인",
        "축소 구간": "계산 불가: 승인된 축소 정책 미확인",
        "금액·수량": "계산 불가: 승인 정책 provenance 미검증",
    }
    _display_numeric_bindings(table, detail_lines, numeric_bindings)
    if institutional_context is not None:
        core_lines.append(
            f"13F 보고 기준일 {institutional_context.report_period}; 공개시점: {institutional_context.publication_label}; "
            f"점수 {institutional_context.validation_status}, 거래 판단 미반영."
        )
        detail_lines.append(
            "13F 원문 accession: " + (", ".join(institutional_context.accessions) or "확인 불가")
        )

    return NonPostingBriefing(
        status=DataAvailabilityStatus.PARTIAL,
        decision=InvestmentDecision.WAIT,
        section_judgement="대기 — 승인된 투자·위험 정책을 확인할 때까지 매수·추가매수·축소 판단을 보류합니다.",
        section_table=table,
        section_core=tuple(core_lines),
        section_conditions=("A 도메인의 적격 가격과 가치평가 결과가 결속될 때 재평가합니다.", "승인된 정책 출처와 같은 시점의 개인 상태가 검증된 뒤에만 규모를 계산합니다."),
        section_details=tuple(detail_lines),
        reasons=tuple(reasons),
        verified_hash=inputs.snapshot_hash,
        numeric_bindings=numeric_bindings,
    )

__all__ = [
    "InstitutionalBriefingContext",
    "NumericBinding",
    "NonPostingBriefing",
    "generate_briefing",
    "make_institutional_briefing_context",
]
