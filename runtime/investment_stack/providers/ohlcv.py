"""OHLCV bar series parser and provider adapter for public equity and crypto.

Implements REQ-2026-09-23-v1 R07 and CONTRACT-01 OHLCV contracts.
Enforces price bounds invariants, non-negative volume, chronological ordering,
session completeness checks against analysis_as_of, and split-adjustment tracking.

Guarantees:
- Unverified raw OHLCV (lacking split/adjustment/calendar receipts) is preserved as raw data,
  but NOT promoted to validated BarSet/technical input without explicit verification receipts.
- Yahoo Chart OHLCV parser supporting live-verified 1d interval feeds.
- Incomplete bars are strictly isolated and barred from completed BarSet series.

Limits:
- Exchange holidays/session gaps are not validated against an official calendar.
- Adjustment receipts are caller-provided markers; this module does not verify them against corporate-action records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
import re
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import AdjustmentMode, Bar, BarSet
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability

HttpTransport = Callable[[str, Mapping[str, str] | None, float], tuple[int, bytes, Mapping[str, str]]]
_NAVER_NUMBER = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$")


def _safe_json_loads(payload: str | bytes) -> Any:
    return json.loads(payload, parse_float=Decimal)


def _parse_naver_decimal(value: Any) -> Decimal:
    """Parse Naver's decimal strings, allowing only correctly grouped thousands commas."""
    text = str(value).strip()
    if not _NAVER_NUMBER.fullmatch(text):
        raise ValueError(f"Invalid Naver numeric format: {text!r}")
    return parse_finite_decimal(text.replace(",", ""))


@dataclass(frozen=True, slots=True)
class OHLCVParseResult:
    """Encapsulates parsed Bar series, completeness evaluation, and diagnostics."""

    bar_set: BarSet | None
    bars: tuple[Bar, ...] = ()
    incomplete_bars: tuple[Bar, ...] = ()
    discarded_bars: tuple[dict[str, Any], ...] = ()
    missing_sessions: tuple[str, ...] = ()
    error_reasons: tuple[str, ...] = ()
    adjustment_verified: bool = False

    @property
    def is_usable(self) -> bool:
        return self.bar_set is not None and bool(self.bar_set.bars) and not self.error_reasons


def parse_naver_ohlcv(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | bytes,
    *,
    instrument_id: str = "KRX:005930",
    currency: str = "KRW",
    timezone_str: str = "Asia/Seoul",
    session_start: str = "09:00:00",
    session_end: str = "15:30:00",
    interval: str = "1D",
    analysis_as_of: datetime | None = None,
    request_url: str | None = None,
    evidence_id_prefix: str | None = None,
    adjustment_verified: bool = False,
    adjustment_receipt: str | None = None,
    calendar_receipt: str | None = None,
) -> OHLCVParseResult:
    """Parse Naver Pay Securities daily OHLCV (dayCandle) JSON response.

    Enforces:
    1. Identity check: payload code must match requested instrument.
    2. Adjustment fidelity: A strict `adjustment_verified is True` and a non-empty receipt
       are both required to create a BarSet. Otherwise raw bars are preserved but blocked.
    3. Price bounds: low <= min(open, close) <= max(open, close) <= high.
    4. Session completeness: if session_close > analysis_as_of, bar is placed in incomplete_bars.
    """
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return OHLCVParseResult(
                bar_set=None,
                error_reasons=(f"JSON_DECODE_ERROR: {exc}",),
            )
    else:
        data = payload

    # Naver's public `/price` endpoint returns a top-level list with no echoed
    # instrument id. Bind that response only to the exact public request route;
    # a detached list fixture cannot establish which instrument it belongs to.
    if isinstance(data, (list, tuple)):
        parsed_url = urlparse(request_url or "")
        route_parts = parsed_url.path.strip("/").split("/")
        expected_code = instrument_id.split(":")[-1].strip()
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "m.stock.naver.com"
            or parsed_url.port not in (None, 443)
            or len(route_parts) != 4
            or route_parts[:2] != ["api", "stock"]
            or route_parts[3] != "price"
        ):
            return OHLCVParseResult(
                bar_set=None,
                error_reasons=("UNBOUND_RESPONSE_IDENTITY: Naver list response requires its public /price request URL",),
            )
        route_code = route_parts[2]
        if route_code != expected_code:
            return OHLCVParseResult(
                bar_set=None,
                error_reasons=(f"IDENTITY_MISMATCH: request route code '{route_code}' does not match requested '{expected_code}'",),
            )
        normalized_items: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, Mapping):
                normalized_items.append({})
                continue
            raw_date = str(item.get("localTradedAt", "")).strip()
            normalized_date = raw_date.replace("-", "") if len(raw_date) == 10 else raw_date
            normalized_items.append({
                "localDate": normalized_date,
                "openPrice": item.get("openPrice"),
                "highPrice": item.get("highPrice"),
                "lowPrice": item.get("lowPrice"),
                "closePrice": item.get("closePrice"),
                "accumulatedTradingVolume": item.get("accumulatedTradingVolume"),
            })
        data = {"code": route_code, "priceInfos": normalized_items}
    elif isinstance(data, Mapping):
        data = dict(data)
    else:
        return OHLCVParseResult(bar_set=None, error_reasons=("INVALID_NAVER_PRICE_PAYLOAD",))

    # 1. Identity Check
    payload_code = data.get("code")
    if not payload_code:
        return OHLCVParseResult(
            bar_set=None,
            error_reasons=("MISSING_PAYLOAD_IDENTITY",),
        )

    expected_code = instrument_id.split(":")[-1].strip()
    if str(payload_code).strip() != expected_code:
        return OHLCVParseResult(
            bar_set=None,
            error_reasons=(
                f"IDENTITY_MISMATCH: payload code '{payload_code}' does not match requested '{expected_code}'",
            ),
        )

    raw_items = data.get("priceInfos")
    if not isinstance(raw_items, (list, tuple)):
        return OHLCVParseResult(
            bar_set=None,
            error_reasons=("MISSING_PRICE_INFOS_ARRAY",),
        )

    tz = ZoneInfo(timezone_str)
    start_time_obj = time.fromisoformat(session_start)
    end_time_obj = time.fromisoformat(session_end)

    ev_prefix = evidence_id_prefix or f"naver_ohlcv_{instrument_id.replace(':', '_')}"

    as_of_tz: datetime | None = None
    if analysis_as_of is not None:
        if analysis_as_of.tzinfo is None:
            as_of_tz = analysis_as_of.replace(tzinfo=tz)
        else:
            as_of_tz = analysis_as_of.astimezone(tz)

    completed_bars: list[Bar] = []
    incomplete_bars: list[Bar] = []
    discarded_bars: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    has_adjustment_receipt = (
        isinstance(adjustment_receipt, str) and bool(adjustment_receipt.strip())
    )
    is_adj_confirmed = adjustment_verified is True and has_adjustment_receipt
    resolved_adj_mode = (
        AdjustmentMode.SPLIT_ADJUSTED if is_adj_confirmed else AdjustmentMode.RAW
    )

    for idx, item in enumerate(raw_items):
        if not isinstance(item, Mapping):
            discarded_bars.append({"index": idx, "reason": "ITEM_NOT_AN_OBJECT", "item": item})
            continue

        raw_date = str(item.get("localDate", "")).strip()
        if len(raw_date) != 8 or not raw_date.isdigit():
            discarded_bars.append({"index": idx, "reason": "INVALID_DATE_FORMAT", "localDate": raw_date})
            continue

        if raw_date in seen_dates:
            discarded_bars.append({"index": idx, "reason": "DUPLICATE_SESSION_DATE", "localDate": raw_date})
            continue
        seen_dates.add(raw_date)

        try:
            bar_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        except ValueError as exc:
            discarded_bars.append({"index": idx, "reason": f"INVALID_CALENDAR_DATE: {exc}", "localDate": raw_date})
            continue

        session_open = datetime.combine(bar_date, start_time_obj, tzinfo=tz)
        session_close = datetime.combine(bar_date, end_time_obj, tzinfo=tz)

        # Exclude completely future bars relative to as_of
        if as_of_tz is not None and session_open > as_of_tz:
            discarded_bars.append({
                "index": idx,
                "reason": "FUTURE_BAR",
                "session_open": session_open.isoformat(),
                "as_of": as_of_tz.isoformat(),
            })
            continue

        try:
            o = _parse_naver_decimal(item["openPrice"])
            h = _parse_naver_decimal(item["highPrice"])
            l = _parse_naver_decimal(item["lowPrice"])
            c = _parse_naver_decimal(item["closePrice"])
            v = _parse_naver_decimal(item.get("accumulatedTradingVolume", "0"))
        except Exception as exc:
            discarded_bars.append({"index": idx, "reason": f"DECIMAL_PARSE_ERROR: {exc}", "item": item})
            continue

        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            discarded_bars.append({
                "index": idx, "reason": "NON_POSITIVE_PRICE",
                "open": o, "high": h, "low": l, "close": c,
            })
            continue

        if v < 0:
            discarded_bars.append({"index": idx, "reason": "NEGATIVE_VOLUME", "volume": v})
            continue

        # Invariant bounds check: low <= min(open, close) <= max(open, close) <= high
        if l > min(o, c) or h < max(o, c) or l > h:
            discarded_bars.append({
                "index": idx, "reason": "BOUNDS_INVARIANT_VIOLATION",
                "open": o, "high": h, "low": l, "close": c,
            })
            continue

        is_complete = True
        if as_of_tz is not None and session_close > as_of_tz:
            is_complete = False

        session_str = bar_date.isoformat()
        bar_ev_id = f"{ev_prefix}_{raw_date}"

        pub_avail = PublicAvailability.from_source_date(
            source_date=bar_date,
            source_timezone=timezone_str,
            locator=request_url or f"naver_ohlcv:{instrument_id}",
        )

        bar = Bar(
            bar_id=f"bar_{bar_ev_id}",
            evidence_id=bar_ev_id,
            instrument_id=instrument_id,
            interval=interval,
            session_date=session_str,
            open_time=session_open,
            close_time=session_close,
            timezone=timezone_str,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
            currency=currency,
            public_availability=pub_avail,
            volume_unit="SHARES",
            adjustment_mode=resolved_adj_mode,
            is_complete=is_complete,
        )

        if is_complete:
            completed_bars.append(bar)
        else:
            incomplete_bars.append(bar)

    completed_bars.sort(key=lambda b: b.open_time)

    # 2. Enforce Adjustment Verification Guard:
    # If unverified, raw bars are returned, but BarSet is not created and is_usable=False.
    if not is_adj_confirmed:
        return OHLCVParseResult(
            bar_set=None,
            bars=tuple(completed_bars),
            incomplete_bars=tuple(incomplete_bars),
            discarded_bars=tuple(discarded_bars),
            error_reasons=(
                "UNVERIFIED_ADJUSTMENT: requires a strict verified flag and a non-empty adjustment receipt",
            ),
            adjustment_verified=False,
        )

    bar_set: BarSet | None = None
    if completed_bars:
        try:
            bar_set = BarSet.create(
                instrument_id=instrument_id,
                interval=interval,
                currency=currency,
                adjustment_mode=resolved_adj_mode,
                bars=completed_bars,
            )
        except Exception as exc:
            return OHLCVParseResult(
                bar_set=None,
                bars=tuple(completed_bars),
                incomplete_bars=tuple(incomplete_bars),
                discarded_bars=tuple(discarded_bars),
                error_reasons=(f"BARSET_CREATION_FAILED: {exc}",),
                adjustment_verified=True,
            )

    return OHLCVParseResult(
        bar_set=bar_set,
        bars=tuple(completed_bars),
        incomplete_bars=tuple(incomplete_bars),
        discarded_bars=tuple(discarded_bars),
        adjustment_verified=True,
    )


def parse_yahoo_chart_ohlcv(
    payload: Mapping[str, Any] | str | bytes,
    *,
    instrument_id: str = "NASDAQ:AAPL",
    interval: str = "1D",
    analysis_as_of: datetime | None = None,
    evidence_id_prefix: str | None = None,
) -> OHLCVParseResult:
    """Parse Yahoo Finance Chart OHLCV response (Live HTTP 200 confirmed by supervisor).

    Payload schema: chart.result[0].meta, timestamps, indicators.quote[0], indicators.adjclose[0].
    Enforces identity matching, bounds checking, and forming bar isolation.
    """
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return OHLCVParseResult(bar_set=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",))
    else:
        data = dict(payload)

    chart_obj = data.get("chart", {})
    results = chart_obj.get("result")
    if not isinstance(results, (list, tuple)) or not results:
        err = chart_obj.get("error")
        return OHLCVParseResult(bar_set=None, error_reasons=(f"YAHOO_CHART_ERROR: {err}",))

    res_data = results[0]
    meta = res_data.get("meta", {})
    symbol = str(meta.get("symbol", "")).strip().upper()
    expected_ticker = instrument_id.split(":")[-1].strip().upper()
    if symbol != expected_ticker:
        return OHLCVParseResult(
            bar_set=None,
            error_reasons=(
                f"IDENTITY_MISMATCH: payload symbol '{symbol}' != requested '{expected_ticker}'",
            ),
        )

    currency = str(meta.get("currency", "USD")).strip().upper()
    tz_name = str(meta.get("exchangeTimezoneName", "America/New_York")).strip()
    tz = ZoneInfo(tz_name)

    timestamps = res_data.get("timestamp", [])
    indicators = res_data.get("indicators", {})
    quote_list = indicators.get("quote", [{}])[0]
    adj_list = indicators.get("adjclose", [{}])[0].get("adjclose", [])

    opens = quote_list.get("open", [])
    highs = quote_list.get("high", [])
    lows = quote_list.get("low", [])
    closes = quote_list.get("close", [])
    volumes = quote_list.get("volume", [])

    ev_prefix = evidence_id_prefix or f"yahoo_chart_{symbol.lower()}"

    as_of_tz: datetime | None = None
    if analysis_as_of is not None:
        as_of_tz = analysis_as_of if analysis_as_of.tzinfo else analysis_as_of.replace(tzinfo=tz)

    completed_bars: list[Bar] = []
    incomplete_bars: list[Bar] = []
    discarded_bars: list[dict[str, Any]] = []

    for i in range(len(timestamps)):
        epoch = timestamps[i]
        if epoch is None:
            continue

        raw_o, raw_h, raw_l, raw_c, raw_v = opens[i], highs[i], lows[i], closes[i], volumes[i]
        if None in (raw_o, raw_h, raw_l, raw_c):
            discarded_bars.append({"index": i, "reason": "NULL_OHLC_VALUE", "timestamp": epoch})
            continue

        try:
            o = parse_finite_decimal(str(raw_o))
            h = parse_finite_decimal(str(raw_h))
            l = parse_finite_decimal(str(raw_l))
            c = parse_finite_decimal(str(raw_c))
            v = parse_finite_decimal(str(raw_v or "0"))
        except Exception as exc:
            discarded_bars.append({"index": i, "reason": f"DECIMAL_ERROR: {exc}", "timestamp": epoch})
            continue

        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
            discarded_bars.append({"index": i, "reason": "INVALID_PRICE_OR_VOLUME", "timestamp": epoch})
            continue

        if l > min(o, c) or h < max(o, c) or l > h:
            discarded_bars.append({"index": i, "reason": "BOUNDS_VIOLATION", "timestamp": epoch})
            continue

        bar_open_dt = datetime.fromtimestamp(int(epoch), tz=tz)
        bar_close_dt = bar_open_dt.replace(hour=16, minute=0, second=0)

        if as_of_tz is not None and bar_open_dt > as_of_tz:
            discarded_bars.append({"index": i, "reason": "FUTURE_BAR", "open_dt": bar_open_dt.isoformat()})
            continue

        is_complete = True
        if as_of_tz is not None and bar_close_dt > as_of_tz:
            is_complete = False

        pub_avail = PublicAvailability.exact(
            available_at=bar_close_dt, locator=f"yahoo_chart:{symbol}"
        )

        has_adj = i < len(adj_list) and adj_list[i] is not None
        adj_mode = AdjustmentMode.SPLIT_ADJUSTED if has_adj else AdjustmentMode.RAW

        bar = Bar(
            bar_id=f"bar_{ev_prefix}_{epoch}",
            evidence_id=f"{ev_prefix}_{epoch}",
            instrument_id=instrument_id,
            interval=interval,
            session_date=bar_open_dt.strftime("%Y-%m-%d"),
            open_time=bar_open_dt,
            close_time=bar_close_dt,
            timezone=tz_name,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
            currency=currency,
            public_availability=pub_avail,
            volume_unit="SHARES",
            adjustment_mode=adj_mode,
            is_complete=is_complete,
        )

        if is_complete:
            completed_bars.append(bar)
        else:
            incomplete_bars.append(bar)

    completed_bars.sort(key=lambda b: b.open_time)
    bar_set = None
    if completed_bars:
        try:
            bar_set = BarSet.create(
                instrument_id=instrument_id,
                interval=interval,
                currency=currency,
                adjustment_mode=completed_bars[0].adjustment_mode,
                bars=completed_bars,
            )
        except Exception as exc:
            return OHLCVParseResult(
                bar_set=None,
                bars=tuple(completed_bars),
                incomplete_bars=tuple(incomplete_bars),
                discarded_bars=tuple(discarded_bars),
                error_reasons=(f"BARSET_CREATION_FAILED: {exc}",),
                adjustment_verified=True,
            )

    return OHLCVParseResult(
        bar_set=bar_set,
        bars=tuple(completed_bars),
        incomplete_bars=tuple(incomplete_bars),
        discarded_bars=tuple(discarded_bars),
        adjustment_verified=True,
    )


def parse_kraken_ohlc(
    payload: Mapping[str, Any] | str | bytes,
    *,
    pair: str = "XBTUSD",
    instrument_id: str = "CRYPTO:BTC/USD",
    currency: str = "USD",
    interval_minutes: int = 1440,
    analysis_as_of: datetime | None = None,
    evidence_id_prefix: str | None = None,
) -> OHLCVParseResult:
    """Parse Kraken Public REST OHLC response (Candidate endpoint; live probe pending)."""
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return OHLCVParseResult(bar_set=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",))
    else:
        data = dict(payload)

    errors = data.get("error")
    if errors:
        return OHLCVParseResult(bar_set=None, error_reasons=(f"KRAKEN_API_ERROR: {errors}",))

    result_map = data.get("result")
    if not isinstance(result_map, Mapping):
        return OHLCVParseResult(bar_set=None, error_reasons=("MISSING_RESULT_OBJECT",))

    raw_bars = None
    for k, v in result_map.items():
        if k != "last" and isinstance(v, (list, tuple)):
            raw_bars = v
            break

    if not raw_bars:
        return OHLCVParseResult(bar_set=None, error_reasons=("NO_BARS_FOUND_IN_RESULT",))

    ev_prefix = evidence_id_prefix or f"kraken_ohlc_{pair.lower()}"
    interval_str = f"{interval_minutes}m" if interval_minutes < 1440 else "1D"

    completed_bars: list[Bar] = []
    incomplete_bars: list[Bar] = []
    discarded_bars: list[dict[str, Any]] = []

    for idx, raw_row in enumerate(raw_bars):
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) < 6:
            discarded_bars.append({"index": idx, "reason": "MALFORMED_ROW", "row": raw_row})
            continue

        try:
            epoch = int(raw_row[0])
            open_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            close_dt = datetime.fromtimestamp(epoch + interval_minutes * 60, tz=timezone.utc)
        except Exception as exc:
            discarded_bars.append({"index": idx, "reason": f"TIMESTAMP_ERROR: {exc}", "row": raw_row})
            continue

        if analysis_as_of is not None:
            as_of_utc = analysis_as_of if analysis_as_of.tzinfo else analysis_as_of.replace(tzinfo=timezone.utc)
            if open_dt > as_of_utc:
                discarded_bars.append({"index": idx, "reason": "FUTURE_BAR", "open_dt": open_dt.isoformat()})
                continue

        try:
            o = parse_finite_decimal(str(raw_row[1]))
            h = parse_finite_decimal(str(raw_row[2]))
            l = parse_finite_decimal(str(raw_row[3]))
            c = parse_finite_decimal(str(raw_row[4]))
            v = parse_finite_decimal(str(raw_row[6]))
        except Exception as exc:
            discarded_bars.append({"index": idx, "reason": f"DECIMAL_ERROR: {exc}", "row": raw_row})
            continue

        if o <= 0 or h <= 0 or l <= 0 or c <= 0 or v < 0:
            discarded_bars.append({"index": idx, "reason": "INVALID_PRICE_OR_VOLUME", "row": raw_row})
            continue

        if l > min(o, c) or h < max(o, c) or l > h:
            discarded_bars.append({"index": idx, "reason": "BOUNDS_VIOLATION", "row": raw_row})
            continue

        is_complete = True
        if analysis_as_of is not None:
            as_of_utc = analysis_as_of if analysis_as_of.tzinfo else analysis_as_of.replace(tzinfo=timezone.utc)
            if close_dt > as_of_utc:
                is_complete = False

        pub_avail = PublicAvailability.exact(available_at=close_dt, locator=f"kraken_ohlc:{pair}")
        bar_id = f"{ev_prefix}_{epoch}"

        bar = Bar(
            bar_id=f"bar_{bar_id}",
            evidence_id=bar_id,
            instrument_id=instrument_id,
            interval=interval_str,
            session_date=open_dt.strftime("%Y-%m-%d"),
            open_time=open_dt,
            close_time=close_dt,
            timezone="UTC",
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
            currency=currency,
            public_availability=pub_avail,
            volume_unit="SHARES",
            adjustment_mode=AdjustmentMode.RAW,
            is_complete=is_complete,
        )

        if is_complete:
            completed_bars.append(bar)
        else:
            incomplete_bars.append(bar)

    completed_bars.sort(key=lambda b: b.open_time)
    bar_set = None
    if completed_bars:
        try:
            bar_set = BarSet.create(
                instrument_id=instrument_id,
                interval=interval_str,
                currency=currency,
                adjustment_mode=AdjustmentMode.RAW,
                bars=completed_bars,
            )
        except Exception as exc:
            return OHLCVParseResult(
                bar_set=None,
                bars=tuple(completed_bars),
                incomplete_bars=tuple(incomplete_bars),
                discarded_bars=tuple(discarded_bars),
                error_reasons=(f"BARSET_CREATION_FAILED: {exc}",),
                adjustment_verified=True,
            )

    return OHLCVParseResult(
        bar_set=bar_set,
        bars=tuple(completed_bars),
        incomplete_bars=tuple(incomplete_bars),
        discarded_bars=tuple(discarded_bars),
        adjustment_verified=True,
    )


class OHLCVProvider:
    """Capability-first OHLCV Provider for historical bar series."""

    name = "ohlcv_provider"

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        preloaded_bundles: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._transport = transport
        self._bundles = dict(preloaded_bundles or {})

    def fetch_historical_bars(
        self,
        instrument_id: str,
        *,
        analysis_as_of: str | datetime,
        interval: str = "1D",
        page_size: int = 120,
        adjustment_verified: bool = False,
        adjustment_receipt: str | None = None,
    ) -> ProviderResult:
        """Fetch historical completed bars for an instrument as of a cutoff datetime."""
        as_of_dt: datetime
        if isinstance(analysis_as_of, str):
            as_of_dt = datetime.fromisoformat(analysis_as_of)
        else:
            as_of_dt = analysis_as_of

        # 1. Bundled data check
        if instrument_id in self._bundles:
            bundle = self._bundles[instrument_id]
            source_kind = bundle.get("source_type", "naver_ohlcv")
            raw_payload = bundle.get("payload", {})
            if source_kind == "naver_ohlcv":
                parsed = parse_naver_ohlcv(
                    raw_payload,
                    instrument_id=instrument_id,
                    interval=interval,
                    analysis_as_of=as_of_dt,
                    request_url=bundle.get("source_url"),
                    adjustment_verified=adjustment_verified,
                    adjustment_receipt=adjustment_receipt,
                )
            elif source_kind == "yahoo_chart":
                parsed = parse_yahoo_chart_ohlcv(
                    raw_payload,
                    instrument_id=instrument_id,
                    interval=interval,
                    analysis_as_of=as_of_dt,
                )
            elif source_kind == "kraken_ohlc":
                parsed = parse_kraken_ohlc(
                    raw_payload,
                    instrument_id=instrument_id,
                    analysis_as_of=as_of_dt,
                )
            else:
                return ProviderResult(
                    provider=self.name,
                    capability=ProviderCapability.HISTORICAL_PRICE,
                    status=ProviderStatus.ERROR,
                    reason=f"Unsupported bundled source_type: {source_kind}",
                )

            if parsed.is_usable and parsed.bar_set:
                latest_bar = parsed.bar_set.bars[-1]
                obs = ProviderObservation(
                    evidence_type="market",
                    source_name=source_kind,
                    source_url=f"bundle://{instrument_id}",
                    source_tier=2,
                    provider_id=self.name,
                    value=latest_bar.close,
                    unit=latest_bar.currency,
                    currency=latest_bar.currency,
                    instrument_id=instrument_id,
                    metric="historical_ohlcv",
                    retrieved_at=as_of_dt.isoformat(),
                    observed_at=latest_bar.close_time.isoformat(),
                    market_session_date=latest_bar.session_date,
                    official_confirmation_status="EXCHANGE_CONFIRMED",
                    metadata={
                        "bar_count": len(parsed.bar_set.bars),
                        "incomplete_bars_count": len(parsed.incomplete_bars),
                        "discarded_bars_count": len(parsed.discarded_bars),
                    },
                )
                return ProviderResult(
                    provider=self.name,
                    capability=ProviderCapability.HISTORICAL_PRICE,
                    status=ProviderStatus.AVAILABLE,
                    observations=(obs,),
                    metadata={"contract_bar_set": parsed.bar_set},
                )

            return ProviderResult(
                provider=self.name,
                capability=ProviderCapability.HISTORICAL_PRICE,
                status=ProviderStatus.UNAVAILABLE,
                reason="; ".join(parsed.error_reasons) or "No valid completed bars in bundle",
                metadata={
                    "contract_ohlcv_parse_result": parsed,
                    "source_url": bundle.get("source_url"),
                },
            )

        # 2. Injected transport execution
        if self._transport is not None:
            if instrument_id.startswith("KRX:") or instrument_id.isdigit():
                code = instrument_id.split(":")[-1]
                url = f"https://m.stock.naver.com/api/stock/{code}/price?page=1&pageSize={page_size}"
                try:
                    status_code, body, _ = self._transport(url, None, 10.0)
                    if status_code == 200:
                        parsed = parse_naver_ohlcv(
                            body,
                            instrument_id=instrument_id,
                            interval=interval,
                            analysis_as_of=as_of_dt,
                            request_url=url,
                            adjustment_verified=adjustment_verified,
                            adjustment_receipt=adjustment_receipt,
                        )
                        if parsed.is_usable and parsed.bar_set:
                            latest_bar = parsed.bar_set.bars[-1]
                            obs = ProviderObservation(
                                evidence_type="market",
                                source_name="naver_pay",
                                source_url=url,
                                source_tier=2,
                                provider_id=self.name,
                                value=latest_bar.close,
                                unit=latest_bar.currency,
                                currency=latest_bar.currency,
                                instrument_id=instrument_id,
                                metric="historical_ohlcv",
                                retrieved_at=as_of_dt.isoformat(),
                                observed_at=latest_bar.close_time.isoformat(),
                                market_session_date=latest_bar.session_date,
                                official_confirmation_status="EXCHANGE_CONFIRMED",
                                metadata={"bar_count": len(parsed.bar_set.bars)},
                            )
                            return ProviderResult(
                                provider=self.name,
                                capability=ProviderCapability.HISTORICAL_PRICE,
                                status=ProviderStatus.AVAILABLE,
                                observations=(obs,),
                                metadata={"contract_bar_set": parsed.bar_set},
                            )
                        return ProviderResult(
                            provider=self.name,
                            capability=ProviderCapability.HISTORICAL_PRICE,
                            status=ProviderStatus.UNAVAILABLE,
                            reason="; ".join(parsed.error_reasons) or "No valid completed Naver bars",
                            metadata={
                                "contract_ohlcv_parse_result": parsed,
                                "source_url": url,
                                "http_status": status_code,
                            },
                        )
                    return ProviderResult(
                        provider=self.name,
                        capability=ProviderCapability.HISTORICAL_PRICE,
                        status=ProviderStatus.UNAVAILABLE,
                        reason=f"HTTP_{status_code}",
                        metadata={"source_url": url, "http_status": status_code},
                    )
                except Exception as exc:
                    return ProviderResult(
                        provider=self.name,
                        capability=ProviderCapability.HISTORICAL_PRICE,
                        status=ProviderStatus.ERROR,
                        reason=f"Transport error on {url}: {exc}",
                    )

            elif instrument_id.startswith("NASDAQ:") or instrument_id.startswith("NYSE:"):
                ticker = instrument_id.split(":")[-1]
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1mo"
                try:
                    status_code, body, _ = self._transport(url, None, 10.0)
                    if status_code == 200:
                        parsed = parse_yahoo_chart_ohlcv(
                            body,
                            instrument_id=instrument_id,
                            interval=interval,
                            analysis_as_of=as_of_dt,
                        )
                        if parsed.is_usable and parsed.bar_set:
                            latest_bar = parsed.bar_set.bars[-1]
                            obs = ProviderObservation(
                                evidence_type="market",
                                source_name="yahoo_finance",
                                source_url=url,
                                source_tier=2,
                                provider_id=self.name,
                                value=latest_bar.close,
                                unit=latest_bar.currency,
                                currency=latest_bar.currency,
                                instrument_id=instrument_id,
                                metric="historical_ohlcv",
                                retrieved_at=as_of_dt.isoformat(),
                                observed_at=latest_bar.close_time.isoformat(),
                                market_session_date=latest_bar.session_date,
                                official_confirmation_status="EXCHANGE_CONFIRMED",
                                metadata={"bar_count": len(parsed.bar_set.bars)},
                            )
                            return ProviderResult(
                                provider=self.name,
                                capability=ProviderCapability.HISTORICAL_PRICE,
                                status=ProviderStatus.AVAILABLE,
                                observations=(obs,),
                                metadata={"contract_bar_set": parsed.bar_set},
                            )
                        return ProviderResult(
                            provider=self.name,
                            capability=ProviderCapability.HISTORICAL_PRICE,
                            status=ProviderStatus.UNAVAILABLE,
                            reason="; ".join(parsed.error_reasons) or "No valid completed Yahoo bars",
                            metadata={
                                "contract_ohlcv_parse_result": parsed,
                                "source_url": url,
                                "http_status": status_code,
                            },
                        )
                    return ProviderResult(
                        provider=self.name,
                        capability=ProviderCapability.HISTORICAL_PRICE,
                        status=ProviderStatus.UNAVAILABLE,
                        reason=f"HTTP_{status_code}",
                        metadata={"source_url": url, "http_status": status_code},
                    )
                except Exception as exc:
                    return ProviderResult(
                        provider=self.name,
                        capability=ProviderCapability.HISTORICAL_PRICE,
                        status=ProviderStatus.ERROR,
                        reason=f"Transport error on {url}: {exc}",
                    )

        return ProviderResult(
            provider=self.name,
            capability=ProviderCapability.HISTORICAL_PRICE,
            status=ProviderStatus.UNAVAILABLE,
            reason=f"No active transport or bundle available for {instrument_id}",
        )
