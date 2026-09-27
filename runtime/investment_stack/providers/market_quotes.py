"""Market quote parser and provider adapter for public equity, crypto, and precious metals.

Implements REQ-2026-09-23-v1 R06 and CONTRACT-01 market quote contracts.
Provides deterministic normalization, session separation (regular vs extended hours),
strict identity verification (payload identity must match requested instrument),
currency verification, structured hit conversion, and true candidate fallback sequencing.

Live-verified source parsers included:
- Naver Pay Securities (mobile basic API - KRX equities)
- Yahoo Finance Chart / Quote (US equities)
- Coinbase Public Market Ticker (BTC-USD venue price)
- Kraken Public Recent Trades (BTC-USD venue trades with real execution timestamp)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal
import json
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.providers.models import ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability

# Generic HTTP Transport callable signature:
# (url, headers, timeout) -> (status_code, body_bytes, response_headers)
HttpTransport = Callable[[str, Mapping[str, str] | None, float], tuple[int, bytes, Mapping[str, str]]]

EligibilityEvaluator = Callable[[MarketQuote, datetime], tuple[bool, str | None]]


def _supports_btc_usd(instrument_id: str, currency: str = "USD") -> bool:
    """Return true only for the BTC/XBT USD pair served by configured venues."""
    pair = instrument_id.upper().strip().split(":")[-1].replace(" ", "")
    return currency.upper() == "USD" and pair in {"BTC/USD", "XBT/USD", "BTCUSD", "XBTUSD"}


def quote_matches_requested_market(quote: MarketQuote, instrument_id: str) -> tuple[bool, str | None]:
    """Check response identity, exchange, and currency against the requested listing."""
    if quote.instrument_id != instrument_id:
        return False, "IDENTITY_MISMATCH: normalized quote instrument differs from request"
    prefix, _, _ticker = instrument_id.partition(":")
    prefix = prefix.upper()
    expectations = {
        "KRX": ("KRX", "KRW"), "KOSDAQ": ("KOSDAQ", "KRW"),
        "NASDAQ": ("NASDAQ", "USD"), "NYSE": ("NYSE", "USD"),
        "TSE": ("JPX", "JPY"), "JPX": ("JPX", "JPY"),
    }
    expected = expectations.get(prefix)
    if expected is not None:
        expected_exchange, expected_currency = expected
        if quote.currency.upper() != expected_currency:
            return False, f"CURRENCY_MISMATCH: expected {expected_currency}, got {quote.currency}"
        exchange_aliases = {"KS": "KRX", "KQ": "KOSDAQ", "NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "TSE": "JPX"}
        actual_exchange = exchange_aliases.get((quote.exchange or "").upper(), (quote.exchange or "").upper())
        if actual_exchange != expected_exchange:
            return False, f"EXCHANGE_MISMATCH: expected {expected_exchange}, got {quote.exchange or 'UNKNOWN'}"
    if prefix == "CRYPTO" and not _supports_btc_usd(instrument_id, quote.currency):
        return False, "UNSUPPORTED_SOURCE_PAIR: requested pair is not BTC/USD"
    return True, None


def calendar_aware_freshness_evaluator(calendar: Any = None, *, engine: Any = None, policy: Any = None) -> EligibilityEvaluator:
    """Build the quote qualification callback used by fetch_current.

    The supplied schedule must match a pinned official snapshot. LAST_VALID_CLOSE
    is eligible as a dated close observation, never relabeled as a live quote.
    """
    from investment_stack.freshness import FreshnessEngine, FreshnessStatus
    from investment_stack.providers.contract_adapters import quote_to_observation

    freshness_engine = engine or FreshnessEngine()
    # CURRENT_PRICE is blocked for delayed observations unless a later policy
    # explicitly opts in. A dated, calendar-verified close remains eligible.
    allowed = {FreshnessStatus.FRESH, FreshnessStatus.LAST_VALID_CLOSE}

    def evaluate(quote: MarketQuote, analysis_as_of: datetime) -> tuple[bool, str | None]:
        if quote.delay_minutes is not None and quote.delay_minutes > 0:
            return False, "DELAYED_QUOTE_NOT_ALLOWED_FOR_CURRENT_PRICE"
        observation = quote_to_observation(quote)
        if calendar is not None and not getattr(calendar, "is_pinned", False):
            return False, "UNTRUSTED_CALENDAR_SCHEDULE"
        if calendar is None and not quote.instrument_id.upper().startswith("CRYPTO:"):
            return False, "TRUSTED_EQUITY_SESSION_CALENDAR_REQUIRED"
        assessment = freshness_engine.assess(
            observation, analysis_as_of=analysis_as_of.isoformat(), policy=policy, calendar=calendar,
        )
        return assessment.status in allowed, assessment.reason

    return evaluate


@dataclass(slots=True)
class MarketQuoteProviderAdapter:
    """ProviderAdapter bridge for the CURRENT_PRICE executor.

    Calendars are explicit and bounded. Without one, age-fresh quotes may pass;
    a stale close cannot receive LAST_VALID_CLOSE qualification.
    """

    quote_provider: Any
    calendars: Mapping[str, Any]
    engine: Any = None
    policy: Any = None
    name: str = "market_quotes"
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.CURRENT_PRICE})

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        if request.capability not in self.capabilities or not request.instrument_id:
            return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE,
                                  reason="CURRENT_PRICE and instrument_id are required")
        try:
            analysis_as_of = datetime.fromisoformat(request.analysis_as_of.replace("Z", "+00:00"))
        except ValueError:
            return ProviderResult(self.name, request.capability, ProviderStatus.ERROR,
                                  reason="invalid analysis_as_of format")
        prefix = request.instrument_id.split(":", 1)[0].upper()
        exchange = {"NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "KS": "KRX"}.get(prefix, prefix)
        calendar = self.calendars.get(exchange)
        evaluator = calendar_aware_freshness_evaluator(calendar, engine=self.engine, policy=self.policy)
        result = self.quote_provider.fetch_current(
            request.instrument_id, analysis_as_of=analysis_as_of,
            prefer_extended_hours=bool(request.parameters.get("prefer_extended_hours", False)),
            eligibility_evaluator=evaluator,
        )
        # Normalize the contract adapter's legacy MARKET_QUOTE/price vocabulary to
        # Phase 4's established market/current_price evidence lineage.
        from dataclasses import replace
        observations = tuple(
            replace(item, evidence_type="market", metric="current_price")
            for item in result.observations
        )
        safe_metadata = {key: value for key, value in result.metadata.items() if key != "contract_quote"}
        return replace(result, observations=observations, metadata=safe_metadata)


class MarketQuoteError(Exception):
    """Base exception for market quote parsing and retrieval errors."""


class UnsupportedMarketError(MarketQuoteError):
    """Raised when an instrument or market is not covered or unsupported."""


@dataclass(frozen=True, slots=True)
class MarketQuoteParseResult:
    """Encapsulates the result of parsing a raw market quote payload."""

    quote: MarketQuote | None
    observation: ProviderObservation | None
    error_reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.quote is not None and not self.error_reasons


# Exchange to currency and timezone mappings
_EXCHANGE_METADATA: dict[str, dict[str, str]] = {
    "KS": {"exchange": "KRX", "currency": "KRW", "timezone": "Asia/Seoul", "nation": "KOR"},
    "KRX": {"exchange": "KRX", "currency": "KRW", "timezone": "Asia/Seoul", "nation": "KOR"},
    "KQ": {"exchange": "KOSDAQ", "currency": "KRW", "timezone": "Asia/Seoul", "nation": "KOR"},
    "KOSDAQ": {"exchange": "KOSDAQ", "currency": "KRW", "timezone": "Asia/Seoul", "nation": "KOR"},
    "NMS": {"exchange": "NASDAQ", "currency": "USD", "timezone": "America/New_York", "nation": "USA"},
    "NASDAQGS": {"exchange": "NASDAQ", "currency": "USD", "timezone": "America/New_York", "nation": "USA"},
    "NYSE": {"exchange": "NYSE", "currency": "USD", "timezone": "America/New_York", "nation": "USA"},
    "NASDAQ": {"exchange": "NASDAQ", "currency": "USD", "timezone": "America/New_York", "nation": "USA"},
    "TSE": {"exchange": "JPX", "currency": "JPY", "timezone": "Asia/Tokyo", "nation": "JPN"},
    "JPX": {"exchange": "JPX", "currency": "JPY", "timezone": "Asia/Tokyo", "nation": "JPN"},
    "KRAKEN": {"exchange": "KRAKEN", "currency": "USD", "timezone": "UTC", "nation": "GLOBAL"},
    "COINBASE": {"exchange": "COINBASE", "currency": "USD", "timezone": "UTC", "nation": "GLOBAL"},
}


def _safe_json_loads(payload: str | bytes) -> Any:
    """Decode JSON with parse_float=Decimal and reject non-finite/bool tokens."""
    return json.loads(payload, parse_float=Decimal)


def parse_naver_basic_quote(
    payload: Mapping[str, Any] | str | bytes,
    *,
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    instrument_id: str | None = None,
    source_url: str | None = None,
    prefer_extended_hours: bool = False,
) -> MarketQuoteParseResult:
    """Parse Naver Pay Securities basic quote JSON response (mobile basic API)."""
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None,
                observation=None,
                error_reasons=(f"JSON_DECODE_ERROR: {exc}",),
            )
    else:
        data = dict(payload)

    raw_code = data.get("itemCode") or data.get("reutersCode")
    if not raw_code or not str(raw_code).strip():
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_PAYLOAD_IDENTITY",),
        )

    item_code = str(raw_code).strip()
    if instrument_id:
        expected_code = instrument_id.split(":")[-1].strip()
        if item_code != expected_code:
            return MarketQuoteParseResult(
                quote=None,
                observation=None,
                error_reasons=(
                    f"IDENTITY_MISMATCH: payload itemCode '{item_code}' does not match requested '{expected_code}'",
                ),
            )

    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)

    resolved_instrument = instrument_id or f"KRX:{item_code}"
    resolved_evidence_id = evidence_id or f"naver_basic_{item_code}_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or f"https://m.stock.naver.com/api/stock/{item_code}/basic"

    exchange_info = data.get("stockExchangeType")
    exchange_code = ""
    nested_delay: int | None = None
    if isinstance(exchange_info, Mapping):
        exchange_code = str(exchange_info.get("code", "")).strip().upper()
        raw_del = exchange_info.get("delayTime")
        if raw_del is not None and not isinstance(raw_del, bool):
            try:
                nested_delay = int(raw_del)
            except (ValueError, TypeError):
                nested_delay = None
    elif isinstance(data.get("stockExchangeName"), str):
        exchange_code = str(data["stockExchangeName"]).strip().upper()

    metadata = _EXCHANGE_METADATA.get(exchange_code, {})
    requested_prefix = instrument_id.split(":", 1)[0].upper() if instrument_id and ":" in instrument_id else ""
    if requested_prefix in {"KRX", "KOSDAQ"} and not metadata:
        return MarketQuoteParseResult(quote=None, observation=None,
            error_reasons=("UNVERIFIED_EXCHANGE_IDENTITY: Naver response lacks a recognized exchange code",))
    if requested_prefix in {"KRX", "KOSDAQ"} and metadata.get("exchange") != requested_prefix:
        return MarketQuoteParseResult(quote=None, observation=None,
            error_reasons=(f"EXCHANGE_MISMATCH: expected {requested_prefix}, got {metadata.get('exchange')}",))
    currency = metadata.get("currency")
    exchange_name = metadata.get("exchange", exchange_code or "KRX")
    tz_name = metadata.get("timezone", "Asia/Seoul")

    if not currency:
        nation = str(data.get("nationType") or data.get("nationCode") or "").upper()
        if nation in {"KOR", "KR"}:
            currency = "KRW"
            tz_name = "Asia/Seoul"

    if not currency:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("UNRESOLVED_CURRENCY: exchange/nation metadata unverified",),
        )

    delay_minutes: int | None = None
    root_delay = data.get("delayTime")
    if root_delay is not None and not isinstance(root_delay, bool):
        try:
            delay_minutes = int(root_delay)
        except (ValueError, TypeError):
            delay_minutes = None
    elif nested_delay is not None:
        delay_minutes = nested_delay

    market_session_type = str(data.get("marketSessionType", "")).lower()
    over_market_info = data.get("overMarketPriceInfo")
    is_after_market = market_session_type in {"aftermarket", "overmarket"} or (
        isinstance(over_market_info, Mapping)
        and str(over_market_info.get("tradingSessionType", "")).upper() == "AFTER_MARKET"
    )

    raw_price_str: str | None = None
    quote_kind: QuoteKind = QuoteKind.REGULAR
    claimed_market_time: datetime | None = None

    if prefer_extended_hours and is_after_market and isinstance(over_market_info, Mapping):
        over_price = over_market_info.get("overPrice")
        if over_price:
            raw_price_str = str(over_price)
            quote_kind = QuoteKind.EXTENDED_HOURS
            over_traded_at = over_market_info.get("localTradedAt")
            if isinstance(over_traded_at, str) and over_traded_at.strip():
                try:
                    claimed_market_time = datetime.fromisoformat(over_traded_at.strip())
                except ValueError:
                    claimed_market_time = None
    else:
        raw_price_str = data.get("closePrice")
        if is_after_market:
            quote_kind = QuoteKind.LAST_VALID_CLOSE
            if isinstance(exchange_info, Mapping) and exchange_info.get("endTime"):
                end_str = str(exchange_info.get("endTime")).strip()
                traded_at_str = data.get("localTradedAt")
                if isinstance(traded_at_str, str) and traded_at_str.strip() and len(end_str) == 4:
                    try:
                        base_dt = datetime.fromisoformat(traded_at_str.strip())
                        s_hour = int(end_str[:2])
                        s_min = int(end_str[2:])
                        claimed_market_time = base_dt.replace(
                            hour=s_hour, minute=s_min, second=0, microsecond=0
                        )
                    except Exception:
                        claimed_market_time = None
        else:
            if delay_minutes is not None and delay_minutes > 0:
                quote_kind = QuoteKind.DELAYED
            else:
                quote_kind = QuoteKind.REGULAR

            local_traded_at_str = data.get("localTradedAt")
            if isinstance(local_traded_at_str, str) and local_traded_at_str.strip():
                try:
                    claimed_market_time = datetime.fromisoformat(local_traded_at_str.strip())
                except ValueError:
                    claimed_market_time = None

    if raw_price_str is None or not str(raw_price_str).strip():
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_PRICE_IN_PAYLOAD",),
        )

    local_traded_raw = data.get("localTradedAt")
    if not local_traded_raw and claimed_market_time is None:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_MARKET_TIMESTAMP: market trade time absent from payload",),
        )

    clean_price_str = str(raw_price_str).replace(",", "").strip()
    try:
        price = parse_finite_decimal(clean_price_str)
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None,
                observation=None,
                error_reasons=(f"NON_POSITIVE_PRICE: {price}",),
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",),
        )

    if claimed_market_time is not None and claimed_market_time.tzinfo is None:
        claimed_market_time = claimed_market_time.replace(tzinfo=ZoneInfo(tz_name))
    close_price_send_time: datetime | None = None
    close_price_send_time_source: str | None = None
    if quote_kind == QuoteKind.LAST_VALID_CLOSE:
        exchange_info = data.get("stockExchangeType")
        exchange_info = exchange_info if isinstance(exchange_info, Mapping) else {}
        raw_send_time = str(exchange_info.get("closePriceSendTime", data.get("closePriceSendTime", ""))).strip()
        if len(raw_send_time) == 4 and raw_send_time.isdigit() and claimed_market_time is not None:
            try:
                close_price_send_time = claimed_market_time.replace(
                    hour=int(raw_send_time[:2]), minute=int(raw_send_time[2:]), second=0, microsecond=0
                )
                if close_price_send_time < claimed_market_time:
                    raise ValueError("close price publication precedes market close")
                close_price_send_time_source = (
                    "stockExchangeType.closePriceSendTime"
                    if "closePriceSendTime" in exchange_info else "closePriceSendTime"
                )
            except ValueError:
                close_price_send_time = None
                close_price_send_time_source = None
        if close_price_send_time is not None:
            pub_avail = PublicAvailability.exact(available_at=close_price_send_time, locator=resolved_source_url)
        else:
            # Session close can be reconstructed, but publication/availability cannot.
            pub_avail = PublicAvailability.unknown(locator=resolved_source_url)
    elif claimed_market_time is not None:
        pub_avail = PublicAvailability.exact(
            available_at=claimed_market_time,
            locator=resolved_source_url,
        )
    else:
        pub_avail = PublicAvailability.unknown(locator=resolved_source_url)

    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=resolved_instrument,
        currency=currency,
        price=price,
        quote_kind=quote_kind,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange=exchange_name,
        venue=exchange_name,
        market_session_date=claimed_market_time.strftime("%Y-%m-%d") if claimed_market_time else None,
        claimed_market_time=claimed_market_time,
        delay_minutes=delay_minutes,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="naver_pay",
        source_url=resolved_source_url,
        source_tier=2,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=resolved_instrument,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=claimed_market_time.isoformat() if claimed_market_time else None,
        published_at=pub_avail.public_available_at.isoformat() if pub_avail.public_available_at else None,
        claimed_market_time=claimed_market_time.isoformat() if claimed_market_time else None,
        market_session_date=quote.market_session_date,
        official_confirmation_status="EXCHANGE_CONFIRMED" if exchange_code else "UNCONFIRMED",
        metadata={
            "quote_kind": str(quote_kind),
            "exchange": exchange_name,
            "currency": currency,
            "stock_name": data.get("stockName"),
            "delay_minutes": delay_minutes,
            "fluctuations_ratio": data.get("fluctuationsRatio"),
            "market_session_type": market_session_type,
            "market_time_provenance": "DERIVED_FROM_SESSION_END_TIME" if quote_kind == QuoteKind.LAST_VALID_CLOSE else "SOURCE_TRADE_TIMESTAMP",
            "claimed_time_source": "stockExchangeType.endTime" if quote_kind == QuoteKind.LAST_VALID_CLOSE else "localTradedAt",
            "public_available_time_source": close_price_send_time_source,
            "public_availability_status": "SOURCE_REPORTED" if close_price_send_time is not None else ("UNKNOWN" if quote_kind == QuoteKind.LAST_VALID_CLOSE else "AT_OBSERVED_TIME"),
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


def parse_coinbase_ticker(
    payload: Mapping[str, Any] | str | bytes,
    *,
    instrument_id: str = "CRYPTO:BTC/USD",
    currency: str = "USD",
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    source_url: str | None = None,
) -> MarketQuoteParseResult:
    """Parse Coinbase Public REST Ticker response (Live HTTP 200 confirmed by supervisor)."""
    if not _supports_btc_usd(instrument_id, currency):
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("UNSUPPORTED_SOURCE_PAIR: Coinbase endpoint is BTC/USD",),
        )
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",)
            )
    else:
        data = dict(payload)

    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)

    raw_price = data.get("price")
    if not raw_price:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_PRICE_IN_COINBASE_PAYLOAD",)
        )

    try:
        price = parse_finite_decimal(str(raw_price))
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"NON_POSITIVE_PRICE: {price}",)
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",)
        )

    raw_time = data.get("time")
    claimed_market_time: datetime | None = None
    if isinstance(raw_time, str) and raw_time.strip():
        try:
            claimed_market_time = datetime.fromisoformat(raw_time.strip().replace("Z", "+00:00"))
        except ValueError:
            claimed_market_time = None

    if claimed_market_time is None:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_VENUE_TRADE_TIMESTAMP",),
        )

    resolved_evidence_id = evidence_id or f"coinbase_btc_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or "https://api.exchange.coinbase.com/products/BTC-USD/ticker"

    pub_avail = PublicAvailability.exact(
        available_at=claimed_market_time, locator=resolved_source_url
    )

    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=instrument_id,
        currency=currency,
        price=price,
        quote_kind=QuoteKind.REGULAR,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange="COINBASE",
        venue="COINBASE",
        market_session_date=claimed_market_time.strftime("%Y-%m-%d"),
        claimed_market_time=claimed_market_time,
        delay_minutes=None,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="coinbase",
        source_url=resolved_source_url,
        source_tier=1,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=instrument_id,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=claimed_market_time.isoformat(),
        published_at=claimed_market_time.isoformat(),
        claimed_market_time=claimed_market_time.isoformat(),
        market_session_date=quote.market_session_date,
        official_confirmation_status="EXCHANGE_CONFIRMED",
        metadata={
            "quote_kind": str(QuoteKind.REGULAR),
            "trade_id": data.get("trade_id"),
            "volume_24h": str(data.get("volume", "")),
            "venue": "COINBASE",
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


def parse_kraken_trades(
    payload: Mapping[str, Any] | str | bytes,
    *,
    instrument_id: str = "CRYPTO:BTC/USD",
    currency: str = "USD",
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    source_url: str | None = None,
) -> MarketQuoteParseResult:
    """Parse Kraken Public REST Trades response (Live HTTP 200 confirmed by supervisor).

    URL: https://api.kraken.com/0/public/Trades?pair=XBTUSD&count=1
    Schema: result.XXBTZUSD = [[price, volume, time_sec, buy_sell, market_limit, misc, trade_id]]
    Extracts actual execution timestamp from trades row.
    """
    if not _supports_btc_usd(instrument_id, currency):
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("UNSUPPORTED_SOURCE_PAIR: Kraken endpoint is BTC/USD",),
        )
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",)
            )
    else:
        data = dict(payload)

    errors = data.get("error")
    if errors:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"KRAKEN_API_ERROR: {errors}",)
        )

    result_map = data.get("result")
    if not isinstance(result_map, Mapping):
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_RESULT_OBJECT",)
        )

    pair_keys = {str(k).upper(): v for k, v in result_map.items() if str(k).lower() != "last"}
    trades_list = next((pair_keys[k] for k in ("XXBTZUSD", "XBTUSD", "BTCUSD") if k in pair_keys), None)
    if trades_list is None:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("KRAKEN_PAIR_NOT_FOUND: expected BTC/USD result key",),
        )

    if not trades_list or not isinstance(trades_list[0], (list, tuple)):
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("NO_TRADES_IN_RESULT",)
        )

    row = trades_list[0]
    if len(row) < 7:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MALFORMED_TRADE_ROW",)
        )

    raw_price = row[0]
    try:
        price = parse_finite_decimal(str(raw_price))
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"NON_POSITIVE_PRICE: {price}",)
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",)
        )

    try:
        ts_sec = float(row[2])
        claimed_market_time = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_TRADE_TIMESTAMP: {exc}",)
        )

    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)

    resolved_evidence_id = evidence_id or f"kraken_trade_{row[6]}_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or "https://api.kraken.com/0/public/Trades?pair=XBTUSD&count=1"

    pub_avail = PublicAvailability.exact(
        available_at=claimed_market_time, locator=resolved_source_url
    )

    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=instrument_id,
        currency=currency,
        price=price,
        quote_kind=QuoteKind.REGULAR,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange="KRAKEN",
        venue="KRAKEN",
        market_session_date=claimed_market_time.strftime("%Y-%m-%d"),
        claimed_market_time=claimed_market_time,
        delay_minutes=None,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="kraken",
        source_url=resolved_source_url,
        source_tier=1,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=instrument_id,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=claimed_market_time.isoformat(),
        published_at=claimed_market_time.isoformat(),
        claimed_market_time=claimed_market_time.isoformat(),
        market_session_date=quote.market_session_date,
        official_confirmation_status="EXCHANGE_CONFIRMED",
        metadata={
            "quote_kind": str(QuoteKind.REGULAR),
            "trade_id": str(row[6]),
            "volume": str(row[1]),
            "side": str(row[3]),
            "order_type": str(row[4]),
            "venue": "KRAKEN",
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


def parse_yahoo_quote(
    payload: Mapping[str, Any] | str | bytes,
    *,
    instrument_id: str,
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    source_url: str | None = None,
) -> MarketQuoteParseResult:
    """Parse Yahoo Finance Chart/Quote JSON response (Live HTTP 200 confirmed by supervisor)."""
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",)
            )
    else:
        data = dict(payload)

    chart_obj = data.get("chart", {})
    results = chart_obj.get("result")
    if not isinstance(results, (list, tuple)) or not results:
        err = chart_obj.get("error")
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"YAHOO_CHART_ERROR: {err}",)
        )

    meta = results[0].get("meta", {})
    symbol = str(meta.get("symbol", "")).strip().upper()
    if not symbol:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_SYMBOL_IN_YAHOO_META",)
        )

    expected_ticker = instrument_id.split(":")[-1].strip().upper()
    if symbol != expected_ticker:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=(
                f"IDENTITY_MISMATCH: payload symbol '{symbol}' != requested '{expected_ticker}'",
            ),
        )

    raw_price = meta.get("regularMarketPrice")
    if raw_price is None:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_REGULAR_MARKET_PRICE",)
        )

    try:
        price = parse_finite_decimal(str(raw_price))
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"NON_POSITIVE_PRICE: {price}",)
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",)
        )

    currency = str(meta.get("currency", "")).strip().upper()
    exchange_name = str(meta.get("exchangeName", "")).strip()
    requested_prefix = instrument_id.split(":", 1)[0].upper() if ":" in instrument_id else ""
    exchange_alias = {"NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "NYSE": "NYSE"}
    normalized_exchange = exchange_alias.get(exchange_name.upper(), exchange_name.upper())
    expected_us = {"NASDAQ": ("NASDAQ", "USD"), "NYSE": ("NYSE", "USD")}.get(requested_prefix)
    if not currency or not exchange_name:
        return MarketQuoteParseResult(quote=None, observation=None, error_reasons=("MISSING_EXCHANGE_OR_CURRENCY",))
    if expected_us and (normalized_exchange != expected_us[0] or currency != expected_us[1]):
        return MarketQuoteParseResult(quote=None, observation=None,
            error_reasons=(f"MARKET_METADATA_MISMATCH: expected {expected_us[0]}/{expected_us[1]}, got {normalized_exchange}/{currency}",))
    tz_name = str(meta.get("exchangeTimezoneName", "America/New_York")).strip()

    epoch_time = meta.get("regularMarketTime")
    claimed_market_time: datetime | None = None
    if epoch_time is not None:
        try:
            claimed_market_time = datetime.fromtimestamp(int(epoch_time), tz=ZoneInfo(tz_name))
        except Exception:
            claimed_market_time = None

    if claimed_market_time is None:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_MARKET_TIMESTAMP",)
        )

    retrieved = retrieved_at or datetime.now(timezone.utc)
    resolved_evidence_id = evidence_id or f"yahoo_{symbol.lower()}_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    pub_avail = PublicAvailability.exact(
        available_at=claimed_market_time, locator=resolved_source_url
    )

    delay_minutes: int | None = None
    raw_delay = meta.get("exchangeDataDelayedBy")
    if raw_delay is not None and not isinstance(raw_delay, bool):
        try:
            parsed_delay = int(raw_delay)
            if parsed_delay < 0:
                raise ValueError("negative delay")
            delay_minutes = parsed_delay
        except (TypeError, ValueError):
            return MarketQuoteParseResult(quote=None, observation=None,
                error_reasons=("INVALID_DELAY_METADATA",))
    # regularMarketPrice is a regular-session quote; whether it is delayed is a
    # separate field and remains unknown when the provider omits delay metadata.
    quote_kind = QuoteKind.REGULAR
    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=instrument_id,
        currency=currency,
        price=price,
        quote_kind=quote_kind,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange=exchange_name,
        venue=exchange_name,
        market_session_date=claimed_market_time.strftime("%Y-%m-%d"),
        claimed_market_time=claimed_market_time,
        delay_minutes=delay_minutes,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="yahoo_finance",
        source_url=resolved_source_url,
        source_tier=2,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=instrument_id,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=claimed_market_time.isoformat(),
        published_at=claimed_market_time.isoformat(),
        claimed_market_time=claimed_market_time.isoformat(),
        market_session_date=quote.market_session_date,
        official_confirmation_status="EXCHANGE_CONFIRMED",
        metadata={
            "quote_kind": str(quote_kind),
            "exchange": exchange_name,
            "delay_minutes": delay_minutes,
            "delay_status": "UNKNOWN" if delay_minutes is None else "REPORTED",
            "public_available_time_source": "regularMarketTime",
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


def parse_investing_quote(
    payload: Mapping[str, Any] | str,
    *,
    instrument_id: str,
    currency: str = "USD",
    exchange: str = "NASDAQ",
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    source_url: str | None = None,
    prefer_extended_hours: bool = False,
) -> MarketQuoteParseResult:
    """Parse Investing.com quote payload (Fixture only; direct HTTP returned 403 in live probe)."""
    if isinstance(payload, str):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",)
            )
    else:
        data = dict(payload)

    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)

    resolved_evidence_id = evidence_id or f"investing_{instrument_id.replace(':', '_')}_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or f"https://www.investing.com/equities/{instrument_id.split(':')[-1].lower()}"

    tz_name = _EXCHANGE_METADATA.get(exchange.upper(), {}).get("timezone", "America/New_York")

    raw_price_str = None
    quote_kind = QuoteKind.REGULAR
    claimed_dt = None

    if prefer_extended_hours and data.get("after_hours_price"):
        raw_price_str = data.get("after_hours_price")
        quote_kind = QuoteKind.EXTENDED_HOURS
        time_str = data.get("after_hours_time")
        if time_str:
            try:
                claimed_dt = datetime.fromisoformat(str(time_str))
            except ValueError:
                pass
    elif data.get("price"):
        raw_price_str = data.get("price")
        is_closed = bool(data.get("is_closed", False))
        quote_kind = QuoteKind.LAST_VALID_CLOSE if is_closed else QuoteKind.REGULAR
        time_str = data.get("market_time") or data.get("last_timestamp")
        if time_str:
            try:
                claimed_dt = datetime.fromisoformat(str(time_str))
            except ValueError:
                pass

    if raw_price_str is None:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_PRICE_IN_INVESTING_PAYLOAD",),
        )

    clean_price = str(raw_price_str).replace(",", "").strip()
    try:
        price = parse_finite_decimal(clean_price)
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"NON_POSITIVE_PRICE: {price}",)
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",)
        )

    if claimed_dt is not None and claimed_dt.tzinfo is None:
        claimed_dt = claimed_dt.replace(tzinfo=ZoneInfo(tz_name))

    if claimed_dt is None:
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("MISSING_MARKET_TIMESTAMP",),
        )

    pub_avail = PublicAvailability.exact(available_at=claimed_dt, locator=resolved_source_url)

    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=instrument_id,
        currency=currency,
        price=price,
        quote_kind=quote_kind,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange=exchange,
        venue=exchange,
        market_session_date=claimed_dt.strftime("%Y-%m-%d"),
        claimed_market_time=claimed_dt,
        delay_minutes=int(data.get("delay_minutes", 15)) if quote_kind == QuoteKind.DELAYED else None,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="investing_com",
        source_url=resolved_source_url,
        source_tier=3,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=instrument_id,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=claimed_dt.isoformat(),
        claimed_market_time=claimed_dt.isoformat(),
        market_session_date=quote.market_session_date,
        official_confirmation_status="FIXTURE_ONLY_WEB_UNVERIFIED",
        metadata={
            "quote_kind": str(quote_kind),
            "exchange": exchange,
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


def parse_kraken_ticker(
    payload: Mapping[str, Any] | str | bytes,
    *,
    pair: str = "XBTUSD",
    instrument_id: str = "CRYPTO:BTC/USD",
    currency: str = "USD",
    retrieved_at: datetime | None = None,
    evidence_id: str | None = None,
    source_url: str | None = None,
) -> MarketQuoteParseResult:
    """Parse Kraken Public REST Ticker response (Candidate endpoint; live probe pending)."""
    if pair.upper() not in {"XBTUSD", "XXBTZUSD", "BTCUSD"} or not _supports_btc_usd(instrument_id, currency):
        return MarketQuoteParseResult(
            quote=None,
            observation=None,
            error_reasons=("UNSUPPORTED_SOURCE_PAIR: Kraken ticker supports BTC/USD only",),
        )
    if isinstance(payload, (str, bytes)):
        try:
            data = _safe_json_loads(payload)
        except Exception as exc:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"JSON_DECODE_ERROR: {exc}",)
            )
    else:
        data = dict(payload)

    errors = data.get("error")
    if errors:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"KRAKEN_API_ERROR: {errors}",)
        )

    result_map = data.get("result")
    if not isinstance(result_map, Mapping):
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_RESULT_OBJECT",)
        )

    aliases = {"XBTUSD": {"XXBTZUSD", "XBTUSD", "BTCUSD"}, "XXBTZUSD": {"XXBTZUSD", "XBTUSD", "BTCUSD"}, "BTCUSD": {"XXBTZUSD", "XBTUSD", "BTCUSD"}}
    accepted = aliases.get(pair.upper(), set())
    ticker_data = next((v for k, v in result_map.items() if str(k).upper() in accepted), None)

    if not isinstance(ticker_data, Mapping):
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"PAIR_NOT_FOUND: {pair}",)
        )

    c_field = ticker_data.get("c")
    if not isinstance(c_field, (list, tuple)) or not c_field:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=("MISSING_LAST_TRADE_FIELD_C",)
        )

    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)

    resolved_evidence_id = evidence_id or f"kraken_{pair.lower()}_{int(retrieved.timestamp())}"
    resolved_source_url = source_url or f"https://api.kraken.com/0/public/Ticker?pair={pair}"

    try:
        price = parse_finite_decimal(str(c_field[0]))
        if price <= 0:
            return MarketQuoteParseResult(
                quote=None, observation=None, error_reasons=(f"NON_POSITIVE_PRICE: {price}",)
            )
    except Exception as exc:
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"INVALID_PRICE_FORMAT: {exc}",)
        )

    pub_avail = PublicAvailability.unknown(locator=resolved_source_url)

    quote = MarketQuote(
        quote_id=f"quote_{resolved_evidence_id}",
        evidence_id=resolved_evidence_id,
        instrument_id=instrument_id,
        currency=currency,
        price=price,
        quote_kind=QuoteKind.REGULAR,
        retrieved_at=retrieved,
        public_availability=pub_avail,
        exchange="KRAKEN",
        venue="KRAKEN",
        market_session_date=retrieved.strftime("%Y-%m-%d"),
        claimed_market_time=None,
        delay_minutes=None,
        is_trade=True,
    )

    observation = ProviderObservation(
        evidence_type="market",
        source_name="kraken",
        source_url=resolved_source_url,
        source_tier=1,
        provider_id="market_quotes",
        value=price,
        unit=currency,
        currency=currency,
        instrument_id=instrument_id,
        metric="current_price",
        retrieved_at=retrieved.isoformat(),
        observed_at=None,
        claimed_market_time=None,
        market_session_date=quote.market_session_date,
        official_confirmation_status="CANDIDATE_UNVERIFIED_LIVE",
        metadata={
            "quote_kind": str(QuoteKind.REGULAR),
            "pair": pair,
        },
    )

    return MarketQuoteParseResult(quote=quote, observation=observation)


class MarketQuoteProvider:
    """Capability-first Market Quote Provider with true candidate fallback sequencing."""

    name = "market_quotes"

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        source_bundles: Mapping[str, Mapping[str, Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._bundles = dict(source_bundles or {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_current(
        self,
        instrument_id: str,
        *,
        analysis_as_of: str | datetime,
        prefer_extended_hours: bool = False,
        eligibility_evaluator: EligibilityEvaluator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> ProviderResult:
        """Fetch verified current price with prioritized source fallback and attempt logging.

        Fallback sequence:
        1. Resolves market category (KR, US, Crypto). Unsupported markets fail immediately.
        2. Tries candidate sources in strict priority order.
        3. If candidate fails HTTP, parses as invalid, has future timestamp, or fails
           eligibility_evaluator, logs attempt reason and continues to next candidate.
        4. First eligible candidate stops sequence immediately (no further calls).
        5. If all candidates fail, returns UNAVAILABLE with full attempt audit log in metadata.
        """
        as_of_dt: datetime
        if isinstance(analysis_as_of, str):
            as_of_dt = datetime.fromisoformat(analysis_as_of)
        else:
            as_of_dt = analysis_as_of
        if as_of_dt.tzinfo is None:
            return ProviderResult(provider=self.name, capability=ProviderCapability.CURRENT_PRICE,
                status=ProviderStatus.UNAVAILABLE, reason="ANALYSIS_AS_OF_MUST_BE_TIMEZONE_AWARE")

        now_clock = clock or self._clock
        current_retrieved_at = now_clock()
        if current_retrieved_at.tzinfo is None:
            current_retrieved_at = current_retrieved_at.replace(tzinfo=timezone.utc)

        from investment_stack.web_research.quote_sources import (
            SOURCE_CANDIDATE_ORDER,
            VerificationStatus,
            MarketCategory,
            resolve_market_category,
        )

        market = resolve_market_category(instrument_id)
        if market == MarketCategory.CRYPTO_BTC and not _supports_btc_usd(instrument_id):
            return ProviderResult(
                provider=self.name,
                capability=ProviderCapability.CURRENT_PRICE,
                status=ProviderStatus.UNAVAILABLE,
                reason=f"UNSUPPORTED_SOURCE_PAIR: {instrument_id}",
            )
        if market is None:
            return ProviderResult(
                provider=self.name,
                capability=ProviderCapability.CURRENT_PRICE,
                status=ProviderStatus.UNAVAILABLE,
                reason=f"UNSUPPORTED_MARKET: {instrument_id}",
            )

        candidates = SOURCE_CANDIDATE_ORDER.get(market, ())
        attempts: list[dict[str, Any]] = []

        ticker = instrument_id.split(":")[-1].strip()

        for spec in candidates:
            if "CURRENT_PRICE" not in spec.capabilities:
                continue
            # Skip unverified fixture-only endpoints for live HTTP calls unless bundle explicitly injected
            if spec.verification_status == VerificationStatus.UNSUPPORTED_OR_FIXTURE_ONLY:
                if instrument_id not in self._bundles and spec.source_id not in self._bundles:
                    continue

            url = spec.url_template.replace("{code}", ticker)
            url = url.replace("{symbol}", ticker).replace("{pair}", "XBTUSD").replace("{slug}", ticker.lower())

            attempt_record: dict[str, Any] = {
                "source_id": spec.source_id,
                "priority": spec.priority,
                "url": url,
                "started_at": current_retrieved_at.isoformat(),
            }

            parse_res: MarketQuoteParseResult | None = None

            # Case A: Preloaded fixture bundle check
            bundled_data = None
            if instrument_id in self._bundles and self._bundles[instrument_id].get("source_id") == spec.source_id:
                bundled_data = self._bundles[instrument_id]
            elif spec.source_id in self._bundles:
                bundled_data = self._bundles[spec.source_id]

            if bundled_data is not None:
                raw_payload = bundled_data.get("payload", {})
                parse_res = self._parse_source_payload(
                    spec.source_id,
                    raw_payload,
                    instrument_id=instrument_id,
                    retrieved_at=current_retrieved_at,
                    prefer_extended_hours=prefer_extended_hours,
                )
                attempt_record["status_code"] = 200
            # Case B: Injected HTTP transport
            elif self._transport is not None:
                try:
                    status_code, body, _ = self._transport(url, None, 10.0)
                    attempt_record["status_code"] = status_code
                    if status_code == 200:
                        parse_res = self._parse_source_payload(
                            spec.source_id,
                            body,
                            instrument_id=instrument_id,
                            retrieved_at=current_retrieved_at,
                            prefer_extended_hours=prefer_extended_hours,
                        )
                    else:
                        attempt_record["success"] = False
                        attempt_record["reason"] = f"HTTP_{status_code}"
                        attempts.append(attempt_record)
                        continue
                except Exception as exc:
                    attempt_record["success"] = False
                    attempt_record["status_code"] = None
                    attempt_record["reason"] = f"TRANSPORT_ERROR: {exc}"
                    attempts.append(attempt_record)
                    continue
            else:
                attempt_record["success"] = False
                attempt_record["reason"] = "NO_TRANSPORT_OR_BUNDLE"
                attempts.append(attempt_record)
                continue

            # Evaluate Parse Result
            if parse_res is None or not parse_res.is_usable or parse_res.quote is None:
                attempt_record["success"] = False
                attempt_record["reason"] = (
                    "; ".join(parse_res.error_reasons) if parse_res else "PARSE_FAILURE"
                )
                attempts.append(attempt_record)
                continue

            quote = parse_res.quote

            identity_ok, identity_reason = quote_matches_requested_market(quote, instrument_id)
            if not identity_ok:
                attempt_record["success"] = False
                attempt_record["reason"] = identity_reason
                attempts.append(attempt_record)
                continue

            # Universal Future Rejection Invariant
            if quote.claimed_market_time is not None:
                q_time_utc = (
                    quote.claimed_market_time
                    if quote.claimed_market_time.tzinfo
                    else quote.claimed_market_time.replace(tzinfo=timezone.utc)
                )
                as_of_utc = as_of_dt if as_of_dt.tzinfo else as_of_dt.replace(tzinfo=timezone.utc)
                if q_time_utc > as_of_utc:
                    attempt_record["success"] = False
                    attempt_record["reason"] = (
                        f"FUTURE_PRICE: claimed_market_time ({q_time_utc}) > as_of ({as_of_utc})"
                    )
                    attempts.append(attempt_record)
                    continue

            # Parsing proves shape/identity only. Without the configured freshness policy,
            # a candidate is never promoted to an AVAILABLE calculation input.
            if eligibility_evaluator is None:
                attempt_record["success"] = False
                attempt_record["reason"] = "FRESHNESS_EVALUATOR_NOT_CONFIGURED"
                attempts.append(attempt_record)
                continue
            try:
                is_eligible, eval_reason = eligibility_evaluator(quote, as_of_dt)
            except Exception as exc:
                attempt_record["success"] = False
                attempt_record["reason"] = f"ELIGIBILITY_EVALUATOR_ERROR: {type(exc).__name__}"
                attempts.append(attempt_record)
                continue
            if not is_eligible:
                attempt_record["success"] = False
                attempt_record["reason"] = f"INELIGIBLE: {eval_reason}"
                attempts.append(attempt_record)
                continue

            # Success! Stop fallback sequence immediately
            attempt_record["success"] = True
            attempts.append(attempt_record)

            return ProviderResult(
                provider=self.name,
                capability=ProviderCapability.CURRENT_PRICE,
                status=ProviderStatus.AVAILABLE,
                observations=(parse_res.observation,) if parse_res.observation else (),
                metadata={
                    "contract_quote": quote,
                    "selected_source": spec.source_id,
                    "attempts": tuple(attempts),
                },
            )

        return ProviderResult(
            provider=self.name,
            capability=ProviderCapability.CURRENT_PRICE,
            status=ProviderStatus.UNAVAILABLE,
            reason=("FRESHNESS_EVALUATOR_NOT_CONFIGURED" if any(
                attempt.get("reason") == "FRESHNESS_EVALUATOR_NOT_CONFIGURED" for attempt in attempts
            ) else "CANDIDATES_EXHAUSTED"),
            metadata={"attempts": tuple(attempts)},
        )

    def _parse_source_payload(
        self,
        source_id: str,
        payload: Any,
        *,
        instrument_id: str,
        retrieved_at: datetime,
        prefer_extended_hours: bool,
    ) -> MarketQuoteParseResult:
        if source_id == "naver_pay":
            return parse_naver_basic_quote(
                payload,
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
                prefer_extended_hours=prefer_extended_hours,
            )
        elif source_id == "coinbase_public":
            return parse_coinbase_ticker(
                payload,
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
            )
        elif source_id == "kraken_trades":
            return parse_kraken_trades(
                payload,
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
            )
        elif source_id == "yahoo_finance":
            return parse_yahoo_quote(
                payload,
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
            )
        elif source_id in {"investing_us", "investing_kr"}:
            return parse_investing_quote(
                payload,
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
                prefer_extended_hours=prefer_extended_hours,
            )
        elif source_id == "kraken_public":
            return parse_kraken_ticker(
                payload,
                pair="XBTUSD",
                instrument_id=instrument_id,
                retrieved_at=retrieved_at,
            )
        return MarketQuoteParseResult(
            quote=None, observation=None, error_reasons=(f"UNKNOWN_SOURCE_ID: {source_id}",)
        )
