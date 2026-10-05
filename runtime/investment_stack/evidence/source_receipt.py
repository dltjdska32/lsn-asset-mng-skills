"""Re-extract facts from stored source bodies.

A URL, provider name, or matching database row is not evidence that a source
supports a number. The stored SHA-256 proves only that the body was not
changed after it was saved. It does not prove that a provider or an official
filing published that body. Unknown bodies fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from investment_stack.providers.market_quotes import parse_naver_basic_quote, parse_yahoo_quote


_EXCHANGE_ALIASES = {
    "NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "KS": "KRX",
    "TSE": "JPX", "TYO": "JPX",
}
_UNVERIFIED_EXCHANGES = frozenset()
_QUOTE_PARSERS = frozenset({"yahoo_chart_v1", "naver_quote_v1"})
_DCF_RECORD = "explicit_dcf_assumption_v1"
_RULE_RECORD = "exchange_trading_rule_v1"
_THESIS_RECORD = "thesis_status_v1"
_FX_PARSER = "yahoo_fx_v1"


def payload_sha256(payload: str) -> str:
    if not isinstance(payload, str) or payload == "":
        raise ValueError("source payload must be a non-empty string")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_table_available(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_documents'"
    ).fetchone()
    return row is not None


def _dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _json_object(payload: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _excerpt_contains(excerpt: str, token: str) -> bool:
    if not token:
        return False
    return re.search(rf"(?<![\w.]){re.escape(token)}(?![\w.])", excerpt) is not None


def _value_tokens(value: Decimal) -> tuple[str, ...]:
    tokens = {str(value), format(value, "f")}
    if value == value.to_integral_value():
        tokens.add(str(int(value)))
    return tuple(token for token in tokens if token)


def load_source_payload(
    connection: sqlite3.Connection, *, run_id: str, evidence_id: str,
) -> tuple[str, str] | None:
    """Return payload and parser id when the stored hash matches the body."""
    if not source_table_available(connection):
        return None
    rows = connection.execute(
        "SELECT parser_id, content_sha256, payload_text FROM source_documents "
        "WHERE run_id = ? AND evidence_id = ?",
        (run_id, evidence_id),
    ).fetchall()
    if len(rows) != 1:
        return None
    parser_id, digest, payload = rows[0][0], rows[0][1], rows[0][2]
    if not isinstance(payload, str) or not isinstance(parser_id, str) or not isinstance(digest, str):
        return None
    try:
        actual = payload_sha256(payload)
    except ValueError:
        return None
    if actual != digest:
        return None
    return payload, parser_id


def _normalize_exchange(value: object) -> str:
    text = str(value or "").strip().upper()
    return _EXCHANGE_ALIASES.get(text, text)


def verify_quote_body(
    payload: str,
    parser_id: str,
    *,
    instrument_id: str,
    currency: str,
    price: Decimal,
    observed_at: datetime,
    exchange: str,
    session_date: str | None,
    retrieved_at: datetime,
) -> tuple[bool, str | None]:
    """Re-parse a provider body and compare identity, currency, time, and price."""
    if parser_id not in _QUOTE_PARSERS:
        return False, "quote source document uses an unregistered parser"
    if parser_id == "yahoo_chart_v1":
        parsed = parse_yahoo_quote(
            payload, instrument_id=instrument_id, retrieved_at=retrieved_at, evidence_id="receipt",
        )
    else:
        parsed = parse_naver_basic_quote(
            payload, instrument_id=instrument_id, retrieved_at=retrieved_at, evidence_id="receipt",
        )
    quote = parsed.quote
    if quote is None:
        detail = ", ".join(parsed.error_reasons) or "unparsed"
        return False, f"quote source body could not be re-extracted ({detail})"
    if quote.instrument_id != instrument_id or str(quote.currency or "").upper() != currency.upper():
        return False, "re-extracted quote instrument or currency does not match the persisted observation"
    if quote.price != price:
        return False, "re-extracted quote price does not match the persisted observation"
    claimed = quote.claimed_market_time
    if claimed is None or claimed.tzinfo is None or claimed != observed_at:
        return False, "re-extracted quote observation time does not match the persisted observation"
    normalized_exchange = _normalize_exchange(quote.exchange)
    requested_exchange = _normalize_exchange(exchange)
    instrument_prefix = instrument_id.partition(":")[0].upper()
    if normalized_exchange in _UNVERIFIED_EXCHANGES or requested_exchange in _UNVERIFIED_EXCHANGES:
        return False, "quote exchange has no pinned trading calendar"
    if instrument_prefix in {"JPX", "TSE"} and normalized_exchange != "JPX":
        return False, "re-extracted quote exchange does not match the Japanese listing"
    if normalized_exchange != requested_exchange:
        return False, "re-extracted quote exchange does not match the persisted session"
    if session_date is not None and quote.market_session_date != session_date:
        return False, "re-extracted quote session date does not match the persisted session"
    return True, None


def verify_dcf_assumption_body(
    payload: str,
    *,
    scenario: str,
    field: str,
    value: Decimal,
    unit: str,
    currency: str | None,
    cutoff: datetime,
) -> str | None:
    """Return a failure reason when an assumption body is not an explicit excerpt."""
    document = _json_object(payload)
    if document is None or document.get("record_type") != _DCF_RECORD:
        return "DCF assumption source body is not an explicit assumption record"
    if any(str(key).casefold() in {"default", "beta", "equity_risk_premium", "erp"} for key in document):
        return "DCF assumption source body contains an unsupported default field"
    if str(document.get("scenario") or "").casefold() != scenario.casefold() or document.get("field") != field:
        return "DCF assumption source body does not identify the persisted scenario field"
    if document.get("unit") != unit:
        return "DCF assumption source body unit does not match persisted evidence"
    body_currency = document.get("currency")
    if currency:
        if str(body_currency or "").upper() != currency.upper():
            return "DCF assumption source body currency does not match persisted evidence"
    elif body_currency not in (None, ""):
        return "DCF assumption source body unexpectedly carries currency"
    published = _dt(document.get("published_at"))
    if published is None or published > cutoff:
        return "DCF assumption source body has a missing or future publication time"
    excerpt = document.get("source_excerpt")
    if not isinstance(excerpt, str) or len(excerpt.strip()) < 24 or field not in excerpt:
        return "DCF assumption value is not contained in a source excerpt"
    basis = str(document.get("cash_flow_basis") or "").upper()
    if field == "starting_fcf":
        if basis not in {"FCFF", "FCFE"}:
            return "DCF starting cash flow basis is not explicit FCFF or FCFE"
        if basis not in excerpt:
            return "DCF starting cash flow basis is not contained in a source excerpt"
    elif basis:
        return "DCF assumption source body carries a cash-flow basis on a non-cash-flow field"
    if not any(_excerpt_contains(excerpt, token) for token in _value_tokens(value)):
        return "DCF assumption value is not contained in a source excerpt"
    body_value = _decimal(document.get("value"))
    if body_value != value:
        return "DCF assumption source body value does not match persisted evidence"
    return None


def read_cash_flow_basis(payload: str) -> str | None:
    """Return FCFF or FCFE only when the stored assumption body says so."""
    document = _json_object(payload)
    if document is None:
        return None
    basis = str(document.get("cash_flow_basis") or "").upper()
    if basis not in {"FCFF", "FCFE"}:
        return None
    return basis


def verify_trading_rule_body(
    payload: str, *, instrument_id: str, currency: str, cutoff: datetime,
) -> tuple[dict[str, Decimal] | None, str | None]:
    document = _json_object(payload)
    if document is None or document.get("record_type") != _RULE_RECORD:
        return None, "trading rule source body is not an exchange rule record"
    if document.get("instrument_id") != instrument_id or str(document.get("currency") or "").upper() != currency.upper():
        return None, "trading rule source body instrument or currency does not match"
    published = _dt(document.get("published_at"))
    if published is None or published > cutoff:
        return None, "trading rule source body has a missing or future publication time"
    excerpt = document.get("rule_excerpt")
    numbers: dict[str, Decimal] = {}
    for field in ("lot_size", "price_tick", "fee_per_unit"):
        number = _decimal(document.get(field))
        if number is None:
            return None, f"trading rule {field} is missing"
        numbers[field] = number
    if numbers["lot_size"] <= 0 or numbers["price_tick"] <= 0 or numbers["fee_per_unit"] < 0:
        return None, "trading rule lot, tick, or fee is invalid"
    if not isinstance(excerpt, str) or instrument_id not in excerpt or currency.upper() not in excerpt.upper():
        return None, "trading rule numbers are not contained in a source excerpt"
    for field, number in numbers.items():
        if not any(_excerpt_contains(excerpt, f"{field}={token}") for token in _value_tokens(number)):
            return None, "trading rule numbers are not contained in a source excerpt"
    return numbers, None


def verify_thesis_body(
    payload: str, *, instrument_id: str, cutoff: datetime,
) -> tuple[bool | None, str | None]:
    document = _json_object(payload)
    if document is None or document.get("record_type") != _THESIS_RECORD:
        return None, "thesis status source body is not an explicit thesis record"
    if document.get("instrument_id") != instrument_id or not isinstance(document.get("impaired"), bool):
        return None, "thesis status source body does not identify the instrument"
    published = _dt(document.get("published_at"))
    if published is None or published > cutoff:
        return None, "thesis status source body has a missing or future publication time"
    excerpt = document.get("rationale_excerpt")
    flag = "true" if document["impaired"] else "false"
    if (
        not isinstance(excerpt, str)
        or instrument_id not in excerpt
        or not _excerpt_contains(excerpt, f"thesis_impaired={flag}")
    ):
        return None, "thesis status is not contained in a rationale excerpt"
    return document["impaired"], None


def load_thesis_status(
    connection: sqlite3.Connection, *, run_id: str, instrument_id: str, cutoff: datetime,
) -> bool | None:
    """Return an explicit impaired flag re-read from a thesis excerpt, or None."""
    if not source_table_available(connection):
        return None
    rows = connection.execute(
        "SELECT evidence_id FROM evidence WHERE run_id = ? AND instrument_id = ? "
        "AND evidence_type = 'thesis' AND metric = 'thesis_status' AND selection_state = 'SELECTED'",
        (run_id, instrument_id),
    ).fetchall()
    if len(rows) != 1:
        return None
    loaded = load_source_payload(connection, run_id=run_id, evidence_id=str(rows[0][0]))
    if loaded is None or loaded[1] != "thesis_status_v1":
        return None
    impaired, reason = verify_thesis_body(loaded[0], instrument_id=instrument_id, cutoff=cutoff)
    if reason is not None:
        return None
    return impaired


def verify_fx_body(
    payload: str, *, base: str, quote: str, observed_at: datetime, retrieved_at: datetime,
) -> tuple[Decimal | None, str | None]:
    """Re-parse a Yahoo currency body. ``KRW=X`` means KRW per 1 USD."""
    if base != "USD":
        return None, "FX source body only supports USD as the base currency"
    document = _json_object(payload)
    if document is None:
        return None, "FX source body is not JSON"
    try:
        meta = document["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None, "FX source body is missing Yahoo currency metadata"
    if not isinstance(meta, dict):
        return None, "FX source body is missing Yahoo currency metadata"
    if meta.get("symbol") != f"{quote}=X" or str(meta.get("currency") or "").upper() != quote.upper():
        return None, "FX source body pair does not match the requested currencies"
    if str(meta.get("instrumentType") or "").upper() != "CURRENCY":
        return None, "FX source body is not a currency instrument"
    rate = _decimal(meta.get("regularMarketPrice"))
    if rate is None or rate <= 0:
        return None, "FX source body rate is missing"
    epoch = meta.get("regularMarketTime")
    timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        claimed = datetime.fromtimestamp(int(epoch), tz=ZoneInfo(timezone_name))
    except (TypeError, ValueError, OSError):
        return None, "FX source body observation time is missing"
    if claimed != observed_at or retrieved_at < claimed:
        return None, "FX source body observation time does not match the persisted observation"
    return rate, None
