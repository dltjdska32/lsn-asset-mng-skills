"""Unit tests for PublicAvailability, point-in-time cutoff rules, and RunContext."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_stack.contracts.context import (
    PinnedPersonalState,
    PublicAvailability,
    PublicAvailabilityKind,
    RunContext,
)
from investment_stack.contracts.errors import (
    PointInTimeError,
    TimezoneValidationError,
)


class ContractContextTests(unittest.TestCase):
    def test_public_availability_exact(self) -> None:
        pub_time = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        avail = PublicAvailability.exact(pub_time, locator="sec:000123")
        self.assertEqual(avail.kind, PublicAvailabilityKind.EXACT)

        # Cutoff before public time -> False
        before_cutoff = datetime(2026, 9, 23, 8, 59, tzinfo=timezone.utc)
        self.assertFalse(avail.is_point_in_time_available(before_cutoff))

        # Cutoff at exact public time -> True
        exact_cutoff = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        self.assertTrue(avail.is_point_in_time_available(exact_cutoff))

        # Cutoff after public time -> True
        after_cutoff = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(avail.is_point_in_time_available(after_cutoff))

    def test_public_availability_date_interval_upper_bound(self) -> None:
        start = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 20, 23, 59, 59, tzinfo=timezone.utc)
        avail = PublicAvailability.date_interval(start, end, tz="UTC")

        # Before interval end -> False
        cutoff_during = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(avail.is_point_in_time_available(cutoff_during))

        # At/After interval end -> True
        cutoff_after = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(avail.is_point_in_time_available(cutoff_after))

    def test_public_availability_date_interval_invalid_range(self) -> None:
        start = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(PointInTimeError):
            PublicAvailability.date_interval(start, end)

    def test_public_availability_unknown_never_point_in_time_eligible(self) -> None:
        avail = PublicAvailability.unknown(locator="unverified_source")
        cutoff = datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(avail.is_point_in_time_available(cutoff))

        with self.assertRaises(PointInTimeError):
            PublicAvailability(
                kind=PublicAvailabilityKind.UNKNOWN,
                public_available_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

    def test_naive_datetime_rejection(self) -> None:
        naive = datetime(2026, 9, 23, 9, 0)
        with self.assertRaises(TimezoneValidationError):
            PublicAvailability.exact(naive, locator="test_source")

        aware = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        avail = PublicAvailability.exact(aware, locator="test_source")
        with self.assertRaises(TimezoneValidationError):
            avail.is_point_in_time_available(naive)

    def test_run_context_validation(self) -> None:
        as_of = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        ctx = RunContext(
            run_id="run-001",
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of=as_of,
            analysis_timezone="Asia/Seoul",
            pinned_personal_state=PinnedPersonalState(state_version=1),
        )
        self.assertEqual(ctx.run_id, "run-001")
        self.assertEqual(ctx.analysis_timezone, "Asia/Seoul")

        avail = PublicAvailability.exact(datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc), locator="test_source")
        self.assertTrue(ctx.is_public_data_available(avail))

    def test_run_context_invalid_timezone_and_naive(self) -> None:
        naive = datetime(2026, 9, 23, 9, 0)
        with self.assertRaises(TimezoneValidationError):
            RunContext(
                run_id="run-001",
                request_mode="SINGLE_ASSET_ANALYSIS",
                analysis_as_of=naive,
                analysis_timezone="UTC",
            )

        aware = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        with self.assertRaises(TimezoneValidationError):
            RunContext(
                run_id="run-001",
                request_mode="SINGLE_ASSET_ANALYSIS",
                analysis_as_of=aware,
                analysis_timezone="Invalid/Timezone_Name",
            )

    def test_public_availability_from_source_date_with_dst(self) -> None:
        # In US/Eastern, 2026-03-08 is the spring forward DST transition day (23 hours long)
        avail = PublicAvailability.from_source_date("2026-03-08", tz="America/New_York", locator="sec:filing")
        self.assertEqual(avail.kind, PublicAvailabilityKind.DATE_INTERVAL)
        self.assertIsNotNone(avail.interval_start)
        self.assertIsNotNone(avail.interval_end)

        # Difference between interval_end and interval_start should be exactly 23 hours across DST spring forward
        diff_hours = (avail.interval_end - avail.interval_start).total_seconds() / 3600.0
        self.assertEqual(diff_hours, 23.0)

        # Before interval_end UTC, point-in-time check is False
        before_end = datetime(2026, 3, 9, 3, 59, tzinfo=timezone.utc)
        self.assertFalse(avail.is_point_in_time_available(before_end))

        # At/After interval_end UTC, point-in-time check is True
        at_end = datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc)
        self.assertTrue(avail.is_point_in_time_available(at_end))


if __name__ == "__main__":
    unittest.main()
