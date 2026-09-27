"""Read-only independent regressions; all data is synthetic and temporary.

Run from repository root with PYTHONPATH=runtime; these assertions describe
the safe behavior and intentionally fail on integration b1f4514.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests.integration import test_r14_equity_mode_bundles as equity_fixture
from tests.integration import test_r14_portfolio_thesis_mode_bundles as portfolio_fixture
from investment_stack.execution import Availability, ModeRequest, execute_mode
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services
from investment_stack.reporting.models import Availability as ReportAvailability
from investment_stack.reporting.thesis_refresh import (
    ComparisonOperator, ObservableCountercondition, ThesisClaim,
    ThesisEvidence, ThesisReviewRequest,
)
from investment_stack.routing import RequestMode


class IndependentBundleReview(unittest.TestCase):
    def test_rc06_delegated_report_ref_resolves_in_run_db(self):
        fixture = equity_fixture.R14EquityModeBundleIntegrationTests()
        self.addCleanup(fixture.doCleanups)
        specs = fixture.specs()[:1]
        run, base = fixture.make_services("review-enriched", specs)
        result = execute_mode(ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS, {
            "research_specs": specs, "target": "FANUC", "assumptions": ("synthetic",),
        }), portfolio_thesis_services(run_db=run, base_services=base))
        stored = {json.loads(row.get("metadata_json") or "{}").get("report_ref")
                  for row in run.fetch_phase6_context()["task_states"]}
        self.assertTrue(result.report_refs)
        self.assertTrue(set(result.report_refs).issubset(stored),
                        f"returned refs are absent from stored manifests: {result.report_refs}")

    def test_rc07_cross_run_thesis_cannot_use_wrong_clock_or_write_wrong_db(self):
        fixture = portfolio_fixture.PortfolioThesisModeBundleIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bound = fixture.new_run("source", RequestMode.THESIS_REVIEW,
            clock="2026-09-27T12:00:00+00:00", state_version=7,
            snapshot_ref="snapshot:7", portfolio_as_of="2026-09-27T11:00:00+00:00")
        requested = fixture.new_run("requested", RequestMode.THESIS_REVIEW,
            clock="2026-09-26T12:00:00+00:00", state_version=6,
            snapshot_ref="snapshot:6", portfolio_as_of="2026-09-26T11:00:00+00:00")
        thesis = ThesisReviewRequest("SYNTH", (ThesisClaim("claim", "synthetic thesis",
            ObservableCountercondition("growth", ComparisonOperator.LT, Decimal("5"), "PERCENT"),
            ("prior",),
            ObservableCountercondition("growth", ComparisonOperator.GTE, Decimal("5"), "PERCENT")),))
        evidence = ThesisEvidence("future-for-requested", "SYNTH", "growth", Decimal("8"), "PERCENT",
            "2026-09-27T11:00:00+00:00", "2026-09-27T11:01:00+00:00", "FRESH", "ELIGIBLE", True)
        result = execute_mode(ModeRequest("requested", RequestMode.THESIS_REVIEW, {
            "thesis_request": thesis, "thesis_evidence": (evidence,),
        }), portfolio_thesis_services(run_db=bound, run_dbs={"requested": requested}))
        self.assertFalse(bound.fetch_phase6_context()["calculations"],
            f"request {result.run_id} wrote calculations into {bound.run_id}; availability={result.availability}")
        self.assertNotEqual(result.availability, Availability.COMPLETE)

    def test_rc08_sdist_version_test_has_its_required_architecture_resource(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = next((ROOT / "dist").glob("*.tar.gz"))
            with tarfile.open(archive) as source:
                source.extractall(temporary, filter="data")
            unpacked = next(Path(temporary).iterdir())
            spec = importlib.util.spec_from_file_location("review_sdist_packaging",
                unpacked / "tests" / "test_packaging.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            case = module.TestPackaging("test_distribution_and_runtime_versions_are_not_conflated")
            outcome = unittest.TestResult()
            case.run(outcome)
            self.assertTrue(outcome.wasSuccessful(), str(outcome.errors + outcome.failures))

    def test_rc09_refresh_pin_does_not_require_outer_portfolio_payload(self):
        fixture = portfolio_fixture.PortfolioThesisModeBundleIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        results = []

        def capture(request, services):
            result = execute_mode(request, services)
            results.append((request, result))
            return result

        with patch.object(portfolio_fixture, "execute_mode", capture):
            fixture.test_all_four_fixed_modes_run_through_report_persistence()
        refresh = next(result for request, result in results if request.mode is RequestMode.REPORT_REFRESH)
        pin = next(state for state in refresh.step_states if state.step == "pin_personal_state")
        self.assertEqual(Availability.COMPLETE, pin.result.availability,
                         f"already verified refresh pin reports missing inputs: {pin.result.missing_inputs}")

    def test_rc10_partial_scenario_cannot_render_available_high_confidence_report(self):
        fixture = portfolio_fixture.PortfolioThesisModeBundleIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        results = []

        def capture(request, services):
            result = execute_mode(request, services)
            results.append((request, result))
            return result

        with patch.object(portfolio_fixture, "execute_mode", capture):
            fixture.test_all_four_fixed_modes_run_through_report_persistence()
        scenario = next(result for request, result in results if request.mode is RequestMode.PORTFOLIO_SCENARIO)
        report = next(state.result.output["report"] for state in scenario.step_states
                      if "report" in state.result.output)
        self.assertEqual(Availability.PARTIAL, scenario.availability)
        self.assertIn("approved_materiality_selector", scenario.missing_inputs)
        self.assertNotEqual(ReportAvailability.AVAILABLE, report.availability,
                            "missing required pipeline inputs were omitted from the user-facing report")


if __name__ == "__main__":
    unittest.main(defaultTest="IndependentBundleReview", verbosity=2)
