from __future__ import annotations

import tempfile
import unittest
import json
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.execution import Availability, ModeRequest, equity_analysis_services, execute_mode
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.pipelines import FixedPipelinePlanner
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.reporting.models import Availability as ReportAvailability
from investment_stack.routing import RequestMode
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend
from investment_stack.providers import EnvironmentCredentials, ProviderFallbackExecutor, build_default_provider_executor
from investment_stack.research import Phase4ResearchRuntime


CUTOFF = "2026-08-14T10:00:00+09:00"


class R14EquityModeBundleIntegrationTests(unittest.TestCase):
    def specs(self, *, second_currency: str = "JPY", second_type: BusinessType = BusinessType.STABLE_CASH_FLOW) -> tuple[EquityResearchSpec, EquityResearchSpec]:
        return (
            EquityResearchSpec("FANUC", "FANUC", "JAPAN", "JPY", BusinessType.STABLE_CASH_FLOW, ticker="6954"),
            EquityResearchSpec("KEYENCE", "KEYENCE", "JAPAN", second_currency, second_type, ticker="6861"),
        )

    def bundle(
        self, specs: tuple[EquityResearchSpec, ...], *, second_period: str = "2026-06-30",
        first_context: dict[str, str | None] | None = None, second_context: dict[str, str | None] | None = None,
        second_metric_contexts: dict[str, dict[str, str | None]] | None = None,
    ) -> dict[str, object]:
        responses: list[dict[str, object]] = []
        for index, spec in enumerate(specs):
            period = second_period if index == 1 else "2026-06-30"
            overrides = second_context if index == 1 else first_context
            context = {
                "start": "2025-07-01", "reporting_frequency": "ANNUAL", "reporting_period": "FY",
                "accounting_standard": "US-GAAP", "consolidation": "CONSOLIDATED",
                "adjustment_basis": "REPORTED", "restatement": "NONE",
                **(overrides or {}),
            }
            responses.append({
                "intent": "LATEST_CURRENT_DATA",
                "query": LiveDeepResearchRuntime._market_query(spec),
                "hits": [{
                    "source_name": "Synthetic Exchange", "source_url": f"https://synthetic.test/{spec.instrument_id}/quote",
                    "title": f"{spec.display_name} synthetic quote", "value": "6000", "currency": spec.currency,
                    "observed_at": "2026-08-14T09:59:00+09:00", "source_tier": 1,
                    "source_kind": "official_exchange", "official_confirmation_status": "OFFICIAL",
                }],
            })
            metrics = (
                ("revenue", "10000", spec.currency), ("operating_income", "2000", spec.currency),
                ("net_income", "1200", spec.currency), ("cash", "5000", spec.currency),
                ("total_debt", "1000", spec.currency), ("equity", "8000", spec.currency),
                ("shares_outstanding", "100", "shares"), ("eps", "12", f"{spec.currency}/share"),
                ("ebitda", "2500", spec.currency),
            )
            responses.append({
                "intent": "LATEST_CURRENT_DATA",
                "query": LiveDeepResearchRuntime._fundamentals_query(spec),
                "hits": [{
                    "source_name": f"{spec.display_name} IR", "source_url": f"https://synthetic.test/{spec.instrument_id}/{metric}",
                    "title": f"{spec.display_name} synthetic {metric}", "value": value, "unit": unit,
                    "currency": spec.currency, "published_at": "2026-08-01T15:00:00+09:00",
                    "source_tier": 2, "source_kind": "official_ir", "official_confirmation_status": "OFFICIAL",
                    "metadata": {
                        "metric": metric, "canonical_metric": metric, "period_end": period,
                        **(context or {}),
                        **((second_metric_contexts or {}).get(metric, {}) if index == 1 else {}),
                    },
                } for metric, value, unit in metrics],
            })
        return {"responses": responses}

    def make_services(
        self, run_id: str, specs: tuple[EquityResearchSpec, ...], *, second_period: str = "2026-06-30",
        first_context: dict[str, str | None] | None = None, second_context: dict[str, str | None] | None = None,
        second_metric_contexts: dict[str, dict[str, str | None]] | None = None,
        mode: RequestMode = RequestMode.SINGLE_ASSET_ANALYSIS,
        state_version: int = 0, snapshot_ref: str | None = None,
    ):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = RunDatabaseManager(Path(temporary.name) / "workspace", run_id)
        self.assertTrue(run.create().valid)
        run.initialize_run_context(
            request_mode=mode.value,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul", state_version=state_version,
            personal_db_instance_id="NONE:TEST",
            portfolio_snapshot_id=snapshot_ref,
        )
        research = Phase4ResearchRuntime(
            providers=build_default_provider_executor(credentials=EnvironmentCredentials({})),
            evidence=EvidenceResearchStore(run),
            web_research=WebResearchAdapter(WebResearchBundleBackend(self.bundle(
                specs, second_period=second_period, first_context=first_context, second_context=second_context,
                second_metric_contexts=second_metric_contexts,
            ))),
        )
        analysis = Phase5AssetAnalysisRuntime(
            run, materiality=MaterialityEngine(MaterialityConfig("R14-synthetic", Decimal("0.05"), Decimal("0.2"), Decimal("0.8"))),
        )
        deep = LiveDeepResearchRuntime(research=research, analysis=analysis,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul")
        phase6 = Phase6ReportReviewRuntime(run)
        return run, equity_analysis_services(deep_research=deep, phase6=phase6, run_db=run)

    def test_report_refresh_replay_requires_allowlisted_mode_flag_and_exact_pin(self) -> None:
        specs = self.specs()[:1]
        run, services = self.make_services(
            "r14-refresh-equity", specs, mode=RequestMode.REPORT_REFRESH,
            state_version=8, snapshot_ref="snapshot:synthetic-8",
        )
        context = type("RefreshContext", (), {
            "run_id": run.run_id, "analysis_as_of": CUTOFF,
            "analysis_timezone": "Asia/Seoul", "state_version": 8,
            "pinned_state_ref": "snapshot:synthetic-8",
        })()
        allowed = execute_mode(ModeRequest(
            run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
            {"research_specs": specs, "refresh_context": context}, refresh_replay=True,
        ), services)
        self.assertEqual(Availability.PARTIAL, allowed.availability, allowed.unsupported_reasons)
        self.assertTrue(allowed.report_refs)

        mismatched_context = type("RefreshContext", (), {
            "run_id": run.run_id, "analysis_as_of": CUTOFF,
            "analysis_timezone": "Asia/Seoul", "state_version": 9,
            "pinned_state_ref": "snapshot:synthetic-9",
        })()
        rejected = execute_mode(ModeRequest(
            run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
            {"research_specs": specs, "refresh_context": mismatched_context}, refresh_replay=True,
        ), services)
        self.assertEqual(Availability.UNSUPPORTED, rejected.availability)

        unflagged = execute_mode(ModeRequest(
            run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS,
            {"research_specs": specs, "refresh_context": context},
        ), services)
        self.assertEqual(Availability.UNSUPPORTED, unflagged.availability)

    def test_single_asset_pipeline_persists_real_evidence_calculations_and_report(self) -> None:
        specs = self.specs()[:1]
        run, services = self.make_services("r14-single", specs)
        result = execute_mode(ModeRequest("r14-single", RequestMode.SINGLE_ASSET_ANALYSIS,
            {"research_specs": specs, "title": "Synthetic FANUC analysis"}), services)
        self.assertEqual(Availability.PARTIAL, result.availability)
        self.assertEqual([step.value for step in FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps],
            [state.step for state in result.step_states])
        self.assertTrue(result.evidence_refs)
        self.assertGreaterEqual(len(result.calculation_refs), 2)
        self.assertTrue(result.report_refs)
        context = run.fetch_phase6_context()
        report_manifest = next(row for row in context["task_states"] if row["task_name"].startswith("report:"))
        self.assertEqual(result.report_refs[0], json.loads(report_manifest["metadata_json"])["report_ref"])
        report_step = next(state for state in result.step_states if state.step == "render_partial_aware_report")
        self.assertEqual(ReportAvailability.PARTIAL.value, report_step.result.output["report_availability"])
        report = report_step.result.output["report"]
        self.assertIsNotNone(report.briefing)
        self.assertIn("## 최종 판단 브리핑", report.markdown)
        self.assertIn("**지금 판단**", report.briefing)
        self.assertIn("**가격·행동 표**", report.briefing)
        self.assertIn("**핵심 근거**", report.briefing)
        self.assertIn("**판단 변경 조건**", report.briefing)
        self.assertIn("**상세 근거**", report.briefing)
        self.assertIn("대기", report.briefing)
        self.assertIn("정책 누락", report.briefing)
        self.assertNotIn("6,000 JPY/주", report.briefing)
        self.assertGreaterEqual(len(context["calculations"]), 2)
        self.assertTrue({"FANUC_fundamental", "FANUC_valuation", "data_quality"}.issubset(
            {section["section_name"] for section in context["report_sections"]}))
        self.assertTrue(any(row["task_name"].startswith("execute:SINGLE_ASSET_ANALYSIS:") for row in context["task_states"]))

    def test_comparison_runs_real_pipeline_and_builds_complete_compatibility_matrix_without_rank(self) -> None:
        specs = self.specs()
        run, services = self.make_services("r14-compare", specs, mode=RequestMode.ASSET_COMPARISON)
        result = execute_mode(ModeRequest("r14-compare", RequestMode.ASSET_COMPARISON,
            {"research_specs": specs, "title": "Synthetic comparison"}), services)
        self.assertEqual(Availability.PARTIAL, result.availability)
        self.assertTrue(result.evidence_refs)
        self.assertTrue(result.calculation_refs)
        self.assertTrue(result.report_refs)
        context = run.fetch_phase6_context()
        report_manifest = next(row for row in context["task_states"] if row["task_name"].startswith("report:"))
        self.assertEqual(result.report_refs[0], json.loads(report_manifest["metadata_json"])["report_ref"])
        comparison_section = next(row for row in context["report_sections"] if row["section_name"] == "asset_comparison")
        self.assertEqual(ReportAvailability.PARTIAL.value, comparison_section["section_status"])
        calculation = next(row for row in context["calculations"] if row["calculation_name"] == "asset_comparison")
        result_data = json.loads(calculation["result_json"])
        inputs_data = json.loads(calculation["inputs_json"])
        matrix = inputs_data["compatibility_matrix"]
        self.assertTrue(matrix["complete"], matrix)
        self.assertFalse(result_data["ranking_emitted"])
        self.assertTrue(result_data["comparisons"])
        # Bundle search pages do not carry verified venue quote receipts. The
        # comparison can retain fundamentals while omitting price-derived multiples.
        self.assertNotIn("valuation.pe", {item["metric"] for item in result_data["comparisons"]})

    def test_incompatible_periods_or_currency_return_partial_without_comparative_ranking(self) -> None:
        for suffix, specs, period in (
            ("period", self.specs(), "2026-03-31"),
            ("currency", self.specs(second_currency="USD"), "2026-06-30"),
            ("type", self.specs(second_type=BusinessType.FINANCIAL), "2026-06-30"),
        ):
            with self.subTest(kind=suffix):
                run, services = self.make_services(f"r14-{suffix}", specs, second_period=period, mode=RequestMode.ASSET_COMPARISON)
                result = execute_mode(ModeRequest(f"r14-{suffix}", RequestMode.ASSET_COMPARISON,
                    {"research_specs": specs}), services)
                self.assertEqual(Availability.PARTIAL, result.availability)
                comparison = next(row for row in run.fetch_phase6_context()["calculations"]
                    if row["calculation_name"] == "asset_comparison")
                result_data = json.loads(comparison["result_json"])
                inputs_data = json.loads(comparison["inputs_json"])
                self.assertFalse(result_data["ranking_emitted"])
                self.assertFalse(result_data["comparisons"])
                self.assertFalse(inputs_data["compatibility_matrix"]["complete"])

    def test_same_period_end_with_different_reporting_context_is_not_comparable(self) -> None:
        cases = (
            ("annual-quarterly", {"start": "2025-07-01", "reporting_frequency": "ANNUAL", "accounting_standard": "US-GAAP"},
             {"start": "2026-04-01", "reporting_frequency": "QUARTERLY", "accounting_standard": "US-GAAP"}),
            ("gaap-ifrs", {"start": "2026-04-01", "reporting_frequency": "QUARTERLY", "accounting_standard": "US-GAAP"},
             {"start": "2026-04-01", "reporting_frequency": "QUARTERLY", "accounting_standard": "IFRS"}),
            ("same-missing-context", {"start": None, "reporting_frequency": None, "reporting_period": None,
                "accounting_standard": None, "consolidation": None, "adjustment_basis": None, "restatement": None},
             {"start": None, "reporting_frequency": None, "reporting_period": None,
                "accounting_standard": None, "consolidation": None, "adjustment_basis": None, "restatement": None}),
        )
        for suffix, first_context, second_context in cases:
            with self.subTest(context=suffix):
                specs = self.specs()
                run, services = self.make_services(
                    f"r14-context-{suffix}", specs, first_context=first_context,
                    second_context=second_context, mode=RequestMode.ASSET_COMPARISON,
                )
                result = execute_mode(ModeRequest(f"r14-context-{suffix}", RequestMode.ASSET_COMPARISON,
                    {"research_specs": specs}), services)
                self.assertEqual(Availability.PARTIAL, result.availability)
                calculation = next(row for row in run.fetch_phase6_context()["calculations"]
                    if row["calculation_name"] == "asset_comparison")
                inputs = json.loads(calculation["inputs_json"])
                result_data = json.loads(calculation["result_json"])
                pair = inputs["compatibility_matrix"]["pairwise_compatibility"][0]
                self.assertTrue(pair["period_compatible"])
                self.assertFalse(pair["reporting_context_compatible"])
                self.assertFalse(pair["compatible"])
                self.assertFalse(inputs["compatibility_matrix"]["complete"])
                self.assertEqual([], result_data["comparisons"])

    def test_metric_comparison_rejects_context_missing_on_that_metric_only(self) -> None:
        specs = self.specs()
        run, services = self.make_services(
            "r14-metric-context", specs, mode=RequestMode.ASSET_COMPARISON,
            second_metric_contexts={"eps": {"start": None, "restatement": None}},
        )
        result = execute_mode(ModeRequest("r14-metric-context", RequestMode.ASSET_COMPARISON,
            {"research_specs": specs}), services)
        self.assertEqual(Availability.PARTIAL, result.availability)
        calculation = next(row for row in run.fetch_phase6_context()["calculations"]
            if row["calculation_name"] == "asset_comparison")
        inputs = json.loads(calculation["inputs_json"])
        result_data = json.loads(calculation["result_json"])
        checks = inputs["compatibility_matrix"]["metric_context_checks"]
        metrics = {item["metric"]: item for item in result_data["comparisons"]}
        self.assertFalse(inputs["compatibility_matrix"]["complete"])
        self.assertFalse(checks["eps"]["compatible"])
        self.assertNotIn("eps", metrics)
        self.assertIn("revenue", metrics)
        self.assertEqual("0", metrics["revenue"]["delta_vs_first_requested"]["KEYENCE"])

    def test_comparison_requires_two_resolved_assets(self) -> None:
        specs = self.specs()[:1]
        run, services = self.make_services("r14-one-compare", specs, mode=RequestMode.ASSET_COMPARISON)
        result = execute_mode(ModeRequest("r14-one-compare", RequestMode.ASSET_COMPARISON,
            {"research_specs": specs}), services)
        self.assertEqual(Availability.UNSUPPORTED, result.availability)
        self.assertFalse(run.fetch_phase6_context()["evidence"])

    def test_missing_provider_bundle_is_unsupported(self) -> None:
        specs = self.specs()[:1]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = RunDatabaseManager(Path(temporary.name) / "workspace", "r14-no-providers")
        self.assertTrue(run.create().valid)
        run.initialize_run_context(request_mode=RequestMode.SINGLE_ASSET_ANALYSIS.value,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul", state_version=0,
            personal_db_instance_id="NONE:TEST")
        from investment_stack.research import Phase4ResearchRuntime
        research = Phase4ResearchRuntime(providers=ProviderFallbackExecutor(()), evidence=EvidenceResearchStore(run))
        analysis = Phase5AssetAnalysisRuntime(run, materiality=MaterialityEngine(
            MaterialityConfig("R14-empty", Decimal("0.05"), Decimal("0.2"), Decimal("0.8"))))
        deep = LiveDeepResearchRuntime(research=research, analysis=analysis,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul")
        services = equity_analysis_services(deep_research=deep, phase6=Phase6ReportReviewRuntime(run), run_db=run)
        result = execute_mode(ModeRequest("r14-no-providers", RequestMode.SINGLE_ASSET_ANALYSIS,
            {"research_specs": specs}), services)
        self.assertEqual(Availability.UNSUPPORTED, result.availability)


if __name__ == "__main__":
    unittest.main()
