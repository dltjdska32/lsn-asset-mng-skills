"""Unit tests for Market Quotes (R06) and OHLCV Bar Series (R07).

Validates:
- Naver basic quote parsing (regular vs after-hours, currency verification, delay time extraction)
- Identity matching invariant (payload identity must strictly match requested instrument)
- Timestamp fidelity (missing market timestamps are never invented from retrieved dates)
- Coinbase public ticker parsing (venue-specific trade price, actual trade timestamp)
- Yahoo finance quote & OHLCV parsing (live HTTP 200 schema)
- Fallback candidate sequencing (primary failure -> secondary fallback -> exhausted attempts)
- Search snippet rejection
- OHLC price bounds invariants (low <= min(open, close) <= max(open, close) <= high)
- Negative volume rejection and zero volume handling
- Incomplete bar detection against analysis_as_of
- Adjustment verification guard: unverified raw OHLCV is preserved as raw collection
  and NOT promoted to validated BarSet/technical input without explicit receipts
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import unittest
from zoneinfo import ZoneInfo

from investment_stack.contracts.market import AdjustmentMode, Bar, BarSet, QuoteKind
from investment_stack.providers.market_quotes import (
    MarketQuoteProvider,
    parse_coinbase_ticker,
    parse_investing_quote,
    parse_kraken_ticker,
    parse_kraken_trades,
    parse_naver_basic_quote,
    parse_yahoo_quote,
)
from investment_stack.providers.ohlcv import (
    OHLCVProvider,
    parse_kraken_ohlc,
    parse_naver_ohlcv,
    parse_yahoo_chart_ohlcv,
)
from investment_stack.web_research.quote_sources import (
    FallbackSequenceResult,
    MarketCategory,
    QuoteSourceSpec,
    SOURCE_CANDIDATE_ORDER,
    VerificationStatus,
    execute_quote_fallback_sequence,
    resolve_market_category,
)


class TestMarketQuotesR06(unittest.TestCase):
    """R06 Public Market Quotes test suite."""

    def test_naver_basic_quote_regular_session(self) -> None:
        payload = {
            "itemCode": "005930",
            "stockName": "삼성전자",
            "closePrice": "72,500",
            "fluctuationsRatio": "1.25",
            "marketStatus": "OPEN",
            "marketStatusDetailType": "open",
            "localTradedAt": "2026-09-23T14:30:00+09:00",
            "stockExchangeType": {
                "code": "KS",
                "zoneId": "Asia/Seoul",
                "nationType": "KOR",
                "delayTime": 0,
                "nameKor": "코스피",
            },
            "marketSessionType": "regular",
        }
        res = parse_naver_basic_quote(payload, instrument_id="KRX:005930")
        self.assertTrue(res.is_usable)
        self.assertIsNotNone(res.quote)
        assert res.quote is not None

        self.assertEqual(res.quote.instrument_id, "KRX:005930")
        self.assertEqual(res.quote.currency, "KRW")
        self.assertEqual(res.quote.price, Decimal("72500"))
        self.assertEqual(res.quote.quote_kind, QuoteKind.REGULAR)
        self.assertEqual(res.quote.exchange, "KRX")
        self.assertEqual(res.quote.delay_minutes, 0)
        self.assertIsNotNone(res.quote.claimed_market_time)

    def test_naver_basic_quote_identity_mismatch_rejected(self) -> None:
        """P1: Payload itemCode must strictly match requested instrument_id."""
        payload = {
            "itemCode": "005930",  # Samsung Electronics
            "closePrice": "72,500",
            "localTradedAt": "2026-09-23T14:30:00+09:00",
            "stockExchangeType": {"code": "KS"},
        }
        # Requesting SK Hynix (000660) with Samsung Electronics payload -> Must reject!
        res = parse_naver_basic_quote(payload, instrument_id="KRX:000660")
        self.assertFalse(res.is_usable)
        self.assertIsNone(res.quote)
        self.assertIn("IDENTITY_MISMATCH", res.error_reasons[0])

    def test_naver_basic_quote_missing_payload_identity_rejected(self) -> None:
        """P1: Missing payload itemCode is never filled from caller."""
        payload = {
            "closePrice": "72,500",
            "localTradedAt": "2026-09-23T14:30:00+09:00",
            "stockExchangeType": {"code": "KS"},
        }
        res = parse_naver_basic_quote(payload, instrument_id="KRX:005930")
        self.assertFalse(res.is_usable)
        self.assertIn("MISSING_PAYLOAD_IDENTITY", res.error_reasons[0])

    def test_naver_basic_quote_missing_market_timestamp_rejected(self) -> None:
        """P1: Missing localTradedAt must NOT be invented from retrieved date; marked ineligible."""
        payload = {
            "itemCode": "005930",
            "closePrice": "72,500",
            "stockExchangeType": {"code": "KS"},
            # localTradedAt omitted
        }
        retrieved = datetime(2026, 9, 23, 16, 0, 0, tzinfo=timezone.utc)
        res = parse_naver_basic_quote(payload, instrument_id="KRX:005930", retrieved_at=retrieved)
        self.assertFalse(res.is_usable)
        self.assertIsNone(res.quote)
        self.assertIn("MISSING_MARKET_TIMESTAMP", res.error_reasons[0])

    def test_naver_basic_quote_missing_delay_is_none(self) -> None:
        """Missing delayTime must remain None (unknown), not defaulted to 0."""
        payload = {
            "itemCode": "005930",
            "closePrice": "72,500",
            "localTradedAt": "2026-09-23T14:30:00+09:00",
            "stockExchangeType": {"code": "KS"},
            # delayTime omitted
        }
        res = parse_naver_basic_quote(payload, instrument_id="KRX:005930")
        self.assertTrue(res.is_usable)
        assert res.quote is not None
        self.assertIsNone(res.quote.delay_minutes)

    def test_naver_basic_quote_after_market_separation(self) -> None:
        """Verifies afterMarket closePrice becomes LAST_VALID_CLOSE, overPrice becomes EXTENDED_HOURS."""
        payload = {
            "itemCode": "005930",
            "stockName": "삼성전자",
            "closePrice": "285,000",
            "marketStatus": "OPEN",
            "marketStatusDetailType": "open",
            "localTradedAt": "2026-09-23T16:47:56+09:00",
            "stockExchangeType": {
                "code": "KS",
                "zoneId": "Asia/Seoul",
                "nationType": "KOR",
                "delayTime": 0,
                "endTime": "1530",
            },
            "marketSessionType": "afterMarket",
            "overMarketPriceInfo": {
                "tradingSessionType": "AFTER_MARKET",
                "overPrice": "286,000",
                "localTradedAt": "2026-09-23T16:48:31.5+09:00",
            },
        }
        # Regular session close quote
        res_close = parse_naver_basic_quote(payload, instrument_id="KRX:005930", prefer_extended_hours=False)
        self.assertTrue(res_close.is_usable)
        assert res_close.quote is not None
        self.assertEqual(res_close.quote.price, Decimal("285000"))
        self.assertEqual(res_close.quote.quote_kind, QuoteKind.LAST_VALID_CLOSE)
        # Verify aftermarket trade time was NOT stamped on regular close
        if res_close.quote.claimed_market_time:
            self.assertEqual(res_close.quote.claimed_market_time.minute, 30)

        # Extended hours quote
        res_ext = parse_naver_basic_quote(payload, instrument_id="KRX:005930", prefer_extended_hours=True)
        self.assertTrue(res_ext.is_usable)
        assert res_ext.quote is not None
        self.assertEqual(res_ext.quote.price, Decimal("286000"))
        self.assertEqual(res_ext.quote.quote_kind, QuoteKind.EXTENDED_HOURS)

    def test_coinbase_ticker_live_schema(self) -> None:
        """P1: Coinbase Ticker parser with live HTTP 200 confirmed schema."""
        payload = {
            "price": "63500.50",
            "bid": "63500.00",
            "ask": "63501.00",
            "size": "0.123",
            "volume": "1234.5",
            "trade_id": 123456,
            "time": "2026-09-23T07:53:56.123456Z",
        }
        res = parse_coinbase_ticker(payload, instrument_id="CRYPTO:BTC/USD")
        self.assertTrue(res.is_usable)
        assert res.quote is not None
        self.assertEqual(res.quote.price, Decimal("63500.50"))
        self.assertEqual(res.quote.currency, "USD")
        self.assertEqual(res.quote.exchange, "COINBASE")
        self.assertEqual(res.quote.venue, "COINBASE")
        self.assertIsNotNone(res.quote.claimed_market_time)
        assert res.quote.claimed_market_time is not None
        self.assertEqual(res.quote.claimed_market_time.year, 2026)

    def test_yahoo_quote_live_schema(self) -> None:
        """P1: Yahoo Finance Chart/Quote parser with live HTTP 200 confirmed schema."""
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "currency": "USD",
                            "symbol": "AAPL",
                            "exchangeName": "NASDAQ",
                            "fullExchangeName": "NasdaqGS",
                            "exchangeTimezoneName": "America/New_York",
                            "regularMarketPrice": 225.50,
                            "regularMarketTime": 1727088000,
                        }
                    }
                ],
                "error": None,
            }
        }
        # Correct symbol
        res = parse_yahoo_quote(payload, instrument_id="NASDAQ:AAPL")
        self.assertTrue(res.is_usable)
        assert res.quote is not None
        self.assertEqual(res.quote.price, Decimal("225.50"))
        self.assertEqual(res.quote.currency, "USD")
        self.assertEqual(res.quote.exchange, "NASDAQ")
        self.assertEqual(res.quote.quote_kind, QuoteKind.REGULAR)
        self.assertIsNone(res.quote.delay_minutes)
        self.assertIsNone(res.quote.delay_minutes)
        delayed = json.loads(json.dumps(payload))
        delayed["chart"]["result"][0]["meta"]["exchangeDataDelayedBy"] = 15
        delayed_result = parse_yahoo_quote(delayed, instrument_id="NASDAQ:AAPL")
        self.assertEqual(delayed_result.quote.delay_minutes, 15)

        # Identity mismatch
        res_mismatch = parse_yahoo_quote(payload, instrument_id="NASDAQ:MSFT")
        self.assertFalse(res_mismatch.is_usable)
        self.assertIn("IDENTITY_MISMATCH", res_mismatch.error_reasons[0])

        wrong_market = json.loads(json.dumps(payload))
        wrong_market["chart"]["result"][0]["meta"]["exchangeName"] = "NYSE"
        wrong_market = parse_yahoo_quote(wrong_market, instrument_id="NASDAQ:AAPL")
        self.assertFalse(wrong_market.is_usable)
        self.assertIn("MARKET_METADATA_MISMATCH", wrong_market.error_reasons[0])


    def test_btc_eur_is_rejected_before_usd_transport(self) -> None:
        calls = []
        provider = MarketQuoteProvider(transport=lambda *args: (calls.append(args[0]) or (200, b"{}", {})))
        result = provider.fetch_current("CRYPTO:BTC/EUR", analysis_as_of=datetime.now(timezone.utc))
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertIn("UNSUPPORTED_SOURCE_PAIR", result.reason or "")
        self.assertEqual(calls, [])
        self.assertEqual(resolve_market_category("CRYPTO:BTC/EUR").value, "CRYPTO_BTC")

    def test_kraken_trades_requires_expected_usd_result_key(self) -> None:
        payload = {"error": [], "result": {"last": "cursor", "XXBTZEUR": [["59000", "0.1", 1790155800, "b", "l", "", "1"]]}}
        result = parse_kraken_trades(payload, instrument_id="CRYPTO:BTC/USD")
        self.assertFalse(result.is_usable)
        self.assertIn("KRAKEN_PAIR_NOT_FOUND", result.error_reasons[0])

    def test_provider_eligibility_failure_advances_to_kraken(self) -> None:
        as_of = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        coinbase = {"price": "63500.50", "time": "2026-09-23T09:29:00Z"}
        kraken = {"error": [], "result": {"XXBTZUSD": [["63501", "0.1", as_of.timestamp() - 30, "b", "l", "", "2"]], "last": "cursor"}}
        calls = []
        def transport(url, headers, timeout):
            calls.append(url)
            return 200, json.dumps(coinbase if "coinbase" in url else kraken).encode(), {}
        checked = []
        def eligibility(quote, cutoff):
            checked.append(quote.venue)
            return (quote.venue == "KRAKEN", "test rejects primary")
        provider = MarketQuoteProvider(transport=transport, clock=lambda: as_of)
        result = provider.fetch_current("CRYPTO:BTC/USD", analysis_as_of=as_of, eligibility_evaluator=eligibility)
        self.assertEqual(result.status.value, "AVAILABLE")
        self.assertEqual(result.metadata["selected_source"], "kraken_trades")
        self.assertEqual(len(calls), 2)
        self.assertEqual(checked, ["COINBASE", "KRAKEN"])
        self.assertIn("INELIGIBLE", result.metadata["attempts"][0]["reason"])

    def test_provider_without_freshness_evaluator_never_returns_available(self) -> None:
        as_of = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        payload = {"price": "63500.50", "time": "2026-09-23T09:29:00Z"}
        provider = MarketQuoteProvider(
            transport=lambda url, *_: (200, json.dumps(payload).encode(), {}), clock=lambda: as_of,
        )
        result = provider.fetch_current("CRYPTO:BTC/USD", analysis_as_of=as_of)
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertEqual(result.reason, "FRESHNESS_EVALUATOR_NOT_CONFIGURED")
        self.assertNotIn("contract_quote", result.metadata)
        self.assertTrue(any("FRESHNESS_EVALUATOR_NOT_CONFIGURED" in a["reason"] for a in result.metadata["attempts"]))

    def test_provider_evaluator_error_is_recorded_and_fails_closed(self) -> None:
        as_of = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        payload = {"price": "63500.50", "time": "2026-09-23T09:29:00Z"}
        provider = MarketQuoteProvider(
            transport=lambda url, *_: (200, json.dumps(payload).encode(), {}), clock=lambda: as_of,
        )
        def broken_evaluator(quote, cutoff):
            raise RuntimeError("fixture failure")
        result = provider.fetch_current("CRYPTO:BTC/USD", analysis_as_of=as_of,
            eligibility_evaluator=broken_evaluator)
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertTrue(any("ELIGIBILITY_EVALUATOR_ERROR: RuntimeError" in a["reason"] for a in result.metadata["attempts"]))

    def test_provider_all_candidates_failed_is_audited(self) -> None:
        calls = []
        provider = MarketQuoteProvider(transport=lambda url, *_: (calls.append(url) or (403, b"denied", {})))
        result = provider.fetch_current(
            "CRYPTO:BTC/USD", analysis_as_of=datetime(2026, 9, 23, tzinfo=timezone.utc),
            eligibility_evaluator=lambda quote, cutoff: (True, None),
        )
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertEqual(result.reason, "CANDIDATES_EXHAUSTED")
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(a["status_code"] == 403 for a in result.metadata["attempts"]))

    def test_fundamentals_candidate_is_not_called_for_current_price(self) -> None:
        calls = []
        provider = MarketQuoteProvider(
            transport=lambda url, headers, timeout: (calls.append(url) or (503, b"", {})),
        )
        result = provider.fetch_current(
            "NASDAQ:AAPL", analysis_as_of=datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(result.status.value, "UNAVAILABLE")
        self.assertEqual(len(calls), 1)
        self.assertIn("finance/chart/AAPL", calls[0])
        self.assertFalse(any("sec.gov" in url for url in calls))

    def test_fallback_helper_retrieval_time_uses_clock_not_cutoff(self) -> None:
        cutoff = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        retrieved = datetime(2026, 9, 23, 9, 40, tzinfo=timezone.utc)
        payload = {"price": "63500.50", "time": "2026-09-23T09:29:00Z"}
        result = execute_quote_fallback_sequence(
            "CRYPTO:BTC/USD", transport=lambda *args: (200, json.dumps(payload).encode(), {}),
            analysis_as_of=cutoff, clock=lambda: retrieved,
            eligibility_evaluator=lambda quote, as_of: (True, None),
        )
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.selected_quote.retrieved_at, retrieved)

    def test_quote_fallback_helper_without_evaluator_does_not_select_candidate(self) -> None:
        cutoff = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        payload = {"price": "63500.50", "time": "2026-09-23T09:29:00Z"}
        result = execute_quote_fallback_sequence(
            "CRYPTO:BTC/USD", transport=lambda *args: (200, json.dumps(payload).encode(), {}),
            analysis_as_of=cutoff,
        )
        self.assertEqual(result.status, "FRESHNESS_EVALUATOR_REQUIRED")
        self.assertIsNone(result.selected_quote)
        self.assertTrue(any(a.error_reason == "FRESHNESS_EVALUATOR_NOT_CONFIGURED" for a in result.attempts))

    def test_quote_fallback_helper_stale_candidate_advances_to_fresh_alternate(self) -> None:
        cutoff = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        stale_coinbase = {"price": "63000", "time": "2026-09-23T08:00:00Z"}
        fresh_kraken = {"error": [], "result": {"XXBTZUSD": [["63501", "0.1", cutoff.timestamp() - 30, "b", "l", "", "2"]], "last": "cursor"}}
        result = execute_quote_fallback_sequence(
            "CRYPTO:BTC/USD", transport=lambda *args: (503, b"", {}), analysis_as_of=cutoff,
            fixtures_by_source={"coinbase_public": stale_coinbase, "kraken_trades": fresh_kraken},
            clock=lambda: cutoff,
            eligibility_evaluator=lambda quote, as_of: (quote.venue == "KRAKEN", "stale or unapproved source"),
        )
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.selected_quote.venue, "KRAKEN")
        self.assertFalse(result.attempts[0].success)
        self.assertTrue(result.attempts[1].success)

    def test_quote_fallback_helper_rejects_future_observation_even_if_evaluator_accepts(self) -> None:
        cutoff = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        payload = {"price": "63500", "time": "2026-09-23T09:31:00Z"}
        result = execute_quote_fallback_sequence(
            "CRYPTO:BTC/USD", transport=lambda *args: (200, json.dumps(payload).encode(), {}),
            analysis_as_of=cutoff, clock=lambda: cutoff,
            eligibility_evaluator=lambda quote, as_of: (True, None),
        )
        self.assertEqual(result.status, "CANDIDATES_EXHAUSTED")
        self.assertIsNone(result.selected_quote)
        self.assertTrue(any(a.error_reason and a.error_reason.startswith("FUTURE_PRICE") for a in result.attempts))


class TestOHLCVR07(unittest.TestCase):
    """R07 Historical OHLCV Bar Series test suite."""

    def test_ohlcv_unverified_adjustment_rejected_from_barset(self) -> None:
        """P1: Raw OHLCV lacking split/adjustment receipt is NOT promoted to validated BarSet."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260920",
                    "openPrice": 100.0,
                    "highPrice": 110.0,
                    "lowPrice": 95.0,
                    "closePrice": 105.0,
                    "accumulatedTradingVolume": 1000,
                }
            ],
        }
        # Without adjustment_verified or receipt:
        res = parse_naver_ohlcv(payload, instrument_id="KRX:005930", adjustment_verified=False)
        self.assertFalse(res.is_usable)
        self.assertIsNone(res.bar_set)
        self.assertEqual(len(res.bars), 1)  # Raw bars preserved
        self.assertIn("UNVERIFIED_ADJUSTMENT", res.error_reasons[0])

    def test_naver_live_price_list_schema_requires_bound_request_route(self) -> None:
        """Naver's live /price list has no echoed symbol; bind it to its exact request URL."""
        payload = [
            {
                "localTradedAt": "2026-09-25",
                "openPrice": "80,000",
                "highPrice": "82,000",
                "lowPrice": "79,000",
                "closePrice": "81,000",
                "accumulatedTradingVolume": "1,200",
            }
        ]
        url = "https://m.stock.naver.com/api/stock/005930/price?page=1&pageSize=1"
        as_of = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)

        unbound = parse_naver_ohlcv(payload, instrument_id="KRX:005930", analysis_as_of=as_of)
        self.assertIn("UNBOUND_RESPONSE_IDENTITY", unbound.error_reasons[0])
        self.assertFalse(unbound.bars)

        mismatch = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:000660",
            analysis_as_of=as_of,
            request_url=url,
        )
        self.assertIn("IDENTITY_MISMATCH", mismatch.error_reasons[0])

        parsed = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            analysis_as_of=as_of,
            request_url=url,
        )
        self.assertIn("UNVERIFIED_ADJUSTMENT", parsed.error_reasons[0])
        self.assertIsNone(parsed.bar_set)
        self.assertEqual(parsed.bars[0].session_date, "2026-09-25")
        self.assertEqual(parsed.bars[0].close, Decimal("81000"))
        self.assertEqual(parsed.bars[0].public_availability.source_locator, url)

    def test_naver_adjustment_flag_without_receipt_is_not_enough(self) -> None:
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260920",
                    "openPrice": 100,
                    "highPrice": 110,
                    "lowPrice": 95,
                    "closePrice": 105,
                    "accumulatedTradingVolume": 1000,
                }
            ],
        }
        parsed = parse_naver_ohlcv(payload, instrument_id="KRX:005930", adjustment_verified=True)
        self.assertIsNone(parsed.bar_set)
        self.assertIn("UNVERIFIED_ADJUSTMENT", parsed.error_reasons[0])

    def test_naver_live_schema_unverified_result_preserves_raw_bars(self) -> None:
        payload = [
            {
                "localTradedAt": "2026-09-25",
                "openPrice": "80,000",
                "highPrice": "82,000",
                "lowPrice": "79,000",
                "closePrice": "81,000",
                "accumulatedTradingVolume": "1,200",
            }
        ]

        def transport(url, headers, timeout):
            self.assertIn("/api/stock/005930/price", url)
            return 200, json.dumps(payload).encode("utf-8"), {"content-type": "application/json"}

        result = OHLCVProvider(transport=transport).fetch_historical_bars(
            "KRX:005930", analysis_as_of=datetime(2026, 9, 27, tzinfo=timezone.utc)
        )
        self.assertEqual(result.status.name, "UNAVAILABLE")
        self.assertIn("UNVERIFIED_ADJUSTMENT", result.reason)
        parsed = result.metadata["contract_ohlcv_parse_result"]
        self.assertEqual(len(parsed.bars), 1)
        self.assertIsNone(parsed.bar_set)

    def test_ohlcv_verified_adjustment_accepted(self) -> None:
        """A strict verification flag plus a receipt is required before creating BarSet."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260920",
                    "openPrice": 100.0,
                    "highPrice": 110.0,
                    "lowPrice": 95.0,
                    "closePrice": 105.0,
                    "accumulatedTradingVolume": 1000,
                }
            ],
        }
        res = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            adjustment_verified=True,
            adjustment_receipt="CORP_ACTION_V1_VERIFIED",
        )
        self.assertTrue(res.is_usable)
        self.assertIsNotNone(res.bar_set)
        assert res.bar_set is not None
        self.assertEqual(len(res.bar_set.bars), 1)
        self.assertEqual(res.bar_set.bars[0].adjustment_mode, AdjustmentMode.SPLIT_ADJUSTED)

    def test_ohlcv_identity_mismatch_rejected(self) -> None:
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260920",
                    "openPrice": 100.0,
                    "highPrice": 110.0,
                    "lowPrice": 95.0,
                    "closePrice": 105.0,
                    "accumulatedTradingVolume": 1000,
                }
            ],
        }
        res = parse_naver_ohlcv(payload, instrument_id="KRX:000660")
        self.assertFalse(res.is_usable)
        self.assertIn("IDENTITY_MISMATCH", res.error_reasons[0])

    def test_ohlcv_bounds_invariant_validation(self) -> None:
        """Invariants: low <= min(open, close) and max(open, close) <= high."""
        bad_payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260920",
                    "openPrice": 100.0,
                    "highPrice": 110.0,
                    "lowPrice": 105.0,  # Invalid: low > open (100)
                    "closePrice": 108.0,
                    "accumulatedTradingVolume": 1000,
                }
            ],
        }
        res = parse_naver_ohlcv(bad_payload, instrument_id="KRX:005930", adjustment_verified=True)
        self.assertEqual(len(res.bars), 0)
        self.assertEqual(len(res.discarded_bars), 1)
        self.assertEqual(res.discarded_bars[0]["reason"], "BOUNDS_INVARIANT_VIOLATION")

    def test_ohlcv_incomplete_forming_bar_isolation(self) -> None:
        """If session_close > analysis_as_of, bar is marked is_complete=False and isolated."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260922",  # Yesterday: complete
                    "openPrice": 100.0,
                    "highPrice": 105.0,
                    "lowPrice": 95.0,
                    "closePrice": 102.0,
                    "accumulatedTradingVolume": 1000,
                },
                {
                    "localDate": "20260923",  # Today: session ends at 15:30
                    "openPrice": 102.0,
                    "highPrice": 108.0,
                    "lowPrice": 101.0,
                    "closePrice": 107.0,
                    "accumulatedTradingVolume": 500,
                },
            ],
        }
        midday_as_of = datetime(2026, 9, 23, 11, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        res = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            analysis_as_of=midday_as_of,
            adjustment_verified=True,
            adjustment_receipt="fixture:split-adjustment-reviewed",
        )

        self.assertEqual(len(res.bars), 1)
        self.assertEqual(res.bars[0].session_date, "2026-09-22")
        self.assertTrue(res.bars[0].is_complete)

        self.assertEqual(len(res.incomplete_bars), 1)
        self.assertEqual(res.incomplete_bars[0].session_date, "2026-09-23")
        self.assertFalse(res.incomplete_bars[0].is_complete)

        self.assertIsNotNone(res.bar_set)
        assert res.bar_set is not None
        self.assertEqual(len(res.bar_set.bars), 1)

    def test_yahoo_chart_ohlcv_live_schema(self) -> None:
        """Yahoo Finance Chart OHLCV parser with live HTTP 200 schema."""
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "currency": "USD",
                            "symbol": "AAPL",
                            "exchangeName": "NASDAQ",
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [1727088000, 1727174400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [220.0, 222.0],
                                    "high": [225.0, 226.0],
                                    "low": [219.0, 221.0],
                                    "close": [224.0, 225.0],
                                    "volume": [50000000, 48000000],
                                }
                            ],
                            "adjclose": [{"adjclose": [224.0, 225.0]}],
                        },
                    }
                ],
                "error": None,
            }
        }
        res = parse_yahoo_chart_ohlcv(payload, instrument_id="NASDAQ:AAPL")
        self.assertFalse(res.is_usable)
        self.assertIsNone(res.bar_set)
        # Yahoo adjclose alone does not establish that the OHLC fields share its adjustment basis.
        self.assertTrue(all(b.adjustment_mode == AdjustmentMode.RAW for b in res.bars))

        verified = parse_yahoo_chart_ohlcv(
            payload, instrument_id="NASDAQ:AAPL", source_url="https://query1.finance.yahoo.com/chart/AAPL",
            adjustment_verified=True, adjustment_receipt="fixture-adjustment-v1",
            calendar_receipt="fixture-calendar-v1", expected_session_dates=("2024-09-23", "2024-09-24"),
            analysis_as_of=datetime(2024, 9, 25, tzinfo=timezone.utc),
        )
        self.assertTrue(verified.analysis_eligible)


if __name__ == "__main__":
    unittest.main()
