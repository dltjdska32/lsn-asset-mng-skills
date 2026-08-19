from __future__ import annotations

import json
import sqlite3
import unittest

from investment_stack.reporting.models import Availability, Confidence, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.review.models import ReviewContext, ReviewTrigger
from tests.phase6_support import Phase6RunFixture, add_financial, add_macro, add_market


class Phase6IntegrationTests(unittest.TestCase, Phase6RunFixture):
    def setUp(self):
        self.temp, self.manager = self.make_run(self._testMethodName.replace("_", "-")[:48])
        self.addCleanup(self.temp.cleanup)

    def test_full_asof_headers_and_persistence(self):
        add_market(self.manager)
        add_financial(self.manager)
        add_macro(self.manager)
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Integrated Report",
            sections=(
                ReportSectionInput("price", "Current Price", ("100 USD",), evidence_ids=("e-market",), current_value_claim=True),
                ReportSectionInput("financial", "Financials", ("Revenue 1000",), evidence_ids=("e-fin",)),
                ReportSectionInput("macro", "Macro", ("Real rate 1.5",), evidence_ids=("e-macro",)),
            ),
        )
        self.assertEqual(result.report.availability, Availability.AVAILABLE)
        self.assertEqual(result.report.confidence, Confidence.HIGH)
        self.assertEqual(result.report.as_of.market_data_as_of, "2026-08-14T09:59:00+00:00")
        self.assertEqual(result.report.as_of.financial_data_as_of, "2026-06-30")
        self.assertEqual(result.report.as_of.macro_data_as_of, "2026-08-12T00:00:00+00:00")
        self.assertEqual(result.report.as_of.portfolio_data_as_of, "2026-08-14T08:00:00+00:00")
        raw = sqlite3.connect(self.manager.database_path)
        try:
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM report_sections").fetchone()[0], 4)
            metadata_json = raw.execute("SELECT metadata_json FROM report_sections WHERE section_id='section:price'").fetchone()[0]
        finally:
            raw.close()
        metadata = json.loads(metadata_json)
        self.assertEqual(metadata["evidence_ids"], ["e-market"])
        self.assertEqual(metadata["analysis_as_of"], self.cutoff)

    def test_review_findings_are_persisted_to_run_db_only(self):
        add_market(self.manager, freshness="STALE")
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Partial",
            sections=(ReportSectionInput("analysis", "Analysis", ("Data is stale",), status=Availability.PARTIAL, evidence_ids=("e-market",)),),
            review_context=ReviewContext(critical_evidence_ids=("e-market",)),
        )
        self.assertTrue(result.review.required)
        self.assertIn(ReviewTrigger.STALE_OR_UNKNOWN_CRITICAL_DATA, result.review.triggers)
        self.assertEqual(result.report.confidence, Confidence.LOW)
        raw = sqlite3.connect(self.manager.database_path)
        try:
            count = raw.execute("SELECT COUNT(*) FROM review_findings").fetchone()[0]
        finally:
            raw.close()
        self.assertGreaterEqual(count, 1)
        self.assertFalse((self.manager.workspace_root.parent / "personal.db").exists())

    def test_calculation_lineage_failure_triggers_review_but_report_continues(self):
        self.manager.add_calculation(
            calculation_id="calc-broken",
            calculation_name="broken",
            formula="x",
            inputs={"evidence_ids": ["missing-evidence"]},
            result={"value": "1"},
        )
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Lineage Partial",
            sections=(ReportSectionInput("analysis", "Analysis", ("Result with lineage warning",), status=Availability.PARTIAL, calculation_ids=("calc-broken",)),),
        )
        self.assertIn(ReviewTrigger.LINEAGE_FAILURE, result.review.triggers)
        self.assertEqual(result.review.confidence, Confidence.LOW)
        self.assertTrue(result.report.markdown.startswith("# Lineage Partial"))

    def test_provider_unavailable_keeps_partial_report_available(self):
        self.manager.record_provider_state(provider_name="dart", provider_status="MISSING_CREDENTIAL", capability="fundamentals")
        runtime = Phase6ReportReviewRuntime(self.manager)
        result = runtime.generate(
            title="Partial Provider",
            sections=(ReportSectionInput("fundamentals", "Fundamentals", ("Official filing unavailable; fallback analysis retained.",), status=Availability.PARTIAL),),
        )
        self.assertEqual(result.report.availability, Availability.PARTIAL)
        self.assertIn("MISSING_CREDENTIAL", result.report.markdown)

    def test_singular_evidence_id_lineage_is_checked(self):
        self.manager.add_calculation(
            calculation_id="calc-singular", calculation_name="x", formula="x",
            inputs={"evidence_id": "missing-one"}, result={"value": "1"},
        )
        result = Phase6ReportReviewRuntime(self.manager).generate(
            title="Singular lineage",
            sections=(ReportSectionInput("analysis", "Analysis", ("partial",), status=Availability.PARTIAL, calculation_ids=("calc-singular",)),),
        )
        self.assertIn(ReviewTrigger.LINEAGE_FAILURE, result.review.triggers)


if __name__ == "__main__":
    unittest.main()
