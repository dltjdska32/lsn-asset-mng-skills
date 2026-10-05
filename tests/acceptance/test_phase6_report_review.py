from __future__ import annotations

import unittest

from investment_stack.reporting.models import Availability, Confidence, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.review.models import ReviewContext
from tests.phase6_support import Phase6RunFixture, add_market


class Phase6AcceptanceTests(unittest.TestCase, Phase6RunFixture):
    def setUp(self):
        self.temp, self.manager = self.make_run(self._testMethodName.replace("_", "-")[:48])
        self.addCleanup(self.temp.cleanup)

    def test_partial_unknown_report_is_emitted_instead_of_fabricated_value(self):
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="FANUC Analysis",
            sections=(
                ReportSectionInput("fundamental", "Fundamental", ("Business analysis completed.",), status=Availability.AVAILABLE),
                ReportSectionInput("valuation", "Valuation", ("Current price: UNKNOWN", "Current-price comparison unavailable."), status=Availability.PARTIAL),
            ),
        )
        self.assertEqual(result.report.availability, Availability.PARTIAL)
        self.assertEqual(result.report.confidence, Confidence.MEDIUM)
        self.assertIn("Current price: UNKNOWN", result.report.markdown)
        self.assertIn("시장 시세 기준시각: 확인 불가", result.report.markdown)

    def test_material_stale_data_triggers_conditional_review(self):
        add_market(self.manager, freshness="STALE")
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Stale Evidence",
            sections=(ReportSectionInput("analysis", "Analysis", ("Latest usable quote is stale.",), status=Availability.PARTIAL, evidence_ids=("e-market",)),),
            review_context=ReviewContext(critical_evidence_ids=("e-market",), high_materiality=True),
        )
        self.assertTrue(result.review.required)
        self.assertEqual(result.report.confidence, Confidence.LOW)
        self.assertIn("추가 검토: 필요", result.report.markdown)
        self.assertIn("STALE", result.report.markdown)

    def test_strategy_is_reported_as_analysis_not_execution(self):
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Portfolio Strategy",
            sections=(ReportSectionInput("strategy", "Strategy", ("Candidate: reduce concentration range; no order is created.",), status=Availability.AVAILABLE),),
            review_context=ReviewContext(strong_strategy_change=True),
        )
        self.assertTrue(result.review.required)
        self.assertIn("no order is created", result.report.markdown)

    def test_unavailable_report_triggers_low_confidence_review(self):
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Unavailable",
            sections=(ReportSectionInput("valuation", "Valuation", ("Current price: UNKNOWN",), status=Availability.UNAVAILABLE),),
        )
        self.assertTrue(result.review.required)
        self.assertEqual(result.report.availability, Availability.UNAVAILABLE)
        self.assertEqual(result.report.confidence, Confidence.LOW)


if __name__ == "__main__":
    unittest.main()
