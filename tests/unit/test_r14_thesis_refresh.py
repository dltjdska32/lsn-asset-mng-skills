from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from investment_stack.reporting.thesis_refresh import (
    ComparisonOperator,
    DeltaStatus,
    FixedModeReplay,
    ObservableCountercondition,
    PinnedRefreshContext,
    RefreshStatus,
    ReportRefreshRequest,
    ReportRefreshServices,
    ReportSnapshot,
    ThesisClaim,
    ThesisEvidence,
    ThesisReviewRequest,
    ThesisVerdict,
    refresh_report,
    review_thesis,
)
from investment_stack.reporting.models import Availability
from investment_stack.routing import RequestMode
from investment_stack.evidence import RunDatabaseManager


class ThesisRefreshTests(unittest.TestCase):
    cutoff = "2026-09-27T12:00:00+00:00"
    request = ThesisReviewRequest("SYNTH", (ThesisClaim(
        "growth", "매출 성장률이 유지된다",
        ObservableCountercondition("revenue_growth", ComparisonOperator.LT, 5, "PERCENT"),
        ("ev-prior",),
        ObservableCountercondition("revenue_growth", ComparisonOperator.GTE, 5, "PERCENT"),
    ),))

    def item(self, evidence_id, value, observed_at, *, freshness="FRESH", eligible="ELIGIBLE", selected=True, published="2026-09-27T11:00:00+00:00"):
        return ThesisEvidence(
            evidence_id, "SYNTH", "revenue_growth", value, "PERCENT", observed_at,
            published, freshness, eligible, selected,
        )

    def test_missing_thesis_waits_without_inventing_claim(self):
        result = review_thesis(None, (), analysis_as_of=self.cutoff)
        self.assertEqual(result.status, RefreshStatus.WAIT)
        self.assertEqual(result.assessments, ())
        self.assertEqual(result.section.status.value, "UNAVAILABLE")
        self.assertTrue(result.missing_inputs)

    def test_only_latest_eligible_current_evidence_drives_matrix(self):
        evidence = (
            self.item("ev-old", 2, "2026-09-25T11:00:00+00:00"),
            self.item("ev-stale-new", 0, "2026-09-27T11:30:00+00:00", freshness="STALE"),
            self.item("ev-unapproved", 0, "2026-09-27T11:40:00+00:00", eligible="INELIGIBLE"),
            self.item("ev-future", 0, "2026-09-27T12:30:00+00:00", published="2026-09-27T12:31:00+00:00"),
            self.item("ev-latest", 7, "2026-09-27T11:50:00+00:00"),
        )
        result = review_thesis(self.request, evidence, analysis_as_of=self.cutoff)
        self.assertEqual(result.status, RefreshStatus.COMPLETED)
        self.assertEqual(result.assessments[0].verdict, ThesisVerdict.SUPPORTED)
        self.assertEqual(result.assessments[0].evidence_ids, ("ev-latest",))
        self.assertEqual(result.section.evidence_ids, ("ev-latest",))

    def test_countercondition_refutes_and_conflicting_latest_is_unknown(self):
        refuted = review_thesis(
            self.request, (self.item("ev-break", 4, "2026-09-27T11:45:00+00:00"),),
            analysis_as_of=self.cutoff,
        )
        self.assertEqual(refuted.assessments[0].verdict, ThesisVerdict.REFUTED)
        conflict = review_thesis(
            self.request,
            (self.item("ev-a", 4, "2026-09-27T11:45:00+00:00"), self.item("ev-b", 7, "2026-09-27T11:45:00+00:00")),
            analysis_as_of=self.cutoff,
        )
        self.assertEqual(conflict.status, RefreshStatus.WAIT)
        self.assertEqual(conflict.assessments[0].verdict, ThesisVerdict.UNCONFIRMED)
        self.assertEqual(conflict.assessments[0].evidence_ids, ("ev-a", "ev-b"))
        without_support_condition = ThesisReviewRequest("SYNTH", (ThesisClaim(
            "growth", "매출 성장률이 유지된다",
            ObservableCountercondition("revenue_growth", ComparisonOperator.LT, 5, "PERCENT"),
            ("ev-prior",),
        ),))
        not_falsified = review_thesis(
            without_support_condition,
            (self.item("ev-not-false", 7, "2026-09-27T11:45:00+00:00"),),
            analysis_as_of=self.cutoff,
        )
        self.assertEqual(not_falsified.assessments[0].verdict, ThesisVerdict.UNCONFIRMED)

    def test_each_user_claim_gets_its_own_matrix_row(self):
        request = ThesisReviewRequest("SYNTH", (
            self.request.claims[0],
            ThesisClaim(
                "margin", "영업마진이 개선된다",
                ObservableCountercondition("operating_margin", ComparisonOperator.LTE, 10, "PERCENT"),
                ("ev-old-margin",),
                ObservableCountercondition("operating_margin", ComparisonOperator.GT, 10, "PERCENT"),
            ),
        ))
        evidence = (
            self.item("ev-growth", 8, "2026-09-27T11:00:00+00:00"),
            ThesisEvidence("ev-margin", "SYNTH", "operating_margin", 12, "PERCENT",
                           "2026-09-27T11:30:00+00:00", "2026-09-27T11:31:00+00:00",
                           "FRESH", "ELIGIBLE", True),
        )
        result = review_thesis(request, evidence, analysis_as_of=self.cutoff)
        self.assertEqual(len(result.assessments), 2)
        self.assertEqual([row.verdict for row in result.assessments], [ThesisVerdict.SUPPORTED, ThesisVerdict.SUPPORTED])

    def test_non_timezone_clock_and_nonfinite_condition_are_rejected(self):
        with self.assertRaises(ValueError):
            review_thesis(self.request, (), analysis_as_of="2026-09-27T12:00:00")
        with self.assertRaises(ValueError):
            ObservableCountercondition("metric", "LT", float("nan"), "PERCENT")

    def _make_run(self, workspace: Path, run_id: str, mode: RequestMode, clock: str, state_version: int):
        manager = RunDatabaseManager(workspace, run_id)
        self.assertTrue(manager.create().valid)
        manager.initialize_run_context(
            request_mode=mode.value, analysis_as_of=clock, analysis_timezone="UTC",
            state_version=state_version, personal_db_instance_id="synthetic-only",
            portfolio_snapshot_id=f"snapshot-{state_version}", portfolio_data_as_of=clock,
        )
        return manager

    def test_refresh_uses_new_synthetic_run_pin_and_reports_deltas(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        workspace = Path(temp.name) / "workspace"
        mode = RequestMode.SINGLE_ASSET_ANALYSIS
        target = "SYNTH"
        assumptions = ("horizon=1y",)
        prior_clock = "2026-09-26T12:00:00+00:00"
        new_clock = "2026-09-27T12:00:00+00:00"
        prior = self._make_run(workspace, "prior-run", mode, prior_clock, 1)
        prior.upsert_report_section(
            section_id="section:summary", section_name="summary", section_status="AVAILABLE",
            content_reference="inline-sha256:old", metadata={"report_ref": "report:prior", "analysis_as_of": prior_clock},
        )
        prior.upsert_report_section(
            section_id="section:stable", section_name="stable", section_status="AVAILABLE",
            content_reference="inline-sha256:same", metadata={"report_ref": "report:prior", "analysis_as_of": prior_clock},
        )
        new_holder = {}

        def load_prior(run_id, report_ref):
            self.assertEqual((run_id, report_ref), ("prior-run", "report:prior"))
            sections = prior.fetch_phase6_context()["report_sections"]
            self.assertTrue(sections)
            self.assertTrue(all(json.loads(row["metadata_json"])["report_ref"] == report_ref for row in sections))
            return ReportSnapshot(run_id, report_ref, mode, target, assumptions, prior_clock,
                                  {"summary": "old", "stable": "same"})

        def start_pinned(_prior, _request, _mode):
            manager = self._make_run(workspace, "new-run", mode, new_clock, 2)
            new_holder["manager"] = manager
            return PinnedRefreshContext("new-run", new_clock, "UTC", 2, "snapshot-2")

        def verify_pin(context):
            snapshot = new_holder["manager"].fetch_phase6_context()
            return (
                snapshot["run_metadata"]["analysis_as_of"] == context.analysis_as_of
                and snapshot["run_metadata"]["analysis_timezone"] == context.analysis_timezone
                and snapshot["pinned_personal_state"]["state_version"] == context.state_version
                and snapshot["pinned_personal_state"]["portfolio_snapshot_id"] == context.pinned_state_ref
            )

        def rerun(replay: FixedModeReplay):
            self.assertFalse(replay.posting_enabled)
            self.assertFalse(replay.allow_refresh)
            manager = new_holder["manager"]
            manager.upsert_report_section(
                section_id="section:summary", section_name="summary", section_status="AVAILABLE",
                content_reference="inline-sha256:new", metadata={"report_ref": "report:new", "analysis_as_of": new_clock},
            )
            manager.upsert_report_section(
                section_id="section:stable", section_name="stable", section_status="AVAILABLE",
                content_reference="inline-sha256:same", metadata={"report_ref": "report:new", "analysis_as_of": new_clock},
            )
            return ReportSnapshot("new-run", "report:new", mode, target, assumptions, new_clock,
                                  {"summary": "new", "stable": "same", "new-section": None})

        services = ReportRefreshServices(
            load_prior_report=load_prior, start_pinned_run=start_pinned,
            verify_pinned_run=verify_pin, allowed_mode_runners={mode: rerun},
        )
        result = refresh_report(
            ReportRefreshRequest("prior-run", "report:prior", mode, target, assumptions), services,
        )
        self.assertEqual(result.status, RefreshStatus.WAIT)
        self.assertEqual([delta.status for delta in result.deltas], [DeltaStatus.UNKNOWN, DeltaStatus.UNCHANGED, DeltaStatus.CHANGED])
        self.assertEqual(result.section.name, "report_refresh_delta")
        self.assertEqual(result.section.status.value, "PARTIAL")
        self.assertIn("report_refresh_comparison_incomplete", result.missing_inputs)
        self.assertIn("CHANGED: summary", result.section.lines)
        self.assertFalse((Path(temp.name) / "personal.db").exists())

    def test_partial_fixed_mode_replay_keeps_status_and_missing_inputs(self):
        mode = RequestMode.PERSONAL_PORTFOLIO_ANALYSIS
        prior = ReportSnapshot(
            "prior", "report:prior", mode, "portfolio", ("scope=pinned",),
            "2026-09-26T12:00:00+00:00", {"summary": "same"},
        )
        replayed = ReportSnapshot(
            "new", "report:new", mode, "portfolio", ("scope=pinned",),
            "2026-09-27T12:00:00+00:00", {"summary": "same"},
            Availability.PARTIAL, ("approved_materiality_selector", "selected_asset_research_handler"),
        )
        services = ReportRefreshServices(
            load_prior_report=lambda *_: prior,
            start_pinned_run=lambda *_: PinnedRefreshContext(
                "new", "2026-09-27T12:00:00+00:00", "UTC", 2, "snapshot:new",
            ),
            verify_pinned_run=lambda _context: True,
            allowed_mode_runners={mode: lambda _replay: replayed},
        )
        result = refresh_report(
            ReportRefreshRequest("prior", "report:prior", mode, "portfolio", ("scope=pinned",)),
            services,
        )
        self.assertEqual(RefreshStatus.WAIT, result.status)
        self.assertEqual(Availability.PARTIAL, result.current.availability)
        self.assertEqual(("approved_materiality_selector", "selected_asset_research_handler"),
                         result.missing_inputs)
        self.assertEqual(Availability.PARTIAL, result.section.status)
        self.assertIn("replay_availability", result.section.metadata)
        self.assertEqual("PARTIAL", result.section.metadata["replay_availability"])

    def test_refresh_rejects_recursive_update_missing_runner_and_stale_clock(self):
        empty_services = ReportRefreshServices(lambda *_: None, lambda *_: None, lambda _: True, {})
        for forbidden in (RequestMode.REPORT_REFRESH, RequestMode.THESIS_REVIEW, RequestMode.ASSET_UPDATE):
            with self.subTest(mode=forbidden), self.assertRaises(ValueError):
                refresh_report(ReportRefreshRequest("p", "r", forbidden, "T", ("assumption",)), empty_services)
        with self.assertRaisesRegex(ValueError, "no fixed runner"):
            refresh_report(
                ReportRefreshRequest("p", "r", RequestMode.SINGLE_ASSET_ANALYSIS, "T", ("assumption",)),
                empty_services,
            )

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        workspace = Path(temp.name) / "workspace"
        mode = RequestMode.SINGLE_ASSET_ANALYSIS
        old = "2026-09-26T12:00:00+00:00"
        prior = ReportSnapshot("p", "r", mode, "T", ("a",), old, {})
        services = ReportRefreshServices(
            lambda *_: prior, lambda *_: PinnedRefreshContext("new", old, "UTC", 2, "snapshot"),
            lambda _: True, {mode: lambda _: None},
        )
        with self.assertRaisesRegex(ValueError, "later than"):
            refresh_report(ReportRefreshRequest("p", "r", mode, "T", ("a",)), services)


if __name__ == "__main__":
    unittest.main()
