"""Safe Korean report projection for run-bound technical contexts."""

from __future__ import annotations

from investment_stack.calculations.technical import TechnicalAnalysisResult
from investment_stack.decisions.technical_context import (
    TechnicalBriefingContext,
    build_technical_briefing_context,
)
from investment_stack.decisions.technical_storage import verify_technical_run_binding
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.providers.ohlcv import OHLCVParseResult
from investment_stack.reporting.models import Availability, ReportSectionInput


_INDICATOR_LABELS = (
    ("sma", "단순이동평균(SMA)"),
    ("ema", "지수이동평균(EMA)"),
    ("rsi", "RSI"),
    ("macd", "MACD"),
    ("macd_signal", "MACD 시그널"),
    ("macd_histogram", "MACD 히스토그램"),
    ("relative_volume", "상대 거래량"),
    ("volatility", "변동성"),
    ("atr", "ATR"),
)


def build_technical_report_section(
    *,
    parse_result: OHLCVParseResult | None,
    analysis: TechnicalAnalysisResult | None,
    expected_instrument_id: str,
    run_db: RunDatabaseManager | None = None,
) -> ReportSectionInput:
    """Revalidate calculation and persisted Bar binding before rendering any data."""
    context: TechnicalBriefingContext = build_technical_briefing_context(parse_result, analysis)  # type: ignore[arg-type]
    reasons: list[str] = []
    if parse_result is None or analysis is None:
        reasons.append("TECHNICAL_INPUTS_MISSING")
    if context.status == "UNAVAILABLE":
        reasons.extend(context.reasons or ("TECHNICAL_CONTEXT_UNAVAILABLE",))
    if not isinstance(expected_instrument_id, str) or not expected_instrument_id.strip():
        reasons.append("EXPECTED_INSTRUMENT_ID_MISSING")
    if context.instrument_id != expected_instrument_id:
        reasons.append("TECHNICAL_CONTEXT_INSTRUMENT_MISMATCH")
    bound_evidence_ids: tuple[str, ...] = ()
    if parse_result is not None and run_db is not None and not reasons:
        binding = verify_technical_run_binding(run_db, parse_result, context)
        if binding is None:
            reasons.append("RUN_DATABASE_BINDING_UNVERIFIED")
        else:
            bound_evidence_ids = binding
    else:
        reasons.append("RUN_DATABASE_BINDING_UNVERIFIED")

    values_eligible = not reasons and bool(bound_evidence_ids)
    availability = Availability.UNAVAILABLE
    if values_eligible:
        try:
            availability = Availability(context.status)
        except ValueError:
            availability = Availability.UNAVAILABLE
            reasons.append("TECHNICAL_CONTEXT_STATUS_INVALID")
            values_eligible = False
    lines: list[str] = []
    if values_eligible:
        lines.append("지표는 저장된 run.db typed bar 근거와 입력값의 일치 확인 후 표시합니다.")
    else:
        lines.append("기술적 분석 수치는 실행(run)과 근거 자료의 검증된 연결을 확인할 수 없어 표시하지 않았습니다.")
    if values_eligible and context.last_session_date:
        lines.append(f"마지막 완료 세션: {context.last_session_date}")
    if values_eligible and context.delay_seconds is not None:
        lines.append(f"기준 시각 대비 자료 지연: {context.delay_seconds}초")
    if values_eligible and context.source_url:
        lines.append(f"자료 출처: {context.source_url}")
    if values_eligible:
        for name, label in _INDICATOR_LABELS:
            value = context.indicator(name)
            if value is not None:
                lines.append(f"{label}: {value}")
            else:
                lines.append(f"{label}: 확인 불가 ({'; '.join(context.reasons) or '값 없음'})")
        params = analysis.parameters
        lines.append(
            "계산 상세 근거: "
            f"공식 버전 {analysis.formula_version}; "
            f"SMA {params.sma_period}기간, EMA {params.ema_period}기간, "
            f"RSI {params.rsi_period}기간, MACD 빠른선/느린선/시그널 "
            f"{params.macd_fast}/{params.macd_slow}/{params.macd_signal}기간, "
            f"상대 거래량 {params.relative_volume_period}기간, "
            f"변동성 {params.volatility_period}기간, ATR {params.atr_period}기간."
        )
        lines.append("자료 한계: 출처 원본의 진위와 수정주가·거래일 증빙은 별도 확인이 필요합니다.")
    lines.append("매매 신호: 확인 불가")
    lines.append(f"자료 상태: {availability.value}")

    evidence_ids = bound_evidence_ids if values_eligible else ()
    metadata: dict[str, object] = {
        "technical_status": context.status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "signal_status": "UNAVAILABLE",
        "run_binding_status": "VERIFIED" if values_eligible else "UNVERIFIED",
        "run_id": run_db.run_id if values_eligible and run_db is not None else None,
        "indicator_values_withheld": not values_eligible,
        "missing_indicators": {
            name: {"label": label, "reason": context.reasons}
            for name, label in _INDICATOR_LABELS
            if not values_eligible or context.indicator(name) is None
        },
        "provenance_limitations": [
            "조정 및 거래일 달력 receipt는 caller 제공 표식이며 원본 기록과 대조 검증되지 않았습니다.",
            "run.db typed Bar 내용 hash, 종목, run ID, pinned cutoff가 계산 입력과 모두 일치해야 수치를 표시합니다.",
        ],
    }
    if values_eligible:
        params = analysis.parameters
        metadata.update({
            "instrument_id": context.instrument_id,
            "analysis_as_of": context.analysis_as_of,
            "latest_bar_close_time": context.latest_bar_close_time,
            "validation_receipt_id": context.validation_receipt_id,
            "input_fingerprint": context.input_fingerprint,
            "calculation_detail": {
                "formula_version": analysis.formula_version,
                "indicator_periods": {
                    "sma": params.sma_period,
                    "ema": params.ema_period,
                    "rsi": params.rsi_period,
                    "macd": {
                        "fast": params.macd_fast,
                        "slow": params.macd_slow,
                        "signal": params.macd_signal,
                    },
                    "relative_volume": params.relative_volume_period,
                    "volatility": params.volatility_period,
                    "atr": params.atr_period,
                },
            },
        })
    return ReportSectionInput(
        name="technical_analysis",
        title="기술적 분석",
        status=availability,
        lines=tuple(lines),
        evidence_ids=evidence_ids,
        metadata=metadata,
    )


__all__ = ["build_technical_report_section"]
