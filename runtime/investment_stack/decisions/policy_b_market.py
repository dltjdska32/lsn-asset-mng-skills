"""Read-only bridge from persisted run evidence to D12 B market Money.

This adapter intentionally verifies only the selected quote. Phase 5 DCF
scenario labels/IDs do not bind their assumption values and therefore cannot
produce verified fair-value Money here.
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
        except (sqlite3.Error, OSError, ValueError) as exc:
            reasons.append(f"run database could not be read safely: {type(exc).__name__}")
    # Phase 5 calculation rows can contain scenario IDs without the complete
    # assumption-value provenance required to certify policy fair values.
    reasons.append("base and optimistic fair values unavailable: complete assumption-value provenance is not persisted/verified")
    return PolicyBMarketEvidence(
        run_id=run_id, instrument_id=instrument_id, as_of=as_of,
        quote_per_share=quote, quote_evidence_id=evidence_id if quote else None,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )
