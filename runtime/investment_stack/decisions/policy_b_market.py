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

from investment_stack.decisions.policy_b import Money
from investment_stack.calculations.valuation import DcfAssumptions, EquityValuationAnalyzer
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
) -> tuple[Money | None, Money | None, str | None]:
    """Verify complete persisted base/optimistic assumption-value receipts."""
    calculation_rows = connection.execute(
        "SELECT * FROM calculations WHERE run_id=? AND calculation_name='EQUITY_VALUATION'",
        (run_id,),
    ).fetchall()
    matching: list[tuple[sqlite3.Row, dict[str, Any], dict[str, Any]]] = []
    for calc in calculation_rows:
        inputs, result = _json(calc["inputs_json"]), _json(calc["result_json"])
        if inputs and result and inputs.get("subject") == instrument_id and result.get("subject") == instrument_id:
            matching.append((calc, inputs, result))
    if len(matching) != 1:
        return None, None, "persisted valuation calculation is missing or ambiguous for this run/instrument"
    _, inputs, result = matching[0]
    metadata = result.get("metadata")
    if result.get("analysis_type") != "EQUITY_VALUATION" or not isinstance(metadata, dict):
        return None, None, "persisted valuation result is malformed"
    records = metadata.get("dcf_assumption_value_bindings")
    if not isinstance(records, list) or inputs.get("dcf_assumption_value_bindings") != records:
        return None, None, "persisted DCF assumption value binding contract is missing or inconsistent"
    scenarios: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("scenario"), str):
            return None, None, "persisted DCF assumption binding record is malformed"
        name = record["scenario"].casefold()
        if name in scenarios:
            return None, None, "duplicate persisted DCF scenario binding"
        scenarios[name] = record
    if not {"base", "optimistic"}.issubset(scenarios):
        return None, None, "base/optimistic DCF assumption value bindings are missing"
    currency = metadata.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        return None, None, "persisted valuation currency is missing"
    all_ids: set[str] = set()
    assumptions: dict[str, DcfAssumptions] = {}
    for scenario_name in ("base", "optimistic"):
        record = scenarios[scenario_name]
        values = record.get("values")
        bindings = record.get("evidence")
        if not isinstance(values, dict) or not isinstance(bindings, dict) or set(values) != set(_DCF_FIELDS) or set(bindings) != set(_DCF_FIELDS):
            return None, None, f"{scenario_name} DCF scenario lacks complete assumption values/evidence bindings"
        parsed: dict[str, Decimal] = {}
        for field in _DCF_FIELDS:
            value = _stored_number(values[field])
            evidence_id = bindings[field]
            if value is None or not isinstance(evidence_id, str) or not evidence_id or evidence_id in all_ids:
                return None, None, f"{scenario_name} DCF assumption {field} has invalid or duplicate binding"
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
                return None, None, f"{scenario_name} DCF assumption {field} evidence is missing, duplicate, or conflicting"
            evidence = evidence_rows[0]
            if evidence["evidence_type"] != "assumption":
                return None, None, f"{scenario_name} DCF assumption {field} is not a persisted assumption receipt"
            expected_unit = "currency" if field in {"starting_fcf", "net_debt"} else "ratio"
            if field == "years":
                expected_unit = "years"
            elif field == "shares_outstanding":
                expected_unit = "shares"
            if evidence["unit"] != expected_unit:
                return None, None, f"{scenario_name} DCF assumption {field} evidence unit mismatch"
            if field in {"starting_fcf", "net_debt"}:
                if str(evidence["currency"] or "").upper() != currency.upper():
                    return None, None, f"{scenario_name} DCF assumption {field} evidence currency mismatch"
            elif evidence["currency"] not in (None, ""):
                return None, None, f"{scenario_name} DCF assumption {field} unexpectedly carries currency"
            if not evidence["source_uri"] or not evidence["source_name"]:
                return None, None, f"{scenario_name} DCF assumption {field} lacks a source receipt locator"
            retrieved, published = _dt(evidence["retrieved_at"]), _dt(evidence["published_at"])
            if retrieved is None or published is None or retrieved > cutoff or published > cutoff:
                return None, None, f"{scenario_name} DCF assumption {field} has missing or future provenance time"
            persisted_value = _stored_number(evidence["value_text"])
            if persisted_value != value:
                return None, None, f"{scenario_name} DCF assumption {field} does not equal persisted evidence value"
            parsed[field] = value
        if parsed["years"] != parsed["years"].to_integral_value() or parsed["years"] <= 0:
            return None, None, f"{scenario_name} DCF years must be a positive integer"
        try:
            assumptions[scenario_name] = DcfAssumptions(
                starting_fcf=parsed["starting_fcf"], annual_growth_rate=parsed["annual_growth_rate"],
                discount_rate=parsed["discount_rate"], terminal_growth_rate=parsed["terminal_growth_rate"],
                years=int(parsed["years"]), net_debt=parsed["net_debt"], shares_outstanding=parsed["shares_outstanding"],
            )
        except (ValueError, TypeError):
            return None, None, f"{scenario_name} DCF assumptions are invalid"
    metrics = result.get("metrics")
    if not isinstance(metrics, list):
        return None, None, "persisted valuation metrics are malformed"
    output: dict[str, Money] = {}
    for name in ("base", "optimistic"):
        metric_name = f"dcf_scenario_{name}"
        found = [metric for metric in metrics if isinstance(metric, dict) and metric.get("name") == metric_name]
        if len(found) != 1 or not isinstance(found[0].get("evidence_ids"), list):
            return None, None, f"persisted {name} fair-value metric is missing or ambiguous"
        metric = found[0]
        bound_ids = set(scenarios[name]["evidence"].values())
        if set(metric["evidence_ids"]) != bound_ids:
            return None, None, f"persisted {name} fair-value metric does not bind all assumption evidence"
        reported = _stored_number(metric.get("value"))
        calculated = EquityValuationAnalyzer._dcf_per_share(assumptions[name])
        if reported is None or calculated != reported:
            return None, None, f"persisted {name} fair value does not match its verified assumptions ({calculated} != {reported})"
        output[name] = Money(reported, currency.upper(), verified=True)
    return output["base"], output["optimistic"], None


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
    fair_value: Money | None = None
    optimistic_fair_value: Money | None = None
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
                        "SELECT e.*, m.observation_id, m.value_numeric, m.unit AS market_unit, "
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
                    if len(rows) != 1:
                        reasons.append("selected persisted market quote is missing or ambiguous")
                    else:
                        row = rows[0]
                        evidence_id = row["evidence_id"]
                        status = row["freshness_status"]
                        if not status or status != row["market_freshness"] or status != row["assessment_status"]:
                            reasons.append("quote freshness status is missing or inconsistent")
                        if status not in {"FRESH", "DELAYED", "LAST_VALID_CLOSE"}:
                            reasons.append(f"quote freshness {status or 'UNKNOWN'} is not eligible")
                        currency = row["currency"]
                        if not currency or currency != row["market_currency"]:
                            reasons.append("persisted quote currency is missing or inconsistent")
                        if row["metric"] != "current_price" or row["unit"] not in {"USD/share", "EUR/share", "JPY/share", "GBP/share", "CAD/share", "AUD/share", "CHF/share", "CNY/share", "HKD/share", "KRW/share"}:
                            reasons.append("persisted quote unit is not a supported per-share currency unit")
                        try:
                            value = Decimal(str(row["value_text"]))
                            market_value = Decimal(str(row["value_numeric"]))
                        except (InvalidOperation, TypeError, ValueError):
                            value = market_value = Decimal("NaN")
                        if not value.is_finite() or value <= 0 or market_value != value:
                            reasons.append("persisted evidence and market quote values do not match as a positive finite number")
                        details = _json(row["assessment_details"])
                        metadata = _json(row["market_metadata"])
                        timestamps = [
                            _dt(row["observed_at"]), _dt(row["published_at"]),
                            _dt(row["market_observed_at"]), _dt(row["claimed_market_time"]),
                        ]
                        if any(item is None for item in timestamps):
                            reasons.append("quote observation/publication timestamps are incomplete")
                        elif any(item > cutoff for item in timestamps if item is not None):
                            reasons.append("future-dated quote evidence is not eligible")
                        if status == "LAST_VALID_CLOSE":
                            if details is None or details.get("quote_kind") != "LAST_VALID_CLOSE":
                                reasons.append("LAST_VALID_CLOSE lacks persisted calendar assessment")
                            if not details or not details.get("calendar_id") or not details.get("market_session_date"):
                                reasons.append("LAST_VALID_CLOSE lacks verified calendar/session identity")
                            if row["market_session_date"] != (details or {}).get("market_session_date"):
                                reasons.append("LAST_VALID_CLOSE session date does not match its assessment")
                            if not details or _dt(details.get("effective_time")) is None or _dt(details.get("public_available_time")) is None:
                                reasons.append("LAST_VALID_CLOSE effective/public timestamps are missing")
                            elif _dt(details.get("effective_time")) > cutoff or _dt(details.get("public_available_time")) > cutoff:
                                reasons.append("LAST_VALID_CLOSE assessment contains a future timestamp")
                        if metadata is None:
                            reasons.append("persisted quote metadata is missing or malformed")
                        if not reasons:
                            quote = Money(value, str(currency).upper(), verified=True)
                    fair_value, optimistic_fair_value, valuation_reason = _persisted_dcf_values(
                        connection, run_id=run_id, instrument_id=instrument_id, cutoff=cutoff
                    )
        except (sqlite3.Error, OSError, ValueError) as exc:
            reasons.append(f"run database could not be read safely: {type(exc).__name__}")
    if valuation_reason:
        reasons.append(valuation_reason)
    return PolicyBMarketEvidence(
        run_id=run_id, instrument_id=instrument_id, as_of=as_of,
        quote_per_share=quote, quote_evidence_id=evidence_id if quote else None,
        fair_value_per_share=fair_value,
        optimistic_fair_value_per_share=optimistic_fair_value,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )
