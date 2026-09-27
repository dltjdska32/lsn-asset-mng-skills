import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json

from investment_stack.providers.ohlcv import parse_naver_ohlcv, parse_yahoo_chart_ohlcv

class TestBOHLCV(unittest.TestCase):
    def test_forming_bar_isolation_naver(self):
        """Test that the current incomplete (forming) session is not included in completed bars."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260925", # Completed
                    "openPrice": "80000", "highPrice": "81000", "lowPrice": "79000", "closePrice": "80500", "accumulatedTradingVolume": "1000"
                },
                {
                    "localDate": "20260928", # Forming (session close > as_of)
                    "openPrice": "80500", "highPrice": "82000", "lowPrice": "80000", "closePrice": "81000", "accumulatedTradingVolume": "500"
                }
            ]
        }

        # as_of is during the session on 09-28
        as_of = datetime(2026, 9, 28, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        res = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            analysis_as_of=as_of,
            adjustment_verified=True,
            adjustment_receipt="fixture:reviewed-adjustment",
        )

        self.assertTrue(res.is_usable)
        self.assertEqual(len(res.bars), 1)
        self.assertEqual(res.bars[0].session_date, "2026-09-25")

        self.assertEqual(len(res.incomplete_bars), 1)
        self.assertEqual(res.incomplete_bars[0].session_date, "2026-09-28")

        self.assertEqual(len(res.discarded_bars), 0)

    def test_future_bar_discard(self):
        """Test that fully future bars relative to as_of are discarded."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260930", # Completely in future
                    "openPrice": "80000", "highPrice": "81000", "lowPrice": "79000", "closePrice": "80500", "accumulatedTradingVolume": "1000"
                }
            ]
        }

        as_of = datetime(2026, 9, 28, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        res = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            analysis_as_of=as_of,
            adjustment_verified=True,
            adjustment_receipt="fixture:reviewed-adjustment",
        )

        self.assertEqual(len(res.bars), 0)
        self.assertEqual(len(res.incomplete_bars), 0)
        self.assertEqual(len(res.discarded_bars), 1)
        self.assertEqual(res.discarded_bars[0]["reason"], "FUTURE_BAR")

    def test_unverified_adjustment_guard(self):
        """Test that unverified adjustment blocks BarSet creation but preserves raw bars."""
        payload = {
            "code": "005930",
            "priceInfos": [
                {
                    "localDate": "20260925",
                    "openPrice": "80000", "highPrice": "81000", "lowPrice": "79000", "closePrice": "80500", "accumulatedTradingVolume": "1000"
                }
            ]
        }

        as_of = datetime(2026, 9, 28, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))

        res = parse_naver_ohlcv(
            payload,
            instrument_id="KRX:005930",
            analysis_as_of=as_of,
            adjustment_verified=False,
            adjustment_receipt=None
        )

        # is_usable is False due to UNVERIFIED_ADJUSTMENT
        self.assertFalse(res.is_usable)
        self.assertIsNone(res.bar_set)

        # Raw bars are still accessible for inspection
        self.assertEqual(len(res.bars), 1)
        self.assertEqual(res.bars[0].adjustment_mode.name, "RAW")

if __name__ == "__main__":
    unittest.main()
