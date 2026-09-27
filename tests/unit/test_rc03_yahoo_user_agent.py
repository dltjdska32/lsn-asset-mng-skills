from __future__ import annotations

import json
import unittest
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from investment_stack.providers import EnvironmentCredentials, ProviderRequest, build_default_provider_executor
from investment_stack.providers.registry import ProviderCapability


class YahooUserAgentTests(unittest.TestCase):
    def test_default_executor_sends_browser_user_agent_and_selects_weekend_close(self) -> None:
        cutoff = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        payload = {"chart": {"result": [{"meta": {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 248.50,
            "regularMarketTime": int(datetime(2026, 9, 25, 16, 0, 1, tzinfo=ZoneInfo("America/New_York")).timestamp()),
        }}], "error": None}}
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, headers, timeout))
            return json.dumps(payload).encode("utf-8")

        executor = build_default_provider_executor(credentials=EnvironmentCredentials({}), transport=transport)
        request = ProviderRequest(
            ProviderCapability.CURRENT_PRICE, cutoff.isoformat(), "America/New_York", "NASDAQ:AAPL",
            "current_price", {"quote_currency": "USD"},
        )
        result = executor.execute(request)

        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.observations[0].value, Decimal("248.50"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        self.assertEqual(result.selected.metadata["selected_source"], "yahoo_finance")


if __name__ == "__main__":
    unittest.main()
