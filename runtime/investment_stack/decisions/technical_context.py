"""Provenance-checked, non-posting technical context for briefings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from investment_stack.calculations.technical import (
    TechnicalAnalysisResult,
    TechnicalParameters,
    TechnicalPoint,
    calculate_verified_technical_analysis,
    _bar_fingerprint,
    _extract_bars,
    _validation_receipt_id,
)
from investment_stack.providers.ohlcv import OHLCVParseResult


@dataclass(frozen=True, slots=True)
class TechnicalBriefingContext:
    """Small briefing projection with source lineage and no trading instruction."""

    status: str  # AVAILABLE, PARTIAL, UNAVAILABLE
    reasons: tuple[str, ...]
    last_session_date: str | None
    source_url: str | None
    validation_receipt_id: str | None
    input_fingerprint: str | None
    evidence_ids: tuple[str, ...]
    indicators: tuple[tuple[str, Decimal | None], ...]
    signal_status: str = "UNAVAILABLE"

    def indicator(self, name: str) -> Decimal | None:
        return dict(self.indicators).get(name)


def build_technical_briefing_context(
    parse_result: OHLCVParseResult,
    analysis: TechnicalAnalysisResult,
) -> TechnicalBriefingContext:
    """Bind a calculated result to a verified, point-in-time-eligible OHLCV parse.

    Any mismatch or unavailable provenance fails closed. Raw bars are never accepted
    as an argument, and indicator conditions never imply a trading action.
    """
    if not isinstance(parse_result, OHLCVParseResult):
        return _unavailable("OHLCV_PARSE_RESULT_TYPE_INVALID")
    source = parse_result.source_url
    if not parse_result.analysis_eligible:
        return _unavailable("OHLCV_PARSE_NOT_ANALYSIS_ELIGIBLE", source=source)
    if not isinstance(analysis, TechnicalAnalysisResult):
        return _unavailable("TECHNICAL_RESULT_TYPE_INVALID", source=source)

    bar_set = parse_result.bar_set
    cutoff = parse_result.analysis_as_of
    if bar_set is None or cutoff is None or cutoff.tzinfo is None:
        return _unavailable("OHLCV_CUTOFF_OR_BARSET_UNAVAILABLE", source=source)
    bars = _extract_bars(bar_set)
    if not bars:
        return _unavailable("NO_VERIFIED_COMPLETED_BARS", source=source)
    for bar in bars:
        if not bar.is_complete or bar.close_time > cutoff:
            return _unavailable("FUTURE_OR_INCOMPLETE_BAR_REJECTED", source=source)
        if not bar.public_availability.is_point_in_time_available(cutoff):
            return _unavailable("BAR_PUBLIC_AVAILABILITY_NOT_VERIFIED_BY_CUTOFF", source=source)

    fingerprint = _bar_fingerprint(bars)
    receipt_id = _validation_receipt_id(parse_result)
    if (
        analysis.status not in {"AVAILABLE", "PARTIAL"}
        or analysis.source_url != source
        or analysis.input_fingerprint != fingerprint
        or analysis.validation_receipt_id != receipt_id
    ):
        return _unavailable(
            "TECHNICAL_RESULT_PROVENANCE_MISMATCH",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )

    points = analysis.points
    if len(points) != len(bars) or any(
        not isinstance(point, TechnicalPoint)
        or (point.bar_id, point.evidence_id, point.session_date)
        != (bar.bar_id, bar.evidence_id, bar.session_date)
        for point, bar in zip(points, bars)
    ):
        return _unavailable(
            "TECHNICAL_POINTS_NOT_BOUND_TO_VERIFIED_BARS",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )

    if not _valid_parameters(analysis.parameters):
        return _unavailable(
            "TECHNICAL_RESULT_PARAMETERS_INVALID",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )
    try:
        recalculated = calculate_verified_technical_analysis(parse_result, analysis.parameters)
    except Exception:
        return _unavailable(
            "TECHNICAL_RECALCULATION_FAILED",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )
    if recalculated.points != points or recalculated.status != analysis.status:
        return _unavailable(
            "TECHNICAL_VALUES_DO_NOT_MATCH_VERIFIED_INPUT",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )
    if (
        recalculated.reasons != analysis.reasons
        or recalculated.trend != analysis.trend
        or recalculated.formula_version != analysis.formula_version
        or recalculated.signal_status != analysis.signal_status
    ):
        return _unavailable(
            "TECHNICAL_METADATA_DOES_NOT_MATCH_VERIFIED_INPUT",
            source=source,
            receipt=receipt_id,
            fingerprint=fingerprint,
        )

    # Project only from the fresh calculation, never from caller-supplied result fields.
    verified_points = recalculated.points
    latest = verified_points[-1]
    macd = latest.macd
    indicators: tuple[tuple[str, Decimal | None], ...] = (
        ("sma", latest.sma),
        ("ema", latest.ema),
        ("rsi", latest.rsi),
        ("macd", macd.macd if macd else None),
        ("macd_signal", macd.signal if macd else None),
        ("macd_histogram", macd.histogram if macd else None),
        ("relative_volume", latest.relative_volume),
        ("volatility", latest.volatility),
        ("atr", latest.atr),
    )
    incomplete = tuple(name for name, value in indicators if value is None)
    reasons = tuple(recalculated.reasons) + (("INSUFFICIENT_LOOKBACK_OR_VALUE_UNAVAILABLE",) if incomplete else ())
    status = "PARTIAL" if recalculated.status == "PARTIAL" or incomplete else "AVAILABLE"
    return TechnicalBriefingContext(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        last_session_date=latest.session_date,
        source_url=source,
        validation_receipt_id=receipt_id,
        input_fingerprint=fingerprint,
        evidence_ids=tuple(point.evidence_id for point in verified_points),
        indicators=indicators,
        signal_status="UNAVAILABLE",
    )


def _unavailable(
    reason: str,
    *,
    source: str | None = None,
    receipt: str | None = None,
    fingerprint: str | None = None,
) -> TechnicalBriefingContext:
    return TechnicalBriefingContext(
        status="UNAVAILABLE",
        reasons=(reason,),
        last_session_date=None,
        source_url=source,
        validation_receipt_id=receipt,
        input_fingerprint=fingerprint,
        evidence_ids=(),
        indicators=(),
        signal_status="UNAVAILABLE",
    )


def _valid_parameters(value: object) -> bool:
    if not isinstance(value, TechnicalParameters):
        return False
    periods = (
        value.sma_period,
        value.ema_period,
        value.rsi_period,
        value.macd_fast,
        value.macd_slow,
        value.macd_signal,
        value.relative_volume_period,
        value.volatility_period,
        value.atr_period,
        value.trend_fast,
        value.trend_slow,
    )
    if any(type(period) is not int or period <= 0 for period in periods):
        return False
    return value.macd_fast < value.macd_slow and value.volatility_period >= 2
