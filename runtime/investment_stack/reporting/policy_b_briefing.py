"""Non-posting Korean D12 B section for a verified portfolio analysis.

The caller must validate calculation/evidence references against its pinned run
before passing them here. This formatter does not turn reference IDs into proof.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from investment_stack.decisions.policy_b import PolicyBResult
from investment_stack.decisions.policy_b_sizing import PolicyBSizingResult
from investment_stack.reporting.models import Availability, ReportSectionInput


def build_policy_b_section(
    instrument_id: str,
    analysis_as_of: datetime,
    policy: PolicyBResult | None,
    *,
    sizing: PolicyBSizingResult | None = None,
    evidence_ids: tuple[str, ...] = (),
    calculation_ids: tuple[str, ...] = (),
    missing_inputs: tuple[str, ...] = (),
) -> ReportSectionInput:
    """Render a D12 B policy result while withholding unbound numeric actions."""
    if not isinstance(instrument_id, str) or not instrument_id.strip():
        raise ValueError("instrument_id is required")
    if not isinstance(analysis_as_of, datetime) or analysis_as_of.tzinfo is None:
        raise ValueError("analysis_as_of must be timezone-aware")
    name = f"policy_b:{instrument_id}"
    title = f"추가매수·축소 검토: {instrument_id}"
    core = (
        "지금 판단: 대기. 개인 상태와 가격·가치의 검증된 연결 없이는 거래 규모를 제안하지 않습니다.",
        "가격·행동 표: 진입 가격·금액·수량 대기.",
        "핵심 근거: D12 B 정책은 3회 분할, 종목 8% 상한, 투자현금 10% 하한을 정합니다.",
        "판단 변경 조건: 같은 기준시각의 적격 시세·가치평가·개인 상태·비용·거래 단위를 확인합니다.",
        "상세 근거: 정책은 비거래 검토이며 자동 주문이나 원장 기록을 수행하지 않습니다.",
    )
    if policy is not None and not isinstance(policy, PolicyBResult):
        raise TypeError("policy must be a PolicyBResult")
    reasons = tuple(dict.fromkeys((*missing_inputs, *((policy.unavailable_reasons) if policy else ()))))
    if (
        policy is None or policy.status != "CONDITIONAL" or policy.orders_posted
        or len(policy.entry_tiers) != 3
        or not isinstance(policy.max_total_add_budget, Decimal)
        or not policy.max_total_add_budget.is_finite()
        or policy.additions_stopped or policy.max_total_add_budget <= 0
        or not evidence_ids or not calculation_ids or reasons
    ):
        lines = (*core, "확인 필요: 적정가의 가정 근거, 개인 보유·현금 상태, 예약 자금, 거래 비용과 단위.")
        return ReportSectionInput(
            name, title, lines, status=Availability.PARTIAL,
            metadata={"analysis_as_of": analysis_as_of.isoformat(), "non_posting": True,
                      "policy_status": "WAIT", "missing_inputs": reasons},
        )

    if (
        not isinstance(policy.max_total_add_budget, Decimal)
        or not policy.max_total_add_budget.is_finite()
        or policy.max_total_add_budget < 0
        or any(not isinstance(tier.price, Decimal) or not tier.price.is_finite()
               or tier.price <= 0 or tier.tranche_budget < 0 for tier in policy.entry_tiers)
    ):
        raise ValueError("invalid policy result cannot be displayed")
    prices = ", ".join(
        f"{index}차 {tier.price} {policy.evaluation_currency}/주 이하"
        for index, tier in enumerate(policy.entry_tiers, 1)
    )
    quantity_text = "거래 수량은 별도 비용·거래 단위 검증 전 대기."
    if (isinstance(sizing, PolicyBSizingResult) and sizing.status == "CONDITIONAL"
            and not sizing.orders_posted and len(sizing.tiers) == 3
            and isinstance(sizing.total_maximum_cost, Decimal)
            and sizing.total_maximum_cost.is_finite()
            and sizing.total_maximum_cost <= policy.max_total_add_budget
            and all(
                isinstance(sized.limit_price, Decimal) and sized.limit_price.is_finite()
                and sized.limit_price > 0 and sized.limit_price <= reference.price
                and isinstance(sized.quantity, Decimal) and sized.quantity.is_finite()
                and sized.quantity > 0
                and isinstance(sized.maximum_cost, Decimal) and sized.maximum_cost.is_finite()
                and sized.maximum_cost > 0 and sized.maximum_cost <= reference.tranche_budget
                for sized, reference in zip(sizing.tiers, policy.entry_tiers)
            )
            and sum((tier.maximum_cost for tier in sizing.tiers), Decimal(0)) == sizing.total_maximum_cost):
        quantity_text = "검증된 거래 단위 기준 조건부 수량: " + ", ".join(
            f"{index}차 {tier.quantity}주(상한 {tier.limit_price} {policy.evaluation_currency}/주)"
            for index, tier in enumerate(sizing.tiers, 1)
        ) + ". 주문은 생성하지 않았습니다."
    lines = (
        "지금 판단: 조건부 검토. 매수·축소는 자동 실행되지 않습니다.",
        f"가격·행동 표: {prices}; 추가 예산 상한 {policy.max_total_add_budget} {policy.evaluation_currency}. {quantity_text}",
        "핵심 근거: D12 B는 종목 8% 상한과 투자현금 10% 하한에서 3회 분할을 검토합니다.",
        "판단 변경 조건: 투자 근거 훼손, 비중 10% 초과, 가격이 검증된 낙관 적정가의 1.2배 이상이면 추가매수를 멈추거나 축소를 재검토합니다.",
        "상세 근거: 비거래 정책 계산 결과입니다. 실제 주문은 생성하지 않았습니다.",
    )
    if policy.additions_stopped:
        lines = ("지금 판단: 추가매수 중지. 자동 거래는 없습니다.", *lines[1:])
    return ReportSectionInput(
        name, title, lines, status=Availability.AVAILABLE,
        evidence_ids=evidence_ids, calculation_ids=calculation_ids,
        metadata={"analysis_as_of": analysis_as_of.isoformat(), "non_posting": True,
                  "policy_status": "CONDITIONAL", "stop_reasons": policy.stop_reasons,
                  "reduction_triggers": policy.reduction_triggers},
    )
