from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult
from investment_stack.reporting.builder import InvestmentReportBuilder
from investment_stack.reporting.models import Availability, Confidence, ReportSectionInput
from investment_stack.reporting.runtime import section_from_analysis_result
from investment_stack.review.engine import ConditionalReviewEngine
from investment_stack.review.models import FindingSeverity, ReviewContext, ReviewFinding, ReviewTrigger
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
        self.assertIn("Unknown: latest guidance unavailable", section.lines)
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
        self.assertIn("Market Data As Of: 2026-08-14T09:59:00+00:00", report.markdown)

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
