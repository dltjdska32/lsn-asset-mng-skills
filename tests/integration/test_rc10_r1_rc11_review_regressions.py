"""Independent a1a41b0 review: synthetic configured E2E and new regressions.

Run with PYTHONPATH=runtime from this worktree. No network or real personal DB.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore
from investment_stack.execution import Availability, ModeRequest, compose_seven_mode_services, equity_analysis_services, execute_mode
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services
from investment_stack.institutional.scoring import calculate_consensus_direction
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.personal.intent import ConfirmationState, TransactionIntent, TransactionType
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.providers import ProviderFallbackExecutor
from investment_stack.reporting.models import Availability as ReportAvailability
from investment_stack.reporting.portfolio_modes import PortfolioScenario, ScenarioApproval, ScenarioAdjustment, ScenarioTargetKind
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.reporting.thesis_refresh import (
    ComparisonOperator, ObservableCountercondition, PinnedRefreshContext,
    ReportRefreshServices, ReportSnapshot, ThesisClaim, ThesisEvidence, ThesisReviewRequest,
)
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.routing import RequestMode
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


class FinalReviewProbes(unittest.TestCase):
    def setUp(self):
        from tests.integration.test_r14_equity_mode_bundles import R14EquityModeBundleIntegrationTests
        from tests.integration.test_r14_portfolio_thesis_mode_bundles import PortfolioThesisModeBundleIntegrationTests

        self.equity_fixture = R14EquityModeBundleIntegrationTests()
        self.fixture = PortfolioThesisModeBundleIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.specs = self.equity_fixture.specs()

    def make(self, run_id, mode, *, clock="2026-09-27T12:00:00+00:00", version=7, **options):
        snapshot = f"snapshot:{version}"
        data_time = clock
        run = self.fixture.new_run(run_id, mode, clock=clock, state_version=version,
                                  snapshot_ref=snapshot, portfolio_as_of=data_time)
        self.fixture.seed_portfolio_evidence(run)
        research = Phase4ResearchRuntime(
            providers=ProviderFallbackExecutor(()), evidence=EvidenceResearchStore(run),
            web_research=WebResearchAdapter(WebResearchBundleBackend(self.equity_fixture.bundle(self.specs))),
        )
        analysis = Phase5AssetAnalysisRuntime(run, materiality=MaterialityEngine(
            MaterialityConfig("SYNTHETIC-REVIEW", Decimal(".05"), Decimal(".2"), Decimal(".8"))))
        deep = LiveDeepResearchRuntime(research=research, analysis=analysis,
                                      analysis_as_of=clock, analysis_timezone="UTC")
        equity = equity_analysis_services(deep_research=deep, phase6=Phase6ReportReviewRuntime(run), run_db=run)
        portfolio_bundle = portfolio_thesis_services(run_db=run, base_services=equity, **options)
        personal = PersonalDatabaseManager(self.fixture.root / f"{run_id}-synthetic-personal.db",
                                          backup_directory=self.fixture.root / f"{run_id}-backups")
        self.assertEqual("VALID", personal.initialize().status.value)
        ledger = PersonalLedgerService(personal)
        ledger.register_account("cash", name="Synthetic Cash", currency="USD", timezone_name="UTC")
        services = compose_seven_mode_services(run_db=run, ledger=ledger,
            equity_services=equity, portfolio_thesis_services=portfolio_bundle)
        portfolio = self.fixture.portfolio(clock, version, snapshot, data_time)
        return run, services, ledger, portfolio

    def snapshot(self, run, report_ref):
        item = self.fixture.report_manifest(run, report_ref)
        return ReportSnapshot(run.run_id, report_ref, item["mode"], item["target"],
            tuple(item["assumptions"]), item["analysis_as_of"],
            {row["section_name"]: row["content_reference"] for row in item["section_refs"]})

    def test_configured_composition_runs_all_seven_modes_with_real_handlers(self):
        seen = set()
        prior = prior_result = None
        for mode in RequestMode:
            if mode is RequestMode.REPORT_REFRESH:
                continue
            run, services, ledger, portfolio = self.make(mode.value.lower(), mode,
                scenario_gate_verifier=lambda gate: gate.enabled)
            payload = {}
            if mode in {RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.ASSET_COMPARISON}:
                payload = {"research_specs": self.specs[:1] if mode is RequestMode.SINGLE_ASSET_ANALYSIS else self.specs,
                           "target": "FANUC" if mode is RequestMode.SINGLE_ASSET_ANALYSIS else "FANUC,KEYENCE",
                           "assumptions": ("synthetic-explicit",)}
            elif mode in {RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, RequestMode.PORTFOLIO_SCENARIO}:
                payload = {"portfolio_request": portfolio}
                if mode is RequestMode.PORTFOLIO_SCENARIO:
                    payload["scenario"] = PortfolioScenario("scenario:synthetic", "Synthetic adjustment",
                        ScenarioApproval("gate:synthetic", "policy:synthetic", "approval:synthetic", "validation:synthetic", True),
                        (ScenarioAdjustment(ScenarioTargetKind.POSITION, "SYNTH-EQ", Decimal("10000"), "JPY", "assumption:synthetic"),))
            elif mode is RequestMode.THESIS_REVIEW:
                thesis = ThesisReviewRequest("SYNTH-EQ", (ThesisClaim("claim", "Synthetic growth",
                    ObservableCountercondition("growth", ComparisonOperator.LT, Decimal("5"), "PERCENT"), ("prior",),
                    ObservableCountercondition("growth", ComparisonOperator.GTE, Decimal("5"), "PERCENT")),))
                evidence = ThesisEvidence("current", "SYNTH-EQ", "growth", Decimal("8"), "PERCENT",
                    "2026-09-27T11:00:00+00:00", "2026-09-27T11:01:00+00:00", "FRESH", "ELIGIBLE", True)
                payload = {"thesis_request": thesis, "thesis_evidence": (evidence,)}
            else:
                payload = {"transaction_intent": TransactionIntent(TransactionType.DEPOSIT, account_id="cash",
                    cash_amount="1000", currency="USD", occurred_at=datetime(2026, 9, 27, 11), timezone="UTC",
                    confirmation_state=ConfirmationState.CONFIRMED, idempotency_key="synthetic-deposit")}
            before = ledger.get_current_state_version()
            result = execute_mode(ModeRequest(run.run_id, mode, payload), services)
            self.assertIn(result.availability, {Availability.COMPLETE, Availability.PARTIAL}, result.as_dict())
            if mode is RequestMode.ASSET_UPDATE:
                self.assertEqual("POSTED", result.mutation_receipt["status"])
                self.assertGreater(ledger.get_current_state_version(), before)
            else:
                self.assertEqual(before, ledger.get_current_state_version())
                self.assertIsNone(result.mutation_receipt)
                self.assertTrue(result.report_refs)
                self.fixture.report_manifest(run, result.report_refs[-1])
            if mode is RequestMode.SINGLE_ASSET_ANALYSIS:
                prior, prior_result = run, result
            seen.add(mode)

        prior_snapshot = self.snapshot(prior, prior_result.report_refs[-1])
        new_clock = "2026-09-27T13:00:00+00:00"
        replay_calls = []

        def runner(replay):
            replay_calls.append(replay)
            result = execute_mode(ModeRequest(current.run_id, replay.mode, {
                "research_specs": self.specs[:1], "target": replay.target,
                "assumptions": replay.assumptions, "refresh_context": replay.context,
            }, refresh_replay=True), services)
            self.assertIn(result.availability, {Availability.COMPLETE, Availability.PARTIAL}, result.as_dict())
            self.assertIsNone(result.mutation_receipt)
            return self.snapshot(current, result.report_refs[-1])

        external = ReportRefreshServices(
            lambda run_id, ref: prior_snapshot,
            lambda *_: PinnedRefreshContext("refresh-equity", new_clock, "UTC", 8, "snapshot:8"),
            lambda context: context.run_id == "refresh-equity",
            {RequestMode.SINGLE_ASSET_ANALYSIS: runner},
        )
        current, services, ledger, _ = self.make("refresh-equity", RequestMode.REPORT_REFRESH,
            clock=new_clock, version=8, report_refresh_services=external)
        before = ledger.get_current_state_version()
        refreshed = execute_mode(ModeRequest(current.run_id, RequestMode.REPORT_REFRESH, {
            "previous_run_id": prior.run_id, "previous_report_id": prior_snapshot.report_ref,
            "original_mode": prior_snapshot.mode, "target": prior_snapshot.target,
            "assumptions": prior_snapshot.assumptions,
        }), services)
        self.assertIn(refreshed.availability, {Availability.COMPLETE, Availability.PARTIAL}, refreshed.as_dict())
        self.assertTrue(refreshed.report_refs)
        self.assertEqual(1, len(replay_calls))
        self.assertEqual(before, ledger.get_current_state_version())
        self.assertIsNone(refreshed.mutation_receipt)
        seen.add(RequestMode.REPORT_REFRESH)
        self.assertEqual(set(RequestMode), seen)

    def test_rc10_r1_refresh_preserves_partial_replay_status(self):
        prior, services, _, portfolio = self.make("prior", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS)
        original = execute_mode(ModeRequest("prior", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
            {"portfolio_request": portfolio}), services)
        identity = self.fixture.report_manifest(prior, original.report_refs[-1])
        current, services, _, replacement = self.make("new", RequestMode.REPORT_REFRESH,
            clock="2026-09-27T13:00:00+00:00", version=8, run_dbs={"prior": prior},
            refresh_payload_resolver=lambda replay: {"portfolio_request": replacement})
        refreshed = execute_mode(ModeRequest("new", RequestMode.REPORT_REFRESH, {
            "previous_run_id": "prior", "previous_report_id": original.report_refs[-1],
            "original_mode": "PERSONAL_PORTFOLIO_ANALYSIS", "target": identity["target"],
            "assumptions": tuple(identity["assumptions"]),
        }), services)
        replay_manifests = [json.loads(row.get("metadata_json") or "{}")
                           for row in current.fetch_phase6_context()["task_states"]]
        self.assertTrue(any(row.get("mode") == "PERSONAL_PORTFOLIO_ANALYSIS"
                            and row.get("availability") == "PARTIAL" for row in replay_manifests))
        replay_step_missing = [json.loads(row.get("metadata_json") or "{}").get("missing_inputs")
                               for row in current.fetch_phase6_context()["task_states"]
                               if "PERSONAL_PORTFOLIO_ANALYSIS" in row.get("task_name", "")]
        print(json.dumps({"probe": "RC10-R1", "baseline_sha": "a1a41b03594e6fa2a9ad141d7029b6f05cb53855",
            "prior_mode_status": original.availability.value, "prior_missing_inputs": original.missing_inputs,
            "replay_manifest_statuses": [row.get("availability") for row in replay_manifests
                                         if row.get("mode") == "PERSONAL_PORTFOLIO_ANALYSIS"],
            "replay_step_missing_inputs": replay_step_missing,
            "refresh_mode_status": refreshed.availability.value, "refresh_missing_inputs": refreshed.missing_inputs,
            "refresh_report_status": refreshed.step_states[-1].result.output["report"].availability.value},
            ensure_ascii=False), flush=True)
        self.assertEqual(Availability.PARTIAL, refreshed.availability,
                         "PARTIAL replay became COMPLETE in REPORT_REFRESH")
        self.assertNotEqual(ReportAvailability.AVAILABLE,
                            refreshed.step_states[-1].result.output["report"].availability)

    def test_rc11_cross_manager_consensus_accepts_two_valid_increases(self):
        from tests.unit.test_r12_r13_period_continuity import InstitutionalPeriodContinuityTests

        fixture = InstitutionalPeriodContinuityTests()
        first = fixture.comparison("2024-03-31", "2024-06-30")
        second = replace(first, manager_cik="0000000002", prior_filing_id="b-prior", current_filing_id="b-current",
                         changes=tuple(replace(row, manager_cik="0000000002") for row in first.changes))
        self.assertEqual(1, calculate_consensus_direction(fixture.cusip, (first,)))
        print(json.dumps({"probe": "RC11", "baseline_sha": "a1a41b03594e6fa2a9ad141d7029b6f05cb53855",
            "single_manager_direction": calculate_consensus_direction(fixture.cusip, (first,)),
            "two_managers_both_increased_direction": calculate_consensus_direction(fixture.cusip, (first, second))}), flush=True)
        self.assertEqual(1, calculate_consensus_direction(fixture.cusip, (first, second)))


if __name__ == "__main__":
    unittest.main(defaultTest="FinalReviewProbes", verbosity=2)
