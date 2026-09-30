"""Independent dcd262a review; synthetic temporary DBs, no source patches/network."""
from __future__ import annotations

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
from investment_stack.reporting.models import Availability as ReportAvailability
from investment_stack.reporting.thesis_refresh import ReportRefreshServices, ReportSnapshot, PinnedRefreshContext
from investment_stack.routing import RequestMode


class LatestReviewProbes(unittest.TestCase):
    def setUp(self):
        self.case = helpers.FinalReviewProbes()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def check_external_refresh(self, explicit_complete):
        prior, services, _, portfolio = self.case.make("prior-external", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS)
        original = execute_mode(ModeRequest(prior.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {"portfolio_request": portfolio}), services)
        prior_snapshot = self.case.snapshot(prior, original.report_refs[-1])
        replay_results = []
        supplied_snapshots = []

        def runner(replay):
            result = execute_mode(ModeRequest(current.run_id, replay.mode, {
                "portfolio_request": replacement, "refresh_context": replay.context,
            }, refresh_replay=True), current_services)
            replay_results.append(result)
            # This is the pre-existing seven-field host API. The new status fields
            # are optional; no source/DB patch is used to reach the default.
            snapshot = self.case.snapshot(current, result.report_refs[-1])
            if explicit_complete:
                snapshot = ReportSnapshot(snapshot.run_id, snapshot.report_ref, snapshot.mode,
                    snapshot.target, snapshot.assumptions, snapshot.analysis_as_of,
                    snapshot.section_fingerprints, ReportAvailability.AVAILABLE, ())
            supplied_snapshots.append(snapshot)
            return snapshot

        external = ReportRefreshServices(
            lambda *_: prior_snapshot,
            lambda *_: PinnedRefreshContext("new-external", "2026-09-27T13:00:00+00:00", "UTC", 8, "snapshot:8"),
            lambda context: context.run_id == "new-external",
            {RequestMode.PERSONAL_PORTFOLIO_ANALYSIS: runner},
        )
        current, current_services, _, replacement = self.case.make("new-external", RequestMode.REPORT_REFRESH,
            clock="2026-09-27T13:00:00+00:00", version=8, report_refresh_services=external)
        refreshed = execute_mode(ModeRequest(current.run_id, RequestMode.REPORT_REFRESH, {
            "previous_run_id": prior.run_id, "previous_report_id": prior_snapshot.report_ref,
            "original_mode": prior_snapshot.mode, "target": prior_snapshot.target,
            "assumptions": prior_snapshot.assumptions,
        }), current_services)
        replay = replay_results[0]
        persisted = self.case.fixture.report_manifest(current, replay.report_refs[-1])
        print(json.dumps({"probe": "RC10-R2", "baseline_sha": "dcd262ac1fb0033cb70796e90b848e487191fcb2",
            "explicit_complete": explicit_complete,
            "replay_result": replay.availability.value, "replay_missing": replay.missing_inputs,
            "stored_replay_manifest": persisted["availability"],
            "stored_replay_missing": persisted.get("missing_inputs"),
            "external_snapshot_status": supplied_snapshots[0].availability.value,
            "refresh_result": refreshed.availability.value, "refresh_missing": refreshed.missing_inputs,
            "refresh_report": refreshed.step_states[-1].result.output["report"].availability.value},
            ensure_ascii=False), flush=True)
        self.assertEqual(Availability.PARTIAL, replay.availability)
        self.assertEqual("PARTIAL", persisted["availability"])
        self.assertEqual(Availability.PARTIAL, refreshed.availability,
                         "external snapshot silently upgrades persisted PARTIAL report")
        self.assertTrue(set(replay.missing_inputs).issubset(refreshed.missing_inputs))

    def test_rc10_r2_external_runner_old_snapshot_default_cannot_upgrade_partial(self):
        self.check_external_refresh(False)

    def test_rc10_r2_external_status_cannot_override_persisted_partial_manifest(self):
        self.check_external_refresh(True)

    def test_equity_wait_briefing_has_five_ordered_sections_and_no_posting(self):
        for mode in (RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.ASSET_COMPARISON):
            with self.subTest(mode=mode.value):
                run, services, ledger, _ = self.case.make(mode.value.lower(), mode)
                before = ledger.get_current_state_version()
                result = execute_mode(ModeRequest(run.run_id, mode, {
                    "research_specs": self.case.specs[:1] if mode is RequestMode.SINGLE_ASSET_ANALYSIS else self.case.specs,
                }), services)
                self.assertEqual(before, ledger.get_current_state_version())
                self.assertIsNone(result.mutation_receipt)
                report = result.step_states[-1].result.output["report"]
                text = report.briefing
                self.assertIsNotNone(text)
                headings = ("1. **지금 판단**", "2. **가격·행동 표**", "3. **핵심 근거**", "4. **판단 변경 조건**", "5. **상세 근거**")
                offsets = [text.index(heading) for heading in headings]
                self.assertEqual(offsets, sorted(offsets))
                self.assertIn("대기", text)
                self.assertIn("정책", text)
                self.assertIn("계산 불가", text)
                self.assertNotIn("BUY", text)
                self.assertNotIn("SELL", text)


if __name__ == "__main__":
    unittest.main(defaultTest="LatestReviewProbes", verbosity=2)
