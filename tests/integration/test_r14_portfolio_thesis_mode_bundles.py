from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.models import Availability, ModeRequest, StepResult
from investment_stack.execution.dispatcher import RuntimeServices
from investment_stack.execution.portfolio_thesis_modes import (
    SelectedAssetResearchResult,
    _attach_refresh_identity,
    _format_user_numbers,
    portfolio_thesis_services,
)
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import (
    FxEvidence,
    HistoricalPriceSeries,
    MoneyBalance,
    PinnedPortfolioState,
    PortfolioAnalysisRequest,
    PortfolioPosition,
    PortfolioRiskPolicy,
    PortfolioScenario,
    RiskObservation,
    RiskPeriodPolicy,
    ScenarioAdjustment,
    ScenarioApproval,
    ScenarioTargetKind,
)
from investment_stack.reporting.thesis_refresh import (
    ComparisonOperator,
    ObservableCountercondition,
    ThesisClaim,
    ThesisEvidence,
    ThesisReviewRequest,
)
from investment_stack.pipelines import FixedPipelinePlanner
from investment_stack.routing import RequestMode


class PortfolioThesisModeBundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def new_run(self, run_id: str, mode: RequestMode, *, clock: str, state_version: int,
                snapshot_ref: str, portfolio_as_of: str) -> RunDatabaseManager:
        manager = RunDatabaseManager(self.root / "runs", run_id)
        self.assertTrue(manager.create().valid)
        manager.initialize_run_context(
            request_mode=mode.value, analysis_as_of=clock, analysis_timezone="UTC",
            state_version=state_version, personal_db_instance_id="synthetic-only",
            portfolio_snapshot_id=snapshot_ref, portfolio_data_as_of=portfolio_as_of,
        )
        return manager

    @staticmethod
    def seed_portfolio_evidence(manager: RunDatabaseManager) -> None:
        manager.add_evidence(evidence_id="fx:synthetic:jpy-usd", evidence_type="fx_fixture",
                             metadata={"source": "synthetic fixture", "selected": True})
        for day in ("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"):
            manager.add_evidence(evidence_id=f"price:synthetic:{day}", evidence_type="risk_price_fixture",
                                 metadata={"source": "synthetic fixture", "period": day})

    @staticmethod
    def portfolio(clock: str, state_version: int, snapshot_ref: str, portfolio_as_of: str) -> PortfolioAnalysisRequest:
        return PortfolioAnalysisRequest(
            PinnedPortfolioState(state_version, snapshot_ref, clock, portfolio_as_of),
            "USD",
            (PortfolioPosition("SYNTH-EQ", Decimal("100000"), "JPY", "EQUITY"),),
            (MoneyBalance("SYNTH-CASH", Decimal("100"), "USD"),),
            (),
            fx_evidence=(FxEvidence(
                "JPY", "USD", Decimal("0.01"), "fx:synthetic:jpy-usd",
                "2026-09-26T10:00:00+00:00", "2026-09-26T10:01:00+00:00",
                "ELIGIBLE", "FRESH", True,
            ),),
            price_series=(HistoricalPriceSeries("SYNTH-EQ", "DAILY", tuple(
                RiskObservation(day, Decimal(price), "USD", f"price:synthetic:{day}",
                                "2026-09-25T00:00:00+00:00", "ELIGIBLE", "FRESH", True)
                for day, price in zip(("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"),
                                      ("100", "105", "103", "110", "108"))
            )),),
            period_policy=RiskPeriodPolicy("period-policy:synthetic", "DAILY", "2026-09-20", "2026-09-24", 5),
            risk_policy=PortfolioRiskPolicy("risk-policy:synthetic", True, "approval:synthetic-risk",
                                            Decimal("0.5"), Decimal("0.4"), "validation:synthetic-risk"),
        )

    def report_manifest(self, manager: RunDatabaseManager, report_ref: str) -> dict[str, object]:
        for row in manager.fetch_phase6_context()["task_states"]:
            metadata = json.loads(row.get("metadata_json") or "{}")
            if metadata.get("report_ref") == report_ref:
                return metadata
        self.fail(f"run.db does not contain report manifest {report_ref}")

    def test_user_report_numbers_are_rounded_and_grouped(self):
        line = _format_user_numbers("ratio=0.123456789 weight=12345678901234567890123456789012")
        self.assertIn("0.1235", line)
        self.assertIn("12,345,678,901,234,567,890,123,456,789,012", line)

    def test_non_bundle_report_handler_output_is_not_localized_or_rewritten(self):
        manager = self.new_run(
            "unmodified-equity-run", RequestMode.SINGLE_ASSET_ANALYSIS,
            clock="2026-09-27T12:00:00+00:00", state_version=0,
            snapshot_ref="snapshot:none", portfolio_as_of="2026-09-27T12:00:00+00:00",
        )
        render_step = FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps[-1]
        handlers = {}
        for step in FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps:
            if step is render_step:
                handlers[step] = lambda _request, _context: StepResult(
                    Availability.PARTIAL, output={"rendered_text": "English base report"},
                    report_refs=("unwrapped-base-report",), missing_inputs=("base_partial",),
                )
            else:
                handlers[step] = lambda _request, _context: StepResult(
                    Availability.COMPLETE, output={"sentinel": "base handler"},
                )
        services = portfolio_thesis_services(
            run_db=manager, base_services=RuntimeServices(handlers=handlers, run_db=manager),
        )
        result = execute_mode(
            ModeRequest(manager.run_id, RequestMode.SINGLE_ASSET_ANALYSIS, {}), services,
        )
        self.assertEqual(Availability.PARTIAL, result.availability, result.as_dict())
        self.assertEqual("English base report", result.step_states[-1].result.output["rendered_text"])

    def test_all_four_fixed_modes_run_through_report_persistence(self):
        old_clock = "2026-09-27T12:00:00+00:00"
        old_portfolio_as_of = "2026-09-27T11:30:00+00:00"
        portfolio = self.portfolio(old_clock, 7, "snapshot:synthetic-7", old_portfolio_as_of)
        portfolio_manager = self.new_run(
            "portfolio-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            clock=old_clock, state_version=7, snapshot_ref="snapshot:synthetic-7",
            portfolio_as_of=old_portfolio_as_of,
        )
        self.seed_portfolio_evidence(portfolio_manager)
        services = portfolio_thesis_services(
            run_db=portfolio_manager,
            materiality_selector=lambda _portfolio, _request: ("SYNTH-EQ",),
            selected_asset_research=lambda ids, _request: SelectedAssetResearchResult(
                (ReportSectionInput("selected_asset_research", "Selected Asset Research",
                                    ("Synthetic Phase 4/5 result",),
                                    status=ReportAvailability.PARTIAL),),
                missing_inputs=tuple(f"{item}:credential_backed_market_data" for item in ids),
            ),
        )
        portfolio_result = execute_mode(
            ModeRequest("portfolio-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
                        {"portfolio_request": portfolio}), services,
        )
        self.assertEqual(Availability.PARTIAL, portfolio_result.availability)
        self.assertTrue(portfolio_result.report_refs)
        self.assertEqual("personal_portfolio", self.report_manifest(portfolio_manager, portfolio_result.report_refs[0])["target"])
        portfolio_markdown = portfolio_result.step_states[-1].result.output["report"].markdown
        self.assertNotIn("state_version=", portfolio_markdown)
        self.assertNotIn("snapshot:synthetic-7", portfolio_markdown)
        self.assertIn("보유 자산 현황", portfolio_markdown)
        self.assertIn("상세 계산 근거", portfolio_markdown)
        self.assertTrue(any(row["calculation_name"] == "portfolio_analysis"
                            for row in portfolio_manager.fetch_phase6_context()["calculations"]))
        analysis_calc = next(row for row in portfolio_manager.fetch_phase6_context()["calculations"]
                             if row["calculation_name"] == "portfolio_analysis")
        analysis_inputs = json.loads(analysis_calc["inputs_json"])
        self.assertEqual(["fx:synthetic:jpy-usd"], analysis_inputs["fx_evidence_refs"])
        self.assertEqual(5, len(analysis_inputs["risk_evidence_refs"]))
        self.assertEqual("JPY", analysis_inputs["fx_provenance"][0]["from_currency"])

        scenario_manager = self.new_run(
            "scenario-run", RequestMode.PORTFOLIO_SCENARIO,
            clock=old_clock, state_version=7, snapshot_ref="snapshot:synthetic-7",
            portfolio_as_of=old_portfolio_as_of,
        )
        self.seed_portfolio_evidence(scenario_manager)
        scenario = PortfolioScenario(
            "scenario:synthetic", "explicit hypothetical adjustment",
            ScenarioApproval("gate:synthetic", "policy:synthetic", "approval:synthetic",
                             "validation:synthetic", True),
            (ScenarioAdjustment(ScenarioTargetKind.POSITION, "SYNTH-EQ", Decimal("10000"),
                                "JPY", "assumption:synthetic-value-change"),),
        )
        scenario_services = portfolio_thesis_services(
            run_db=scenario_manager, scenario_gate_verifier=lambda gate: gate.enabled,
        )
        scenario_result = execute_mode(
            ModeRequest("scenario-run", RequestMode.PORTFOLIO_SCENARIO,
                        {"portfolio_request": portfolio, "scenario": scenario}), scenario_services,
        )
        self.assertEqual(Availability.PARTIAL, scenario_result.availability, scenario_result.as_dict())
        self.assertTrue(scenario_result.report_refs)
        scenario_report = self.report_manifest(scenario_manager, scenario_result.report_refs[0])
        self.assertEqual(("assumption:synthetic-value-change",), tuple(scenario_report["assumptions"]))
        self.assertNotIn("assumption:synthetic-value-change",
                         scenario_result.step_states[-1].result.output["report"].markdown)
        stored_scenario = next(row for row in scenario_manager.fetch_phase6_context()["calculations"]
                               if row["calculation_name"] == "portfolio_scenario")
        self.assertFalse(json.loads(stored_scenario["result_json"])["posting_enabled"])
        scenario_inputs = json.loads(stored_scenario["inputs_json"])
        self.assertEqual(["fx:synthetic:jpy-usd"], scenario_inputs["fx_evidence_refs"])
        self.assertEqual(5, len(scenario_inputs["risk_evidence_refs"]))

        thesis_manager = self.new_run(
            "thesis-run", RequestMode.THESIS_REVIEW,
            clock=old_clock, state_version=7, snapshot_ref="snapshot:synthetic-7",
            portfolio_as_of=old_portfolio_as_of,
        )
        thesis = ThesisReviewRequest("SYNTH-EQ", (ThesisClaim(
            "claim:growth", "매출 성장이 유지된다",
            ObservableCountercondition("revenue_growth", ComparisonOperator.LT,
                                       Decimal("5"), "PERCENT"),
            ("evidence:prior-growth",),
            ObservableCountercondition("revenue_growth", ComparisonOperator.GTE,
                                       Decimal("5"), "PERCENT"),
        ),))
        evidence = (ThesisEvidence(
            "evidence:current-growth", "SYNTH-EQ", "revenue_growth", Decimal("8"), "PERCENT",
            "2026-09-27T11:00:00+00:00", "2026-09-27T11:01:00+00:00",
            "FRESH", "ELIGIBLE", True,
        ),)
        thesis_services = portfolio_thesis_services(run_db=thesis_manager)
        thesis_result = execute_mode(
            ModeRequest("thesis-run", RequestMode.THESIS_REVIEW,
                        {"thesis_request": thesis, "thesis_evidence": evidence}), thesis_services,
        )
        self.assertEqual(Availability.COMPLETE, thesis_result.availability)
        self.assertTrue(thesis_result.report_refs)
        thesis_snapshot = thesis_manager.fetch_phase6_context()
        self.assertIn("evidence:current-growth", {row["evidence_id"] for row in thesis_snapshot["evidence"]})
        self.assertTrue(any(row["calculation_name"] == "thesis_review" for row in thesis_snapshot["calculations"]))
        thesis_markdown = thesis_result.step_states[-1].result.output["report"].markdown
        self.assertNotIn("claim:growth", thesis_markdown)
        self.assertIn("투자 논지 검토", thesis_markdown)

        requested_manager = self.new_run(
            "requested-thesis-run", RequestMode.THESIS_REVIEW,
            clock="2026-09-26T12:00:00+00:00", state_version=4,
            snapshot_ref="snapshot:synthetic-4", portfolio_as_of="2026-09-26T11:30:00+00:00",
        )
        before_source = thesis_manager.fetch_phase6_context()
        mismatched_services = portfolio_thesis_services(
            run_db=thesis_manager, run_dbs={requested_manager.run_id: requested_manager},
        )
        mismatched_result = execute_mode(
            ModeRequest(requested_manager.run_id, RequestMode.THESIS_REVIEW,
                        {"thesis_request": thesis, "thesis_evidence": evidence}),
            mismatched_services,
        )
        after_source = thesis_manager.fetch_phase6_context()
        self.assertEqual(Availability.UNSUPPORTED, mismatched_result.availability)
        self.assertTrue(any("does not match the bound run database" in item
                            for item in mismatched_result.unsupported_reasons))
        self.assertEqual(before_source["evidence"], after_source["evidence"])
        self.assertEqual(before_source["calculations"], after_source["calculations"])
        self.assertEqual(before_source["report_sections"], after_source["report_sections"])
        self.assertEqual((), requested_manager.fetch_phase6_context()["calculations"])
        self.assertEqual((), requested_manager.fetch_phase6_context()["report_sections"])

        wrong_mode_manager = self.new_run(
            "wrong-mode-thesis-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            clock=old_clock, state_version=7, snapshot_ref="snapshot:synthetic-7",
            portfolio_as_of=old_portfolio_as_of,
        )
        wrong_mode_result = execute_mode(
            ModeRequest(wrong_mode_manager.run_id, RequestMode.THESIS_REVIEW,
                        {"thesis_request": thesis, "thesis_evidence": evidence}),
            portfolio_thesis_services(run_db=wrong_mode_manager),
        )
        self.assertEqual(Availability.UNSUPPORTED, wrong_mode_result.availability)
        self.assertTrue(any("not initialized for THESIS_REVIEW" in item
                            for item in wrong_mode_result.unsupported_reasons))
        wrong_mode_state = wrong_mode_manager.fetch_phase6_context()
        self.assertEqual((), wrong_mode_state["evidence"])
        self.assertEqual((), wrong_mode_state["calculations"])
        self.assertEqual((), wrong_mode_state["report_sections"])

        identity_manager = self.new_run(
            "identity-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            clock=old_clock, state_version=7, snapshot_ref="snapshot:synthetic-7",
            portfolio_as_of=old_portfolio_as_of,
        )
        original_ref = "delegated-report:synthetic"
        identity_manager.record_task_state(
            task_name="delegated-report", task_status="PARTIAL",
            metadata={"report_ref": original_ref, "availability": "PARTIAL",
                      "section_refs": [{"section_name": "overview", "content_reference": "section:synthetic"}]},
        )
        wrapped = _attach_refresh_identity(
            identity_manager,
            ModeRequest("identity-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, {}),
            StepResult(Availability.PARTIAL, report_refs=(original_ref,),
                       missing_inputs=("synthetic_partial_reason",)),
        )
        self.assertEqual(1, len(wrapped.report_refs))
        enriched_ref = wrapped.report_refs[0]
        enriched_manifest = self.report_manifest(identity_manager, enriched_ref)
        self.assertEqual(enriched_ref, enriched_manifest["report_ref"])
        self.assertEqual(original_ref, enriched_manifest["source_report_ref"])

        scenario_report_markdown = scenario_result.step_states[-1].result.output["report"].markdown
        self.assertIn("분석 일부가 완료되지 않았습니다", scenario_report_markdown)
        self.assertNotIn("approved_materiality_selector", scenario_report_markdown)
        self.assertNotIn("No material stale", scenario_report_markdown)
        completeness = next(row for row in scenario_manager.fetch_phase6_context()["report_sections"]
                            if row["section_name"] == "analysis_completeness")
        completeness_payload = json.loads(completeness["metadata_json"])
        self.assertIn("approved_materiality_selector",
                      completeness_payload["metadata"]["missing_input_ids"])

        # REPORT_REFRESH creates a new run clock/pin and reruns the fixed personal
        # portfolio pipeline with synthetic, explicitly pinned replacement state.
        refreshed_clock = "2026-09-27T13:00:00+00:00"
        refreshed_data_as_of = "2026-09-27T12:30:00+00:00"
        refreshed_portfolio = self.portfolio(
            refreshed_clock, 8, "snapshot:synthetic-8", refreshed_data_as_of,
        )
        refresh_manager = self.new_run(
            "refresh-run", RequestMode.REPORT_REFRESH,
            clock=refreshed_clock, state_version=8, snapshot_ref="snapshot:synthetic-8",
            portfolio_as_of=refreshed_data_as_of,
        )
        self.seed_portfolio_evidence(refresh_manager)
        registries = {"portfolio-run": portfolio_manager}
        received_refresh_contexts = []

        def resolve_refresh_payload(replay):
            received_refresh_contexts.append(replay.context)
            return {"portfolio_request": refreshed_portfolio}

        refresh_services = portfolio_thesis_services(
            run_db=refresh_manager, run_dbs=registries,
            refresh_payload_resolver=resolve_refresh_payload,
        )
        assumptions = ("scope=pinned_portfolio_snapshot", "evaluation_currency=USD")
        with patch("investment_stack.execution.portfolio_thesis_modes.execute_mode",
                   wraps=execute_mode) as replay_execute:
            refresh_result = execute_mode(
                ModeRequest("refresh-run", RequestMode.REPORT_REFRESH, {
                    "previous_run_id": "portfolio-run",
                    "previous_report_id": portfolio_result.report_refs[0],
                    "original_mode": RequestMode.PERSONAL_PORTFOLIO_ANALYSIS.value,
                    "target": "personal_portfolio", "assumptions": assumptions,
                }), refresh_services,
            )
        self.assertEqual(Availability.PARTIAL, refresh_result.availability)
        self.assertIn("approved_materiality_selector", refresh_result.missing_inputs)
        self.assertNotIn("typed_portfolio_request", refresh_result.missing_inputs)
        self.assertEqual(1, len(received_refresh_contexts))
        refresh_context = received_refresh_contexts[0]
        self.assertEqual("refresh-run", refresh_context.run_id)
        self.assertEqual(refreshed_clock, refresh_context.analysis_as_of)
        self.assertEqual(8, refresh_context.state_version)
        self.assertEqual("snapshot:synthetic-8", refresh_context.pinned_state_ref)
        replay_request = replay_execute.call_args.args[0]
        self.assertEqual(refresh_context, replay_request.payload["refresh_context"])
        self.assertTrue(refresh_result.report_refs)
        refresh_manifest = self.report_manifest(refresh_manager, refresh_result.report_refs[-1])
        self.assertEqual("REPORT_REFRESH", refresh_manifest["mode"])
        self.assertEqual("PARTIAL", refresh_manifest["availability"])
        self.assertIn("approved_materiality_selector", refresh_manifest["missing_inputs"])
        refreshed_markdown = refresh_result.step_states[-1].result.output["report"].markdown
        self.assertIn("분석 일부가 완료되지 않았습니다", refreshed_markdown)
        self.assertNotIn("No material stale", refreshed_markdown)
        self.assertTrue(any(row["section_name"] == "report_refresh_delta"
                            for row in refresh_manager.fetch_phase6_context()["report_sections"]))
        self.assertFalse((self.root / "personal.db").exists())


if __name__ == "__main__":
    unittest.main()
