"""Strict aware civil-calendar binding for monthly forecasting adapters.

A local civil label is not a UTC instant. Keep the two representations
separate at model-provider boundaries and compare complete UTC instant paths.
No changes to public ForecastRequest calendar/frequency validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from dateutil.tz import datetime_ambiguous, datetime_exists, gettz

import pandas as pd


def _assert_unambiguous(naive: pd.DatetimeIndex, zone) -> None:
    # dateutil's existence/ambiguity API does not understand a raw pytz tzinfo
    # as a wall-time zone (it expects pytz.localize). Resolve its IANA name
    # through dateutil's transition-aware tzfile before checking civil labels.
    tz_name = getattr(zone, "key", None) or getattr(zone, "zone", None)
    checked_zone = (gettz(tz_name) if tz_name else None) or zone
    for stamp in naive:
        local = stamp.to_pydatetime()
        if not datetime_exists(local, checked_zone):
            raise ValueError("nonexistent DST civil timestamp")
        if datetime_ambiguous(local, checked_zone):
            raise ValueError("ambiguous DST civil timestamp")


def _zone_name(value: datetime) -> str:
    tz = value.tzinfo
    if tz is None or value.utcoffset() is None:
        raise ValueError("calendar timestamps must be offset-aware")
    return str(getattr(tz, "key", None) or getattr(tz, "zone", None) or tz)


@dataclass(frozen=True)
class AwareCalendarPath:
    observed_local: pd.DatetimeIndex
    future_local: pd.DatetimeIndex
    observed_utc: pd.DatetimeIndex
    future_utc: pd.DatetimeIndex
    timezone_name: str


def canonical_calendar_path(request) -> AwareCalendarPath:
    """Derive the predictor path from the *original* single-zone civil calendar.

    Even identical UTC offsets are insufficient evidence of a common calendar.
    Reject mixed timezone identifiers and DST ambiguous/nonexistent local labels.
    """
    if not request.timestamps:
        raise ValueError("explicit bound observed calendar required")
    stamps = list(request.timestamps)
    zone_name = _zone_name(stamps[0])
    if any(_zone_name(v) != zone_name for v in [*stamps, request.target_date]):
        raise ValueError("mixed or unbound calendar timezone")
    try:
        observed = pd.DatetimeIndex(stamps)
        if observed.tz is None:
            raise ValueError("missing civil timezone")
        offset = pd.tseries.frequencies.to_offset(request.frequency)
        future = pd.DatetimeIndex([observed[-1] + offset * (i + 1)
                                   for i in range(request.horizon_steps)])
        if (len(future) != request.horizon_steps or not future.is_monotonic_increasing
                or future.has_duplicates):
            raise ValueError("invalid canonical future calendar")
        # Local naive labels must be uniquely representable by the original
        # timezone. Ambiguous/nonexistent DST civil timestamps are unsupported.
        for original in (observed, future):
            naive = original.tz_localize(None)
            _assert_unambiguous(naive, observed.tz)
            relocalized = naive.tz_localize(observed.tz, ambiguous="raise", nonexistent="raise")
            if not relocalized.tz_convert("UTC").equals(original.tz_convert("UTC")):
                raise ValueError("ambiguous or inconsistent civil calendar")
        if future[-1] != pd.Timestamp(request.target_date):
            raise ValueError("canonical future calendar target mismatch")
        if not observed.is_monotonic_increasing or observed.has_duplicates:
            raise ValueError("invalid observed calendar")
    except (TypeError, OverflowError) as exc:
        raise ValueError(f"unsupported civil calendar: {exc}") from exc
    return AwareCalendarPath(observed, future, observed.tz_convert("UTC"),
                             future.tz_convert("UTC"), zone_name)


def chronos_provider_encoding(calendar: AwareCalendarPath, frequency: str) -> tuple[str, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Use UTC-naive only if its *full* path has the requested cadence.

    Otherwise encode civil labels as naive timestamps for Chronos frequency
    inference; these labels MUST be decoded using the original timezone.
    """
    observed = calendar.observed_utc.tz_localize(None)
    future = calendar.future_utc.tz_localize(None)
    try:
        expected_observed = pd.date_range(end=observed[-1], periods=len(observed), freq=frequency)
        expected_future = pd.DatetimeIndex([observed[-1] + pd.tseries.frequencies.to_offset(frequency) * (i + 1)
                                            for i in range(len(future))])
        if observed.equals(expected_observed) and future.equals(expected_future):
            return "utc-naive-instant", observed, future
    except (ValueError, TypeError):
        pass
    return "civil-naive-label", calendar.observed_local.tz_localize(None), calendar.future_local.tz_localize(None)


def decode_chronos_return(values: Sequence, calendar: AwareCalendarPath, encoding: str) -> pd.DatetimeIndex:
    """Naive provider output is an encoded label; aware output an instant."""
    stamps = [pd.Timestamp(value) for value in values]
    if not stamps or any(pd.isna(stamp) for stamp in stamps):
        raise ValueError("Chronos missing prediction timestamp")
    is_aware = [stamp.tzinfo is not None for stamp in stamps]
    if any(is_aware) and not all(is_aware):
        raise ValueError("Chronos mixed naive/aware returned timestamps")
    if all(is_aware):
        # Aware provider timestamps have absolute meaning in both modes.
        return pd.DatetimeIndex(stamps).tz_convert("UTC")
    naive = pd.DatetimeIndex(stamps)
    if encoding == "utc-naive-instant":
        return naive.tz_localize("UTC")
    if encoding == "civil-naive-label":
        _assert_unambiguous(naive, calendar.observed_local.tz)
        return naive.tz_localize(calendar.observed_local.tz, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    raise ValueError("unrecognized Chronos encoding")
