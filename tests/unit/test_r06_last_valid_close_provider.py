from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from investment_stack.freshness import FreshnessEngine, FreshnessStatus, get_pinned_calendar
from investment_stack.providers.market_quotes import (
    MarketQuoteProviderAdapter,
    MarketQuoteProvider,
    calendar_aware_freshness_evaluator,
    parse_naver_basic_quote,
)
from investment_stack.providers.execution import ProviderFallbackExecutor
from investment_stack.providers.models import ProviderRequest
from investment_stack.providers.registry import ProviderCapability


ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


class LastValidCloseProviderE2ETests(unittest.TestCase):
    def test_yahoo_provider_selection_preserves_nasdaq_close_lineage(self) -> None:
        calendar = get_pinned_calendar("NASDAQ")
        self.assertIsNotNone(calendar)
        cutoff = datetime(2026, 9, 27, 12, 0, tzinfo=ET)
        payload = {"chart": {"result": [{"meta": {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 341.07,
            "regularMarketTime": 1790366401,
        }}], "error": None}}
        provider = MarketQuoteProvider(
            source_bundles={"NASDAQ:AAPL": {"source_id": "yahoo_finance", "payload": payload}},
            clock=lambda: cutoff,
        )
        result = provider.fetch_current(
            "NASDAQ:AAPL", analysis_as_of=cutoff,
            eligibility_evaluator=calendar_aware_freshness_evaluator(calendar),
        )
        self.assertEqual(result.status.value, "AVAILABLE")
        self.assertEqual(result.metadata["selected_source"], "yahoo_finance")
        quote = result.metadata["contract_quote"]
        self.assertEqual(quote.claimed_market_time.isoformat(), "2026-09-25T16:00:01-04:00")
        assessment = FreshnessEngine().assess(
            result.observations[0], analysis_as_of=cutoff.isoformat(), calendar=calendar,
        )
        self.assertEqual(assessment.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertEqual(assessment.market_session_date, "2026-09-25")
        self.assertIn("휴장 중 마지막 유효 거래일 종가", assessment.reason)

        # Existing A-owned purpose executor still only accepts FRESH; expose this
        # integration boundary rather than claiming end-to-end report approval.
        request = ProviderRequest(ProviderCapability.CURRENT_PRICE, cutoff.isoformat(), "America/New_York", "NASDAQ:AAPL")
        self.assertFalse(ProviderFallbackExecutor(())._is_eligible_for_purpose(request, result))

    def test_provider_adapter_contract_connects_selected_result_to_executor(self) -> None:
        calendar = get_pinned_calendar("NASDAQ")
        cutoff = datetime(2026, 9, 27, 12, 0, tzinfo=ET)
        payload = {"chart": {"result": [{"meta": {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 341.07,
            "regularMarketTime": 1790366401,
        }}], "error": None}}
        adapter = MarketQuoteProviderAdapter(MarketQuoteProvider(
            source_bundles={"NASDAQ:AAPL": {"source_id": "yahoo_finance", "payload": payload}},
            clock=lambda: cutoff,
        ), {"NASDAQ": calendar})
        self.assertTrue(callable(adapter.fetch))
        request = ProviderRequest(ProviderCapability.CURRENT_PRICE, cutoff.isoformat(), "America/New_York", "NASDAQ:AAPL")
        result = adapter.fetch(request)
        self.assertEqual(result.status.value, "AVAILABLE")
        assessment = FreshnessEngine().assess(result.observations[0], analysis_as_of=cutoff.isoformat(), calendar=calendar)
        self.assertEqual(assessment.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertFalse(ProviderFallbackExecutor((adapter,))._is_eligible_for_purpose(request, result))

    def test_naver_close_publication_time_gates_provider_result(self) -> None:
        cutoff = datetime(2026, 9, 27, 12, 0, tzinfo=KST)
        payload = {
            "itemCode": "005930", "closePrice": "286,500",
            "localTradedAt": "2026-09-23T20:20:21+09:00",
            "marketSessionType": "afterMarket", "closePriceSendTime": "1630",
            "stockExchangeType": {"code": "KS", "delayTime": 0, "endTime": "1530"},
        }
        parsed = parse_naver_basic_quote(payload, instrument_id="KRX:005930", retrieved_at=cutoff)
        self.assertTrue(parsed.is_usable)
        quote = parsed.quote
        self.assertEqual(quote.claimed_market_time.isoformat(), "2026-09-23T15:30:00+09:00")
        self.assertEqual(quote.public_availability.public_available_at.isoformat(), "2026-09-23T16:30:00+09:00")
        self.assertEqual(parsed.observation.metadata["market_time_provenance"], "DERIVED_FROM_SESSION_END_TIME")
        self.assertEqual(parsed.observation.metadata["public_available_time_source"], "closePriceSendTime")

        calendar = get_pinned_calendar("KRX")
        evaluator = calendar_aware_freshness_evaluator(calendar)
        allowed, reason = evaluator(quote, datetime(2026, 9, 23, 16, 0, tzinfo=KST))
        self.assertFalse(allowed)
        self.assertIn("not yet published", reason)

        provider = MarketQuoteProvider(
            source_bundles={"KRX:005930": {"source_id": "naver_pay", "payload": payload}},
            clock=lambda: cutoff,
        )
        result = provider.fetch_current("KRX:005930", analysis_as_of=cutoff,
                                        eligibility_evaluator=evaluator)
        self.assertEqual(result.status.value, "AVAILABLE")
        selected = result.metadata["contract_quote"]
        self.assertEqual(selected.claimed_market_time.isoformat(), "2026-09-23T15:30:00+09:00")
        assessed = FreshnessEngine().assess(result.observations[0], analysis_as_of=cutoff.isoformat(), calendar=calendar)
        self.assertEqual(assessed.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertEqual(assessed.public_available_time, "2026-09-23T07:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
