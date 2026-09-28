"""Non-posting Korean D12 B section for a portfolio analysis.

An ID list or a caller-supplied readiness flag is not a release receipt. Until
the reporting path can verify a complete pinned market and personal decision,
the public section must withhold actionable prices and quantities.
"""

from __future__ import annotations

from datetime import datetime
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
        "판단 변경 조건: 같은 기준시각의 적격 시세·가치평가·개인 상태·비용·거래 단위를 확인합니다. 보유 비중 10% 초과, 검증된 낙관 가치의 1.2배 이상, 투자 근거 훼손은 축소 검토 조건입니다.",
        "상세 근거: 정책은 비거래 검토이며 자동 주문이나 원장 기록을 수행하지 않습니다.",
    )
    if policy is not None and not isinstance(policy, PolicyBResult):
        raise TypeError("policy must be a PolicyBResult")
    reasons = tuple(dict.fromkeys((
        *missing_inputs,
        *((policy.unavailable_reasons) if policy else ()),
        "pinned market/personal decision release receipt is unavailable",
    )))
    lines = (*core, "확인 필요: 적정가의 가정 근거, 개인 보유·현금 상태, 예약 자금, 거래 비용과 단위.")
    return ReportSectionInput(
        name, title, lines, status=Availability.PARTIAL,
        metadata={"analysis_as_of": analysis_as_of.isoformat(), "non_posting": True,
                  "policy_status": "WAIT", "missing_inputs": reasons},
    )
