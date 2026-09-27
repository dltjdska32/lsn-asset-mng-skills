from __future__ import annotations

import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from investment_stack.freshness import get_pinned_calendar
from investment_stack.providers.market_quotes import calendar_aware_freshness_evaluator, parse_yahoo_quote


ET = ZoneInfo("America/New_York")


class DelayedQuoteGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cutoff = datetime(2026, 9, 28, 10, 1, tzinfo=ET)
        self.calendar = get_pinned_calendar("NASDAQ")
        self.evaluator = calendar_aware_freshness_evaluator(self.calendar)

    def payload(self, delay: int | None | str = "missing") -> dict:
        meta = {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 250.25,
            "regularMarketTime": int(datetime(2026, 9, 28, 9, 46, tzinfo=ET).timestamp()),
        }
        if delay != "missing":
            meta["exchangeDataDelayedBy"] = delay
        return {"chart": {"result": [{"meta": meta}], "error": None}}

    def test_reported_delay_is_rejected_even_inside_freshness_window(self) -> None:
        parsed = parse_yahoo_quote(self.payload(15), instrument_id="NASDAQ:AAPL")
        self.assertTrue(parsed.is_usable)
        allowed, reason = self.evaluator(parsed.quote, self.cutoff)
        self.assertFalse(allowed)
        self.assertEqual(reason, "DELAYED_QUOTE_NOT_ALLOWED_FOR_CURRENT_PRICE")

    def test_zero_or_unknown_delay_still_requires_a_valid_active_session(self) -> None:
        for delay in (0, "missing"):
            with self.subTest(delay=delay):
                parsed = parse_yahoo_quote(self.payload(delay), instrument_id="NASDAQ:AAPL")
                self.assertTrue(parsed.is_usable)
                allowed, _ = self.evaluator(parsed.quote, self.cutoff)
                self.assertTrue(allowed)

        outside_session = datetime(2026, 9, 28, 8, 46, tzinfo=ET)
        payload = json.loads(json.dumps(self.payload(None)))
        payload["chart"]["result"][0]["meta"]["regularMarketTime"] = int(outside_session.timestamp())
        parsed = parse_yahoo_quote(payload, instrument_id="NASDAQ:AAPL")
        allowed, _ = self.evaluator(parsed.quote, self.cutoff)
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
