"""Optional quote-body capture. Japan listings are not requested.

The captured body still has to pass the stored-document reparse before a D12
price can use it. This module does not place orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.freshness import FreshnessEngine, FreshnessStatus, get_pinned_calendar
from investment_stack.providers.market_quotes import parse_naver_basic_quote, parse_yahoo_quote
from investment_stack.providers.models import ProviderObservation


@dataclass(frozen=True, slots=True)
class QuoteCapture:
    instrument_id: str
    parser_id: str
    body: str
    price: str
    currency: str
    exchange: str = ""
    claimed_market_time: datetime | None = None
    market_session_date: str = ""
    quote_kind: str = "REGULAR"
    source_url: str = ""


def capture_quote_body(instrument_id: str, *, transport, retrieved_at) -> QuoteCapture | None:
    """Fetch one public quote body. `transport(url, headers, timeout)` returns (status, body, headers)."""
    prefix, _, symbol = instrument_id.partition(":")
    prefix = prefix.upper()
    if not symbol:
        return None
    if prefix in {"NASDAQ", "NYSE"}:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        parser_id = "yahoo_chart_v1"
        parse = lambda body: parse_yahoo_quote(body, instrument_id=instrument_id, retrieved_at=retrieved_at)
    elif prefix in {"JPX", "TSE"}:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.T"
        parser_id = "yahoo_chart_v1"
        parse = lambda body: parse_yahoo_quote(body, instrument_id=instrument_id, retrieved_at=retrieved_at)
    elif prefix in {"KRX", "KOSDAQ"}:
        url = f"https://m.stock.naver.com/api/stock/{symbol}/basic"
        parser_id = "naver_quote_v1"
        parse = lambda body: parse_naver_basic_quote(body, instrument_id=instrument_id, retrieved_at=retrieved_at)
    else:
        return None
    try:
        status, body, _headers = transport(url, {}, 10.0)
    except (OSError, TimeoutError, ValueError):
        return None
    if status != 200 or body is None:
        return None
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    parsed = parse(text)
    quote = parsed.quote
    if quote is None:
        return None
    kind = getattr(quote.quote_kind, "value", quote.quote_kind)
    return QuoteCapture(
        instrument_id, parser_id, text, str(quote.price), str(quote.currency),
        exchange=str(quote.exchange or ""),
        claimed_market_time=quote.claimed_market_time,
        market_session_date=str(quote.market_session_date or ""),
        quote_kind=str(kind or "REGULAR"),
        source_url=url,
    )


def _urllib_status_transport(url: str, headers, timeout: float):
    from investment_stack.providers.http import urllib_transport

    body = urllib_transport(url, headers or {}, timeout)
    return 200, body, {}


_QUOTE_UNITS = {"USD": "USD/share", "KRW": "KRW/share", "JPY": "JPY/share"}


def _evidence_id(capture: QuoteCapture, retrieved_at: datetime) -> str:
    stamp = retrieved_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"quote-refresh-{capture.instrument_id.replace(':', '-')}-{stamp}"


def _analysis_cutoff(run) -> datetime | None:
    metadata = run.fetch_metadata()
    raw = metadata.get("analysis_as_of") if isinstance(metadata, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def store_unselected_capture(run, capture: QuoteCapture, *, retrieved_at: datetime) -> str:
    """Save a fetched body without selecting it. Selection still requires the receipt path."""
    evidence_id = _evidence_id(capture, retrieved_at)
    run.add_phase4_evidence(
        evidence_id=evidence_id,
        evidence_type="market",
        source_uri=capture.source_url or None,
        retrieved_at=retrieved_at.isoformat(),
        instrument_id=capture.instrument_id,
        metric="current_price",
        value=capture.price,
        currency=capture.currency,
        source_name=capture.parser_id,
        provider_id="quote_refresh",
        metadata={"quote_refresh": True},
    )
    run.add_source_document(
        document_id=f"doc-{evidence_id}",
        evidence_id=evidence_id,
        parser_id=capture.parser_id,
        payload_text=capture.body,
    )
    return evidence_id


def store_qualified_capture(run, capture: QuoteCapture, *, retrieved_at: datetime) -> str:
    """Store a public quote and select it only when freshness and the pinned calendar agree."""
    cutoff = _analysis_cutoff(run)
    claimed = capture.claimed_market_time
    unit = _QUOTE_UNITS.get(capture.currency.upper())
    prefix = capture.instrument_id.partition(":")[0].upper()
    exchange = {"TSE": "JPX", "TYO": "JPX", "NMS": "NASDAQ", "NYQ": "NYSE"}.get(prefix, prefix)
    if prefix in {"TSE", "JPX"}:
        exchange = "JPX"
    calendar = get_pinned_calendar(exchange)
    if cutoff is None or claimed is None or unit is None or calendar is None:
        return store_unselected_capture(run, capture, retrieved_at=retrieved_at)
    observed = claimed.isoformat()
    observation = ProviderObservation(
        evidence_type="market", source_name=capture.parser_id, source_url=capture.source_url,
        source_tier=2, provider_id="quote_refresh", value=Decimal(capture.price), unit=unit,
        currency=capture.currency, instrument_id=capture.instrument_id, metric="current_price",
        retrieved_at=retrieved_at.isoformat(), observed_at=observed, published_at=observed,
        claimed_market_time=observed, market_session_date=capture.market_session_date,
        metadata={"quote_kind": capture.quote_kind, "exchange": exchange},
    )
    assessed = FreshnessEngine().assess(observation, analysis_as_of=cutoff.isoformat(), calendar=calendar)
    if assessed.status not in {FreshnessStatus.FRESH, FreshnessStatus.DELAYED, FreshnessStatus.LAST_VALID_CLOSE}:
        return store_unselected_capture(run, capture, retrieved_at=retrieved_at)
    evidence_id = _evidence_id(capture, retrieved_at)
    run.add_phase4_evidence(
        evidence_id=evidence_id, evidence_type="market", source_uri=capture.source_url,
        retrieved_at=retrieved_at.isoformat(), instrument_id=capture.instrument_id,
        metric="current_price", value=capture.price, unit=unit, currency=capture.currency,
        source_name=capture.parser_id, source_tier=2, observed_at=observed, published_at=observed,
        freshness_status=assessed.status.value, provider_id="quote_refresh",
        metadata={"quote_refresh": True},
    )
    run.add_market_observation(
        observation_id=f"obs-{evidence_id}", evidence_id=evidence_id,
        instrument_id=capture.instrument_id, observed_at=observed, value=capture.price,
        unit=unit, currency=capture.currency, claimed_market_time=observed,
        market_session_date=capture.market_session_date, provider_id="quote_refresh",
        freshness_status=assessed.status.value,
        metadata={"quote_kind": capture.quote_kind, "exchange": exchange},
    )
    run.add_freshness_assessment(
        freshness_id=f"fresh-{evidence_id}", evidence_id=evidence_id, status=assessed.status.value,
        details={
            "quote_kind": assessed.quote_kind or capture.quote_kind,
            "effective_time": assessed.effective_time,
            "public_available_time": assessed.public_available_time or observed,
            "market_session_date": assessed.market_session_date or capture.market_session_date,
            "calendar_id": assessed.calendar_id,
        },
    )
    run.add_source_document(
        document_id=f"doc-{evidence_id}", evidence_id=evidence_id,
        parser_id=capture.parser_id, payload_text=capture.body,
    )
    run.mark_evidence_selected(evidence_id=evidence_id, reason="public quote body reparsed and freshness matched")
    return evidence_id


def refresh_requested_quotes(run, payload: dict, *, transport=None, retrieved_at: datetime | None = None) -> tuple[str, ...]:
    """Capture public quote bodies only when the caller sets refresh_market_bodies true."""
    if payload.get("refresh_market_bodies") is not True:
        return ()
    raw = payload.get("instrument_ids", payload.get("instrument_id"))
    if isinstance(raw, str):
        identifiers = (raw,)
    elif isinstance(raw, (list, tuple)):
        identifiers = tuple(str(item) for item in raw)
    else:
        identifiers = ()
    fetch = transport or _urllib_status_transport
    when = retrieved_at or datetime.now(timezone.utc)
    stored: list[str] = []
    for instrument_id in identifiers:
        captured = capture_quote_body(instrument_id, transport=fetch, retrieved_at=when)
        if captured is None:
            continue
        stored.append(store_qualified_capture(run, captured, retrieved_at=when))
    return tuple(stored)
