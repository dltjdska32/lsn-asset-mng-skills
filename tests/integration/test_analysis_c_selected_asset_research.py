from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType
from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager, SelectedEvidence
from investment_stack.execution.models import Availability, ModeRequest
from investment_stack.execution.dispatcher import execute_mode
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services
from investment_stack.execution.selected_asset_research import LiveSelectedAssetResearch
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.freshness import FreshnessAssessment, FreshnessStatus
from investment_stack.providers import EnvironmentCredentials, ProviderObservation, build_default_provider_executor
from investment_stack.research import Phase4ResearchRuntime, ResearchOutcome
from investment_stack.routing import RequestMode
from investment_stack.reporting.portfolio_modes import PinnedPortfolioState, PortfolioAnalysisRequest, PortfolioPosition
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


class SelectedAssetResearchIntegrationTests(unittest.TestCase):
    clock = "2026-08-14T10:00:00+09:00"
    spec = EquityResearchSpec("FANUC", "FANUC", "JAPAN", "JPY", BusinessType.STABLE_CASH_FLOW,
                              ticker="6954", news_query=None)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.make_run("analysis-c", self.clock)
        market_query = LiveDeepResearchRuntime._market_query(self.spec)
        fundamentals_query = LiveDeepResearchRuntime._fundamentals_query(self.spec)
        financial_hits = []
        for metric, value, unit in (("revenue", "10000", "JPY"), ("operating_income", "2000", "JPY"),
                                    ("net_income", "1200", "JPY"), ("cash", "5000", "JPY"),
                                    ("total_debt", "1000", "JPY"), ("equity", "8000", "JPY"),
                                    ("shares_outstanding", "100", "shares"), ("eps", "12", "JPY/share"),
                                    ("ebitda", "2500", "JPY")):
            financial_hits.append({"source_name": "FANUC IR", "source_url": f"https://example.test/{metric}",
                                   "title": metric, "value": value, "unit": unit, "currency": "JPY",
                                   "published_at": "2026-08-01T15:00:00+09:00", "source_tier": 2,
                                   "source_kind": "official_ir", "official_confirmation_status": "OFFICIAL",
                                   "metadata": {"metric": metric, "canonical_metric": metric, "period_end": "2026-06-30"}})
        bundle = {"responses": [
            {"intent": "LATEST_CURRENT_DATA", "query": market_query, "hits": [{
                "source_name": "JPX", "source_url": "https://example.test/quote", "title": "quote",
                "value": "6000", "currency": "JPY", "observed_at": "2026-08-14T09:59:00+09:00",
                "source_tier": 1, "source_kind": "official_exchange", "official_confirmation_status": "OFFICIAL"}]},
            {"intent": "LATEST_CURRENT_DATA", "query": fundamentals_query, "hits": financial_hits},
        ]}
        research = Phase4ResearchRuntime(
            providers=build_default_provider_executor(credentials=EnvironmentCredentials({})),
            evidence=EvidenceResearchStore(self.run),
            web_research=WebResearchAdapter(WebResearchBundleBackend(bundle)),
        )
        analysis = Phase5AssetAnalysisRuntime(self.run, materiality=MaterialityEngine(
            MaterialityConfig("synthetic", Decimal("0.05"), Decimal("0.20"), Decimal("0.80"))))
        self.runtime = LiveDeepResearchRuntime(research=research, analysis=analysis,
                                               analysis_as_of=self.clock, analysis_timezone="Asia/Seoul")
        self.service = LiveSelectedAssetResearch(self.runtime, {"FANUC": self.spec})

    def make_run(self, run_id: str, clock: str) -> RunDatabaseManager:
        run = RunDatabaseManager(self.root, run_id)
        self.assertTrue(run.create().valid)
        run.initialize_run_context(request_mode=RequestMode.PERSONAL_PORTFOLIO_ANALYSIS.value,
                                   analysis_as_of=clock, analysis_timezone="Asia/Seoul",
                                   state_version=1, personal_db_instance_id="SYNTHETIC",
                                   portfolio_snapshot_id="snapshot:synthetic", portfolio_data_as_of=clock)
        return run

    def test_materiality_selected_asset_runs_live_phase4_to_phase5_and_binds_report_refs(self) -> None:
        result = self.service(("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertEqual((), result.unsupported_reasons)
        self.assertEqual(1, len(result.sections))
        section = result.sections[0]
        self.assertEqual("selected_asset:FANUC", section.name)
        self.assertTrue(section.evidence_ids)
        self.assertEqual(2, len(section.calculation_ids))
        self.assertFalse(any("현재가: COMPLETE" in line or "현재가: PARTIAL" in line for line in section.lines))
        self.assertFalse(any("명시 가정에 따른 조건부 평가값" in line for line in section.lines))
        context = self.run.fetch_phase6_context()
        self.assertTrue(set(section.evidence_ids).issubset({row["evidence_id"] for row in context["evidence"]}))
        self.assertTrue(set(section.calculation_ids).issubset({row["calculation_id"] for row in context["calculations"]}))
        self.assertTrue(any(row["task_name"] == "deep_research:FANUC" for row in context["task_states"]))

    def test_wrong_run_and_wrong_spec_instrument_fail_closed(self) -> None:
        wrong_run = self.service(("FANUC",), ModeRequest("other-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertTrue(wrong_run.unsupported_reasons)
        mismatch = LiveSelectedAssetResearch(self.runtime, {
            "FANUC": EquityResearchSpec("OTHER", "Other", "JAPAN", "JPY")})
        wrong_spec = mismatch(("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertTrue(wrong_spec.unsupported_reasons)
        self.assertEqual((), self.run.fetch_phase6_context()["evidence"])

    def test_missing_spec_is_partial_and_wrong_clock_is_unsupported(self) -> None:
        missing = self.service(("NO-SPEC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertEqual(("resolved_equity_research_spec:NO-SPEC",), missing.missing_inputs)
        wrong_clock_runtime = LiveDeepResearchRuntime(research=self.runtime.research, analysis=self.runtime.analysis,
                                                      analysis_as_of="2026-08-14T10:01:00+09:00",
                                                      analysis_timezone="Asia/Seoul")
        wrong_clock = LiveSelectedAssetResearch(wrong_clock_runtime, {"FANUC": self.spec})
        result = wrong_clock(("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertTrue(result.unsupported_reasons)
        self.assertEqual((), self.run.fetch_phase6_context()["evidence"])

    def test_missing_provider_and_web_material_is_partial(self) -> None:
        empty_research = Phase4ResearchRuntime(
            providers=build_default_provider_executor(credentials=EnvironmentCredentials({})),
            evidence=EvidenceResearchStore(self.run),
        )
        empty_runtime = LiveDeepResearchRuntime(research=empty_research, analysis=self.runtime.analysis,
                                                analysis_as_of=self.clock, analysis_timezone="Asia/Seoul")
        result = LiveSelectedAssetResearch(empty_runtime, {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertIn("current_price:FANUC", result.missing_inputs)
        self.assertIn("fundamentals:FANUC", result.missing_inputs)
        self.assertEqual("PARTIAL", result.sections[0].status.value)
        self.assertTrue(any("current_price:FANUC" in line for line in result.sections[0].lines))

    def test_non_portfolio_mode_is_rejected_before_research(self) -> None:
        result = self.service(("FANUC",), ModeRequest(self.run.run_id, RequestMode.SINGLE_ASSET_ANALYSIS))
        self.assertTrue(result.unsupported_reasons)
        context = self.run.fetch_phase6_context()
        self.assertEqual((), context["evidence"])
        self.assertFalse(any(row["task_name"] == "deep_research:FANUC" for row in context["task_states"]))

    def _dcf_runtime(self, *, persist_metric: bool, wrong_id: bool = False):
        original_runtime = self.runtime

        class DcfRuntime:
            research = original_runtime.research
            analysis = original_runtime.analysis
            analysis_as_of = original_runtime.analysis_as_of
            analysis_timezone = original_runtime.analysis_timezone

            def analyze_equity(self, spec):
                outcome = original_runtime.analyze_equity(spec)
                valuation = outcome.analysis.valuation
                metric = MetricResult("dcf_scenario_base", Decimal("1234.50"), "JPY/share",
                                      "explicit evidence-backed DCF", evidence_ids=outcome.evidence_ids)
                calculation_id = valuation.metadata["calculation_id"]
                if persist_metric:
                    calculation_id = "calc:synthetic-dcf-value"
                if wrong_id:
                    calculation_id = "calc:missing-valuation-result"
                with_dcf = AnalysisResult(
                    valuation.subject, valuation.analysis_type, AnalysisStatus.COMPLETE,
                    (metric,), valuation.findings, valuation.risks, valuation.unknowns,
                    {**valuation.metadata, "calculation_id": calculation_id},
                )
                if persist_metric:
                    original_runtime.analysis.run_db.add_calculation(
                        calculation_id="calc:synthetic-dcf-value", calculation_name="EQUITY_VALUATION",
                        formula="synthetic explicit assumptions", inputs={"subject": spec.instrument_id,
                                                                            "evidence_ids": list(outcome.evidence_ids)},
                        result=LiveSelectedAssetResearch._serialize_analysis_result(with_dcf),
                    )
                return replace(outcome, analysis=replace(outcome.analysis, valuation=with_dcf))

        return DcfRuntime()

    def test_persisted_evidence_backed_dcf_value_is_explicitly_not_a_buy_price(self) -> None:
        result = LiveSelectedAssetResearch(self._dcf_runtime(persist_metric=True), {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        lines = result.sections[0].lines
        self.assertTrue(any("명시 가정에 따른 조건부 평가값, 매수 가격 아님" in line
                            and "DCF 기준 시나리오 주당 평가 참고값=1234.50 JPY/share" in line for line in lines))
        self.assertFalse(any("dcf_scenario_base" in line for line in lines))
        self.assertFalse(any("현재가:" in line for line in lines))

    def test_dcf_value_missing_from_persisted_calculation_is_hidden_and_partial(self) -> None:
        result = LiveSelectedAssetResearch(self._dcf_runtime(persist_metric=False), {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        section = result.sections[0]
        self.assertFalse(any("dcf_scenario_base=1234.50" in line for line in section.lines))
        self.assertFalse(any("조건부 평가값" in line for line in section.lines))
        self.assertIn("phase5_result_binding:FANUC:valuation", section.metadata["missing_inputs"])
        self.assertEqual("PARTIAL", section.status.value)

    def test_dcf_value_with_unresolved_calculation_id_is_hidden(self) -> None:
        result = LiveSelectedAssetResearch(self._dcf_runtime(persist_metric=True, wrong_id=True),
                                           {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        self.assertFalse(any("dcf_scenario_base=1234.50" in line for line in result.sections[0].lines))
        self.assertIn("phase5_result_binding:FANUC:valuation", result.sections[0].metadata["missing_inputs"])

    def test_forged_findings_and_unknowns_are_hidden_without_result_json_match(self) -> None:
        original_runtime = self.runtime

        class ForgedRuntime:
            research = original_runtime.research
            analysis = original_runtime.analysis
            analysis_as_of = original_runtime.analysis_as_of
            analysis_timezone = original_runtime.analysis_timezone

            def analyze_equity(self, spec):
                outcome = original_runtime.analyze_equity(spec)
                valuation = outcome.analysis.valuation
                forged = replace(
                    valuation,
                    findings=(*valuation.findings, "적정가 999999 JPY/share"),
                    unknowns=(*valuation.unknowns, "dcf_value_per_share=999999"),
                )
                return replace(outcome, analysis=replace(outcome.analysis, valuation=forged))

        result = LiveSelectedAssetResearch(ForgedRuntime(), {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        section = result.sections[0]
        self.assertFalse(any("999999" in line for line in section.lines))
        self.assertIn("phase5_result_binding:FANUC:valuation", section.metadata["missing_inputs"])
        self.assertEqual("PARTIAL", section.status.value)

    def _last_close_runtime(self, session_date: str, *, naive_times: bool = False):
        original_runtime = self.runtime

        class LastCloseRuntime:
            research = original_runtime.research
            analysis = original_runtime.analysis
            analysis_as_of = original_runtime.analysis_as_of
            analysis_timezone = original_runtime.analysis_timezone

            def analyze_equity(self, spec):
                outcome = original_runtime.analyze_equity(spec)
                evidence_id = "evidence:synthetic-last-close"
                observation_id = "observation:synthetic-last-close"
                offset = "" if naive_times else "+09:00"
                claimed_time = f"{session_date}T15:00:00{offset}"
                calendar_id = "jpx-synthetic-calendar-v1"
                public_time = f"{session_date}T15:05:00{offset}"
                assessment = FreshnessAssessment(
                    FreshnessStatus.LAST_VALID_CLOSE, claimed_time, 86400,
                    "verified completed exchange session", session_date, "LAST_VALID_CLOSE",
                    calendar_id, public_time,
                )
                observation = ProviderObservation(
                    evidence_type="market", source_name="JPX", source_url="https://example.test/quote",
                    source_tier=1, provider_id="synthetic", value=Decimal("6000"), unit="JPY/share",
                    currency="JPY", instrument_id=spec.instrument_id, metric="current_price",
                    observed_at=claimed_time, claimed_market_time=claimed_time,
                    market_session_date=session_date,
                )
                original_runtime.analysis.run_db.add_phase4_evidence(
                    evidence_id=evidence_id, evidence_type="market", source_uri=observation.source_url,
                    retrieved_at=original_runtime.analysis_as_of,
                    instrument_id=spec.instrument_id, metric="current_price",
                    value=observation.value, unit=observation.unit, currency=observation.currency,
                    source_name="JPX", source_tier=1, observed_at=claimed_time,
                    freshness_status=FreshnessStatus.LAST_VALID_CLOSE.value, provider_id="synthetic",
                )
                original_runtime.analysis.run_db.add_market_observation(
                    observation_id=observation_id, evidence_id=evidence_id, instrument_id=spec.instrument_id,
                    observed_at=claimed_time, value="6000", unit="JPY/share", currency="JPY",
                    claimed_market_time=claimed_time, market_session_date=session_date,
                    provider_id="synthetic", freshness_status=FreshnessStatus.LAST_VALID_CLOSE.value,
                )
                original_runtime.analysis.run_db.mark_evidence_selected(
                    evidence_id=evidence_id, reason="synthetic verified last-close selection",
                )
                original_runtime.analysis.run_db.add_observation_selection(
                    selection_id="selection:synthetic-last-close", observation_id=observation_id,
                    selection_reason="synthetic verified last-close selection",
                )
                original_runtime.analysis.run_db.add_freshness_assessment(
                    freshness_id="freshness:synthetic-last-close", evidence_id=evidence_id,
                    status=FreshnessStatus.LAST_VALID_CLOSE.value,
                    details={"market_session_date": session_date, "effective_time": claimed_time,
                             "quote_kind": "LAST_VALID_CLOSE",
                             "calendar_id": calendar_id,
                             "public_available_time": public_time},
                )
                note = (f"가격 입력 기준: {session_date} 마지막 유효 거래일 종가 ({spec.currency}); "
                        f"종가 시각 {claimed_time}; 공개시각 {public_time}; 달력 {calendar_id}. 실시간 시세가 아닙니다.")
                selected = SelectedEvidence(observation, assessment, evidence_id, observation_id, False,
                                            "verified", (observation,))
                market = ResearchOutcome(selected, (), False)
                valuation = outcome.analysis.valuation
                analyzed = replace(outcome.analysis, valuation=replace(
                    valuation, findings=(*valuation.findings, note),
                ))
                return replace(outcome, market=market, analysis=analyzed,
                               evidence_ids=(*outcome.evidence_ids, evidence_id))

        return LastCloseRuntime()

    def test_verified_last_valid_close_note_survives_full_result_check(self) -> None:
        result = LiveSelectedAssetResearch(self._last_close_runtime("2026-08-13"), {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        section = result.sections[0]
        self.assertTrue(any("2026-08-13 마지막 유효 거래일 종가" in line for line in section.lines),
                        (section.lines, dict(section.metadata)))
        self.assertNotIn("phase5_result_binding:FANUC:valuation", section.metadata["missing_inputs"])

    def test_future_last_valid_close_is_rejected_against_pinned_run_clock(self) -> None:
        result = LiveSelectedAssetResearch(self._last_close_runtime("2026-08-15"), {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        section = result.sections[0]
        self.assertFalse(any("2026-08-15 마지막 유효 거래일 종가" in line for line in section.lines))
        self.assertTrue(any("저장된 계산 근거와 일치하지 않아 표시하지 않았습니다" in line
                            for line in section.lines))
        self.assertIn("phase5_result_binding:FANUC:valuation", section.metadata["missing_inputs"])
        self.assertEqual("PARTIAL", section.status.value)

    def test_last_valid_close_with_naive_timestamp_is_rejected(self) -> None:
        result = LiveSelectedAssetResearch(self._last_close_runtime("2026-08-13", naive_times=True),
                                           {"FANUC": self.spec})(
            ("FANUC",), ModeRequest(self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS))
        section = result.sections[0]
        self.assertFalse(any("마지막 유효 거래일 종가" in line for line in section.lines))
        self.assertIn("phase5_result_binding:FANUC:valuation", section.metadata["missing_inputs"])

    def test_portfolio_pipeline_reports_selected_asset_evaluation_section(self) -> None:
        portfolio = PortfolioAnalysisRequest(
            PinnedPortfolioState(1, "snapshot:synthetic", self.clock, self.clock), "JPY",
            (PortfolioPosition("FANUC", Decimal("600000"), "JPY", "EQUITY"),), (), (),
        )
        services = portfolio_thesis_services(
            run_db=self.run,
            materiality_selector=lambda _portfolio, _request: ("FANUC",),
            selected_asset_research=self.service,
        )
        result = execute_mode(ModeRequest(
            self.run.run_id, RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, {"portfolio_request": portfolio}), services)
        self.assertIn(result.availability, {Availability.COMPLETE, Availability.PARTIAL})
        report = result.step_states[-1].result.output["report"]
        section = next(item for item in report.sections if item.name == "selected_asset:FANUC")
        self.assertTrue(section.evidence_ids)
        self.assertEqual(2, len(section.calculation_ids))
        self.assertIn("FANUC", report.markdown)


if __name__ == "__main__":
    unittest.main()
