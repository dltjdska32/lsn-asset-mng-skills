from decimal import Decimal
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from investment_stack.calculations.technical import TechnicalParameters, calculate_verified_technical_analysis
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import AdjustmentMode, Bar, BarSet
from investment_stack.decisions.technical_storage import register_technical_bar_set
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.providers.ohlcv import OHLCVParseResult
from investment_stack.reporting.models import Availability
from investment_stack.reporting.technical_section import build_technical_report_section


def _parse_result() -> OHLCVParseResult:
    cutoff = datetime(2026, 9, 10, 23, tzinfo=timezone.utc)
    bars = []
    for i in range(6):
        day = datetime(2026, 9, 1, 9, tzinfo=timezone.utc) + timedelta(days=i)
        close_time = day + timedelta(hours=7)
        bars.append(Bar(
            bar_id=f"bar-{i}", evidence_id=f"evidence-{i}", instrument_id="TEST:ABC",
            interval="1D", session_date=day.date().isoformat(), open_time=day,
            close_time=close_time, timezone="UTC", open=Decimal("10"),
            high=Decimal("20"), low=Decimal("9"), close=Decimal(str(10 + i)),
            volume=Decimal("100"), currency="USD",
            public_availability=PublicAvailability.exact(close_time, locator=f"fixture-{i}"),
            adjustment_mode=AdjustmentMode.SPLIT_ADJUSTED,
        ))
    bar_set = BarSet.create("TEST:ABC", "1D", "USD", AdjustmentMode.SPLIT_ADJUSTED, bars)
    return OHLCVParseResult(
        bar_set=bar_set, bars=tuple(bars), adjustment_verified=True,
        source_url="https://example.test/ohlcv", adjustment_receipt="caller-adjustment-attestation",
        calendar_receipt="caller-calendar-attestation", expected_session_dates=tuple(b.session_date for b in bars),
        analysis_as_of=cutoff,
    )


class TestTechnicalReportSection(unittest.TestCase):
    def test_withholds_values_without_trusted_run_binding(self):
        parsed = _parse_result()
        result = calculate_verified_technical_analysis(
            parsed, TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2),
        )
        section = build_technical_report_section(
            parse_result=parsed, analysis=result, expected_instrument_id="TEST:ABC",
        )
        self.assertEqual(section.status, Availability.UNAVAILABLE)
        self.assertEqual(section.evidence_ids, ())
        self.assertEqual(section.metadata["signal_status"], "UNAVAILABLE")
        self.assertIn("RUN_DATABASE_BINDING_UNVERIFIED", section.metadata["reason_codes"])
        self.assertNotIn("2026-09-06", "\n".join(section.lines))
        self.assertNotIn("https://example.test/ohlcv", "\n".join(section.lines))
        self.assertNotIn("370800초", "\n".join(section.lines))

    def test_instrument_mismatch_and_missing_context_fail_closed(self):
        parsed = _parse_result()
        result = calculate_verified_technical_analysis(
            parsed, TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2),
        )
        mismatch = build_technical_report_section(
            parse_result=parsed, analysis=result, expected_instrument_id="NYSE:OTHER"
        )
        missing = build_technical_report_section(
            parse_result=None, analysis=None, expected_instrument_id="NASDAQ:TEST",
        )
        self.assertIn("TECHNICAL_CONTEXT_INSTRUMENT_MISMATCH", mismatch.metadata["reason_codes"])
        self.assertEqual(mismatch.status, Availability.UNAVAILABLE)
        self.assertIn("TECHNICAL_INPUTS_MISSING", missing.metadata["reason_codes"])
        self.assertIn("RUN_DATABASE_BINDING_UNVERIFIED", missing.metadata["reason_codes"])
        self.assertEqual(missing.status, Availability.UNAVAILABLE)

    def test_forged_analysis_value_or_metadata_is_revalidated_and_suppressed(self):
        parsed = _parse_result()
        result = calculate_verified_technical_analysis(
            parsed, TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2),
        )
        altered_point = replace(result.points[-1], sma=Decimal("999999"))
        forged_value = replace(result, points=result.points[:-1] + (altered_point,))
        forged_metadata = replace(result, reasons=("FORGED",))
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunDatabaseManager(tmp, "technical-forgery-test")
            self.assertTrue(manager.create().valid)
            manager.initialize_run_context(
                request_mode="single_asset_analysis",
                analysis_as_of=parsed.analysis_as_of.isoformat(), analysis_timezone="UTC",
            )
            self.assertIsNotNone(register_technical_bar_set(manager, parsed))
            for forged in (forged_value, forged_metadata):
                with self.subTest(forged=forged):
                    section = build_technical_report_section(
                        parse_result=parsed, analysis=forged, expected_instrument_id="TEST:ABC",
                        run_db=manager,
                    )
                    self.assertEqual(section.status, Availability.UNAVAILABLE)
                    self.assertEqual(section.evidence_ids, ())
                    self.assertTrue(section.metadata["indicator_values_withheld"])
                    self.assertNotIn("2026-09-06", "\n".join(section.lines))
                    self.assertNotIn("https://example.test/ohlcv", "\n".join(section.lines))
                    self.assertNotIn("370800초", "\n".join(section.lines))

    def test_registered_typed_bars_allow_only_exact_run_bound_values(self):
        parsed = _parse_result()
        params = TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2)
        result = calculate_verified_technical_analysis(parsed, params)
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunDatabaseManager(tmp, "technical-test-run")
            self.assertTrue(manager.create().valid)
            manager.initialize_run_context(
                request_mode="single_asset_analysis",
                analysis_as_of=parsed.analysis_as_of.isoformat(), analysis_timezone="UTC",
            )
            self.assertEqual(register_technical_bar_set(manager, parsed), tuple(f"evidence-{i}" for i in range(6)))
            section = build_technical_report_section(
                parse_result=parsed, analysis=result, expected_instrument_id="TEST:ABC", run_db=manager,
            )
            self.assertEqual(section.status, Availability.PARTIAL)
            self.assertEqual(section.evidence_ids, tuple(f"evidence-{i}" for i in range(6)))
            self.assertFalse(section.metadata["indicator_values_withheld"])
            self.assertIn("단순이동평균(SMA): 14.5", "\n".join(section.lines))
            self.assertEqual(section.metadata["run_id"], manager.run_id)
            detail = section.metadata["calculation_detail"]
            self.assertEqual(detail["formula_version"], result.formula_version)
            self.assertEqual(detail["indicator_periods"]["sma"], params.sma_period)
            self.assertEqual(detail["indicator_periods"]["macd"], {
                "fast": params.macd_fast, "slow": params.macd_slow,
                "signal": params.macd_signal,
            })

    def test_different_registered_input_and_run_cutoff_do_not_bind(self):
        parsed = _parse_result()
        params = TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2)
        result = calculate_verified_technical_analysis(parsed, params)
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunDatabaseManager(tmp, "technical-cutoff-test")
            self.assertTrue(manager.create().valid)
            manager.initialize_run_context(
                request_mode="single_asset_analysis",
                analysis_as_of="2026-09-11T00:00:00+00:00", analysis_timezone="UTC",
            )
            self.assertIsNone(register_technical_bar_set(manager, parsed))
            section = build_technical_report_section(
                parse_result=parsed, analysis=result, expected_instrument_id="TEST:ABC", run_db=manager,
            )
            self.assertEqual(section.status, Availability.UNAVAILABLE)
            self.assertEqual(section.evidence_ids, ())
            self.assertIn("RUN_DATABASE_BINDING_UNVERIFIED", section.metadata["reason_codes"])

    def test_registered_bar_hash_mismatch_withholds_values_and_evidence_ids(self):
        original = _parse_result()
        params = TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2)
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunDatabaseManager(tmp, "technical-content-test")
            self.assertTrue(manager.create().valid)
            manager.initialize_run_context(
                request_mode="single_asset_analysis",
                analysis_as_of=original.analysis_as_of.isoformat(), analysis_timezone="UTC",
            )
            self.assertIsNotNone(register_technical_bar_set(manager, original))
            changed_bars = original.bar_set.bars[:-1] + (
                replace(original.bar_set.bars[-1], close=Decimal("15.5")),
            )
            changed_set = BarSet.create(
                original.bar_set.instrument_id, original.bar_set.interval,
                original.bar_set.currency, original.bar_set.adjustment_mode, changed_bars,
            )
            changed = replace(original, bar_set=changed_set, bars=changed_bars)
            changed_result = calculate_verified_technical_analysis(changed, params)
            section = build_technical_report_section(
                parse_result=changed, analysis=changed_result,
                expected_instrument_id="TEST:ABC", run_db=manager,
            )
            self.assertEqual(section.status, Availability.UNAVAILABLE)
            self.assertEqual(section.evidence_ids, ())
            self.assertTrue(section.metadata["indicator_values_withheld"])
            self.assertIn("RUN_DATABASE_BINDING_UNVERIFIED", section.metadata["reason_codes"])

    def test_different_source_url_for_same_bars_is_not_bound(self):
        registered = _parse_result()
        params = TechnicalParameters(2, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2)
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunDatabaseManager(tmp, "technical-source-test")
            self.assertTrue(manager.create().valid)
            manager.initialize_run_context(
                request_mode="single_asset_analysis",
                analysis_as_of=registered.analysis_as_of.isoformat(), analysis_timezone="UTC",
            )
            self.assertIsNotNone(register_technical_bar_set(manager, registered))
            relabeled = replace(registered, source_url="https://forged.example/ohlcv")
            result = calculate_verified_technical_analysis(relabeled, params)
            section = build_technical_report_section(
                parse_result=relabeled, analysis=result, expected_instrument_id="TEST:ABC",
                run_db=manager,
            )
            self.assertEqual(section.status, Availability.UNAVAILABLE)
            self.assertEqual(section.evidence_ids, ())
            self.assertTrue(section.metadata["indicator_values_withheld"])
            self.assertNotIn("forged.example", "\n".join(section.lines))
            self.assertNotIn(registered.source_url, "\n".join(section.lines))
            self.assertIn("RUN_DATABASE_BINDING_UNVERIFIED", section.metadata["reason_codes"])


if __name__ == "__main__":
    unittest.main()
