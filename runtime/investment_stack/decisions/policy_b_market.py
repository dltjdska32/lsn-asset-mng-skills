"""Read-only bridge from persisted run evidence to D12 B market Money.

This adapter verifies a selected quote and independently rebuilds persisted
DCF scenario values from same-run selected assumption evidence.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from investment_stack.decisions.policy_b import Money
from investment_stack.calculations.valuation import DcfAssumptions, EquityValuationAnalyzer
from investment_stack.evidence.source_receipt import (
    load_source_payload,
    read_cash_flow_basis,
    source_table_available,
    verify_dcf_assumption_body,
    verify_quote_body,
)
from investment_stack.freshness import FreshnessEngine
from investment_stack.freshness.calendar import get_pinned_calendar
from investment_stack.providers import ProviderObservation
from investment_stack.storage.sqlite import sqlite_readonly_connection


@dataclass(frozen=True, slots=True)
class PolicyBMarketEvidence:
    run_id: str
    instrument_id: str
    as_of: str
    quote_per_share: Money | None
    quote_evidence_id: str | None
    fair_value_per_share: Money | None = None
    optimistic_fair_value_per_share: Money | None = None
    conservative_fair_value_per_share: Money | None = None
    quote_kind: str | None = None
    quote_source_count: int = 0
    cash_flow_basis: str | None = None
    unavailable_reasons: tuple[str, ...] = ()


def _dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def _json(value: object) -> dict[str, Any] | None:
    try:
        decoded = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


_DCF_FIELDS = (
    "starting_fcf", "annual_growth_rate", "discount_rate", "terminal_growth_rate",
    "years", "net_debt", "shares_outstanding",
)


def _stored_number(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, str):
        try:
            direct = Decimal(value)
            if direct.is_finite():
                return direct
        except InvalidOperation:
            pass
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, bool) or parsed is None:
            return None
        number = Decimal(str(parsed))
    except (TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
        return None
    return number if number.is_finite() else None


def _persisted_dcf_values(
    connection: sqlite3.Connection, *, run_id: str, instrument_id: str, cutoff: datetime,
    basis_out: list[str] | None = None,
) -> tuple[Money | None, Money | None, Money | None, str | None]:
    """Verify complete persisted base/optimistic assumption-value receipts."""
    calculation_rows = connection.execute(
        "SELECT * FROM calculations WHERE run_id=? AND calculation_name='EQUITY_VALUATION'",
        (run_id,),
    ).fetchall()
    matching: list[tuple[sqlite3.Row, dict[str, Any], dict[str, Any]]] = []
    for calc in calculation_rows:
        inputs, result = _json(calc["inputs_json"]), _json(calc["result_json"])
        if inputs and result and inputs.get("subject") == instrument_id and result.get("subject") == instrument_id:
            # An explicit unavailable attempt contains no valuation and cannot
            # create ambiguity with a source-bound calculation at the same pin.
            if (result.get("status") == "UNAVAILABLE"
                    and isinstance(result.get("metrics"), list)
                    and all(isinstance(m, dict) and m.get("value") is None
                            and m.get("status") == "UNAVAILABLE" for m in result["metrics"])
                    and isinstance(result.get("metadata"), dict)
                    and not result["metadata"].get("dcf_assumption_value_bindings")):
                continue
            matching.append((calc, inputs, result))
    if len(matching) != 1:
        return None, None, None, "persisted valuation calculation is missing or ambiguous for this run/instrument"
    _, inputs, result = matching[0]
    metadata = result.get("metadata")
    if result.get("analysis_type") != "EQUITY_VALUATION" or not isinstance(metadata, dict):
        return None, None, None, "persisted valuation result is malformed"
    records = metadata.get("dcf_assumption_value_bindings")
    if not isinstance(records, list) or inputs.get("dcf_assumption_value_bindings") != records:
        return None, None, None, "persisted DCF assumption value binding contract is missing or inconsistent"
    scenarios: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("scenario"), str):
            return None, None, None, "persisted DCF assumption binding record is malformed"
        name = record["scenario"].casefold()
        if name in scenarios:
            return None, None, None, "duplicate persisted DCF scenario binding"
        scenarios[name] = record
    if not {"base", "optimistic"}.issubset(scenarios):
        return None, None, None, "base/optimistic DCF assumption value bindings are missing"
    currency = metadata.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        return None, None, None, "persisted valuation currency is missing"
    all_ids: set[str] = set()
    assumptions: dict[str, DcfAssumptions] = {}
    scenario_order = ("base", "optimistic") + (("conservative",) if "conservative" in scenarios else ())
    for scenario_name in scenario_order:
        record = scenarios[scenario_name]
        values = record.get("values")
        bindings = record.get("evidence")
        if not isinstance(values, dict) or not isinstance(bindings, dict) or set(values) != set(_DCF_FIELDS) or set(bindings) != set(_DCF_FIELDS):
            return None, None, None, f"{scenario_name} DCF scenario lacks complete assumption values/evidence bindings"
        parsed: dict[str, Decimal] = {}
        for field in _DCF_FIELDS:
            value = _stored_number(values[field])
            evidence_id = bindings[field]
            if value is None or not isinstance(evidence_id, str) or not evidence_id or evidence_id in all_ids:
                return None, None, None, f"{scenario_name} DCF assumption {field} has invalid or duplicate binding"
            all_ids.add(evidence_id)
            evidence_rows = connection.execute(
                "SELECT * FROM evidence WHERE run_id=? AND evidence_id=? AND instrument_id=? "
                "AND metric=? AND selection_state='SELECTED'",
                (run_id, evidence_id, instrument_id, f"dcf_assumption:{scenario_name}:{field}"),
            ).fetchall()
            competitors = connection.execute(
                "SELECT * FROM evidence WHERE run_id=? AND instrument_id=? AND metric=? "
                "AND selection_state='SELECTED'",
                (run_id, instrument_id, f"dcf_assumption:{scenario_name}:{field}"),
            ).fetchall()
            if len(evidence_rows) != 1 or len(competitors) != 1:
                return None, None, None, f"{scenario_name} DCF assumption {field} evidence is missing, duplicate, or conflicting"
            evidence = evidence_rows[0]
            if evidence["evidence_type"] != "assumption":
                return None, None, None, f"{scenario_name} DCF assumption {field} is not a persisted assumption receipt"
            expected_unit = "currency" if field in {"starting_fcf", "net_debt"} else "ratio"
            if field == "years":
                expected_unit = "years"
            elif field == "shares_outstanding":
                expected_unit = "shares"
            if evidence["unit"] != expected_unit:
                return None, None, None, f"{scenario_name} DCF assumption {field} evidence unit mismatch"
            if field in {"starting_fcf", "net_debt"}:
                if str(evidence["currency"] or "").upper() != currency.upper():
                    return None, None, None, f"{scenario_name} DCF assumption {field} evidence currency mismatch"
            elif evidence["currency"] not in (None, ""):
                return None, None, None, f"{scenario_name} DCF assumption {field} unexpectedly carries currency"
            if not evidence["source_uri"] or not evidence["source_name"]:
                return None, None, None, f"{scenario_name} DCF assumption {field} lacks a source receipt locator"
            retrieved, published = _dt(evidence["retrieved_at"]), _dt(evidence["published_at"])
            if retrieved is None or published is None or retrieved > cutoff or published > cutoff:
                return None, None, None, f"{scenario_name} DCF assumption {field} has missing or future provenance time"
            persisted_value = _stored_number(evidence["value_text"])
            if persisted_value != value:
                return None, None, None, f"{scenario_name} DCF assumption {field} does not equal persisted evidence value"
            parsed[field] = value
        if parsed["years"] != parsed["years"].to_integral_value() or parsed["years"] <= 0:
            return None, None, None, f"{scenario_name} DCF years must be a positive integer"
        try:
            assumptions[scenario_name] = DcfAssumptions(
                starting_fcf=parsed["starting_fcf"], annual_growth_rate=parsed["annual_growth_rate"],
                discount_rate=parsed["discount_rate"], terminal_growth_rate=parsed["terminal_growth_rate"],
                years=int(parsed["years"]), net_debt=parsed["net_debt"], shares_outstanding=parsed["shares_outstanding"],
            )
        except (ValueError, TypeError):
            return None, None, None, f"{scenario_name} DCF assumptions are invalid"
    metrics = result.get("metrics")
    if not isinstance(metrics, list):
        return None, None, None, "persisted valuation metrics are malformed"
    for name in assumptions:
        metric_name = f"dcf_scenario_{name}"
        found = [metric for metric in metrics if isinstance(metric, dict) and metric.get("name") == metric_name]
        if len(found) != 1 or not isinstance(found[0].get("evidence_ids"), list):
            return None, None, None, f"persisted {name} fair-value metric is missing or ambiguous"
        metric = found[0]
        bound_ids = set(scenarios[name]["evidence"].values())
        if set(metric["evidence_ids"]) != bound_ids:
            return None, None, None, f"persisted {name} fair-value metric does not bind all assumption evidence"
        reported = _stored_number(metric.get("value"))
        calculated = EquityValuationAnalyzer._dcf_per_share(assumptions[name])
        if reported is None or calculated != reported:
            return None, None, None, f"persisted {name} fair value does not match its verified assumptions ({calculated} != {reported})"
    missing_document = False
    saw_document = False
    cash_flow_bases: dict[str, str] = {}
    if source_table_available(connection):
        for scenario_name, assumption_values in assumptions.items():
            for field in _DCF_FIELDS:
                evidence_id = scenarios[scenario_name]["evidence"][field]
                loaded = load_source_payload(connection, run_id=run_id, evidence_id=evidence_id)
                if loaded is None:
                    missing_document = True
                    continue
                saw_document = True
                payload, parser_id = loaded
                if parser_id != "explicit_dcf_assumption_v1":
                    return None, None, None, f"{scenario_name} DCF assumption {field} uses an unregistered source parser"
                expected_unit = "currency" if field in {"starting_fcf", "net_debt"} else "ratio"
                field_currency = currency if field in {"starting_fcf", "net_debt"} else None
                if field == "years":
                    expected_unit = "years"
                elif field == "shares_outstanding":
                    expected_unit = "shares"
                receipt_reason = verify_dcf_assumption_body(
                    payload, scenario=scenario_name, field=field,
                    value=getattr(assumption_values, field) if field != "years" else Decimal(assumption_values.years),
                    unit=expected_unit, currency=field_currency, cutoff=cutoff,
                )
                if receipt_reason:
                    return None, None, None, receipt_reason
                if field == "starting_fcf":
                    basis = read_cash_flow_basis(payload)
                    if basis is None:
                        return None, None, None, f"{scenario_name} DCF starting cash flow basis is not explicit FCFF or FCFE"
                    cash_flow_bases[scenario_name] = basis
    if not saw_document:
        return None, None, None, (
            "DCF fair values unavailable: no independently verifiable source-content receipt "
            "contract is available for assumption evidence"
        )
    if missing_document or "conservative" not in assumptions:
        return None, None, None, (
            "DCF fair values unavailable: conservative/base/optimistic source-content receipts are incomplete"
        )
    if set(cash_flow_bases) != set(assumptions) or len(set(cash_flow_bases.values())) != 1:
        return None, None, None, "DCF scenarios do not share one explicit FCFF or FCFE basis"
    agreed_basis = next(iter(set(cash_flow_bases.values())))
    if agreed_basis == "FCFE" and any(item.net_debt != 0 for item in assumptions.values()):
        return None, None, None, "FCFE per share cannot also subtract net debt"
    if basis_out is not None:
        basis_out.append(agreed_basis)
    code = currency.upper()
    values = {
        name: Money(EquityValuationAnalyzer._dcf_per_share(item), code, True)
        for name, item in assumptions.items()
    }
    return values["conservative"], values["base"], values["optimistic"], None


_QUOTE_UNIT_BY_CURRENCY = {
    "USD": "USD/share", "EUR": "EUR/share", "JPY": "JPY/share", "GBP": "GBP/share",
    "CAD": "CAD/share", "AUD": "AUD/share", "CHF": "CHF/share", "CNY": "CNY/share",
    "HKD": "HKD/share", "KRW": "KRW/share",
}


def _reassess_persisted_quote(row: sqlite3.Row, *, cutoff: datetime) -> tuple[bool, str | None]:
    """Rebuild freshness from the persisted observation and trusted calendar."""
    metadata = _json(row["market_metadata"])
    if metadata is None:
        return False, "persisted market observation metadata is missing or malformed"
    value = _stored_number(row["value_text"])
    try:
        source_tier = int(row["source_tier"] or 0)
    except (TypeError, ValueError):
        source_tier = None
    if value is None or source_tier is None:
        return False, "persisted quote value or source tier is invalid"
    observation = ProviderObservation(
        evidence_type="market",
        source_name=str(row["source_name"] or ""),
        source_url=row["source_uri"],
        source_tier=source_tier,
        provider_id=str(row["provider_id"] or ""),
        value=value,
        unit=row["unit"],
        currency=row["currency"],
        instrument_id=row["instrument_id"],
        metric=row["metric"],
        retrieved_at=row["retrieved_at"],
        observed_at=row["observed_at"],
        published_at=row["published_at"],
        claimed_market_time=row["claimed_market_time"],
        market_session_date=row["market_session_date"],
        updated_at=row["updated_at"],
        event_time=row["event_time"],
        metadata=metadata,
    )
    exchange = str(metadata.get("exchange") or "").upper()
    aliases = {"NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "KS": "KRX"}
    exchange = aliases.get(exchange, exchange)
    calendar = get_pinned_calendar(exchange) if row["freshness_status"] == "LAST_VALID_CLOSE" else None
    if row["freshness_status"] == "LAST_VALID_CLOSE" and calendar is None:
        return False, "LAST_VALID_CLOSE has no trusted pinned calendar for its exchange"
    try:
        assessed = FreshnessEngine().assess(
            observation, analysis_as_of=cutoff.isoformat(), calendar=calendar,
        )
    except (TypeError, ValueError, OverflowError):
        return False, "persisted quote cannot be independently reassessed"
    stored_status = row["freshness_status"]
    if assessed.status.value != stored_status:
        return False, (
            f"persisted freshness label {stored_status} does not match independently assessed "
            f"{assessed.status.value}"
        )
    if stored_status == "LAST_VALID_CLOSE":
        details = _json(row["assessment_details"])
        if details is None:
            return False, "LAST_VALID_CLOSE assessment details are missing"
        if (
            details.get("calendar_id") != calendar.schedule_id
            or assessed.calendar_id != calendar.schedule_id
            or details.get("market_session_date") != assessed.market_session_date
            or details.get("quote_kind") != assessed.quote_kind
            or _dt(details.get("effective_time")) != _dt(assessed.effective_time)
            or _dt(details.get("public_available_time")) != _dt(assessed.public_available_time)
            or _dt(row["published_at"]) != _dt(assessed.public_available_time)
        ):
            return False, "persisted LAST_VALID_CLOSE fields do not match pinned calendar reassessment"
    return True, None


def load_policy_b_market_evidence(
    database: str | Path,
    *,
    run_id: str,
    instrument_id: str,
    as_of: str,
) -> PolicyBMarketEvidence:
    """Return verified persisted quote Money; all failures are explicit.

    LAST_VALID_CLOSE is admitted only when the same-run selected evidence,
    persisted market row and unique persisted freshness assessment prove it.
    FRESH and DELAYED are also admitted only when their recorded timestamps
    are no later than the pinned analysis time. No caller-supplied flags or
    evidence IDs are accepted as proof.
    """
    reasons: list[str] = []
    cutoff = _dt(as_of)
    if cutoff is None:
        reasons.append("analysis as_of must be an ISO timestamp with timezone")
    quote: Money | None = None
    quote_kind: str | None = None
    quote_source_count = 0
    cash_flow_basis: str | None = None
    fair_value: Money | None = None
    optimistic_fair_value: Money | None = None
    conservative_fair_value: Money | None = None
    valuation_reason: str | None = None
    evidence_id: str | None = None
    if not run_id or not instrument_id:
        reasons.append("run_id and instrument_id are required")
    if not reasons:
        try:
            with sqlite_readonly_connection(database) as connection:
                connection.row_factory = sqlite3.Row
                runs = connection.execute(
                    "SELECT run_id, analysis_as_of FROM run_metadata WHERE run_id = ?", (run_id,)
                ).fetchall()
                if len(runs) != 1 or _dt(runs[0]["analysis_as_of"]) != cutoff:
                    reasons.append("pinned run metadata does not match run_id/as_of")
                else:
                    rows = connection.execute(
                        "SELECT e.*, m.observation_id, m.instrument_id AS market_instrument_id, "
                        "m.value_numeric, m.unit AS market_unit, "
                        "m.currency AS market_currency, m.observed_at AS market_observed_at, "
                        "m.claimed_market_time, m.market_session_date, m.provider_id AS market_provider_id, "
                        "m.freshness_status AS market_freshness, m.metadata_json AS market_metadata, "
                        "f.status AS assessment_status, f.details_json AS assessment_details "
                        "FROM evidence e JOIN market_observations m ON m.evidence_id=e.evidence_id "
                        "AND m.run_id=e.run_id LEFT JOIN freshness_assessments f "
                        "ON f.evidence_id=e.evidence_id AND f.run_id=e.run_id "
                        "WHERE e.run_id=? AND e.instrument_id=? AND e.evidence_type='market' "
                        "AND e.metric='current_price' AND e.selection_state='SELECTED'",
                        (run_id, instrument_id),
                    ).fetchall()
                    quote_signatures = {
                        (str(item["value_numeric"]), str(item["currency"] or "").upper(), item["freshness_status"])
                        for item in rows
                    }
                    if not rows:
                        reasons.append("selected persisted market quote is missing or ambiguous")
                    elif len(quote_signatures) != 1:
                        reasons.append(
                            "selected quote sources disagree; current price and action numbers stay withheld"
                        )
                    else:
                        row = rows[0]
                        evidence_id = row["evidence_id"]
                        status = row["freshness_status"]
                        if not status or status != row["market_freshness"] or status != row["assessment_status"]:
                            reasons.append("quote freshness status is missing or inconsistent")
                        if status not in {"FRESH", "DELAYED", "LAST_VALID_CLOSE"}:
                            reasons.append(f"quote freshness {status or 'UNKNOWN'} is not eligible")
                        currency = row["currency"]
                        if not currency or str(currency).upper() != str(row["market_currency"] or "").upper():
                            reasons.append("persisted quote currency is missing or inconsistent")
                        expected_unit = _QUOTE_UNIT_BY_CURRENCY.get(str(currency or "").upper())
                        if (
                            row["metric"] != "current_price" or not expected_unit
                            or row["unit"] != expected_unit or row["market_unit"] != expected_unit
                        ):
                            reasons.append("persisted evidence/market units do not match the quote currency per-share unit")
                        if (
                            row["instrument_id"] != instrument_id
                            or row["market_instrument_id"] != instrument_id
                            or row["market_instrument_id"] != row["instrument_id"]
                        ):
                            reasons.append("persisted evidence and market observation instrument IDs do not match")
                        evidence_observed = _dt(row["observed_at"])
                        market_observed = _dt(row["market_observed_at"])
                        claimed_market = _dt(row["claimed_market_time"])
                        if evidence_observed is None or market_observed is None or evidence_observed != market_observed:
                            reasons.append("persisted evidence and market observation timestamps do not match")
                        if evidence_observed is None or claimed_market is None or evidence_observed != claimed_market:
                            reasons.append("persisted claimed market time does not match evidence observation time")
                        if not row["provider_id"] or row["provider_id"] != row["market_provider_id"]:
                            reasons.append("persisted evidence and market observation provider IDs do not match")
                        source_uri = str(row["source_uri"] or "").strip()
                        source_host = urlparse(source_uri)
                        if (
                            not row["source_name"] or source_host.scheme.lower() != "https"
                            or not source_host.hostname
                        ):
                            reasons.append("persisted quote lacks the source name and HTTPS locator required by market provider receipts")
                        try:
                            value = _stored_number(row["value_text"])
                            market_value = Decimal(str(row["value_numeric"]))
                        except (InvalidOperation, TypeError, ValueError):
                            value = market_value = Decimal("NaN")
                        if value is None or not value.is_finite() or value <= 0 or market_value != value:
                            reasons.append("persisted evidence and market quote values do not match as a positive finite number")
                        details = _json(row["assessment_details"])
                        metadata = _json(row["market_metadata"])
                        timestamps = [
                            _dt(row["observed_at"]), _dt(row["published_at"]), _dt(row["retrieved_at"]),
                            _dt(row["market_observed_at"]), _dt(row["claimed_market_time"]),
                        ]
                        if any(item is None for item in timestamps):
                            reasons.append("quote observation/publication timestamps are incomplete")
                        elif any(item > cutoff for item in timestamps if item is not None):
                            reasons.append("future-dated quote evidence is not eligible")
                        if status in {"FRESH", "DELAYED", "LAST_VALID_CLOSE"}:
                            verified, freshness_reason = _reassess_persisted_quote(row, cutoff=cutoff)
                            if not verified and freshness_reason:
                                reasons.append(freshness_reason)
                        if metadata is None:
                            reasons.append("persisted quote metadata is missing or malformed")
                        if not reasons:
                            loaded = load_source_payload(
                                connection, run_id=run_id, evidence_id=str(row["evidence_id"]),
                            )
                            if loaded is None:
                                reasons.append(
                                    "quote unavailable for D12: source URI/provider fields lack an independently "
                                    "authenticated source-content receipt"
                                )
                            else:
                                payload, parser_id = loaded
                                exchange = str((metadata or {}).get("exchange") or "")
                                session_date = row["market_session_date"] if status == "LAST_VALID_CLOSE" else None
                                retrieved = _dt(row["retrieved_at"])
                                verified, receipt_reason = verify_quote_body(
                                    payload, parser_id, instrument_id=instrument_id, currency=str(currency),
                                    price=value, observed_at=evidence_observed, exchange=exchange,
                                    session_date=session_date, retrieved_at=retrieved or cutoff,
                                ) if evidence_observed is not None and value is not None else (False, "quote source body could not be re-extracted")
                                if not verified:
                                    reasons.append(receipt_reason or "quote source body could not be re-extracted")
                                else:
                                    session_kind = str((metadata or {}).get("quote_kind") or "").upper()
                                    if status in {"FRESH", "DELAYED"} and session_kind != "REGULAR":
                                        reasons.append(
                                            "quote session is not REGULAR; premarket and after-hours prices "
                                            "are not used as the current price"
                                        )
                                    elif status == "LAST_VALID_CLOSE" and session_kind != "LAST_VALID_CLOSE":
                                        reasons.append("last valid close is not labeled as a non-realtime close")
                                    else:
                                        for extra in rows[1:]:
                                            extra_loaded = load_source_payload(
                                                connection, run_id=run_id, evidence_id=str(extra["evidence_id"]),
                                            )
                                            extra_meta = _json(extra["market_metadata"]) or {}
                                            extra_value = _stored_number(extra["value_text"])
                                            extra_observed = _dt(extra["observed_at"])
                                            extra_session = (
                                                extra["market_session_date"] if status == "LAST_VALID_CLOSE" else None
                                            )
                                            extra_ok, extra_reason = verify_quote_body(
                                                extra_loaded[0], extra_loaded[1],
                                                instrument_id=instrument_id, currency=str(currency),
                                                price=value, observed_at=extra_observed,
                                                exchange=str(extra_meta.get("exchange") or ""),
                                                session_date=extra_session,
                                                retrieved_at=_dt(extra["retrieved_at"]) or cutoff,
                                            ) if extra_loaded is not None and extra_observed is not None and extra_value == value else (
                                                False, "selected quote sources disagree; current price and action numbers stay withheld",
                                            )
                                            if not extra_ok or str(extra_meta.get("quote_kind") or "").upper() != session_kind:
                                                reasons.append(extra_reason or "selected quote sources disagree")
                                                break
                                        else:
                                            quote = Money(value, str(currency).upper(), verified=True)
                                            quote_kind = status
                                            evidence_id = row["evidence_id"]
                                            quote_source_count = len(rows)
                    basis_out: list[str] = []
                    conservative_fair_value, fair_value, optimistic_fair_value, valuation_reason = _persisted_dcf_values(
                        connection, run_id=run_id, instrument_id=instrument_id, cutoff=cutoff,
                        basis_out=basis_out,
                    )
                    if basis_out:
                        cash_flow_basis = basis_out[0]
        except (sqlite3.Error, OSError, ValueError) as exc:
            reasons.append(f"run database could not be read safely: {type(exc).__name__}")
    if valuation_reason:
        reasons.append(valuation_reason)
    return PolicyBMarketEvidence(
        run_id=run_id, instrument_id=instrument_id, as_of=as_of,
        quote_per_share=quote, quote_evidence_id=evidence_id if quote else None,
        fair_value_per_share=fair_value,
        optimistic_fair_value_per_share=optimistic_fair_value,
        conservative_fair_value_per_share=conservative_fair_value,
        quote_kind=quote_kind if quote else None,
        quote_source_count=quote_source_count if quote else 0,
        cash_flow_basis=cash_flow_basis if fair_value else None,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )
