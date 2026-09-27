"""Non-posting judgements and 5-section Korean briefing contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

from investment_stack.contracts.calculation import CalculationRecord, DataAvailabilityStatus, InvestmentDecision
from investment_stack.contracts.slots import SelectedInputSet
from investment_stack.contracts.errors import ContractValidationError


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
            "현재가": "대기" if has_price else "계산 불가: 가격 누락",
            "목표/적정가": "대기" if calculations else "계산 불가: A결과 부재",
            "정책한도": "대기" if has_policy else "계산 불가: 정책 누락",
            "개인비중": "대기" if has_personal_snapshot else "계산 불가: 스냅샷 누락",
            "실행규모": "계산 불가: 판단 보류",
        }

        return NonPostingBriefing(
            status=status,
            decision=InvestmentDecision.INCONCLUSIVE,
            section_judgement="판단 보류 (핵심 입력 부재)",
            section_table=table,
            section_core=(),
            section_conditions=(),
            section_details=tuple(reasons),
            reasons=tuple(reasons),
            verified_hash=inputs.snapshot_hash
        )

    # Valid scenario (not fully implemented in current phase, fallback to WAIT)
    reasons.append("Domain A calculation results are structurally bound, but final BUY/scale judgement is explicitly reserved/withheld until A-domain results and approved policies are fully linked.")

    return NonPostingBriefing(
        status=DataAvailabilityStatus.PARTIAL,
        decision=InvestmentDecision.WAIT,
        section_judgement="대기 (최종 매수·규모 판단 보류)",
        section_table={"진행상태": "계산 불가: A도메인 실 판단 통합 대기"},
        section_core=("기본 데이터 구조는 결속되었으나, 구체적인 매매 임계값과 규모는 산출되지 않았습니다.",),
        section_conditions=("A 도메인의 적정가 및 할인율 산출 결과가 입수될 때,", "개인 포트폴리오 위험 한도 검증이 완료될 때."),
        section_details=tuple(reasons),
        reasons=tuple(reasons),
        verified_hash=inputs.snapshot_hash
    )

__all__ = ["NonPostingBriefing", "generate_briefing"]
