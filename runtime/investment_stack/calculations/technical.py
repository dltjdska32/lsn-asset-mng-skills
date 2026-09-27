"""Technical indicators, price analysis, and trading signal gate.

Implements REQ-2026-09-23-v1 R08 and DESIGN-2026-09-23-v0.1 §4 R08.
Provides deterministic Decimal calculations for SMA, EMA, Wilder RSI, MACD,
True Range, ATR, Relative Volume, and Volatility with explicit caller periods.

Includes trend analysis, pivot support/resistance, breakout detection without
future bar leak, prefix invariance, and strict signal gating preventing unauthorized
trading signals without approved policy thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
import math
from typing import Any, Sequence

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.market import Bar, BarSet


ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
FIFTY = Decimal("50")
HUNDRED = Decimal("100")


class TechnicalCalculationError(Exception):
    """Base exception for technical calculation errors."""


class InsufficientBarsError(TechnicalCalculationError):
    """Raised when bar count is insufficient for the requested period."""


@dataclass(frozen=True, slots=True)
class MacdPoint:
    """Represents a single calculated MACD point."""

    macd: Decimal | None
    signal: Decimal | None
    histogram: Decimal | None


@dataclass(frozen=True, slots=True)
class TrendEvaluation:
    """Deterministic price trend analysis based on completed moving averages."""

    price_vs_fast: str  # ABOVE, BELOW, EQUAL, UNAVAILABLE
    price_vs_slow: str  # ABOVE, BELOW, EQUAL, UNAVAILABLE
    fast_slope: str     # RISING, FALLING, FLAT, UNAVAILABLE
    crossover: str      # GOLDEN_CROSS, DEATH_CROSS, NONE, UNAVAILABLE
    fast_period: int
    slow_period: int
    latest_close: Decimal
    fast_ma: Decimal | None
    slow_ma: Decimal | None


@dataclass(frozen=True, slots=True)
class SupportResistanceLevel:
    """A verified support or resistance level with source bar provenance."""

    level_type: str  # SUPPORT or RESISTANCE
    price: Decimal
    source_bar_id: str
    source_session_date: str
    lookback_window: int
    confirmed: bool


@dataclass(frozen=True, slots=True)
class BreakoutEvaluation:
    """Deterministic breakout detection against prior resistance with volume confirmation."""

    is_breakout: bool
    breakout_type: str  # BULLISH_BREAKOUT, BEARISH_BREAKDOWN, NONE, UNAVAILABLE
    target_level: Decimal | None
    latest_close: Decimal
    latest_volume: Decimal
    relative_volume: Decimal | None
    resistance_bar_id: str | None
    breakout_bar_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class TradingSignalResult:
    """Gated trading signal container.

    Enforces that without an approved risk/signal policy, signals remain UNAVAILABLE.
    """

    status: str  # AVAILABLE, UNAVAILABLE, DISABLED
    signal: str | None  # None if unapproved
    reason: str
    approved_policy_id: str | None = None
    indicator_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TechnicalParameters:
    sma_period: int
    ema_period: int
    rsi_period: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    relative_volume_period: int
    volatility_period: int
    atr_period: int
    trend_fast: int
    trend_slow: int


@dataclass(frozen=True, slots=True)
class TechnicalPoint:
    bar_id: str
    evidence_id: str
    session_date: str
    sma: Decimal | None
    ema: Decimal | None
    rsi: Decimal | None
    macd: MacdPoint | None
    relative_volume: Decimal | None
    volatility: Decimal | None
    atr: Decimal | None


@dataclass(frozen=True, slots=True)
class TechnicalAnalysisResult:
    status: str
    points: tuple[TechnicalPoint, ...]
    source_url: str | None
    input_fingerprint: str | None
    validation_receipt_id: str | None
    formula_version: str
    signal_status: str
    trend: TrendEvaluation | None = None
    reasons: tuple[str, ...] = ()


def calculate_verified_technical_analysis(parse_result: Any, params: TechnicalParameters) -> TechnicalAnalysisResult:
    """Calculate indicators only from an OHLCV parse result with complete source/calendar lineage."""
    if not getattr(parse_result, "analysis_eligible", False):
        return TechnicalAnalysisResult("UNAVAILABLE", (), getattr(parse_result, "source_url", None), None,
                                       None, "R08-v1", "UNAVAILABLE", None,
                                       ("OHLCV_PROVENANCE_OR_COMPLETENESS_NOT_VERIFIED",))
    bar_set = parse_result.bar_set
    bars = _extract_bars(bar_set)
    series = (
        calculate_sma(bars, params.sma_period), calculate_ema(bars, params.ema_period),
        calculate_wilder_rsi(bars, params.rsi_period), calculate_macd(bars, params.macd_fast, params.macd_slow, params.macd_signal),
        calculate_relative_volume(bars, params.relative_volume_period), calculate_volatility(bars, params.volatility_period),
        calculate_atr(bars, params.atr_period),
    )
    points = tuple(TechnicalPoint(b.bar_id, b.evidence_id, b.session_date, *(s[i] for s in series)) for i, b in enumerate(bars))
    complete = bool(points) and all(p.sma is not None and p.ema is not None and p.rsi is not None and p.macd is not None
                                    and p.macd.signal is not None and p.relative_volume is not None
                                    and p.volatility is not None and p.atr is not None for p in points)
    trend = detect_trend(bars, params.trend_fast, params.trend_slow)
    return TechnicalAnalysisResult("AVAILABLE" if complete else "PARTIAL", points, parse_result.source_url,
                                   _bar_fingerprint(bars), _validation_receipt_id(parse_result), "R08-v1",
                                   "UNAVAILABLE", trend,
                                   () if complete else ("INSUFFICIENT_LOOKBACK_FOR_SOME_INDICATORS",))


def _bar_fingerprint(bars: Sequence[Bar]) -> str:
    import hashlib, json
    payload = json.dumps([(b.bar_id, b.evidence_id, b.session_date, str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume)) for b in bars], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _validation_receipt_id(parse_result: Any) -> str:
    import hashlib
    return hashlib.sha256((str(parse_result.source_url) + str(parse_result.adjustment_receipt) + str(parse_result.calendar_receipt)
                           + _bar_fingerprint(parse_result.bar_set.bars)).encode()).hexdigest()


def _extract_bars(bars_or_set: BarSet | Sequence[Bar]) -> tuple[Bar, ...]:
    """Extract and validate completed, contiguous bars from input.

    Invariants:
    1. Input must be BarSet or Sequence[Bar].
    2. Input must not contain duplicate session dates or out-of-order bars.
    3. Incomplete bars are not silently skipped to stitch non-contiguous bars together.
       An incomplete bar is only permitted as a trailing forming bar; embedded incomplete
       bars in the middle of a series will raise TechnicalCalculationError.
    4. Each bar must be an authentic Bar instance.
    """
    if isinstance(bars_or_set, BarSet):
        raw_bars = bars_or_set.bars
    elif isinstance(bars_or_set, (list, tuple)):
        raw_bars = tuple(bars_or_set)
    else:
        raise TypeError(f"Expected BarSet or Sequence[Bar], got {type(bars_or_set).__name__}")

    if not raw_bars:
        return ()

    prev_time = None
    seen_dates: set[str] = set()
    completed: list[Bar] = []

    for idx, b in enumerate(raw_bars):
        if not isinstance(b, Bar):
            raise TypeError(f"Element at index {idx} is not a Bar instance: {type(b).__name__}")

        if b.session_date in seen_dates:
            raise TechnicalCalculationError(
                f"Duplicate session date '{b.session_date}' detected in bar sequence at index {idx}"
            )
        seen_dates.add(b.session_date)

        if prev_time is not None and b.open_time <= prev_time:
            raise TechnicalCalculationError(
                f"Bars must be strictly chronological: bar at {b.open_time} <= previous {prev_time}"
            )
        prev_time = b.open_time

        if b.is_complete:
            completed.append(b)
        else:
            if idx < len(raw_bars) - 1:
                raise TechnicalCalculationError(
                    f"Incomplete bar found at non-terminal index {idx} ({b.session_date}). Cannot stitch non-contiguous series."
                )

    return tuple(completed)


# -------------------------------------------------------------------------
# Core Indicators (Explicit Caller Periods Only)
# -------------------------------------------------------------------------

def calculate_sma(bars_or_set: BarSet | Sequence[Bar], period: int) -> tuple[Decimal | None, ...]:
    """Calculate Simple Moving Average (SMA).

    Formula: Sum of n completed closes / n.
    Indices < period - 1 return None.
    Prefix invariance: Appending new bars does not alter prior indices.
    """
    if period <= 0:
        raise ValueError(f"period must be strictly positive, got {period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n < period:
        return tuple(result)

    dec_period = Decimal(str(period))
    running_sum = Decimal("0")

    for i in range(period):
        running_sum += bars[i].close

    result[period - 1] = running_sum / dec_period

    for i in range(period, n):
        running_sum += bars[i].close - bars[i - period].close
        result[i] = running_sum / dec_period

    return tuple(result)


def calculate_ema(bars_or_set: BarSet | Sequence[Bar], period: int) -> tuple[Decimal | None, ...]:
    """Calculate Exponential Moving Average (EMA).

    Formula: alpha = 2 / (period + 1).
    Seed: First valid EMA at index period - 1, seeded by SMA of first period bars.
    Subsequent: alpha * C_i + (1 - alpha) * prev_EMA.
    """
    if period <= 0:
        raise ValueError(f"period must be strictly positive, got {period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n < period:
        return tuple(result)

    dec_period = Decimal(str(period))
    alpha = TWO / (dec_period + ONE)
    one_minus_alpha = ONE - alpha

    # Seed with SMA of first period bars
    sma_seed = sum(bars[i].close for i in range(period)) / dec_period
    result[period - 1] = sma_seed
    prev_ema = sma_seed

    for i in range(period, n):
        current_ema = (alpha * bars[i].close) + (one_minus_alpha * prev_ema)
        result[i] = current_ema
        prev_ema = current_ema

    return tuple(result)


def calculate_wilder_rsi(bars_or_set: BarSet | Sequence[Bar], period: int) -> tuple[Decimal | None, ...]:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing.

    First valid value at index period (needs period + 1 bars: 0 to period).
    Boundary rules:
      avg_loss == 0 and avg_gain > 0 -> 100
      avg_gain == 0 and avg_loss > 0 -> 0
      avg_gain == 0 and avg_loss == 0 -> 50
    """
    if period <= 0:
        raise ValueError(f"period must be strictly positive, got {period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n <= period:
        return tuple(result)

    dec_period = Decimal(str(period))

    # Calculate initial deltas for first period
    sum_gain = Decimal("0")
    sum_loss = Decimal("0")
    for i in range(1, period + 1):
        delta = bars[i].close - bars[i - 1].close
        if delta > ZERO:
            sum_gain += delta
        elif delta < ZERO:
            sum_loss += (-delta)

    avg_gain = sum_gain / dec_period
    avg_loss = sum_loss / dec_period

    def _compute_rsi(gain: Decimal, loss: Decimal) -> Decimal:
        if loss == ZERO and gain > ZERO:
            return HUNDRED
        if gain == ZERO and loss > ZERO:
            return ZERO
        if gain == ZERO and loss == ZERO:
            return FIFTY
        rs = gain / loss
        return HUNDRED - (HUNDRED / (ONE + rs))

    result[period] = _compute_rsi(avg_gain, avg_loss)

    for i in range(period + 1, n):
        delta = bars[i].close - bars[i - 1].close
        current_gain = delta if delta > ZERO else ZERO
        current_loss = -delta if delta < ZERO else ZERO

        avg_gain = ((avg_gain * (dec_period - ONE)) + current_gain) / dec_period
        avg_loss = ((avg_loss * (dec_period - ONE)) + current_loss) / dec_period
        result[i] = _compute_rsi(avg_gain, avg_loss)

    return tuple(result)


def calculate_macd(
    bars_or_set: BarSet | Sequence[Bar],
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> tuple[MacdPoint | None, ...]:
    """Calculate Moving Average Convergence Divergence (MACD).

    Invariant: fast_period < slow_period.
    macd_line = EMA(fast) - EMA(slow).
    signal_line = EMA(macd_line, signal_period), seeded by SMA of first signal_period MACDs.
    histogram = macd_line - signal_line.
    """
    if fast_period >= slow_period:
        raise ValueError(
            f"fast_period ({fast_period}) must be strictly less than slow_period ({slow_period})"
        )
    if fast_period <= 0 or signal_period <= 0:
        raise ValueError("Periods must be strictly positive integers")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[MacdPoint | None] = [None] * n

    fast_ema = calculate_ema(bars, fast_period)
    slow_ema = calculate_ema(bars, slow_period)

    # Compute MACD line
    macd_series: list[Decimal | None] = [None] * n
    valid_macd_indices: list[int] = []
    for i in range(n):
        f = fast_ema[i]
        s = slow_ema[i]
        if f is not None and s is not None:
            val = f - s
            macd_series[i] = val
            valid_macd_indices.append(i)

    # Need at least signal_period valid MACD values to compute signal line
    if len(valid_macd_indices) < signal_period:
        # Emit MACD points with None signal/histogram
        for i in valid_macd_indices:
            result[i] = MacdPoint(macd=macd_series[i], signal=None, histogram=None)
        return tuple(result)

    dec_signal_period = Decimal(str(signal_period))
    alpha_sig = TWO / (dec_signal_period + ONE)
    one_minus_alpha = ONE - alpha_sig

    # Seed signal line with SMA of first signal_period MACD values
    first_sig_idx = valid_macd_indices[signal_period - 1]
    sig_seed = sum(macd_series[valid_macd_indices[j]] for j in range(signal_period)) / dec_signal_period  # type: ignore

    prev_sig = sig_seed

    # Prior to signal seed
    for idx in valid_macd_indices[: signal_period - 1]:
        result[idx] = MacdPoint(macd=macd_series[idx], signal=None, histogram=None)

    result[first_sig_idx] = MacdPoint(
        macd=macd_series[first_sig_idx],
        signal=sig_seed,
        histogram=macd_series[first_sig_idx] - sig_seed,  # type: ignore
    )

    # Subsequent points
    for idx in valid_macd_indices[signal_period:]:
        cur_macd = macd_series[idx]
        assert cur_macd is not None
        cur_sig = (alpha_sig * cur_macd) + (one_minus_alpha * prev_sig)
        result[idx] = MacdPoint(
            macd=cur_macd,
            signal=cur_sig,
            histogram=cur_macd - cur_sig,
        )
        prev_sig = cur_sig

    return tuple(result)


def calculate_true_range(bars_or_set: BarSet | Sequence[Bar]) -> tuple[Decimal | None, ...]:
    """Calculate True Range (TR) for each bar.

    Bar 0: High - Low
    Bar i (i >= 1): max(High - Low, abs(High - prev_Close), abs(Low - prev_Close))
    """
    bars = _extract_bars(bars_or_set)
    n = len(bars)
    if n == 0:
        return ()

    result: list[Decimal | None] = [None] * n
    result[0] = bars[0].high - bars[0].low

    for i in range(1, n):
        hl = bars[i].high - bars[i].low
        hc = abs(bars[i].high - bars[i - 1].close)
        lc = abs(bars[i].low - bars[i - 1].close)
        result[i] = max(hl, hc, lc)

    return tuple(result)


def calculate_atr(bars_or_set: BarSet | Sequence[Bar], period: int) -> tuple[Decimal | None, ...]:
    """Calculate Average True Range (ATR) with Wilder's smoothing.

    First valid ATR at index period (needs period + 1 bars: 0 to period),
    seeded by SMA of first period True Ranges (from bar 1 to period).
    """
    if period <= 0:
        raise ValueError(f"period must be strictly positive, got {period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n <= period:
        return tuple(result)

    tr_series = calculate_true_range(bars)
    dec_period = Decimal(str(period))

    # Seed ATR at index period using average of TR from bar 1 to period
    sum_tr = sum(tr_series[i] for i in range(1, period + 1))  # type: ignore
    prev_atr = sum_tr / dec_period
    result[period] = prev_atr

    for i in range(period + 1, n):
        cur_tr = tr_series[i]
        assert cur_tr is not None
        cur_atr = ((prev_atr * (dec_period - ONE)) + cur_tr) / dec_period
        result[i] = cur_atr
        prev_atr = cur_atr

    return tuple(result)


def calculate_relative_volume(
    bars_or_set: BarSet | Sequence[Bar],
    lookback_period: int,
) -> tuple[Decimal | None, ...]:
    """Calculate Relative Volume (RVol).

    Formula: current_bar_volume / average_volume_of_previous_lookback_bars.
    Excludes current bar volume from the denominator lookback window.
    If denominator average volume is 0 or lookback unavailable -> None.
    """
    if lookback_period <= 0:
        raise ValueError(f"lookback_period must be positive, got {lookback_period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n <= lookback_period:
        return tuple(result)

    dec_lookback = Decimal(str(lookback_period))
    running_vol = sum(bars[j].volume for j in range(lookback_period))

    # At index lookback_period, previous bars are [0 .. lookback_period - 1]
    for i in range(lookback_period, n):
        if i > lookback_period:
            running_vol += bars[i - 1].volume - bars[i - 1 - lookback_period].volume

        avg_vol = running_vol / dec_lookback
        if avg_vol == ZERO:
            result[i] = None
        else:
            result[i] = bars[i].volume / avg_vol

    return tuple(result)


def calculate_volatility(
    bars_or_set: BarSet | Sequence[Bar],
    period: int,
    annualization_factor: Decimal | None = None,
) -> tuple[Decimal | None, ...]:
    """Calculate sample historical volatility based on log returns.

    Period n >= 2 returns. Needs n + 1 prices.
    Uses Decimal arithmetic and ln approximation with sample standard deviation (ddof=1).
    """
    if period < 2:
        raise ValueError(f"period for volatility must be >= 2, got {period}")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    result: list[Decimal | None] = [None] * n
    if n <= period:
        return tuple(result)

    dec_period = Decimal(str(period))
    dec_ddof = Decimal(str(period - 1))

    # Compute log returns: r_i = ln(C_i / C_{i-1})
    log_returns: list[Decimal] = []
    for i in range(1, n):
        ratio = bars[i].close / bars[i - 1].close
        try:
            # Decimal.ln() is exact in current precision context
            r = ratio.ln()
        except Exception:
            # Fallback to float math then convert back to Decimal if ratio out of context
            r = Decimal(str(math.log(float(ratio))))
        log_returns.append(r)

    # log_returns[0] corresponds to bar 1
    for i in range(period, n):
        # Window of log returns for bar i is log_returns[i - period : i]
        window = log_returns[i - period : i]
        mean_r = sum(window) / dec_period
        sum_sq = sum((x - mean_r) ** 2 for x in window)
        variance = sum_sq / dec_ddof
        try:
            vol = variance.sqrt()
        except Exception:
            vol = Decimal(str(math.sqrt(float(variance))))

        if annualization_factor is not None:
            if annualization_factor <= ZERO:
                raise ValueError("annualization_factor must be positive")
            try:
                ann_sqrt = annualization_factor.sqrt()
            except Exception:
                ann_sqrt = Decimal(str(math.sqrt(float(annualization_factor))))
            vol = vol * ann_sqrt

        result[i] = vol

    return tuple(result)


# -------------------------------------------------------------------------
# Structural Analysis: Trend, Support/Resistance, Breakout
# -------------------------------------------------------------------------

def detect_trend(
    bars_or_set: BarSet | Sequence[Bar],
    fast_period: int,
    slow_period: int,
) -> TrendEvaluation:
    """Evaluate trend direction, moving average relation, and crossovers."""
    bars = _extract_bars(bars_or_set)
    if not bars:
        return TrendEvaluation(
            price_vs_fast="UNAVAILABLE",
            price_vs_slow="UNAVAILABLE",
            fast_slope="UNAVAILABLE",
            crossover="UNAVAILABLE",
            fast_period=fast_period,
            slow_period=slow_period,
            latest_close=ZERO,
            fast_ma=None,
            slow_ma=None,
        )

    fast_ma = calculate_sma(bars, fast_period)
    slow_ma = calculate_sma(bars, slow_period)

    latest_close = bars[-1].close
    f_latest = fast_ma[-1]
    s_latest = slow_ma[-1]

    def _comp(p: Decimal, ma: Decimal | None) -> str:
        if ma is None:
            return "UNAVAILABLE"
        if p > ma:
            return "ABOVE"
        if p < ma:
            return "BELOW"
        return "EQUAL"

    price_vs_fast = _comp(latest_close, f_latest)
    price_vs_slow = _comp(latest_close, s_latest)

    # Slope of fast MA over last 2 points
    fast_slope = "UNAVAILABLE"
    if len(fast_ma) >= 2 and fast_ma[-1] is not None and fast_ma[-2] is not None:
        if fast_ma[-1] > fast_ma[-2]:  # type: ignore
            fast_slope = "RISING"
        elif fast_ma[-1] < fast_ma[-2]:  # type: ignore
            fast_slope = "FALLING"
        else:
            fast_slope = "FLAT"

    # Crossover detection
    crossover = "NONE"
    if len(fast_ma) >= 2 and len(slow_ma) >= 2:
        f_prev, f_curr = fast_ma[-2], fast_ma[-1]
        s_prev, s_curr = slow_ma[-2], slow_ma[-1]
        if f_prev is not None and f_curr is not None and s_prev is not None and s_curr is not None:
            if f_prev <= s_prev and f_curr > s_curr:
                crossover = "GOLDEN_CROSS"
            elif f_prev >= s_prev and f_curr < s_curr:
                crossover = "DEATH_CROSS"

    return TrendEvaluation(
        price_vs_fast=price_vs_fast,
        price_vs_slow=price_vs_slow,
        fast_slope=fast_slope,
        crossover=crossover,
        fast_period=fast_period,
        slow_period=slow_period,
        latest_close=latest_close,
        fast_ma=f_latest,
        slow_ma=s_latest,
    )


def detect_support_resistance(
    bars_or_set: BarSet | Sequence[Bar],
    lookback_period: int,
    confirmation_bars: int = 1,
) -> tuple[SupportResistanceLevel, ...]:
    """Detect pivot high (resistance) and pivot low (support) without future bar leak.

    Only confirmed pivots where confirmation_bars subsequent completed bars exist
    are returned. Records source_bar_id and session_date.
    """
    if lookback_period <= 0 or confirmation_bars < 0:
        raise ValueError("lookback_period and confirmation_bars must be positive")

    bars = _extract_bars(bars_or_set)
    n = len(bars)
    total_window = lookback_period + confirmation_bars
    if n < total_window + 1:
        return ()

    levels: list[SupportResistanceLevel] = []

    # Check potential pivot points at index p
    for p in range(lookback_period, n - confirmation_bars):
        cand = bars[p]

        # Check pivot high (resistance)
        is_pivot_high = all(cand.high > bars[p - k].high for k in range(1, lookback_period + 1)) and all(
            cand.high > bars[p + c].high for c in range(1, confirmation_bars + 1)
        )
        if is_pivot_high:
            levels.append(
                SupportResistanceLevel(
                    level_type="RESISTANCE",
                    price=cand.high,
                    source_bar_id=cand.bar_id,
                    source_session_date=cand.session_date,
                    lookback_window=lookback_period,
                    confirmed=True,
                )
            )

        # Check pivot low (support)
        is_pivot_low = all(cand.low < bars[p - k].low for k in range(1, lookback_period + 1)) and all(
            cand.low < bars[p + c].low for c in range(1, confirmation_bars + 1)
        )
        if is_pivot_low:
            levels.append(
                SupportResistanceLevel(
                    level_type="SUPPORT",
                    price=cand.low,
                    source_bar_id=cand.bar_id,
                    source_session_date=cand.session_date,
                    lookback_window=lookback_period,
                    confirmed=True,
                )
            )

    return tuple(levels)


def detect_breakout(
    bars_or_set: BarSet | Sequence[Bar],
    resistance_level: Decimal,
    volume_threshold_ratio: Decimal,
    relative_vol_lookback: int,
    resistance_source_bar_id: str | None = None,
) -> BreakoutEvaluation:
    """Evaluate if the latest completed bar achieved a valid breakout.

    Invariants:
    1. Latest close must exceed resistance_level.
    2. Relative volume must exceed volume_threshold_ratio.
    3. The bar that created the resistance level CANNOT be the same bar that breaks out.
    """
    bars = _extract_bars(bars_or_set)
    if not bars:
        return BreakoutEvaluation(
            is_breakout=False,
            breakout_type="UNAVAILABLE",
            target_level=resistance_level,
            latest_close=ZERO,
            latest_volume=ZERO,
            relative_volume=None,
            resistance_bar_id=resistance_source_bar_id,
            breakout_bar_id=None,
            reason="No bars provided",
        )

    latest_bar = bars[-1]
    if resistance_source_bar_id and latest_bar.bar_id == resistance_source_bar_id:
        return BreakoutEvaluation(
            is_breakout=False,
            breakout_type="NONE",
            target_level=resistance_level,
            latest_close=latest_bar.close,
            latest_volume=latest_bar.volume,
            relative_volume=None,
            resistance_bar_id=resistance_source_bar_id,
            breakout_bar_id=latest_bar.bar_id,
            reason="The same bar cannot create resistance and break out simultaneously",
        )

    rvol_series = calculate_relative_volume(bars, relative_vol_lookback)
    latest_rvol = rvol_series[-1]

    if latest_bar.close > resistance_level:
        if latest_rvol is not None and latest_rvol >= volume_threshold_ratio:
            return BreakoutEvaluation(
                is_breakout=True,
                breakout_type="BULLISH_BREAKOUT",
                target_level=resistance_level,
                latest_close=latest_bar.close,
                latest_volume=latest_bar.volume,
                relative_volume=latest_rvol,
                resistance_bar_id=resistance_source_bar_id,
                breakout_bar_id=latest_bar.bar_id,
                reason="Close exceeded resistance with confirmed relative volume",
            )
        else:
            return BreakoutEvaluation(
                is_breakout=False,
                breakout_type="NONE",
                target_level=resistance_level,
                latest_close=latest_bar.close,
                latest_volume=latest_bar.volume,
                relative_volume=latest_rvol,
                resistance_bar_id=resistance_source_bar_id,
                breakout_bar_id=latest_bar.bar_id,
                reason="Price exceeded resistance but relative volume confirmation failed",
            )

    return BreakoutEvaluation(
        is_breakout=False,
        breakout_type="NONE",
        target_level=resistance_level,
        latest_close=latest_bar.close,
        latest_volume=latest_bar.volume,
        relative_volume=latest_rvol,
        resistance_bar_id=resistance_source_bar_id,
        breakout_bar_id=latest_bar.bar_id,
        reason="Latest close did not exceed resistance level",
    )


# -------------------------------------------------------------------------
# Trading Signal Gate
# -------------------------------------------------------------------------

def evaluate_signal_gate(
    bars_or_set: BarSet | Sequence[Bar],
    *,
    approved_policy_id: str | None = None,
    caller_approved: bool = False,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> TradingSignalResult:
    """Enforce security gate on trading signals.

    Rule: Neither an RSI oversold condition nor a golden cross alone or combined
    may trigger an automated BUY/SELL trade recommendation unless explicit user risk
    policy and parameter approval are confirmed. Without caller_approved=True,
    trading signals remain strictly UNAVAILABLE.
    """
    bars = _extract_bars(bars_or_set)
    rsi_vals = calculate_wilder_rsi(bars, rsi_period) if bars else ()
    macd_vals = calculate_macd(bars, macd_fast, macd_slow, macd_signal) if bars else ()

    summary = {
        "bar_count": len(bars),
        "latest_rsi": str(rsi_vals[-1]) if rsi_vals and rsi_vals[-1] is not None else None,
        "latest_macd": (
            {
                "macd": str(macd_vals[-1].macd) if macd_vals[-1] and macd_vals[-1].macd else None,
                "signal": str(macd_vals[-1].signal) if macd_vals[-1] and macd_vals[-1].signal else None,
            }
            if macd_vals and macd_vals[-1]
            else None
        ),
    }

    if not caller_approved or not approved_policy_id:
        return TradingSignalResult(
            status="UNAVAILABLE",
            signal=None,
            reason="UNAPPROVED_POLICY: Trading signals require explicit caller approval and risk policy ID",
            approved_policy_id=None,
            indicator_summary=summary,
        )

    # Fail-closed invariant: There is no approved risk policy registry yet.
    # We must not trust external arbitrary strings/booleans for trading signals.
    return TradingSignalResult(
        status="UNAVAILABLE",
        signal=None,
        reason="FAIL_CLOSED: Signal generation is disabled pending verified policy registry implementation",
        approved_policy_id=None,
        indicator_summary=summary,
    )
