"""Verify RC12 history preservation, reopening, and actual refresh comparison."""
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("review_helpers", Path(__file__).with_name("review_code_01_final_probes.py"))
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
from investment_stack.contracts.slots import SelectedInputSet
from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution import ModeRequest, execute_mode
from investment_stack.pipelines import PipelineStep
from investment_stack.routing import RequestMode


class BriefingRoundtripChecks(unittest.TestCase):
    def setUp(self):
        self.case = helpers.FinalReviewProbes()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_prior_and_current_briefing_survive_reopen_with_verified_content_hash(self):
        run, services, _, _ = self.case.make("history", RequestMode.SINGLE_ASSET_ANALYSIS)
        request = ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
                              {"research_specs": self.case.specs[:1]})
        initial = execute_mode(request, services)
        first = initial.step_states[-1].result
        context = {state.step: state.result for state in initial.step_states[:-1]}
        selected = SelectedInputSet.create(run.run_id, "EQUITY_BRIEFING", 1, (), instrument_id="FANUC")
        second_request = ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS, {
            "research_specs": self.case.specs[:1], "briefing_contexts": {"FANUC": {"selected_inputs": selected}},
            "pinned_state_version": 7, "pinned_snapshot_ref": "snapshot:7",
        })
        render = services.handlers[PipelineStep.RENDER_PARTIAL_AWARE_REPORT]
        second = render(second_request, context)
        repeated_first = render(request, context)
        self.assertNotEqual(first.report_refs, second.report_refs)
        self.assertEqual(first.report_refs, repeated_first.report_refs)

        reopened = RunDatabaseManager(run.workspace_root, run.run_id)
        self.assertTrue(reopened.open().valid)
        rows = reopened.fetch_phase6_context()["report_sections"]
        briefings = [row for row in rows if row["section_name"] == "final_briefing"]
        self.assertEqual(2, len(briefings), "identical re-render must not create another version")
        by_ref = {row["content_reference"]: row for row in briefings}
        for result in (first, second):
            manifest = self.case.fixture.report_manifest(reopened, result.report_refs[-1])
            refs = [row for row in manifest["section_refs"] if row["section_name"] == "final_briefing"]
            self.assertEqual(1, len(refs))
            saved = by_ref[refs[0]["content_reference"]]
            payload = json.loads(saved["metadata_json"])
            self.assertEqual(result.output["report"].briefing, payload["rendered_markdown"])
            self.assertEqual("WAIT", payload["typed_briefing"]["decision"])
            self.assertEqual([], payload["typed_briefing"]["numeric_bindings"])
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.assertEqual(f"inline-sha256:{digest}", saved["content_reference"])
        print("RC12 roundtrip: two immutable versions, identical-render ref reuse, exact rendered text and typed WAIT restored; hashes verified.", flush=True)

    def test_actual_equity_refresh_includes_final_briefing_delta(self):
        captured = []
        def observe(request, services):
            result = execute_mode(request, services)
            if request.mode is RequestMode.REPORT_REFRESH:
                captured.append(result)
            return result
        # Observe the test harness entry point; production handlers remain intact.
        with patch.object(helpers, "execute_mode", observe):
            self.case.test_configured_composition_runs_all_seven_modes_with_real_handlers()
        self.assertEqual(1, len(captured))
        refresh = next(state.result.output["refresh_result"] for state in captured[0].step_states
                       if "refresh_result" in state.result.output)
        delta = next(item for item in refresh.deltas if item.section == "final_briefing")
        self.assertEqual("CHANGED", delta.status.value)
        self.assertTrue(delta.previous_fingerprint)
        self.assertTrue(delta.current_fingerprint)
        self.assertNotEqual(delta.previous_fingerprint, delta.current_fingerprint)
        print("RC12 refresh: actual configured equity replay exposes final_briefing CHANGED with both stored fingerprints.", flush=True)


if __name__ == "__main__":
    unittest.main(defaultTest="BriefingRoundtripChecks", verbosity=2)
