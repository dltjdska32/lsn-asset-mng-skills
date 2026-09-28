from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.freshness import FreshnessStatus
from investment_stack.providers import ProviderFallbackExecutor, ProviderObservation, ProviderRequest, build_default_provider_executor
from investment_stack.providers.execution import assess_current_price_observation
from investment_stack.providers.market_quotes import MarketQuoteProvider, MarketQuoteProviderAdapter
from investment_stack.providers.registry import ProviderCapability
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.reporting.runtime import section_from_analysis_result
from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType
from investment_stack.deep_research import EquityResearchSpec, LiveDeepResearchRuntime
from investment_stack.execution.analysis_modes import _persisted_last_valid_close_note, _validated_analysis_section
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.web_research.adapter import WebResearchAdapter
from investment_stack.web_research.models import WebResearchHit, WebResearchResponse


class WeekendPriceEndToEndTests(unittest.TestCase):
    def test_missing_calendar_and_wrong_currency_fail_closed_even_when_recent(self) -> None:
        recent = "2026-09-25T20:00:00+00:00"
        unsupported = ProviderObservation(
            evidence_type="market", source_name="feed", source_url=None, source_tier=1,
            provider_id="feed", value="10", currency="USD", instrument_id="NYSE:XYZ",
            observed_at=recent, published_at=recent, claimed_market_time=recent,
            market_session_date="2026-09-25", metadata={"exchange": "NYSE", "quote_kind": "LAST_VALID_CLOSE"},
        )
        self.assertEqual(
            assess_current_price_observation(unsupported, analysis_as_of="2026-09-25T20:01:00+00:00").status,
            FreshnessStatus.UNAVAILABLE,
        )
        wrong_currency = ProviderObservation(
            evidence_type="market", source_name="feed", source_url=None, source_tier=1,
            provider_id="feed", value="10", currency="EUR", instrument_id="NASDAQ:XYZ",
            observed_at=recent, published_at=recent, claimed_market_time=recent,
            market_session_date="2026-09-25", metadata={"exchange": "NASDAQ", "quote_kind": "LAST_VALID_CLOSE"},
        )
        self.assertEqual(
            assess_current_price_observation(wrong_currency, analysis_as_of="2026-09-25T20:01:00+00:00").status,
            FreshnessStatus.UNAVAILABLE,
        )

    def test_web_claimed_market_metadata_cannot_authorize_current_price(self) -> None:
        hit = WebResearchHit(
            "Search", "https://example.test", "quote", value="341.07", currency="USD",
            observed_at="2026-09-25T20:00:01Z", quote_kind="LAST_VALID_CLOSE",
            metadata={"instrument_id": "NASDAQ:AAPL", "exchange": "NASDAQ",
                      "market_session_date": "2026-09-25", "quote_kind": "LAST_VALID_CLOSE"},
        )
        backend = lambda intent, query, as_of: WebResearchResponse(intent, (hit,))
        result = WebResearchAdapter(backend).fetch_current("AAPL", analysis_as_of="2026-09-27T12:00:00-04:00", instrument_id="NASDAQ:AAPL")
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertEqual(result.observations, ())

    def test_nasdaq_close_flows_through_phase4_calculation_and_report(self) -> None:
        default = build_default_provider_executor()
        self.assertEqual(default._adapters[0].name, "market_quotes")

        cutoff = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        payload = {"chart": {"result": [{"meta": {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 341.07,
            "regularMarketTime": 1790366401,
        }}], "error": None}}
        adapter = MarketQuoteProviderAdapter(
            MarketQuoteProvider(
                source_bundles={"NASDAQ:AAPL": {"source_id": "yahoo_finance", "payload": payload}},
                clock=lambda: cutoff,
            ),
            {"NASDAQ": default._adapters[0].calendars["NASDAQ"]},
        )
        with tempfile.TemporaryDirectory() as temp:
            run = RunDatabaseManager(Path(temp) / "workspace", "weekend-price")
            self.assertTrue(run.create().valid)
            run.initialize_run_context(
                request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=cutoff.isoformat(),
                analysis_timezone="America/New_York", state_version=0,
                personal_db_instance_id="NONE:TEST",
            )
            store = EvidenceResearchStore(run)
            runtime = Phase4ResearchRuntime(
                providers=ProviderFallbackExecutor((adapter,)), evidence=store,
                web_research=WebResearchAdapter(lambda intent, query, as_of: WebResearchResponse(intent, ())),
            )
            analysis = Phase5AssetAnalysisRuntime(
                run, materiality=MaterialityEngine(MaterialityConfig("test", Decimal("0.05"), Decimal("0.20"), Decimal("0.80"))),
            )
            captured_prices = []
            analyze_equity = analysis.analyze_equity
            def capture_equity(fundamental, valuation):
                captured_prices.append(valuation.current_price)
                return analyze_equity(fundamental, valuation)
            analysis.analyze_equity = capture_equity
            deep = LiveDeepResearchRuntime(
                research=runtime, analysis=analysis, analysis_as_of=cutoff.isoformat(), analysis_timezone="America/New_York",
            )
            outcome = deep.analyze_equity(EquityResearchSpec(
                instrument_id="NASDAQ:AAPL", display_name="Apple", ticker="AAPL", country="USA", currency="USD",
                business_type=BusinessType.STABLE_CASH_FLOW, market_query="AAPL current price", fundamentals_query="AAPL fundamentals",
            ))

            self.assertEqual(outcome.market.selected.observation.value, Decimal("341.07"))
            self.assertEqual(outcome.market.selected.freshness.status, FreshnessStatus.LAST_VALID_CLOSE)
            self.assertEqual(outcome.market.selected.freshness.calendar_id, "nasdaq-2026-09-official-snapshot-v1")
            self.assertEqual(outcome.market.selected.freshness.market_session_date, "2026-09-25")
            self.assertEqual(captured_prices, [Decimal("341.07")])
            phase6 = run.fetch_phase6_context()
            market = phase6["market_observations"][0]
            self.assertEqual(market["market_session_date"], "2026-09-25")
            self.assertEqual(Decimal(str(market["value_numeric"])), Decimal("341.07"))
            freshness = json.loads(phase6["freshness_assessments"][0]["details_json"])
            self.assertEqual(freshness["calendar_id"], "nasdaq-2026-09-official-snapshot-v1")
            self.assertEqual(freshness["public_available_time"], "2026-09-25T20:00:01+00:00")

            section = section_from_analysis_result(outcome.analysis.valuation, name="valuation")
            report_text = " ".join(section.lines)
            self.assertIn("마지막 유효 거래일 종가", report_text)
            self.assertIn("실시간 시세가 아닙니다", report_text)
            self.assertIn("공개시각 2026-09-25T20:00:01+00:00", report_text)
            self.assertIn("2026-09-25 마지막 유효 거래일 종가", report_text)
            valuation_result = outcome.analysis.valuation
            close_note = _persisted_last_valid_close_note(outcome, phase6, run_id=run.run_id)
            self.assertIsNotNone(close_note)
            self.assertEqual(valuation_result.findings[-1], close_note)
            canonical_result = replace(valuation_result, findings=valuation_result.findings[:-1])
            guarded_section = _validated_analysis_section(
                canonical_result, name="valuation", title="Valuation",
                stored_calculations=phase6["calculations"], run_id=run.run_id,
            )
            self.assertTrue(guarded_section.metadata["numeric_output_verified"])
            self.assertNotIn(close_note, guarded_section.lines)
            final_lines = (*guarded_section.lines, close_note)
            self.assertIn("마지막 유효 거래일 종가", " ".join(final_lines))
            self.assertIn("실시간 시세가 아닙니다", " ".join(final_lines))

    def test_krx_close_flows_through_phase4_and_publication_gate(self) -> None:
        default = build_default_provider_executor()
        calendar = default._adapters[0].calendars["KRX"]
        payload = {
            "itemCode": "005930", "closePrice": "286,500",
            "localTradedAt": "2026-09-23T20:20:21+09:00", "marketSessionType": "afterMarket",
            "stockExchangeType": {"code": "KS", "delayTime": 0, "endTime": "1530", "closePriceSendTime": "1630"},
        }
        provider = MarketQuoteProvider(
            source_bundles={"KRX:005930": {"source_id": "naver_pay", "payload": payload}},
            clock=lambda: datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )
        adapter = MarketQuoteProviderAdapter(provider, {"KRX": calendar})
        sunday = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        request = ProviderRequest(ProviderCapability.CURRENT_PRICE, sunday.isoformat(), "Asia/Seoul", "KRX:005930", "current_price", {"quote_currency": "KRW"})
        selected = ProviderFallbackExecutor((adapter,)).execute(request).selected
        self.assertIsNotNone(selected)
        with tempfile.TemporaryDirectory() as temp:
            run = RunDatabaseManager(Path(temp) / "workspace", "krx-weekend-price")
            self.assertTrue(run.create().valid)
            run.initialize_run_context(
                request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=sunday.isoformat(),
                analysis_timezone="Asia/Seoul", state_version=0, personal_db_instance_id="NONE:TEST",
            )
            research = Phase4ResearchRuntime(
                providers=ProviderFallbackExecutor((adapter,)), evidence=EvidenceResearchStore(run),
                web_research=WebResearchAdapter(lambda intent, query, as_of: WebResearchResponse(intent, ())),
            )
            analysis = Phase5AssetAnalysisRuntime(
                run, materiality=MaterialityEngine(MaterialityConfig("test", Decimal("0.05"), Decimal("0.20"), Decimal("0.80"))),
            )
            captured_prices = []
            analyze_equity = analysis.analyze_equity
            def capture_equity(fundamental, valuation):
                captured_prices.append(valuation.current_price)
                return analyze_equity(fundamental, valuation)
            analysis.analyze_equity = capture_equity
            deep = LiveDeepResearchRuntime(research=research, analysis=analysis, analysis_as_of=sunday.isoformat(), analysis_timezone="Asia/Seoul")
            outcome = deep.analyze_equity(EquityResearchSpec(
                instrument_id="KRX:005930", display_name="Samsung Electronics", ticker="005930", country="KOR", currency="KRW",
                business_type=BusinessType.STABLE_CASH_FLOW, market_query="005930 price", fundamentals_query="005930 fundamentals",
            ))
            assessment = outcome.market.selected.freshness
            self.assertEqual(assessment.status, FreshnessStatus.LAST_VALID_CLOSE)
            self.assertEqual(assessment.market_session_date, "2026-09-23")
            self.assertEqual(assessment.calendar_id, "krx-2026-chuseok-official-snapshot-v1")
            self.assertEqual(assessment.public_available_time, "2026-09-23T07:30:00+00:00")
            self.assertEqual(captured_prices, [Decimal("286500")])
            section = section_from_analysis_result(outcome.analysis.valuation, name="valuation")
            report_text = " ".join(section.lines)
            self.assertIn("2026-09-23 마지막 유효 거래일 종가", report_text)
            self.assertIn("공개시각 2026-09-23T07:30:00+00:00", report_text)
            self.assertIn("실시간 시세가 아닙니다", report_text)

        before_publication = ProviderRequest(
            ProviderCapability.CURRENT_PRICE, "2026-09-23T16:00:00+09:00", "Asia/Seoul", "KRX:005930", "current_price", {"quote_currency": "KRW"},
        )
        after_reopened = ProviderRequest(
            ProviderCapability.CURRENT_PRICE, "2026-09-28T10:00:00+09:00", "Asia/Seoul", "KRX:005930", "current_price", {"quote_currency": "KRW"},
        )
        self.assertIsNone(ProviderFallbackExecutor((adapter,)).execute(before_publication).selected)
        self.assertIsNone(ProviderFallbackExecutor((adapter,)).execute(after_reopened).selected)


if __name__ == "__main__":
    unittest.main()
