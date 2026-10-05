"""Tests for ReportBuilder briefing output formatting."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from investment_stack.contracts.calculation import DataAvailabilityStatus, InvestmentDecision
from investment_stack.decisions.briefing import NonPostingBriefing
from investment_stack.reporting.builder import InvestmentReportBuilder
from investment_stack.reporting.models import Availability, Confidence, ReportSectionInput
from investment_stack.review.models import ReviewResult


class TestBuilderBriefingFormatting(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_db = MagicMock()
        self.mock_db.fetch_phase6_context.return_value = {
            "run_metadata": {
                "analysis_as_of": "2024-01-01T00:00:00Z",
                "analysis_timezone": "UTC"
            },
            "evidence": [],
            "calculations": [],
            "provider_states": [],
            "conflicts": [],
            "market_observations": [],
            "financial_observations": [],
            "macro_observations": [],
            "pinned_personal_state": {}
        }
        self.builder = InvestmentReportBuilder(self.mock_db)

    def test_briefing_markdown_formatting(self) -> None:
        briefing = NonPostingBriefing(
            status=DataAvailabilityStatus.PARTIAL,
            decision=InvestmentDecision.WAIT,
            section_judgement="대기 (최종 매수·규모 판단 보류)",
            section_table={"진행상태": "계산 불가: A도메인 통합 대기"},
            section_core=("기본 데이터 구조는 결속됨",),
            section_conditions=("할인율 산출 입수 시",),
            section_details=("디테일 사유 ID: 9999",),
            reasons=(),
            verified_hash="mock_hash_123"
        )

        review = ReviewResult(
            required=False,
            triggers=(),
            confidence=Confidence.HIGH,
            findings=()
        )

        report = self.builder.build(
            title="Test Report",
            sections=(),
            review=review,
            briefing=briefing
        )

        md = report.markdown

        # Verify 5 sections are present in order
        self.assertIn("1. **지금 판단**: 대기", md)
        self.assertIn("2. **가격·행동 표**:", md)
        self.assertIn("- 진행상태: 계산 불가", md)
        self.assertIn("3. **핵심 근거**:", md)
        self.assertIn("4. **판단 변경 조건**:", md)
        self.assertIn("5. **상세 근거**:", md)

        # IDs shouldn't leak to 1~4
        idx_core = md.find("3. **핵심 근거**")
        idx_cond = md.find("4. **판단 변경 조건**")
        idx_det = md.find("5. **상세 근거**")

        self.assertTrue(idx_core < idx_cond < idx_det)

        # Verify IDs are in section 5
        self.assertNotIn("9999", md[:idx_det])
        self.assertIn("9999", md[idx_det:])
