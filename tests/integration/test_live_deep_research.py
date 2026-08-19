from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType, PositionExposure
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.materiality import LightweightAsset, MaterialityConfig, MaterialityEngine
from investment_stack.providers import EnvironmentCredentials, build_default_provider_executor
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.web_research import WebResearchAdapter, WebResearchBundleBackend


CUTOFF = "2026-08-14T10:00:00+09:00"


class LiveDeepResearchIntegrationTests(unittest.TestCase):
    def make_runtime(self, bundle: dict[str, object]) -> tuple[RunDatabaseManager, LiveDeepResearchRuntime]:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        run = RunDatabaseManager(root / "workspace", "live-deep-research")
        self.assertTrue(run.create().valid)
        run.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of=CUTOFF,
            analysis_timezone="Asia/Seoul",
            state_version=0,
            personal_db_instance_id="NONE:TEST",
        )
        web = WebResearchAdapter(WebResearchBundleBackend(bundle))
        research = Phase4ResearchRuntime(
            providers=build_default_provider_executor(credentials=EnvironmentCredentials({})),
            evidence=EvidenceResearchStore(run),
            web_research=web,
        )
        analysis = Phase5AssetAnalysisRuntime(
            run,
            materiality=MaterialityEngine(MaterialityConfig("test", Decimal("0.05"), Decimal("0.20"), Decimal("0.80"))),
        )
        return run, LiveDeepResearchRuntime(
            research=research,
            analysis=analysis,
            analysis_as_of=CUTOFF,
            analysis_timezone="Asia/Seoul",
        )

    @staticmethod
    def spec() -> EquityResearchSpec:
        return EquityResearchSpec(
            instrument_id="FANUC",
            display_name="FANUC",
            ticker="6954",
            country="JAPAN",
            currency="JPY",
            business_type=BusinessType.STABLE_CASH_FLOW,
            news_query="FANUC latest relevant official news",
        )

    def bundle(self, *, future_price: bool = False) -> dict[str, object]:
        spec = self.spec()
        market_query = LiveDeepResearchRuntime._market_query(spec)
        fundamentals_query = LiveDeepResearchRuntime._fundamentals_query(spec)
        price_time = "2026-08-14T10:01:00+09:00" if future_price else "2026-08-14T09:59:00+09:00"
        financial_hits = []
        for metric, value, unit in (
            ("revenue", "10000", "JPY"),
            ("operating_income", "2000", "JPY"),
            ("net_income", "1200", "JPY"),
            ("cash", "5000", "JPY"),
            ("total_debt", "1000", "JPY"),
            ("equity", "8000", "JPY"),
            ("shares_outstanding", "100", "shares"),
            ("eps", "12", "JPY/share"),
            ("ebitda", "2500", "JPY"),
        ):
            financial_hits.append(
                {
                    "source_name": "FANUC IR",
                    "source_url": f"https://fanuc.test/ir/{metric}",
                    "title": f"FANUC official {metric}",
                    "value": value,
                    "unit": unit,
                    "currency": "JPY",
                    "published_at": "2026-08-01T15:00:00+09:00",
                    "source_tier": 2,
                    "source_kind": "official_ir",
                    "official_confirmation_status": "OFFICIAL",
                    "metadata": {"metric": metric, "canonical_metric": metric, "period_end": "2026-06-30"},
                }
            )
        return {
            "responses": [
                {
                    "intent": "LATEST_CURRENT_DATA",
                    "query": market_query,
                    "hits": [
                        {
                            "source_name": "JPX",
                            "source_url": "https://jpx.test/6954",
                            "title": "FANUC timestamped quote",
                            "value": "6000",
                            "currency": "JPY",
                            "observed_at": price_time,
                            "source_tier": 1,
                            "source_kind": "official_exchange",
                            "official_confirmation_status": "OFFICIAL",
                        }
                    ],
                },
                {
                    "intent": "LATEST_CURRENT_DATA",
                    "query": fundamentals_query,
                    "hits": financial_hits,
                },
                {
                    "intent": "LATEST_RELEVANT_NEWS",
                    "query": "FANUC latest relevant official news",
                    "hits": [
                        {
                            "source_name": "FANUC IR",
                            "source_url": "https://fanuc.test/ir/news",
                            "title": "Official guidance update",
                            "published_at": "2026-08-10T10:00:00+09:00",
                            "source_tier": 2,
                            "source_kind": "official_ir",
                            "official_confirmation_status": "OFFICIAL",
                            "event_cluster_id": "fanuc-guidance-1",
                        }
                    ],
                },
            ]
        }

    def test_selected_equity_runs_web_fallback_financials_and_valuation_with_lineage(self) -> None:
        run, runtime = self.make_runtime(self.bundle())
        result = runtime.analyze_equity(self.spec())

        self.assertEqual(Decimal("6000"), result.analysis.valuation.metrics[0].value * Decimal("12"))
        self.assertEqual(Decimal("10000"), result.normalized_metrics["revenue"])
        self.assertEqual(Decimal("12"), result.normalized_metrics["eps"])
        self.assertGreaterEqual(len(result.evidence_ids), 2)

        context = run.fetch_phase6_context()
        self.assertEqual(1, len(context["market_observations"]))
        self.assertGreaterEqual(len(context["financial_observations"]), 9)
        selected_financial = [
            row for row in context["evidence"]
            if row["evidence_type"] == "financial" and row["selection_state"] == "SELECTED"
        ]
        self.assertGreaterEqual(len(selected_financial), 9)
        self.assertEqual(2, len(context["calculations"]))
        calculation_inputs = [json.loads(row["inputs_json"]) for row in context["calculations"]]
        self.assertTrue(any(result.evidence_ids[0] in item.get("evidence_ids", []) for item in calculation_inputs))
        provider_statuses = {(row["provider_name"], row["provider_status"]) for row in context["provider_states"]}
        self.assertIn(("opendart", "MISSING_CREDENTIAL"), provider_statuses)
        self.assertIn(("web_research", "AVAILABLE"), provider_statuses)

    def test_scaled_financial_units_are_normalized_before_valuation_multiples(self) -> None:
        bundle = self.bundle()
        fundamentals_query = LiveDeepResearchRuntime._fundamentals_query(self.spec())
        response = next(
            item for item in bundle["responses"]
            if item["intent"] == "LATEST_CURRENT_DATA" and item["query"] == fundamentals_query
        )
        replacements = {
            "revenue": ("120000", "JPY million"),
            "operating_income": ("24000", "JPY million"),
            "net_income": ("12000", "JPY million"),
            "cash": ("50000", "JPY million"),
            "total_debt": ("10000", "JPY million"),
            "equity": ("80000", "JPY million"),
            "shares_outstanding": ("100", "million shares"),
            "eps": ("120", "JPY/share"),
            "ebitda": ("20000", "JPY million"),
        }
        for hit in response["hits"]:
            metric = hit["metadata"]["canonical_metric"]
            if metric in replacements:
                hit["value"], hit["unit"] = replacements[metric]

        run, runtime = self.make_runtime(bundle)
        result = runtime.analyze_equity(self.spec())
        metrics = {metric.name: metric.value for metric in result.analysis.valuation.metrics}

        self.assertEqual(Decimal("120000000000"), result.normalized_metrics["revenue"])
        self.assertEqual(Decimal("100000000"), result.normalized_metrics["shares_outstanding"])
        self.assertEqual(Decimal("5"), metrics["price_to_sales"])
        self.assertEqual(Decimal("28"), metrics["ev_to_ebitda"])
        self.assertEqual(Decimal("7.5"), metrics["pb"])
        self.assertEqual(Decimal("50"), metrics["pe"])

        task = [
            row for row in run.fetch_phase6_context()["task_states"]
            if row["task_name"] == "deep_research:FANUC"
        ][-1]
        self.assertEqual("COMPLETED", task["task_status"])
        self.assertEqual([], json.loads(task["metadata_json"])["normalization_warnings"])

    def test_web_financial_metric_without_explicit_unit_is_not_used_in_valuation(self) -> None:
        bundle = self.bundle()
        fundamentals_query = LiveDeepResearchRuntime._fundamentals_query(self.spec())
        response = next(
            item for item in bundle["responses"]
            if item["intent"] == "LATEST_CURRENT_DATA" and item["query"] == fundamentals_query
        )
        revenue = next(hit for hit in response["hits"] if hit["metadata"]["canonical_metric"] == "revenue")
        revenue.pop("unit")

        run, runtime = self.make_runtime(bundle)
        result = runtime.analyze_equity(self.spec())
        metrics = {metric.name: metric.value for metric in result.analysis.valuation.metrics}

        self.assertNotIn("revenue", result.normalized_metrics)
        self.assertIsNone(metrics["price_to_sales"])
        task = [
            row for row in run.fetch_phase6_context()["task_states"]
            if row["task_name"] == "deep_research:FANUC"
        ][-1]
        metadata = json.loads(task["metadata_json"])
        self.assertEqual("PARTIAL", task["task_status"])
        self.assertIn("revenue: web financial input missing explicit unit/scale", metadata["normalization_warnings"])

    def test_mismatched_financial_currency_is_excluded_from_valuation(self) -> None:
        bundle = self.bundle()
        fundamentals_query = LiveDeepResearchRuntime._fundamentals_query(self.spec())
        response = next(
            item for item in bundle["responses"]
            if item["intent"] == "LATEST_CURRENT_DATA" and item["query"] == fundamentals_query
        )
        ebitda = next(hit for hit in response["hits"] if hit["metadata"]["canonical_metric"] == "ebitda")
        ebitda["currency"] = "USD"
        ebitda["unit"] = "USD"

        run, runtime = self.make_runtime(bundle)
        result = runtime.analyze_equity(self.spec())
        metrics = {metric.name: metric.value for metric in result.analysis.valuation.metrics}

        self.assertNotIn("ebitda", result.normalized_metrics)
        self.assertIsNone(metrics["ev_to_ebitda"])
        task = [
            row for row in run.fetch_phase6_context()["task_states"]
            if row["task_name"] == "deep_research:FANUC"
        ][-1]
        metadata = json.loads(task["metadata_json"])
        self.assertIn("ebitda: currency mismatch USD != JPY", metadata["normalization_warnings"])

    def test_future_market_price_is_not_promoted_to_current_valuation_input(self) -> None:
        run, runtime = self.make_runtime(self.bundle(future_price=True))
        result = runtime.analyze_equity(self.spec())
        pe = next(metric for metric in result.analysis.valuation.metrics if metric.name == "pe")
        self.assertIsNone(pe.value)
        self.assertIsNone(result.market.selected.observation)
        context = run.fetch_phase6_context()
        # The Web Research adapter rejects after-cutoff price hits before they can
        # become calculation evidence. Provider state still records the fallback failure.
        future_market = [row for row in context["evidence"] if row["evidence_type"] == "market"]
        self.assertEqual([], future_market)
        web_states = [
            row for row in context["provider_states"]
            if row["provider_name"] == "web_research" and row.get("capability") == "current_price"
        ]
        self.assertTrue(web_states)
        self.assertEqual("UNAVAILABLE", web_states[-1]["provider_status"])


    def test_portfolio_materiality_callback_executes_live_research_after_gate(self) -> None:
        run, runtime = self.make_runtime(self.bundle())
        result = runtime.analysis.analyze_portfolio(
            lightweight_assets=(
                LightweightAsset(
                    "FANUC", Decimal("7"), Decimal("0.35"), None, None, Decimal("0.2"),
                    user_specified=True,
                ),
            ),
            exposures=(PositionExposure("FANUC", Decimal("407710"), asset_class="EQUITY", country="JAPAN", currency="JPY"),),
            risk_assets=(),
            deep_analyzers={"FANUC": runtime.equity_callback(self.spec())},
            allocation_denominator=Decimal("1160000"),
            denominator_resolved=True,
        )
        self.assertIn("FANUC", result.deep_results)
        context = run.fetch_phase6_context()
        task_names = [row["task_name"] for row in context["task_states"]]
        self.assertIn("deep_research:FANUC", task_names)
        self.assertGreaterEqual(len(context["financial_observations"]), 9)

    def test_bundle_requires_structured_source_identity(self) -> None:
        with self.assertRaises(ValueError):
            WebResearchBundleBackend({"responses": [{"intent": "LATEST_CURRENT_DATA", "query": "q", "hits": [{}]}]})


if __name__ == "__main__":
    unittest.main()
