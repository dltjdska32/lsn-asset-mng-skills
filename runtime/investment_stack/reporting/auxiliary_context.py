"""Chart and 13F context that cannot authorize a trade by itself."""

from __future__ import annotations

from datetime import datetime, timezone

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.institutional.models import InstitutionalFeatureSet
from investment_stack.institutional.scoring import check_13f_trade_gate
from investment_stack.reporting.models import Availability, ReportSectionInput


def trade_context_note() -> str:
    """Return the fixed statement that 13F scores are not a trading condition."""
    gate = check_13f_trade_gate(InstitutionalFeatureSet(
        manager_cik="UNBOUND",
        target_cusip="UNBOUND",
        as_of=datetime(1970, 1, 1, tzinfo=timezone.utc),
        holding_period="",
        quarterly_share_change_pct=None,
        portfolio_weight_current=None,
        portfolio_weight_change=None,
        institutional_consensus_direction=None,
        consecutive_quarters_held=0,
        information_lag_days=None,
        coverage_quality_score=None,
        is_point_in_time=False,
        score_status="UNAVAILABLE",
    ))
    return (
        "13F 점수는 기간 외 검증 전 매매 조건으로 사용하지 않습니다. "
        f"현재 거래 반영 상태는 {gate.state.value}입니다."
    )


def build_auxiliary_context_section(
    mode: str,
    instrument_id: str | None,
    run_db: RunDatabaseManager | None = None,
) -> ReportSectionInput:
    """State the fixed role of chart evidence and unvalidated 13F scores."""
    del run_db
    subject = instrument_id or "요청 범위"
    lines = (
        f"{mode} 모드의 차트·13F 맥락: {subject}.",
        "차트 지표는 저장된 봉과 재계산이 일치할 때만 기술적 분석 섹션에 표시하며, 그 자체로 매수·추가매수 수량이 되지 않습니다.",
        trade_context_note(),
    )
    return ReportSectionInput(
        f"auxiliary_context:{instrument_id or mode}",
        "차트·13F 맥락",
        lines,
        status=Availability.AVAILABLE,
        metadata={"mode": mode, "orders_posted": False},
    )
