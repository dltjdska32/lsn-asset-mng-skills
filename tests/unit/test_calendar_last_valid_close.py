from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from investment_stack.freshness import (
    ExchangeCalendarSchedule,
    ExchangeSession,
    FreshnessEngine,
    FreshnessPolicy,
    FreshnessStatus,
    MarketSession,
    get_pinned_calendar,
)
from investment_stack.providers.models import ProviderObservation


ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def session(day: str, tz: ZoneInfo, open_time: str, close_time: str) -> ExchangeSession:
    return ExchangeSession(
        date.fromisoformat(day),
        datetime.fromisoformat(f"{day}T{open_time}").replace(tzinfo=tz),
        datetime.fromisoformat(f"{day}T{close_time}").replace(tzinfo=tz),
    )


def nasdaq_calendar() -> ExchangeCalendarSchedule:
    result = get_pinned_calendar("NASDAQ")
    assert result is not None
    return result


def krx_calendar() -> ExchangeCalendarSchedule:
    result = get_pinned_calendar("KRX")
    assert result is not None
    return result


def observation(*, market_date: str, claimed: str, exchange: str, currency: str,
                instrument: str, quote_kind: str = "REGULAR", published: str | None = None,
                **metadata) -> ProviderObservation:
    return ProviderObservation(
        evidence_type="market", source_name="fixture", source_url="https://quotes.example.test/",
        source_tier=1, provider_id="test", value=Decimal("100"), currency=currency,
        instrument_id=instrument, observed_at=claimed, claimed_market_time=claimed,
        market_session_date=market_date, published_at=published,
        metadata={"quote_kind": quote_kind, "exchange": exchange, **metadata},
    )


class CalendarLastValidCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FreshnessEngine(FreshnessPolicy(timedelta(minutes=15), timedelta(days=1)))

    def assess(self, obs: ProviderObservation, cutoff: str, calendar: ExchangeCalendarSchedule,
               market_session: MarketSession | None = None):
        return self.engine.assess(obs, analysis_as_of=cutoff, calendar=calendar, market_session=market_session)

    def test_yahoo_nasdaq_friday_close_is_valid_on_sunday(self) -> None:
        obs = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                          exchange="NMS", currency="USD", instrument="NASDAQ:AAPL",
                          published="2026-09-25T16:00:01-04:00")
        result = self.assess(obs, "2026-09-27T12:00:00-04:00", nasdaq_calendar(), MarketSession.HOLIDAY)
        self.assertEqual(result.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertEqual(result.market_session_date, "2026-09-25")
        self.assertIn("휴장 중 마지막 유효 거래일 종가", result.reason)
        self.assertIn("16:00:00-04:00", result.reason)
        self.assertEqual(result.effective_time, "2026-09-25T20:00:01+00:00")

    def test_krx_september_23_close_is_last_session_on_chuseok_sunday(self) -> None:
        obs = observation(market_date="2026-09-23", claimed="2026-09-23T15:30:00+09:00",
                          exchange="KRX", currency="KRW", instrument="KRX:005930",
                          quote_kind="LAST_VALID_CLOSE", published="2026-09-23T16:30:00+09:00")
        result = self.assess(obs, "2026-09-27T12:00:00+09:00", krx_calendar(), MarketSession.HOLIDAY)
        self.assertEqual(result.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertEqual(result.market_session_date, "2026-09-23")
        self.assertIn("2026-09-23T15:30:00+09:00", result.reason)
        self.assertIn("2026-09-23T16:30:00+09:00", result.reason)

    def test_krx_close_is_not_available_before_close_price_send_time(self) -> None:
        obs = observation(market_date="2026-09-23", claimed="2026-09-23T15:30:00+09:00",
                          exchange="KRX", currency="KRW", instrument="KRX:005930",
                          quote_kind="LAST_VALID_CLOSE", published="2026-09-23T16:30:00+09:00")
        before_publication = self.assess(obs, "2026-09-23T16:00:00+09:00", krx_calendar())
        self.assertEqual(before_publication.status, FreshnessStatus.UNAVAILABLE)
        at_publication = self.assess(obs, "2026-09-23T16:30:00+09:00", krx_calendar())
        self.assertEqual(at_publication.status, FreshnessStatus.LAST_VALID_CLOSE)

    def test_friday_quote_is_stale_after_monday_nasdaq_open(self) -> None:
        obs = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                          exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL")
        result = self.assess(obs, "2026-09-28T09:31:00-04:00", nasdaq_calendar(), MarketSession.REGULAR)
        self.assertIn(result.status, {FreshnessStatus.STALE, FreshnessStatus.UNAVAILABLE})
        self.assertNotEqual(result.status, FreshnessStatus.LAST_VALID_CLOSE)

    def test_pre_open_reason_is_distinct_from_holiday(self) -> None:
        obs = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                          exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL",
                          published="2026-09-25T16:00:01-04:00")
        result = self.assess(obs, "2026-09-28T08:00:00-04:00", nasdaq_calendar())
        self.assertEqual(result.status, FreshnessStatus.LAST_VALID_CLOSE)
        self.assertIn("개장 전 직전 유효 거래일 종가", result.reason)
        self.assertNotIn("휴장 중", result.reason)

    def test_krx_previous_session_is_not_last_close_when_a_later_session_exists(self) -> None:
        obs = observation(market_date="2026-09-22", claimed="2026-09-22T15:30:00+09:00",
                          exchange="KRX", currency="KRW", instrument="KRX:005930",
                          quote_kind="LAST_VALID_CLOSE", published="2026-09-22T16:30:00+09:00")
        result = self.assess(obs, "2026-09-27T12:00:00+09:00", krx_calendar())
        self.assertEqual(result.status, FreshnessStatus.STALE)

    def test_wrong_exchange_or_currency_fails_closed(self) -> None:
        wrong_exchange = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                                     exchange="NYSE", currency="USD", instrument="NASDAQ:AAPL")
        result = self.assess(wrong_exchange, "2026-09-27T12:00:00-04:00", nasdaq_calendar())
        self.assertEqual(result.status, FreshnessStatus.UNAVAILABLE)
        wrong_currency = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                                     exchange="NASDAQ", currency="EUR", instrument="NASDAQ:AAPL")
        self.assertEqual(self.assess(wrong_currency, "2026-09-27T12:00:00-04:00", nasdaq_calendar()).status,
                         FreshnessStatus.UNAVAILABLE)

    def test_missing_coverage_or_old_quote_fails_closed(self) -> None:
        obs = observation(market_date="2025-09-02", claimed="2025-09-02T16:00:00-04:00",
                          exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL")
        result = self.assess(obs, "2026-09-27T12:00:00-04:00", nasdaq_calendar())
        self.assertEqual(result.status, FreshnessStatus.UNAVAILABLE)

    def test_delayed_quote_and_incomplete_bar_cannot_be_last_close(self) -> None:
        delayed = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                             exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL", quote_kind="DELAYED")
        self.assertEqual(self.assess(delayed, "2026-09-27T12:00:00-04:00", nasdaq_calendar()).status,
                         FreshnessStatus.UNAVAILABLE)
        incomplete = observation(market_date="2026-09-28", claimed="2026-09-28T10:00:00-04:00",
                                 exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL", bar_complete=False)
        self.assertEqual(self.assess(incomplete, "2026-09-28T10:01:00-04:00", nasdaq_calendar()).status,
                         FreshnessStatus.UNAVAILABLE)

    def test_crypto_never_uses_exchange_closed_last_close_shortcut(self) -> None:
        crypto = observation(market_date="2026-09-27", claimed="2026-09-27T12:00:00+00:00",
                             exchange="COINBASE", currency="USD", instrument="CRYPTO:BTC/USD")
        result = self.engine.assess(crypto, analysis_as_of="2026-09-27T12:01:00+00:00",
                                    market_session=MarketSession.TWENTY_FOUR_SEVEN, calendar=nasdaq_calendar())
        self.assertEqual(result.status, FreshnessStatus.FRESH)

    def test_closed_market_without_calendar_fails_closed(self) -> None:
        obs = observation(market_date="2026-09-25", claimed="2026-09-25T16:00:01-04:00",
                          exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL")
        result = self.engine.assess(obs, analysis_as_of="2026-09-27T12:00:00-04:00",
                                    market_session=MarketSession.HOLIDAY)
        self.assertEqual(result.status, FreshnessStatus.UNAVAILABLE)

    def test_unapproved_calendar_source_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExchangeCalendarSchedule("NASDAQ", "USD", "America/New_York", "fake", ("https://example.test/calendar",),
                date(2026, 9, 24), date(2026, 9, 28), ())

    def test_official_url_with_omitted_midweek_session_is_not_trusted(self) -> None:
        pinned = nasdaq_calendar()
        tampered = replace(pinned, sessions=(pinned.sessions[0], pinned.sessions[2]))
        obs = observation(market_date="2026-09-24", claimed="2026-09-24T16:00:00-04:00",
                          exchange="NASDAQ", currency="USD", instrument="NASDAQ:AAPL")
        result = self.assess(obs, "2026-09-27T12:00:00-04:00", tampered)
        self.assertEqual(result.status, FreshnessStatus.UNAVAILABLE)
        self.assertIn("not in the pinned trusted registry", result.reason)


if __name__ == "__main__":
    unittest.main()
