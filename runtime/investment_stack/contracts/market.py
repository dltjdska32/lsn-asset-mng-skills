"""Market quotes, OHLCV bars, and bar series contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from investment_stack.contracts.codec import (
    parse_finite_decimal,
    parse_strict_bool,
    parse_strict_int,
    register_decoder,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    TimezoneValidationError,
)


class QuoteKind(StrEnum):
    REGULAR = "REGULAR"
    EXTENDED_HOURS = "EXTENDED_HOURS"
    DELAYED = "DELAYED"
    LAST_VALID_CLOSE = "LAST_VALID_CLOSE"


class AdjustmentMode(StrEnum):
    RAW = "RAW"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """A verified single market price observation with clear session and timing semantics."""

    quote_id: str
    evidence_id: str
    instrument_id: str
    currency: str
    price: Decimal
    quote_kind: QuoteKind | str
    retrieved_at: datetime
    public_availability: PublicAvailability
    exchange: str | None = None
    venue: str | None = None
    market_session_date: str | None = None
    claimed_market_time: datetime | None = None
    delay_minutes: int | None = None
    is_trade: bool = True

    def __post_init__(self) -> None:
        if not self.quote_id or not self.evidence_id or not self.instrument_id or not self.currency:
            raise ContractValidationError("quote_id, evidence_id, instrument_id, currency must be non-empty")

        finite_price = parse_finite_decimal(self.price)
        if finite_price <= 0:
            raise DecimalValidationError(f"Market quote price must be positive, got: {finite_price}")
        if finite_price != self.price:
            object.__setattr__(self, "price", finite_price)

        if not isinstance(self.is_trade, bool):
            raise ContractValidationError(f"is_trade must be bool, got {type(self.is_trade).__name__}")

        if not isinstance(self.public_availability, PublicAvailability):
            raise ContractValidationError(
                f"public_availability must be an instance of PublicAvailability, got {type(self.public_availability).__name__}"
            )

        if self.retrieved_at.tzinfo is None:
            raise TimezoneValidationError("retrieved_at must be timezone-aware")
        if self.claimed_market_time is not None and self.claimed_market_time.tzinfo is None:
            raise TimezoneValidationError("claimed_market_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Bar:
    """A single OHLCV bar with price bounds, volume, and split adjustment integrity."""

    bar_id: str
    evidence_id: str
    instrument_id: str
    interval: str
    session_date: str
    open_time: datetime
    close_time: datetime
    timezone: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    currency: str
    public_availability: PublicAvailability
    volume_unit: str = "SHARES"
    adjustment_mode: AdjustmentMode | str = AdjustmentMode.RAW
    split_ratio: Decimal | None = None
    is_complete: bool = True

    def __post_init__(self) -> None:
        if not self.bar_id or not self.evidence_id or not self.instrument_id:
            raise ContractValidationError("bar_id, evidence_id, instrument_id must be non-empty strings")
        if not isinstance(self.public_availability, PublicAvailability):
            raise ContractValidationError(
                f"public_availability must be an instance of PublicAvailability, got {type(self.public_availability).__name__}"
            )
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise TimezoneValidationError("Bar open_time and close_time must be timezone-aware")
        if self.open_time > self.close_time:
            raise ContractValidationError(
                f"Bar open_time ({self.open_time}) cannot be after close_time ({self.close_time})"
            )

        o = parse_finite_decimal(self.open)
        h = parse_finite_decimal(self.high)
        l = parse_finite_decimal(self.low)
        c = parse_finite_decimal(self.close)
        v = parse_finite_decimal(self.volume)

        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            raise DecimalValidationError("Bar OHLC prices must all be strictly positive")
        if v < 0:
            raise DecimalValidationError("Bar volume must be non-negative")

        if l > min(o, c) or h < max(o, c) or l > h:
            raise ContractValidationError(
                f"Bar OHLC bounds invariant violated: low={l}, open={o}, close={c}, high={h}"
            )

        if self.split_ratio is not None:
            sr = parse_finite_decimal(self.split_ratio)
            if sr <= 0:
                raise DecimalValidationError("split_ratio must be positive")
            if sr != self.split_ratio:
                object.__setattr__(self, "split_ratio", sr)

        if o != self.open:
            object.__setattr__(self, "open", o)
        if h != self.high:
            object.__setattr__(self, "high", h)
        if l != self.low:
            object.__setattr__(self, "low", l)
        if c != self.close:
            object.__setattr__(self, "close", c)
        if v != self.volume:
            object.__setattr__(self, "volume", v)


@dataclass(frozen=True, slots=True)
class BarSet:
    """An ordered, contiguous sequence of validated Bars for technical calculation."""

    instrument_id: str
    interval: str
    currency: str
    adjustment_mode: AdjustmentMode | str
    bars: tuple[Bar, ...]

    @classmethod
    def create(
        cls,
        instrument_id: str,
        interval: str,
        currency: str,
        adjustment_mode: AdjustmentMode | str,
        bars: Iterable[Bar],
    ) -> BarSet:
        bar_list = list(bars)
        if not bar_list:
            return cls(
                instrument_id=instrument_id,
                interval=interval,
                currency=currency,
                adjustment_mode=adjustment_mode,
                bars=(),
            )

        prev_time: datetime | None = None
        for b in bar_list:
            if b.instrument_id != instrument_id:
                raise ContractValidationError(
                    f"Bar instrument_id ({b.instrument_id}) does not match BarSet ({instrument_id})"
                )
            if b.interval != interval:
                raise ContractValidationError(
                    f"Bar interval ({b.interval}) does not match BarSet interval ({interval})"
                )
            if b.currency != currency:
                raise ContractValidationError(
                    f"Bar currency ({b.currency}) does not match BarSet ({currency})"
                )
            if str(b.adjustment_mode) != str(adjustment_mode):
                raise ContractValidationError(
                    f"Bar adjustment_mode ({b.adjustment_mode}) does not match BarSet ({adjustment_mode})"
                )
            if prev_time is not None:
                if b.open_time <= prev_time:
                    raise ContractValidationError(
                        f"Bars in BarSet must be strictly chronological: prev={prev_time}, current={b.open_time}"
                    )
            prev_time = b.open_time

        return cls(
            instrument_id=instrument_id,
            interval=interval,
            currency=currency,
            adjustment_mode=adjustment_mode,
            bars=tuple(bar_list),
        )


# Decoders
def _decode_market_quote(payload: dict[str, Any]) -> MarketQuote:
    allowed_keys = {
        "quote_id",
        "evidence_id",
        "instrument_id",
        "currency",
        "price",
        "quote_kind",
        "retrieved_at",
        "public_availability",
        "exchange",
        "venue",
        "market_session_date",
        "claimed_market_time",
        "delay_minutes",
        "is_trade",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"MarketQuote payload has extra keys: {sorted(extra)}")

    required_keys = {
        "quote_id",
        "evidence_id",
        "instrument_id",
        "currency",
        "price",
        "quote_kind",
        "retrieved_at",
        "public_availability",
    }
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"MarketQuote payload missing required keys: {sorted(missing)}")

    from investment_stack.contracts.codec import decode_contract

    pub = decode_contract(payload["public_availability"], expected_kind="PublicAvailability")
    claimed = datetime.fromisoformat(payload["claimed_market_time"]) if payload.get("claimed_market_time") else None
    delay = parse_strict_int(payload["delay_minutes"]) if payload.get("delay_minutes") is not None else None
    is_trade = parse_strict_bool(payload["is_trade"]) if "is_trade" in payload else True

    return MarketQuote(
        quote_id=payload["quote_id"],
        evidence_id=payload["evidence_id"],
        instrument_id=payload["instrument_id"],
        currency=payload["currency"],
        price=parse_finite_decimal(payload["price"]),
        quote_kind=QuoteKind(payload["quote_kind"]),
        retrieved_at=datetime.fromisoformat(payload["retrieved_at"]),
        public_availability=pub,
        exchange=payload.get("exchange"),
        venue=payload.get("venue"),
        market_session_date=payload.get("market_session_date"),
        claimed_market_time=claimed,
        delay_minutes=delay,
        is_trade=is_trade,
    )


def _decode_bar(payload: dict[str, Any]) -> Bar:
    allowed_keys = {
        "bar_id",
        "evidence_id",
        "instrument_id",
        "interval",
        "session_date",
        "open_time",
        "close_time",
        "timezone",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "currency",
        "public_availability",
        "volume_unit",
        "adjustment_mode",
        "split_ratio",
        "is_complete",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"Bar payload has extra keys: {sorted(extra)}")

    required_keys = {
        "bar_id",
        "evidence_id",
        "instrument_id",
        "interval",
        "session_date",
        "open_time",
        "close_time",
        "timezone",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "currency",
        "public_availability",
    }
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"Bar payload missing required keys: {sorted(missing)}")

    from investment_stack.contracts.codec import decode_contract

    pub = decode_contract(payload["public_availability"], expected_kind="PublicAvailability")
    sr = parse_finite_decimal(payload["split_ratio"]) if payload.get("split_ratio") is not None else None

    return Bar(
        bar_id=payload["bar_id"],
        evidence_id=payload["evidence_id"],
        instrument_id=payload["instrument_id"],
        interval=payload["interval"],
        session_date=payload["session_date"],
        open_time=datetime.fromisoformat(payload["open_time"]),
        close_time=datetime.fromisoformat(payload["close_time"]),
        timezone=payload["timezone"],
        open=parse_finite_decimal(payload["open"]),
        high=parse_finite_decimal(payload["high"]),
        low=parse_finite_decimal(payload["low"]),
        close=parse_finite_decimal(payload["close"]),
        volume=parse_finite_decimal(payload["volume"]),
        currency=payload["currency"],
        public_availability=pub,
        volume_unit=payload.get("volume_unit", "SHARES"),
        adjustment_mode=AdjustmentMode(payload.get("adjustment_mode", "RAW")),
        split_ratio=sr,
        is_complete=bool(payload.get("is_complete", True)),
    )


def _decode_bar_set(payload: dict[str, Any]) -> BarSet:
    allowed_keys = {"instrument_id", "interval", "currency", "adjustment_mode", "bars"}
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"BarSet payload has extra keys: {sorted(extra)}")

    required_keys = {"instrument_id", "interval", "currency", "adjustment_mode", "bars"}
    missing = required_keys - set(payload.keys())
    if missing:
        raise ContractValidationError(f"BarSet payload missing required keys: {sorted(missing)}")

    raw_bars = payload.get("bars", [])
    bars = tuple(_decode_bar(b) for b in raw_bars)
    return BarSet.create(
        instrument_id=payload["instrument_id"],
        interval=payload["interval"],
        currency=payload["currency"],
        adjustment_mode=AdjustmentMode(payload["adjustment_mode"]),
        bars=bars,
    )


register_decoder("MarketQuote", _decode_market_quote)
register_decoder("Bar", _decode_bar)
register_decoder("BarSet", _decode_bar_set)
