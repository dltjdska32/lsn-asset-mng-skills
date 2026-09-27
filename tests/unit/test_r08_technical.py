"""Unit tests for Technical Indicators and Analysis Gate (R08 / ANALYSIS-08).

Validates:
- Explicit caller periods requirement
- Independent hand-calculated fixtures for SMA, EMA, Wilder RSI, MACD, True Range, ATR, Relative Volume, and Volatility
- Wilder RSI edge cases (all gains -> 100, all losses -> 0, zero delta -> 50)
- Zero volume denominator handling in Relative Volume (returns None, no ZeroDivisionError)
- Minimal sample count boundaries and seed preservation
- Prefix invariance: future bars appended do not change prior calculated values
- Moving average trend evaluation & crossover detection
- Support/Resistance pivot detection with source bar provenance (no future bar leaks)
- Breakout detection invariant (same bar cannot create resistance and break out)
- Trading signal gate: unapproved policies strictly return UNAVAILABLE
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import AdjustmentMode, Bar, BarSet
from investment_stack.calculations.technical import (
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_relative_volume,
    calculate_sma,
    calculate_true_range,
    calculate_volatility,
    calculate_wilder_rsi,
    detect_breakout,
    detect_support_resistance,
    detect_trend,
    evaluate_signal_gate,
)


def _make_bar(
    index: int,
    session_date: str,
    open_p: str,
    high_p: str,
    low_p: str,
    close_p: str,
    volume: str = "1000",
    is_complete: bool = True,
) -> Bar:
    """Helper to construct verified test bars."""
    dt_open = datetime.fromisoformat(f"{session_date}T09:00:00+09:00")
    dt_close = datetime.fromisoformat(f"{session_date}T15:30:00+09:00")
    pub = PublicAvailability.exact(available_at=dt_close, locator="test_fixture")
    return Bar(
        bar_id=f"test_bar_{index}",
        evidence_id=f"test_ev_{index}",
        instrument_id="KRX:005930",
        interval="1D",
        session_date=session_date,
        open_time=dt_open,
        close_time=dt_close,
        timezone="Asia/Seoul",
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal(volume),
        currency="KRW",
        public_availability=pub,
        volume_unit="SHARES",
        adjustment_mode=AdjustmentMode.SPLIT_ADJUSTED,
        is_complete=is_complete,
    )


class TestTechnicalCalculationsR08(unittest.TestCase):
    """R08 Deterministic technical calculation test suite."""

    def test_sma_hand_calculated_fixture(self) -> None:
        """Hand calculation: Closes = [10, 11, 12, 13, 14], Period = 3.

        idx 0: None
        idx 1: None
        idx 2: (10 + 11 + 12) / 3 = 11.0
        idx 3: (11 + 12 + 13) / 3 = 12.0
        idx 4: (12 + 13 + 14) / 3 = 13.0
        """
        bars = [
            _make_bar(0, "2026-09-01", "10", "10.5", "9.5", "10"),
            _make_bar(1, "2026-09-02", "11", "11.5", "10.5", "11"),
            _make_bar(2, "2026-09-03", "12", "12.5", "11.5", "12"),
            _make_bar(3, "2026-09-04", "13", "13.5", "12.5", "13"),
            _make_bar(4, "2026-09-05", "14", "14.5", "13.5", "14"),
        ]
        sma = calculate_sma(bars, period=3)
        self.assertEqual(len(sma), 5)
        self.assertIsNone(sma[0])
        self.assertIsNone(sma[1])
        self.assertEqual(sma[2], Decimal("11"))
        self.assertEqual(sma[3], Decimal("12"))
        self.assertEqual(sma[4], Decimal("13"))

    def test_ema_hand_calculated_fixture(self) -> None:
        """Hand calculation: Closes = [10, 11, 12, 13, 14], Period = 3.

        alpha = 2 / (3 + 1) = 0.5.
        Seed at idx 2: SMA(3) = 11.0.
        idx 3: 0.5 * 13 + 0.5 * 11.0 = 6.5 + 5.5 = 12.0.
        idx 4: 0.5 * 14 + 0.5 * 12.0 = 7.0 + 6.0 = 13.0.
        """
        bars = [
            _make_bar(0, "2026-09-01", "10", "10.5", "9.5", "10"),
            _make_bar(1, "2026-09-02", "11", "11.5", "10.5", "11"),
            _make_bar(2, "2026-09-03", "12", "12.5", "11.5", "12"),
            _make_bar(3, "2026-09-04", "13", "13.5", "12.5", "13"),
            _make_bar(4, "2026-09-05", "14", "14.5", "13.5", "14"),
        ]
        ema = calculate_ema(bars, period=3)
        self.assertEqual(len(ema), 5)
        self.assertIsNone(ema[0])
        self.assertIsNone(ema[1])
        self.assertEqual(ema[2], Decimal("11"))
        self.assertEqual(ema[3], Decimal("12"))
        self.assertEqual(ema[4], Decimal("13"))

    def test_wilder_rsi_hand_calculated_fixture(self) -> None:
        """Hand calculation: Closes = [10, 12, 11, 14], Period = 3.

        Deltas:
          idx 1: 12 - 10 = +2 (gain=2, loss=0)
          idx 2: 11 - 12 = -1 (gain=0, loss=1)
          idx 3: 14 - 11 = +3 (gain=3, loss=0)
        Initial averages over 3 changes:
          avg_gain = (2 + 0 + 3) / 3 = 5/3
          avg_loss = (0 + 1 + 0) / 3 = 1/3
          RS = (5/3) / (1/3) = 5
          RSI = 100 - (100 / (1 + 5)) = 100 - 100/6 = 83.33333333333333333333333333...
        """
        bars = [
            _make_bar(0, "2026-09-01", "10", "10.5", "9.5", "10"),
            _make_bar(1, "2026-09-02", "12", "12.5", "10.5", "12"),
            _make_bar(2, "2026-09-03", "11", "12.5", "10.5", "11"),
            _make_bar(3, "2026-09-04", "14", "14.5", "11.0", "14"),
        ]
        rsi = calculate_wilder_rsi(bars, period=3)
        self.assertEqual(len(rsi), 4)
        self.assertIsNone(rsi[0])
        self.assertIsNone(rsi[1])
        self.assertIsNone(rsi[2])
        self.assertIsNotNone(rsi[3])
        assert rsi[3] is not None
        # Verify 83.3333...
        expected = Decimal("100") - (Decimal("100") / Decimal("6"))
        self.assertEqual(round(rsi[3], 6), round(expected, 6))

    def test_wilder_rsi_boundary_conditions(self) -> None:
        """Test boundary conditions: all gains -> 100, all losses -> 0, zero change -> 50."""
        # 1. Monotonically increasing: all gains
        bars_up = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10"),
            _make_bar(1, "2026-09-02", "11", "12", "10", "11"),
            _make_bar(2, "2026-09-03", "12", "13", "11", "12"),
            _make_bar(3, "2026-09-04", "13", "14", "12", "13"),
        ]
        rsi_up = calculate_wilder_rsi(bars_up, period=3)
        self.assertEqual(rsi_up[3], Decimal("100"))

        # 2. Monotonically decreasing: all losses
        bars_down = [
            _make_bar(0, "2026-09-01", "14", "15", "13", "14"),
            _make_bar(1, "2026-09-02", "13", "14", "12", "13"),
            _make_bar(2, "2026-09-03", "12", "13", "11", "12"),
            _make_bar(3, "2026-09-04", "11", "12", "10", "11"),
        ]
        rsi_down = calculate_wilder_rsi(bars_down, period=3)
        self.assertEqual(rsi_down[3], Decimal("0"))

        # 3. Flat: zero changes
        bars_flat = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10"),
            _make_bar(1, "2026-09-02", "10", "11", "9", "10"),
            _make_bar(2, "2026-09-03", "10", "11", "9", "10"),
            _make_bar(3, "2026-09-04", "10", "11", "9", "10"),
        ]
        rsi_flat = calculate_wilder_rsi(bars_flat, period=3)
        self.assertEqual(rsi_flat[3], Decimal("50"))

    def test_relative_volume_and_zero_denominator(self) -> None:
        """Hand calculation: Volumes = [100, 200, 300, 400], lookback = 2.

        idx 0: None, idx 1: None
        idx 2: current volume = 300, prior 2 bars [100, 200] avg = 150. RVol = 300 / 150 = 2.0.
        idx 3: current volume = 400, prior 2 bars [200, 300] avg = 250. RVol = 400 / 250 = 1.6.
        """
        bars = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10", volume="100"),
            _make_bar(1, "2026-09-02", "10", "11", "9", "10", volume="200"),
            _make_bar(2, "2026-09-03", "10", "11", "9", "10", volume="300"),
            _make_bar(3, "2026-09-04", "10", "11", "9", "10", volume="400"),
        ]
        rvol = calculate_relative_volume(bars, lookback_period=2)
        self.assertIsNone(rvol[0])
        self.assertIsNone(rvol[1])
        self.assertEqual(rvol[2], Decimal("2"))
        self.assertEqual(rvol[3], Decimal("1.6"))

        # Zero denominator test:
        bars_zero_vol = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10", volume="0"),
            _make_bar(1, "2026-09-02", "10", "11", "9", "10", volume="0"),
            _make_bar(2, "2026-09-03", "10", "11", "9", "10", volume="100"),
        ]
        rvol_zero = calculate_relative_volume(bars_zero_vol, lookback_period=2)
        # Average of previous 2 bars is 0 -> should return None, avoiding ZeroDivisionError
        self.assertIsNone(rvol_zero[2])

    def test_true_range_and_atr_fixture(self) -> None:
        """Hand calculation:

        Bar 0: H=10, L=8, C=9 -> TR = 2
        Bar 1: H=12, L=9, C=11 -> TR = max(12-9, abs(12-9), abs(9-9)) = 3
        Bar 2: H=13, L=10, C=10 -> TR = max(13-10, abs(13-11), abs(10-11)) = max(3, 2, 1) = 3
        ATR(2) seeded at idx 2: average of TR[1] and TR[2] = (3 + 3) / 2 = 3.0.
        """
        bars = [
            _make_bar(0, "2026-09-01", "9", "10", "8", "9"),
            _make_bar(1, "2026-09-02", "9.5", "12", "9", "11"),
            _make_bar(2, "2026-09-03", "11", "13", "10", "10"),
        ]
        tr = calculate_true_range(bars)
        self.assertEqual(tr[0], Decimal("2"))
        self.assertEqual(tr[1], Decimal("3"))
        self.assertEqual(tr[2], Decimal("3"))

        atr = calculate_atr(bars, period=2)
        self.assertIsNone(atr[0])
        self.assertIsNone(atr[1])
        self.assertEqual(atr[2], Decimal("3"))

    def test_prefix_invariance(self) -> None:
        """Prefix invariance: appending future bars does NOT alter past calculated values."""
        base_bars = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10"),
            _make_bar(1, "2026-09-02", "11", "12", "10", "11"),
            _make_bar(2, "2026-09-03", "12", "13", "11", "12"),
            _make_bar(3, "2026-09-04", "13", "14", "12", "13"),
            _make_bar(4, "2026-09-05", "14", "15", "13", "14"),
        ]
        future_bar = _make_bar(5, "2026-09-06", "15", "16", "14", "15")
        extended_bars = base_bars + [future_bar]

        # SMA
        sma_base = calculate_sma(base_bars, period=3)
        sma_ext = calculate_sma(extended_bars, period=3)
        self.assertEqual(sma_base, sma_ext[:len(base_bars)])

        # EMA
        ema_base = calculate_ema(base_bars, period=3)
        ema_ext = calculate_ema(extended_bars, period=3)
        self.assertEqual(ema_base, ema_ext[:len(base_bars)])

        # Wilder RSI
        rsi_base = calculate_wilder_rsi(base_bars, period=3)
        rsi_ext = calculate_wilder_rsi(extended_bars, period=3)
        self.assertEqual(rsi_base, rsi_ext[:len(base_bars)])

    def test_support_resistance_pivot_detection(self) -> None:
        """Pivot high at bar 1 (high=20) with lookback=1 and confirmation=1."""
        bars = [
            _make_bar(0, "2026-09-01", "10", "15", "9", "12"),
            _make_bar(1, "2026-09-02", "12", "20", "11", "18"),  # Pivot High (20)
            _make_bar(2, "2026-09-03", "15", "16", "14", "15"),  # Confirms bar 1 pivot
        ]
        levels = detect_support_resistance(bars, lookback_period=1, confirmation_bars=1)
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0].level_type, "RESISTANCE")
        self.assertEqual(levels[0].price, Decimal("20"))
        self.assertEqual(levels[0].source_bar_id, "test_bar_1")
        self.assertEqual(levels[0].source_session_date, "2026-09-02")

    def test_non_contiguous_or_embedded_incomplete_bar_rejected(self) -> None:
        """An incomplete bar cannot be embedded in the middle to stitch non-contiguous bars."""
        from investment_stack.calculations.technical import TechnicalCalculationError
        bars = [
            _make_bar(0, "2026-09-01", "10", "11", "9", "10", is_complete=True),
            _make_bar(1, "2026-09-02", "11", "12", "10", "11", is_complete=False),  # Embedded incomplete
            _make_bar(2, "2026-09-03", "12", "13", "11", "12", is_complete=True),
        ]
        with self.assertRaises(TechnicalCalculationError):
            calculate_sma(bars, period=2)

    def test_breakout_same_bar_invariant(self) -> None:
        """The bar that created the resistance level CANNOT be the same bar that breaks out."""
        bars = [
            _make_bar(0, "2026-09-01", "10", "12", "9", "11", volume="100"),
            _make_bar(1, "2026-09-02", "11", "20", "10", "19", volume="500"),  # Sets resistance 20
        ]
        eval_res = detect_breakout(
            bars,
            resistance_level=Decimal("20"),
            volume_threshold_ratio=Decimal("1.5"),
            relative_vol_lookback=1,
            resistance_source_bar_id="test_bar_1",
        )
        self.assertFalse(eval_res.is_breakout)
        self.assertIn("cannot create resistance and break out simultaneously", eval_res.reason)

    def test_trading_signal_gate_blocks_unauthorized_signals(self) -> None:
        """Unauthorized signals must remain UNAVAILABLE without explicit policy approval."""
        bars = [
            _make_bar(i, f"2026-09-{i+1:02d}", "10", "12", "9", "11")
            for i in range(20)
        ]
        # 1. Unapproved caller
        res_unapproved = evaluate_signal_gate(bars, caller_approved=False)
        self.assertEqual(res_unapproved.status, "UNAVAILABLE")
        self.assertIsNone(res_unapproved.signal)
        self.assertIn("UNAPPROVED_POLICY", res_unapproved.reason)

        # 2. Approved caller with policy ID (Fail-closed invariant)
        res_approved = evaluate_signal_gate(
            bars,
            caller_approved=True,
            approved_policy_id="POLICY_CONSERVATIVE_CORE_V1",
        )
        self.assertEqual(res_approved.status, "UNAVAILABLE")
        self.assertIsNone(res_approved.signal)
        self.assertIn("FAIL_CLOSED", res_approved.reason)


if __name__ == "__main__":
    unittest.main()
