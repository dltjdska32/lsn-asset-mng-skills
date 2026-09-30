"""Adapters bridging ProviderObservation and typed contract domain models."""

from __future__ import annotations

from typing import Any

from investment_stack.contracts.codec import (
    encode_envelope,
    format_decimal,
    parse_strict_int,
    to_canonical_dict,
)
from investment_stack.contracts.errors import ContractValidationError
from investment_stack.contracts.financial import FinancialFact
from investment_stack.contracts.institutional import Holding13F
from investment_stack.contracts.market import Bar, MarketQuote
from investment_stack.providers.models import ProviderObservation


def fact_to_observation(
    fact: FinancialFact, provider_id: str = "financial_adapter"
) -> ProviderObservation:
    """Map a FinancialFact to a backward-compatible ProviderObservation."""
    pub_at = (
        fact.public_availability.public_available_at.isoformat()
        if fact.public_availability.public_available_at
        else None
    )
    if fact.dimension == "MONEY":
        canonical_unit = fact.currency or "MONEY"
    elif fact.dimension == "SHARES":
        canonical_unit = "shares"
    elif fact.dimension == "MONEY_PER_SHARE":
        canonical_unit = f"{fact.currency}/share" if fact.currency else "USD/share"
    else:
        canonical_unit = fact.raw_unit
    meta = {
        "fact_id": fact.fact_id,
        "taxonomy": fact.taxonomy,
        "original_tag": fact.original_tag,
        "raw_unit": fact.raw_unit,
        "explicit_scale": str(fact.explicit_scale),
        "scale_multiplier": format_decimal(fact.scale_multiplier),
        "period_type": str(fact.period_type),
        "period_start": fact.period_start,
        "duration_days": fact.duration_days,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "reporting_frequency": str(fact.reporting_frequency),
        "consolidation": str(fact.consolidation),
        "accounting_standard": str(fact.accounting_standard),
        "adjustment_basis": str(fact.adjustment_basis),
        "share_basis": str(fact.share_basis) if fact.share_basis else None,
        "form": fact.form,
        "accession": fact.accession,
        "filed_date": fact.filed_date,
        "accepted_at": fact.accepted_at,
        "restatement_of": fact.restatement_of,
    }
    return ProviderObservation(
        evidence_type="FINANCIAL_FACT",
        source_name=fact.taxonomy,
        source_url=fact.source_locator,
        source_tier=1,
        provider_id=provider_id,
        value=format_decimal(fact.normalized_value),
        unit=canonical_unit,
        currency=fact.currency,
        instrument_id=fact.instrument_id,
        metric=fact.canonical_metric,
        observed_at=fact.period_end,
        published_at=pub_at,
        metadata=meta,
    )


def quote_to_observation(
    quote: MarketQuote, provider_id: str = "market_quote_adapter"
) -> ProviderObservation:
    """Map a MarketQuote to a backward-compatible ProviderObservation."""
    pub_at = (
        quote.public_availability.public_available_at.isoformat()
        if quote.public_availability.public_available_at
        else None
    )
    claimed = quote.claimed_market_time.isoformat() if quote.claimed_market_time else None
    return ProviderObservation(
        evidence_type="MARKET_QUOTE",
        source_name=quote.exchange or quote.venue or "exchange",
        source_url=quote.public_availability.source_locator,
        source_tier=1,
        provider_id=provider_id,
        value=format_decimal(quote.price),
        unit="PRICE",
        currency=quote.currency,
        instrument_id=quote.instrument_id,
        metric="price",
        retrieved_at=quote.retrieved_at.isoformat(),
        observed_at=claimed or pub_at,
        published_at=pub_at,
        claimed_market_time=claimed,
        market_session_date=quote.market_session_date,
        metadata={
            "quote_id": quote.quote_id,
            "evidence_id": quote.evidence_id,
            "quote_kind": str(quote.quote_kind),
            "exchange": quote.exchange,
            "venue": quote.venue,
            "delay_minutes": quote.delay_minutes,
            "is_trade": quote.is_trade,
            "public_availability": to_canonical_dict(quote.public_availability),
        },
    )


def bar_to_observation(
    bar: Bar, provider_id: str = "ohlcv_adapter"
) -> ProviderObservation:
    """Map a Bar to a backward-compatible ProviderObservation."""
    pub_at = (
        bar.public_availability.public_available_at.isoformat()
        if bar.public_availability.public_available_at
        else None
    )
    return ProviderObservation(
        evidence_type="OHLCV_BAR",
        source_name="market_ohlcv",
        source_url=None,
        source_tier=1,
        provider_id=provider_id,
        value=format_decimal(bar.close),
        unit=bar.currency or "PRICE",
        currency=bar.currency,
        instrument_id=bar.instrument_id,
        metric="close",
        observed_at=bar.close_time.isoformat(),
        published_at=pub_at,
        market_session_date=bar.session_date,
        metadata={
            "bar_id": bar.bar_id,
            "interval": bar.interval,
            "open": format_decimal(bar.open),
            "high": format_decimal(bar.high),
            "low": format_decimal(bar.low),
            "close": format_decimal(bar.close),
            "volume": format_decimal(bar.volume),
            "volume_unit": bar.volume_unit,
            "open_time": bar.open_time.isoformat(),
            "close_time": bar.close_time.isoformat(),
            "timezone": bar.timezone,
            "adjustment_mode": str(bar.adjustment_mode),
            "split_ratio": format_decimal(bar.split_ratio) if bar.split_ratio is not None else None,
            "is_complete": bar.is_complete,
        },
    )


def holding_to_observation(
    holding: Holding13F, provider_id: str = "sec_13f_adapter"
) -> ProviderObservation:
    """Map a Holding13F to a backward-compatible ProviderObservation."""
    return ProviderObservation(
        evidence_type="INSTITUTIONAL_HOLDING_13F",
        source_name="SEC_EDGAR",
        source_url=None,
        source_tier=1,
        provider_id=provider_id,
        value=format_decimal(holding.normalized_value),
        unit="USD",
        currency=holding.value_currency,
        instrument_id=holding.mapped_instrument_id or holding.cusip,
        metric="holding_value",
        metadata={
            "holding_id": holding.holding_id,
            "filing_id": holding.filing_id,
            "cusip": holding.cusip,
            "issuer_name": holding.issuer_name,
            "security_class": holding.security_class,
            "put_call": str(holding.put_call),
            "quantity_type": str(holding.quantity_type),
            "raw_quantity": format_decimal(holding.raw_quantity),
            "raw_value": format_decimal(holding.raw_value),
            "normalized_shares": format_decimal(holding.normalized_shares),
            "value_scale": format_decimal(holding.value_scale) if holding.value_scale is not None else None,
            "discretion": holding.discretion,
            "voting_sole": format_decimal(holding.voting_sole) if holding.voting_sole is not None else None,
            "voting_shared": format_decimal(holding.voting_shared) if holding.voting_shared is not None else None,
            "voting_none": format_decimal(holding.voting_none) if holding.voting_none is not None else None,
        },
    )


def observation_to_contract_envelope(obs: ProviderObservation) -> dict[str, Any]:
    """Encode a ProviderObservation into a versioned contract envelope."""
    return encode_envelope("ProviderObservation", to_canonical_dict(obs))


def _decode_observation(payload: dict[str, Any]) -> ProviderObservation:
    allowed_keys = {
        "evidence_type",
        "source_name",
        "source_url",
        "source_tier",
        "provider_id",
        "value",
        "unit",
        "currency",
        "instrument_id",
        "metric",
        "retrieved_at",
        "observed_at",
        "published_at",
        "claimed_market_time",
        "market_session_date",
        "updated_at",
        "event_time",
        "headline",
        "official_confirmation_status",
        "event_cluster_id",
        "relevance_reason",
        "metadata",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"ProviderObservation payload has extra keys: {sorted(extra)}")

    tier = parse_strict_int(payload["source_tier"])
    meta = dict(payload.get("metadata", {}))

    return ProviderObservation(
        evidence_type=payload["evidence_type"],
        source_name=payload["source_name"],
        source_url=payload.get("source_url"),
        source_tier=tier,
        provider_id=payload["provider_id"],
        value=payload.get("value"),
        unit=payload.get("unit"),
        currency=payload.get("currency"),
        instrument_id=payload.get("instrument_id"),
        metric=payload.get("metric"),
        retrieved_at=payload.get("retrieved_at"),
        observed_at=payload.get("observed_at"),
        published_at=payload.get("published_at"),
        claimed_market_time=payload.get("claimed_market_time"),
        market_session_date=payload.get("market_session_date"),
        updated_at=payload.get("updated_at"),
        event_time=payload.get("event_time"),
        headline=payload.get("headline"),
        official_confirmation_status=payload.get("official_confirmation_status"),
        event_cluster_id=payload.get("event_cluster_id"),
        relevance_reason=payload.get("relevance_reason"),
        metadata=meta,
    )


from investment_stack.contracts.codec import register_decoder
register_decoder("ProviderObservation", _decode_observation)
