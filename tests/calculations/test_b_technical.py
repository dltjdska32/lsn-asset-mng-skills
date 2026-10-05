import unittest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from investment_stack.contracts.market import Bar, PublicAvailability, AdjustmentMode, BarSet
from investment_stack.calculations.technical import (
    evaluate_signal_gate,
    detect_breakout,
    TechnicalCalculationError,
    _extract_bars
)

def _mock_bar(idx: int, close_px: float, is_complete: bool = True) -> Bar:
    dt = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=idx)
    return Bar(
        bar_id=f"b_{idx}",
        evidence_id=f"e_{idx}",
        instrument_id="TEST:1",
        interval="1D",
        session_date=dt.strftime("%Y-%m-%d"),
        open_time=dt,
        close_time=dt + timedelta(hours=8),
        timezone="UTC",
        open=Decimal(str(close_px)),
        high=Decimal(str(close_px + 1)),
        low=Decimal(str(close_px - 1)),
        close=Decimal(str(close_px)),
        volume=Decimal("1000"),
        currency="USD",
        public_availability=PublicAvailability.unknown(locator=None),
        volume_unit="SHARES",
        adjustment_mode=AdjustmentMode.SPLIT_ADJUSTED,
        is_complete=is_complete
    )

class TestBTechnical(unittest.TestCase):
    def test_signal_gate_unapproved(self):
        """Verify that trading signals remain UNAVAILABLE without explicit approval."""
        bars = [_mock_bar(i, 100 + i) for i in range(20)]

        # We did not pass caller_approved=True or a policy ID
        res = evaluate_signal_gate(bars, caller_approved=False, approved_policy_id=None)

        self.assertEqual(res.status, "UNAVAILABLE")
        self.assertIsNone(res.signal)
        self.assertIn("UNAPPROVED_POLICY", res.reason)

    def test_signal_gate_fail_closed(self):
        """Verify that even with external approval strings, signals remain UNAVAILABLE (fail-closed)."""
        bars = [_mock_bar(i, 100 + i) for i in range(20)]

        res = evaluate_signal_gate(bars, caller_approved=True, approved_policy_id="POLICY_123")

        self.assertEqual(res.status, "UNAVAILABLE")
        self.assertIsNone(res.signal)
        self.assertIn("FAIL_CLOSED", res.reason)

    def test_extract_bars_rejects_embedded_incomplete(self):
        """Verify embedded incomplete bars cause an error, but trailing is dropped."""
        # Trailing incomplete bar is gracefully dropped
        b1 = _mock_bar(1, 100, is_complete=True)
        b2 = _mock_bar(2, 101, is_complete=False) # Trailing

        extracted = _extract_bars([b1, b2])
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].bar_id, "b_1")

        # Embedded incomplete bar raises error
        b3 = _mock_bar(3, 102, is_complete=True)
        with self.assertRaises(TechnicalCalculationError):
            _extract_bars([b1, b2, b3])

    def test_detect_breakout_same_bar_rejection(self):
        """A single bar cannot be both the resistance origin and the breakout bar."""
        bars = [_mock_bar(i, 100 + i) for i in range(5)]
        latest_bar = bars[-1]

        res = detect_breakout(
            bars,
            resistance_level=Decimal("103"),
            volume_threshold_ratio=Decimal("1.0"),
            relative_vol_lookback=2,
            resistance_source_bar_id=latest_bar.bar_id # Same bar ID
        )

        self.assertFalse(res.is_breakout)
        self.assertEqual(res.breakout_type, "NONE")
        self.assertIn("same bar cannot create resistance", res.reason)

if __name__ == "__main__":
    unittest.main()
