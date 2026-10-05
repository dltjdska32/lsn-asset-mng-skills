"""Non-posting Korean D12 B section for a portfolio analysis.

An ID list, caller-built policy, or readiness flag cannot release prices or
quantities. Numbers appear only after this module re-reads run.db source
documents and the pinned personal ledger.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import sqlite3

from investment_stack.decisions.policy_b import EntryPricePrerequisites, PolicyBInput, PolicyBResult, evaluate_policy_b
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence
from investment_stack.decisions.policy_b_personal import bind_personal_snapshot
from investment_stack.decisions.policy_b_sizing import PolicyBSizingResult, size_policy_b_tranches
from investment_stack.evidence.source_receipt import load_thesis_status
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.storage.sqlite import sqlite_readonly_connection


def _money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _quantity(amount: Decimal) -> str:
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _quote_label(kind: str | None, source_count: int) -> str:
    if source_count > 1:
        scope = f"저장 출처 {source_count}곳의 가격이 일치"
    else:
        scope = "단일 저장 출처"
    integrity = "본문 해시 일치는 공급자나 공식 공시의 진위가 아닙니다."
    if kind == "LAST_VALID_CLOSE":
        return f"비실시간 마지막 유효 거래일 종가({scope}). {integrity}"
    if kind == "DELAYED":
        return f"지연 시세({scope}). {integrity}"
    return f"저장 본문을 재추출한 정규장 시세({scope}). {integrity}"


_MONITORING_LINE = (
    "감시: 급락·뉴스 중복·가이던스 차이·고객 집중·데이터센터는 저장된 값이 있을 때만 검토합니다. "
    "변동성 참고가는 행동 가격이 아니며 80/75/70 진입가와 수량을 바꾸지 않습니다. "
    "실시간 시세 본문은 refresh_market_bodies가 참일 때 저장하고, 재검증과 거래일 달력이 맞을 때만 현재가가 됩니다. "
    "본문 해시는 거래소 서명이 아닙니다. 기간 외 13F와 실제 개인 금액은 여기서 만들지 않습니다."
)


def _release_lines(
    run_db: object,
    personal_ledger: object,
    instrument_id: str,
    analysis_as_of: datetime,
    evaluation_currency: str | None,
) -> tuple[str, ...] | None:
    database = getattr(run_db, "database_path", None)
    run_id = getattr(run_db, "run_id", None)
    if not database or not isinstance(run_id, str) or not run_id:
        return None
    market = load_policy_b_market_evidence(
        database, run_id=run_id, instrument_id=instrument_id, as_of=analysis_as_of.isoformat(),
    )
    quote = market.quote_per_share
    currency = evaluation_currency.strip().upper() if isinstance(evaluation_currency, str) and evaluation_currency.strip() else ""
    if quote is None or not currency or quote.currency.upper() != currency:
        return None
    if any(item is None or not item.verified or item.currency.upper() != currency for item in (
        market.fair_value_per_share, market.optimistic_fair_value_per_share, market.conservative_fair_value_per_share,
    )):
        return None
    personal = bind_personal_snapshot(
        run_db, personal_ledger, instrument_id=instrument_id, evaluation_currency=currency,
    )
    if not personal.eligible_for_policy_sizing or personal.orders_posted or personal.trading_rules is None:
        return None
    try:
        with sqlite_readonly_connection(database) as connection:
            thesis = load_thesis_status(
                connection, run_id=run_id, instrument_id=instrument_id, cutoff=analysis_as_of,
            )
    except (OSError, sqlite3.Error, ValueError):
        return None
    if not isinstance(thesis, bool):
        return None
    policy = evaluate_policy_b(PolicyBInput(
        evaluation_currency=currency,
        fair_value_per_share=market.fair_value_per_share,
        optimistic_fair_value_per_share=market.optimistic_fair_value_per_share,
        quote_per_share=quote,
        portfolio_value=personal.portfolio_denominator,
        cash=personal.investable_cash,
        holding_value=personal.instrument_holding_value,
        holding_units=personal.instrument_holding_units,
        holding_units_verified=True,
        thesis_impaired=thesis,
        entry_price_prerequisites=EntryPricePrerequisites(True, True, True, True, True),
    ))
    if thesis:
        triggers = " ".join(policy.reduction_triggers) or "투자 논지 훼손으로 축소 재평가가 필요합니다."
        return (
            "지금 판단: 추가매수 중지. 기록된 투자 논지가 훼손되었습니다.",
            "가격·행동 표: 추가매수 가격·금액·수량은 계산하지 않습니다.",
            f"핵심 근거: {_quote_label(market.quote_kind, market.quote_source_count)} {_money(quote.amount)} {currency}/주.",
            f"판단 변경 조건: {triggers}",
            "상세 근거: 이 검토는 주문이나 원장 반영을 수행하지 않습니다.",
        )
    if policy.status != "CONDITIONAL" or policy.orders_posted:
        return None
    sizing = size_policy_b_tranches(policy, personal.trading_rules, receipt_bound=True)
    if sizing.status != "CONDITIONAL_NON_POSTING" or sizing.orders_posted or len(sizing.tiers) != 3:
        return None
    base = market.fair_value_per_share
    optimistic = market.optimistic_fair_value_per_share
    conservative = market.conservative_fair_value_per_share
    assert base is not None and optimistic is not None and conservative is not None
    assert policy.max_total_add_budget is not None
    tiers = []
    for index, tier in enumerate(sizing.tiers, start=1):
        tiers.append(
            f"{index}차 조건부 진입 {_money(tier.limit_price)} {currency}/주, "
            f"예산 {_money(policy.entry_tiers[index - 1].tranche_budget)} {currency}, "
            f"수량 {_quantity(tier.quantity)}주."
        )
    reduction = "현재 감지된 축소 검토: " + (
        " ".join(policy.reduction_triggers) if policy.reduction_triggers else "없음."
    )
    return (
        "지금 판단: 조건부 추가매수 검토. 주문이나 원장 반영은 하지 않습니다.",
        f"가격·행동 표: {_quote_label(market.quote_kind, market.quote_source_count)} {_money(quote.amount)} {currency}/주. "
        f"현금흐름 기준은 원문에 적힌 {market.cash_flow_basis}입니다. "
        f"모형 적정가 보수 {_money(conservative.amount)} / 기준 {_money(base.amount)} / "
        f"낙관 {_money(optimistic.amount)} {currency}/주. 적정가는 시장 예측 가격이 아닙니다. "
        + " ".join(tiers)
        + f" 추가 예산 상한 {_money(policy.max_total_add_budget)} {currency}.",
        "핵심 근거: 저장된 원문으로 재계산한 기준 적정가의 80/75/70% 분할, 예약금 제외 투자현금 하한 10%, v7 집중도 검토. "
        "차트와 13F 점수는 이 수량의 매매 조건이 아닙니다.",
        "판단 변경 조건: 집중도만으로 자동 감축하지 않으며, 검증된 낙관 적정가의 1.2배 이상이면 "
        f"보유량 1/3 축소 검토, 투자 논지 훼손 시 추가매수 중지. {reduction}",
        "상세 근거: 수량은 검증된 호가 단위·최소 거래 단위·수수료로 예산 안에서 내림한 비거래 계산입니다. "
        "민감도는 원문에 명시된 충격 가정이 있을 때만 따로 계산하며, 기본 충격은 만들지 않습니다.",
        _MONITORING_LINE,
    )


def build_policy_b_section(
    instrument_id: str,
    analysis_as_of: datetime,
    policy: PolicyBResult | None,
    *,
    sizing: PolicyBSizingResult | None = None,
    evidence_ids: tuple[str, ...] = (),
    calculation_ids: tuple[str, ...] = (),
    missing_inputs: tuple[str, ...] = (),
    run_db: object | None = None,
    personal_ledger: object | None = None,
    evaluation_currency: str | None = None,
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
        "핵심 근거: 가격 분할은 3회, 투자현금 하한은 10%이며 집중도는 v7 자본 경쟁에서 검토합니다.",
        "판단 변경 조건: 같은 기준시각의 적격 시세·가치평가·개인 상태·비용·거래 단위를 확인합니다. 검증된 낙관 가치의 1.2배 이상, 투자 근거 훼손은 축소 검토 조건입니다.",
        "상세 근거: 정책은 비거래 검토이며 자동 주문이나 원장 기록을 수행하지 않습니다.",
        _MONITORING_LINE,
    )
    if policy is not None and not isinstance(policy, PolicyBResult):
        raise TypeError("policy must be a PolicyBResult")
    if sizing is not None and not isinstance(sizing, PolicyBSizingResult):
        raise TypeError("sizing must be a PolicyBSizingResult")
    del evidence_ids, calculation_ids
    if run_db is not None and personal_ledger is not None:
        try:
            released = _release_lines(
                run_db, personal_ledger, instrument_id, analysis_as_of, evaluation_currency,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            released = None
        if released is not None:
            return ReportSectionInput(
                name, title, released, status=Availability.PARTIAL,
                metadata={"analysis_as_of": analysis_as_of.isoformat(), "non_posting": True,
                          "policy_status": "CONDITIONAL_NON_POSTING", "orders_posted": False},
            )
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
