from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult
from investment_stack.reporting.builder import InvestmentReportBuilder
from investment_stack.reporting.models import Availability, Confidence, ReportSectionInput
from investment_stack.reporting.runtime import section_from_analysis_result
from investment_stack.review.engine import ConditionalReviewEngine
from investment_stack.review.models import FindingSeverity, ReviewContext, ReviewFinding, ReviewResult, ReviewTrigger
from tests.phase6_support import Phase6RunFixture, add_market


class Phase6UnitTests(unittest.TestCase, Phase6RunFixture):
    def setUp(self):
        self.temp, self.manager = self.make_run(self._testMethodName.replace("_", "-")[:48])
        self.addCleanup(self.temp.cleanup)

    def test_section_from_analysis_preserves_partial_and_unknown(self):
        result = AnalysisResult(
            "EQ", "fundamental", AnalysisStatus.PARTIAL,
            metrics=(MetricResult("roe", None, status=AnalysisStatus.PARTIAL, reason="missing equity", evidence_ids=("e1",)),),
            unknowns=("latest guidance unavailable",),
        )
        section = section_from_analysis_result(result)
        self.assertEqual(section.status, Availability.PARTIAL)
        self.assertIn("확인 불가: latest guidance unavailable", section.lines)
        self.assertFalse(any(line.startswith("Unknown:") or line.startswith("Risk:") for line in section.lines))
        self.assertIn("roe: UNKNOWN", "\n".join(section.lines))

    def test_current_value_requires_selected_timestamped_nonstale_market_evidence(self):
        add_market(self.manager)
        review = ConditionalReviewEngine(self.manager).evaluate()
        report = InvestmentReportBuilder(self.manager).build(
            title="TEST",
            sections=(ReportSectionInput("price", "Current Price", ("Price is 100 USD",), evidence_ids=("e-market",), current_value_claim=True),),
            review=review,
        )
        self.assertEqual(report.as_of.market_data_as_of, "2026-08-14T09:59:00+00:00")
        self.assertIn("시장 시세 기준시각: 2026-08-14T09:59:00+00:00", report.markdown)

    def test_stale_market_evidence_cannot_be_labeled_current(self):
        add_market(self.manager, freshness="STALE")
        review = ConditionalReviewEngine(self.manager).evaluate()
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="TEST",
                sections=(ReportSectionInput("price", "Current Price", ("100",), evidence_ids=("e-market",), current_value_claim=True),),
                review=review,
            )

    def test_retrieved_at_is_not_a_substitute_for_observed_at(self):
        add_market(self.manager, observed_at=None)
        review = ConditionalReviewEngine(self.manager).evaluate()
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="TEST",
                sections=(ReportSectionInput("price", "Current Price", ("100",), evidence_ids=("e-market",), current_value_claim=True),),
                review=review,
            )

    def test_rumor_cannot_change_base_case(self):
        add_market(self.manager, confirmation="RUMOR")
        review = ConditionalReviewEngine(self.manager).evaluate(ReviewContext(base_case_evidence_ids=("e-market",)))
        self.assertIn(ReviewTrigger.NEWS_REPORTED_OR_RUMOR_MATERIAL, review.triggers)
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="TEST",
                sections=(ReportSectionInput("thesis", "Base Case", ("Bullish",), evidence_ids=("e-market",), base_case=True),),
                review=review,
            )

    def test_news_reported_base_case_is_partial_and_triggers_review(self):
        add_market(self.manager, confirmation="NEWS_REPORTED")
        review = ConditionalReviewEngine(self.manager).evaluate(ReviewContext(base_case_evidence_ids=("e-market",)))
        report = InvestmentReportBuilder(self.manager).build(
            title="TEST",
            sections=(ReportSectionInput("thesis", "Base Case", ("Context only pending confirmation",), evidence_ids=("e-market",), base_case=True),),
            review=review,
        )
        self.assertTrue(review.required)
        self.assertEqual(report.availability, Availability.PARTIAL)

    def test_optional_reviewer_runs_only_when_triggered(self):
        calls = []
        engine = ConditionalReviewEngine(self.manager)
        clean = engine.evaluate(independent_reviewer=lambda packet: calls.append(packet) or ())
        self.assertFalse(clean.required)
        self.assertEqual(calls, [])
        triggered = engine.evaluate(
            ReviewContext(high_materiality=True),
            independent_reviewer=lambda packet: calls.append(packet) or (ReviewFinding(FindingSeverity.LOW, "CHECK", "reviewed"),),
        )
        self.assertTrue(triggered.required)
        self.assertEqual(len(calls), 1)
        self.assertTrue(triggered.independent_reviewer_used)

    def test_conflict_causes_low_confidence_review(self):
        self.manager.add_conflict(conflict_id="c1", conflict_type="SOURCE_VALUE_CONFLICT", status="OPEN", details={"values": [1, 2]})
        result = ConditionalReviewEngine(self.manager).evaluate()
        self.assertIn(ReviewTrigger.SOURCE_CONFLICT, result.triggers)
        self.assertEqual(result.confidence, Confidence.LOW)

    def test_partial_conflict_report_is_korean_and_keeps_ids_in_details(self):
        self.manager.add_conflict(conflict_id="conflict-private", conflict_type="SOURCE_VALUE_CONFLICT", status="OPEN", details={"values": [1, 2]})
        review = ConditionalReviewEngine(self.manager).evaluate()
        report = InvestmentReportBuilder(self.manager).build(
            title="TEST", sections=(ReportSectionInput("overview", "요약", ("자료를 확인했습니다",), status=Availability.PARTIAL),), review=review,
        )
        self.assertEqual(Availability.PARTIAL, report.availability)
        self.assertIn("자료 제공처 간 값이 다른 항목 1건", report.markdown)
        self.assertIn("하나의 값으로 합치지 않았습니다", report.markdown)
        body, details = report.markdown.split("## 상세 근거", maxsplit=1)
        self.assertNotIn("SOURCE_CONFLICT", body)
        self.assertIn("SOURCE_CONFLICT", details)
        self.assertNotIn("conflict-private", report.markdown)
        self.assertIn("분석 기준시각:", report.markdown)

    def test_material_review_codes_are_distinguished_and_unknown_details_are_retained(self):
        review = ConditionalReviewEngine(self.manager).evaluate()
        findings = (
            ReviewFinding(FindingSeverity.HIGH, "UNSUPPORTED_MODEL", "model not supported"),
            ReviewFinding(FindingSeverity.HIGH, "MISSING_CRITICAL_EVIDENCE", "evidence:private-42 missing"),
            ReviewFinding(FindingSeverity.HIGH, "CALCULATION_LINEAGE", "lineage could not be verified"),
            ReviewFinding(FindingSeverity.CRITICAL, "FUTURE_REVIEW_CODE", "source:private-17 needs investigation"),
        )
        review = ReviewResult(True, review.triggers, findings, Confidence.LOW)
        report = InvestmentReportBuilder(self.manager).build(title="TEST", sections=(), review=review)
        body, details = report.markdown.split("## 상세 근거", maxsplit=1)
        self.assertIn("요청한 분석 또는 가치평가 방법은 지원되지 않아", body)
        self.assertIn("판단에 필요한 핵심 근거가 연결되지 않아", body)
        self.assertIn("계산과 원자료의 연결을 확인할 수 없어", body)
        self.assertNotIn("FUTURE_REVIEW_CODE", body)
        self.assertNotIn("private-17", body)
        self.assertIn("FUTURE_REVIEW_CODE", details)
        self.assertIn("source:private-17 needs investigation", details)
        self.assertIn("MISSING_CRITICAL_EVIDENCE", details)
        self.assertIn("evidence:private-42 missing", details)

    def test_report_builder_returns_content_addressed_refs_without_owning_manifest(self):
        review = ConditionalReviewEngine(self.manager).evaluate()
        builder = InvestmentReportBuilder(self.manager)
        original = builder.build(title="TEST", sections=(ReportSectionInput("summary", "요약", ("처음 내용",)),), review=review)
        replay = builder.build(title="TEST", sections=(ReportSectionInput("summary", "요약", ("처음 내용",)),), review=review)
        revised = builder.build(title="TEST", sections=(ReportSectionInput("summary", "요약", ("다음 내용",)),), review=review)
        self.assertEqual(original.persisted_section_refs, replay.persisted_section_refs)
        self.assertNotEqual(original.persisted_section_refs[0][1], revised.persisted_section_refs[0][1])
        self.assertEqual("summary", original.persisted_section_refs[0][0])
        rows = self.manager.fetch_phase6_context()["report_sections"]
        report_rows = [row for row in rows if row["section_name"] == "summary"]
        self.assertEqual(2, len(report_rows))
        rows_by_id = {row["section_id"]: row for row in report_rows}
        for section_name, section_id, content_reference in revised.persisted_section_refs:
            if section_name == "summary":
                self.assertEqual(content_reference, rows_by_id[section_id]["content_reference"])
        self.assertFalse(any(row["section_name"] in {"final_briefing", "investment_briefing"} for row in rows))

    def test_materiality_pass_in_run_db_triggers_review(self):
        self.manager.add_materiality_decision(decision_id="m1", subject="EQ", decision="PASS", rationale="weight threshold")
        result = ConditionalReviewEngine(self.manager).evaluate()
        self.assertIn(ReviewTrigger.HIGH_MATERIALITY, result.triggers)

    def test_report_redacts_secret_shaped_text(self):
        review = ConditionalReviewEngine(self.manager).evaluate()
        report = InvestmentReportBuilder(self.manager).build(
            title="token=abc123 report",
            sections=(ReportSectionInput("notes", "Notes", ("api_key=supersecret",),),),
            review=review,
        )
        self.assertNotIn("abc123", report.markdown)
        self.assertNotIn("supersecret", report.markdown)
        self.assertIn("[REDACTED]", report.markdown)

    def test_empty_substantive_report_is_unavailable(self):
        review = ConditionalReviewEngine(self.manager).evaluate()
        report = InvestmentReportBuilder(self.manager).build(title="No Data", sections=(), review=review)
        self.assertEqual(report.availability, Availability.UNAVAILABLE)
        self.assertEqual(report.confidence, Confidence.LOW)


if __name__ == "__main__":
    unittest.main()
