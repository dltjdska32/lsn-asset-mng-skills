import unittest
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from investment_stack.contracts.market import QuoteKind
from investment_stack.providers.market_quotes import (
    MarketQuoteProvider,
    parse_naver_basic_quote,
    parse_coinbase_ticker,
    parse_yahoo_quote,
    _supports_btc_usd
)

class TestBMarketQuotes(unittest.TestCase):
    def test_supports_btc_usd_identity(self):
        self.assertTrue(_supports_btc_usd("CRYPTO:BTC/USD", "USD"))
        self.assertTrue(_supports_btc_usd("XBT/USD", "USD"))
        self.assertFalse(_supports_btc_usd("CRYPTO:ETH/USD", "USD"))
        self.assertFalse(_supports_btc_usd("CRYPTO:BTC/USD", "EUR"))

    def test_parse_naver_basic_quote_future_rejection_in_provider(self):
        """Test that future claimed time is rejected in fetch_current."""
        # Simulated payload from Naver
        payload = {
            "itemCode": "005930",
            "closePrice": "80000",
            "localTradedAt": "2026-09-28T15:30:00",  # Future time
            "stockExchangeType": {"code": "KS"}
        }

        provider = MarketQuoteProvider(
            source_bundles={"KRX:005930": {"source_id": "naver_pay", "payload": payload}}
        )

        # As of is before the localTradedAt
        as_of = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
        result = provider.fetch_current("KRX:005930", analysis_as_of=as_of)

        self.assertEqual(result.status.name, "UNAVAILABLE")
        self.assertIn("CANDIDATES_EXHAUSTED", result.reason)
        # Check that attempt reason correctly flags future price
        attempts = result.metadata["attempts"]
        self.assertTrue(any("FUTURE_PRICE" in att.get("reason", "") for att in attempts))

    def test_parse_yahoo_quote_identity_mismatch(self):
        """Test Yahoo parser strictly validates payload symbol against requested instrument."""
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "symbol": "MSFT",
                        "regularMarketPrice": 300.5,
                        "currency": "USD",
                        "regularMarketTime": 1700000000
                    }
                }]
            }
        }
        res = parse_yahoo_quote(payload, instrument_id="NASDAQ:AAPL")
        self.assertFalse(res.is_usable)
        self.assertIn("IDENTITY_MISMATCH", res.error_reasons[0])
        self.assertIn("MSFT", res.error_reasons[0])

    def test_coinbase_ticker_missing_time(self):
        """Test Coinbase parser when trade time is missing or malformed."""
        payload = {
            "price": "50000",
            # "time": missing
        }
        res = parse_coinbase_ticker(payload)
        self.assertFalse(res.is_usable)
        self.assertIn("MISSING_VENUE_TRADE_TIMESTAMP", res.error_reasons[0])

    def test_eligibility_fallback_sequencing(self):
        """Test that eligibility evaluator can skip stale candidates in fetch_current."""
        payload_stale = {
            "itemCode": "005930",
            "closePrice": "80000",
            "localTradedAt": "2026-09-25T15:30:00",
            "stockExchangeType": {"code": "KS"}
        }

        # First source will provide stale data. In reality, multiple candidates
        # are tried. We mock the eligibility evaluator to reject it.
        provider = MarketQuoteProvider(
            source_bundles={"KRX:005930": {"source_id": "naver_pay", "payload": payload_stale}}
        )

        as_of = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)

        def stale_eval(quote, as_of_dt):
            # E.g. reject if older than 1 day
            return False, "STALE_DATA_REJECTED"

        result = provider.fetch_current(
            "KRX:005930",
            analysis_as_of=as_of,
            eligibility_evaluator=stale_eval
        )

        self.assertEqual(result.status.name, "UNAVAILABLE")
        attempts = result.metadata["attempts"]
        self.assertTrue(any("INELIGIBLE: STALE_DATA_REJECTED" in att.get("reason", "") for att in attempts))

if __name__ == "__main__":
    unittest.main()
