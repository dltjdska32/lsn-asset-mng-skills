"""RC12: distinct user briefings must remain distinguishable by stored report ref."""
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
from investment_stack.contracts.slots import SelectedInputSet
from investment_stack.execution import ModeRequest, execute_mode
from investment_stack.pipelines import PipelineStep
from investment_stack.routing import RequestMode


class BriefingPersistenceProbe(unittest.TestCase):
    def test_rc12_changed_briefing_changes_retrievable_report_identity(self):
        case = helpers.FinalReviewProbes()
        case.setUp()
        self.addCleanup(case.doCleanups)
        run, services, ledger, _ = case.make("brief-persist", RequestMode.SINGLE_ASSET_ANALYSIS)
        before_state = ledger.get_current_state_version()
        request = ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
                              {"research_specs": case.specs[:1]})
        result = execute_mode(request, services)
        original = result.step_states[-1].result
        original_manifest = case.fixture.report_manifest(run, original.report_refs[-1])
        context = {state.step: state.result for state in result.step_states[:-1]}
        selected = SelectedInputSet.create(run.run_id, "EQUITY_BRIEFING", 1, (), instrument_id="FANUC")
        changed_request = ModeRequest(run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS, {
            "research_specs": case.specs[:1],
            "briefing_contexts": {"FANUC": {"selected_inputs": selected}},
            "pinned_state_version": 7, "pinned_snapshot_ref": "snapshot:7",
        })
        # Re-render the same real calculated results through its public handler.
        # No implementation function, prior report, or database row is patched.
        changed = services.handlers[PipelineStep.RENDER_PARTIAL_AWARE_REPORT](changed_request, context)
        changed_manifest = case.fixture.report_manifest(run, changed.report_refs[-1])
        old_report = original.output["report"]
        new_report = changed.output["report"]
        old_line = next(line.strip() for line in old_report.briefing.splitlines() if "개인비중" in line)
        new_line = next(line.strip() for line in new_report.briefing.splitlines() if "개인비중" in line)
        print(json.dumps({"probe": "RC12", "baseline_sha": "2b01ab3047cb1f22d1087099cda768c2aba2e316",
            "old_personal_state_line": old_line, "new_personal_state_line": new_line,
            "different_briefing": old_report.briefing != new_report.briefing,
            "same_report_ref": original.report_refs == changed.report_refs,
            "same_persisted_section_refs": original_manifest["section_refs"] == changed_manifest["section_refs"],
            "persisted_section_names": [row["section_name"] for row in run.fetch_phase6_context()["report_sections"]]},
            ensure_ascii=False), flush=True)
        self.assertEqual(before_state, ledger.get_current_state_version())
        self.assertNotEqual(old_report.briefing, new_report.briefing)
        self.assertNotEqual(original.report_refs, changed.report_refs,
                            "different user-facing briefing content collapsed to the same stored report identity")


if __name__ == "__main__":
    unittest.main(defaultTest="BriefingPersistenceProbe", verbosity=2)
