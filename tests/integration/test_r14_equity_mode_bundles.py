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

    def bundle(self, specs: tuple[EquityResearchSpec, ...], *, second_period: str = "2026-06-30") -> dict[str, object]:
        responses: list[dict[str, object]] = []
        for index, spec in enumerate(specs):
            period = second_period if index == 1 else "2026-06-30"
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
                    "metadata": {"metric": metric, "canonical_metric": metric, "period_end": period},
                } for metric, value, unit in metrics],
            })
        return {"responses": responses}

    def make_services(self, run_id: str, specs: tuple[EquityResearchSpec, ...], *, second_period: str = "2026-06-30", mode: RequestMode = RequestMode.SINGLE_ASSET_ANALYSIS):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = RunDatabaseManager(Path(temporary.name) / "workspace", run_id)
        self.assertTrue(run.create().valid)
        run.initialize_run_context(
            request_mode=mode.value,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul", state_version=0,
            personal_db_instance_id="NONE:TEST",
        )
        research = Phase4ResearchRuntime(
            providers=build_default_provider_executor(credentials=EnvironmentCredentials({})),
            evidence=EvidenceResearchStore(run),
            web_research=WebResearchAdapter(WebResearchBundleBackend(self.bundle(specs, second_period=second_period))),
        )
        analysis = Phase5AssetAnalysisRuntime(
            run, materiality=MaterialityEngine(MaterialityConfig("R14-synthetic", Decimal("0.05"), Decimal("0.2"), Decimal("0.8"))),
        )
        deep = LiveDeepResearchRuntime(research=research, analysis=analysis,
            analysis_as_of=CUTOFF, analysis_timezone="Asia/Seoul")
        phase6 = Phase6ReportReviewRuntime(run)
        return run, equity_analysis_services(deep_research=deep, phase6=phase6, run_db=run)

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
        self.assertIn("valuation.pe", {item["metric"] for item in result_data["comparisons"]})

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
