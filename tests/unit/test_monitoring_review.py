from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.execution.quote_refresh import capture_quote_body, refresh_requested_quotes
from tests.storage_support import sqlite_connection
from investment_stack.monitoring.review import (
    BarClose,
    bundled_jpx_calendar,
    customer_concentration,
    datacenter_status,
    decide_alert,
    dedupe_news,
    guidance_delta,
    review_drops,
    thirteen_f_trade_adoption,
    volatility_shadow_price,
)


def _bars(*closes: str) -> tuple[BarClose, ...]:
    return tuple(BarClose(Decimal(close), Decimal("100")) for close in closes)


class MonitoringReviewTests(unittest.TestCase):
    def test_missing_bars_wait_and_do_not_invent_a_price(self) -> None:
        review = review_drops(())
        self.assertEqual("WAIT", review.status)
        self.assertIsNone(volatility_shadow_price(Decimal("100"), ()))

    def test_session_drop_is_review_only(self) -> None:
        review = review_drops((BarClose(Decimal("100"), Decimal("10")), BarClose(Decimal("94"), Decimal("10"))))
        self.assertEqual("DROP_REVIEW", review.status)
        shadow = volatility_shadow_price(Decimal("80"), _bars("10", "11", "9", "10", "12"))
        self.assertIsNotNone(shadow)
        self.assertEqual(Decimal("76"), shadow)

    def test_duplicate_news_and_known_events_stay_silent(self) -> None:
        items = dedupe_news((
            {"source_url": "https://Example.test/a?x=1", "title": "Same"},
            {"source_url": "https://example.test/a", "title": "Same again"},
            {"title": "Other story"},
        ))
        self.assertEqual(2, len(items))
        checked = datetime(2026, 9, 29, tzinfo=timezone.utc)
        decision = decide_alert(
            known_event_ids=frozenset({"known"}), incoming_event_ids=("known",),
            drop_status="NO_DROP", last_checked_at=checked, observed_at=checked,
        )
        self.assertEqual("NO_ALERT", decision.status)

    def test_guidance_customer_and_datacenter_do_not_invent_missing_fields(self) -> None:
        self.assertIsNone(guidance_delta(None, Decimal("10")))
        self.assertEqual(Decimal("-2"), guidance_delta(Decimal("10"), Decimal("8")))
        status, ratio = customer_concentration((("A", Decimal("30")), ("B", Decimal("70"))))
        self.assertEqual("CONCENTRATED:B", status)
        self.assertEqual(Decimal("0.7"), ratio)
        tracked = datacenter_status({"power": "40MW"})
        self.assertEqual("40MW", tracked["power"])
        self.assertEqual("WAIT", tracked["permit"])

    def test_japan_calendar_and_13f_flag_do_not_open_trades(self) -> None:
        calendar = bundled_jpx_calendar()
        self.assertIsNotNone(calendar)
        self.assertIsNotNone(calendar.session_for_date(date(2026, 9, 29)))
        self.assertIsNone(calendar.session_for_date(date(2026, 1, 1)))
        self.assertEqual("DISABLED", thirteen_f_trade_adoption({"out_of_period_passed": True}))

    def test_live_capture_skips_japan_and_keeps_a_parsed_us_body(self) -> None:
        observed = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)
        japan = json.dumps({"chart": {"result": [{"meta": {
            "symbol": "6954.T", "regularMarketPrice": 7000, "currency": "JPY",
            "exchangeName": "JPX", "exchangeTimezoneName": "Asia/Tokyo",
            "regularMarketTime": int(observed.timestamp()),
        }}], "error": None}})
        captured_japan = capture_quote_body(
            "JPX:6954", transport=lambda url, headers, timeout: (200, japan, {}), retrieved_at=observed,
        )
        self.assertIsNotNone(captured_japan)
        self.assertEqual("JPY", captured_japan.currency)
        payload = json.dumps({"chart": {"result": [{"meta": {
            "symbol": "ABC", "regularMarketPrice": 100, "currency": "USD",
            "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York",
            "regularMarketTime": int(observed.timestamp()),
        }}], "error": None}})
        captured = capture_quote_body(
            "NASDAQ:ABC",
            transport=lambda url, headers, timeout: (200, payload, {}),
            retrieved_at=observed,
        )
        self.assertIsNotNone(captured)
        self.assertEqual("yahoo_chart_v1", captured.parser_id)
        self.assertIn("ABC", captured.body)

    def test_refresh_stores_an_unselected_body_only_when_requested(self) -> None:
        observed = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)
        payload = json.dumps({"chart": {"result": [{"meta": {
            "symbol": "ABC", "regularMarketPrice": 100, "currency": "USD",
            "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York",
            "regularMarketTime": int(observed.timestamp()),
        }}], "error": None}})
        calls = {"count": 0}

        def transport(url, headers, timeout):
            del url, headers, timeout
            calls["count"] += 1
            return 200, payload, {}

        with tempfile.TemporaryDirectory() as temporary:
            run = RunDatabaseManager(temporary, "refresh-run")
            self.assertTrue(run.create().valid)
            self.assertEqual((), refresh_requested_quotes(
                run, {"instrument_id": "NASDAQ:ABC"}, transport=transport, retrieved_at=observed,
            ))
            self.assertEqual(0, calls["count"])
            stored = refresh_requested_quotes(
                run,
                {"refresh_market_bodies": True, "instrument_ids": ["NASDAQ:ABC", "JPX:6954"]},
                transport=transport, retrieved_at=observed,
            )
            self.assertEqual(1, len(stored))
            self.assertEqual(2, calls["count"])
            with sqlite_connection(run.database_path, readonly=True) as connection:
                state = connection.execute(
                    "SELECT selection_state FROM evidence WHERE evidence_id=?", (stored[0],),
                ).fetchone()
            self.assertNotEqual(("SELECTED",), state)


if __name__ == "__main__":
    unittest.main()
