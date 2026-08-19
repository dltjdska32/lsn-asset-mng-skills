from __future__ import annotations

import unittest

from investment_stack.reporting.builder import InvestmentReportBuilder
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.review.engine import ConditionalReviewEngine
from investment_stack.review.models import ReviewContext
from tests.phase6_support import Phase6RunFixture, add_market


class Phase6AdversarialTests(unittest.TestCase, Phase6RunFixture):
    def setUp(self):
        self.temp, self.manager = self.make_run(self._testMethodName.replace("_", "-")[:48])
        self.addCleanup(self.temp.cleanup)

    def test_missing_evidence_reference_is_rejected(self):
        review = ConditionalReviewEngine(self.manager).evaluate()
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="Bad lineage",
                sections=(ReportSectionInput("bad", "Bad", ("claim",), evidence_ids=("missing",)),),
                review=review,
            )

    def test_unverified_base_case_is_rejected(self):
        add_market(self.manager, confirmation="UNVERIFIED")
        review = ConditionalReviewEngine(self.manager).evaluate(ReviewContext(base_case_evidence_ids=("e-market",)))
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="Bad base case",
                sections=(ReportSectionInput("thesis", "Thesis", ("base case changed",), evidence_ids=("e-market",), base_case=True),),
                review=review,
            )

    def test_optional_reviewer_failure_does_not_suppress_partial_report(self):
        runtime = Phase6ReportReviewRuntime(self.manager)
        def broken(_packet):
            raise RuntimeError("review service down")
        result = runtime.generate(
            title="Review fallback",
            sections=(ReportSectionInput("analysis", "Analysis", ("Deterministic analysis retained.",), status=Availability.PARTIAL),),
            review_context=ReviewContext(high_materiality=True),
            independent_reviewer=broken,
        )
        self.assertTrue(result.review.required)
        self.assertFalse(result.review.independent_reviewer_used)
        self.assertIn("Deterministic analysis retained.", result.report.markdown)

    def test_current_price_cannot_use_unselected_market_observation(self):
        add_market(self.manager, selected=False)
        review = ConditionalReviewEngine(self.manager).evaluate()
        with self.assertRaises(ValueError):
            InvestmentReportBuilder(self.manager).build(
                title="Unselected",
                sections=(ReportSectionInput("price", "Current Price", ("100",), evidence_ids=("e-market",), current_value_claim=True),),
                review=review,
            )

    def test_optional_reviewer_output_is_redacted_before_persistence(self):
        runtime = Phase6ReportReviewRuntime(self.manager)
        def reviewer(_packet):
            from investment_stack.review.models import FindingSeverity, ReviewFinding
            return (ReviewFinding(FindingSeverity.MEDIUM, "SECRET", "token=abc123"),)
        result = runtime.generate(
            title="Redaction",
            sections=(ReportSectionInput("analysis", "Analysis", ("safe",),),),
            review_context=ReviewContext(high_materiality=True),
            independent_reviewer=reviewer,
        )
        self.assertNotIn("abc123", result.report.markdown)
        self.assertNotIn("abc123", result.review.findings[-1].text)


if __name__ == "__main__":
    unittest.main()
