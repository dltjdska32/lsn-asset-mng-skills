"""Independent stored-report boundary checks for integration 2b01ab3.

Uses injected synthetic research and temporary personal/run databases only.
"""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("review_helpers", Path(__file__).with_name("review_code_01_final_probes.py"))
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
from investment_stack.execution import Availability, ModeRequest, execute_mode
from investment_stack.execution.portfolio_thesis_modes import SelectedAssetResearchResult
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput
from investment_stack.reporting.thesis_refresh import ReportRefreshServices, PinnedRefreshContext
from investment_stack.routing import RequestMode


class RefreshBindingChecks(unittest.TestCase):
    def test_stored_identity_and_conservative_completeness(self):
        case = helpers.FinalReviewProbes()
        case.setUp()
        self.addCleanup(case.doCleanups)
        options = {
            "materiality_selector": lambda portfolio, request: ("SYNTH-EQ",),
            "selected_asset_research": lambda ids, request: SelectedAssetResearchResult((
                ReportSectionInput("selected_asset_research", "Synthetic research", ("Explicit synthetic complete input",)),)),
        }
        prior, service, _, portfolio = case.make("prior-binding", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, **options)
        original = execute_mode(ModeRequest(prior.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {"portfolio_request": portfolio}), service)
        self.assertEqual(Availability.COMPLETE, original.availability, original.as_dict())
        prior_snapshot = case.snapshot(prior, original.report_refs[-1])
        mutations = {
            "valid_complete": lambda snapshot: snapshot,
            "missing_ref": lambda snapshot: replace(snapshot, report_ref="run-report:does-not-exist"),
            "wrong_run": lambda snapshot: replace(snapshot, run_id="other-run"),
            "wrong_mode": lambda snapshot: replace(snapshot, mode=RequestMode.SINGLE_ASSET_ANALYSIS),
            "wrong_target": lambda snapshot: replace(snapshot, target="different-target"),
            "wrong_assumptions": lambda snapshot: replace(snapshot, assumptions=("changed",)),
            "wrong_clock": lambda snapshot: replace(snapshot, analysis_as_of="2026-09-27T14:00:00+00:00"),
            "wrong_sections": lambda snapshot: replace(snapshot, section_fingerprints={"unverified": "bad-hash"}),
            "unavailable_external": lambda snapshot: replace(snapshot, availability=ReportAvailability.UNAVAILABLE),
            "missing_external": lambda snapshot: replace(snapshot, missing_inputs=("synthetic_external_missing",)),
        }
        for index, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(name=name):
                run_id = f"new-binding-{index}"
                clock = "2026-09-27T13:00:00+00:00"
                def runner(replay):
                    result = execute_mode(ModeRequest(current.run_id, replay.mode, {
                        "portfolio_request": replacement, "refresh_context": replay.context,
                    }, refresh_replay=True), services)
                    self.assertEqual(Availability.COMPLETE, result.availability, result.as_dict())
                    snapshot = case.snapshot(current, result.report_refs[-1])
                    manifest = case.fixture.report_manifest(current, result.report_refs[-1])
                    snapshot = replace(snapshot, availability=ReportAvailability(manifest["availability"]),
                                       missing_inputs=tuple(manifest["missing_inputs"]))
                    return mutate(snapshot)
                external = ReportRefreshServices(
                    lambda *_: prior_snapshot,
                    lambda *_: PinnedRefreshContext(run_id, clock, "UTC", 8, "snapshot:8"),
                    lambda context: context.run_id == run_id,
                    {RequestMode.PERSONAL_PORTFOLIO_ANALYSIS: runner},
                )
                current, services, ledger, replacement = case.make(run_id, RequestMode.REPORT_REFRESH,
                    clock=clock, version=8, report_refresh_services=external, **options)
                before = ledger.get_current_state_version()
                result = execute_mode(ModeRequest(run_id, RequestMode.REPORT_REFRESH, {
                    "previous_run_id": prior.run_id, "previous_report_id": prior_snapshot.report_ref,
                    "original_mode": prior_snapshot.mode, "target": prior_snapshot.target,
                    "assumptions": prior_snapshot.assumptions,
                }), services)
                self.assertIsNone(result.mutation_receipt)
                self.assertEqual(before, ledger.get_current_state_version())
                print(json.dumps({"check": name, "availability": result.availability.value,
                    "missing_inputs": result.missing_inputs, "unsupported_reasons": result.unsupported_reasons}), flush=True)
                if name == "valid_complete":
                    self.assertEqual(Availability.COMPLETE, result.availability)
                else:
                    self.assertNotEqual(Availability.COMPLETE, result.availability)
                if name == "missing_external":
                    self.assertIn("synthetic_external_missing", result.missing_inputs)


if __name__ == "__main__":
    unittest.main(defaultTest="RefreshBindingChecks", verbosity=2)
