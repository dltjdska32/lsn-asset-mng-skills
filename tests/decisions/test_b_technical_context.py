from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from investment_stack.calculations.technical import (
    TechnicalParameters,
    calculate_verified_technical_analysis,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import AdjustmentMode, Bar, BarSet
from investment_stack.decisions.technical_context import build_technical_briefing_context
from investment_stack.providers.ohlcv import OHLCVParseResult


def _fixture(*, future: bool = False, verified: bool = True) -> OHLCVParseResult:
    cutoff = datetime(2026, 9, 10, 23, tzinfo=timezone.utc)
    bars = []
    for i in range(6):
        day = datetime(2026, 9, 1, 9, tzinfo=timezone.utc) + timedelta(days=i)
        if future and i == 5:
            day = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)
        close_time = day + timedelta(hours=7)
        bar = Bar(
            bar_id=f"bar-{i}", evidence_id=f"evidence-{i}", instrument_id="TEST:ABC",
            interval="1D", session_date=day.date().isoformat(), open_time=day,
            close_time=close_time, timezone="UTC", open=Decimal("10"),
            high=Decimal("20"), low=Decimal("9"), close=Decimal(str(10 + i)),
            volume=Decimal("100"), currency="USD",
            public_availability=PublicAvailability.exact(close_time, locator=f"fixture-{i}"),
            adjustment_mode=AdjustmentMode.SPLIT_ADJUSTED,
        )
        bars.append(bar)
    bar_set = BarSet.create("TEST:ABC", "1D", "USD", AdjustmentMode.SPLIT_ADJUSTED, bars)
    return OHLCVParseResult(
        bar_set=bar_set, bars=tuple(bars), adjustment_verified=verified,
        source_url="https://example.test/ohlcv", adjustment_receipt="adjustment-v1",
        calendar_receipt="calendar-v1", expected_session_dates=tuple(b.session_date for b in bars),
        analysis_as_of=cutoff,
    )


PARAMS = TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2)


class TestTechnicalBriefingContext(unittest.TestCase):
    def test_context_carries_verified_lineage_and_indicator_values(self):
        parsed = _fixture()
        result = calculate_verified_technical_analysis(parsed, PARAMS)
        context = build_technical_briefing_context(parsed, result)
        self.assertEqual(context.status, "PARTIAL")
        self.assertIn("INSUFFICIENT_LOOKBACK_FOR_SOME_INDICATORS", context.reasons)
        self.assertEqual(context.last_session_date, "2026-09-06")
        self.assertEqual(context.source_url, parsed.source_url)
        self.assertEqual(context.validation_receipt_id, result.validation_receipt_id)
        self.assertEqual(context.input_fingerprint, result.input_fingerprint)
        self.assertEqual(context.evidence_ids, tuple(f"evidence-{i}" for i in range(6)))
        self.assertEqual(context.indicator("sma"), Decimal("14.5"))
        self.assertEqual(context.signal_status, "UNAVAILABLE")

    def test_unverified_source_is_rejected(self):
        parsed = _fixture(verified=False)
        result = calculate_verified_technical_analysis(parsed, PARAMS)
        context = build_technical_briefing_context(parsed, result)
        self.assertEqual(context.status, "UNAVAILABLE")
        self.assertIn("OHLCV_PARSE_NOT_ANALYSIS_ELIGIBLE", context.reasons)
        self.assertFalse(context.evidence_ids)

    def test_future_close_is_rejected_even_if_parse_claims_eligible(self):
        parsed = _fixture(future=True)
        self.assertTrue(parsed.analysis_eligible)
        result = calculate_verified_technical_analysis(parsed, PARAMS)
        context = build_technical_briefing_context(parsed, result)
        self.assertEqual(context.status, "UNAVAILABLE")
        self.assertIn("FUTURE_OR_INCOMPLETE_BAR_REJECTED", context.reasons)

    def test_result_with_matching_identity_but_wrong_fingerprint_is_rejected(self):
        parsed = _fixture()
        result = calculate_verified_technical_analysis(parsed, PARAMS)
        context = build_technical_briefing_context(parsed, replace(result, input_fingerprint="wrong"))
        self.assertEqual(context.status, "UNAVAILABLE")
        self.assertIn("TECHNICAL_RESULT_PROVENANCE_MISMATCH", context.reasons)

    def test_result_with_forged_indicator_value_is_rejected(self):
        parsed = _fixture()
        result = calculate_verified_technical_analysis(parsed, PARAMS)
        forged_latest = replace(result.points[-1], sma=Decimal("999999"))
        forged = replace(result, points=result.points[:-1] + (forged_latest,))
        context = build_technical_briefing_context(parsed, forged)
        self.assertEqual(context.status, "UNAVAILABLE")
        self.assertIn("TECHNICAL_VALUES_DO_NOT_MATCH_VERIFIED_INPUT", context.reasons)


if __name__ == "__main__":
    unittest.main()
