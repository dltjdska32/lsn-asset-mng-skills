"""Register and verify technical Bar evidence against a persisted run database."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from investment_stack.contracts.codec import compute_content_hash, decode_contract, encode_envelope
from investment_stack.contracts.market import Bar
from investment_stack.decisions.technical_context import (
    TechnicalBriefingContext,
    _bar_fingerprint,
)
from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.providers.ohlcv import OHLCVParseResult


def _pinned_cutoff(manager: RunDatabaseManager) -> datetime | None:
    try:
        text = manager.fetch_metadata().get("analysis_as_of")
        if not isinstance(text, str) or not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except Exception:
        return None


def register_technical_bar_set(
    manager: RunDatabaseManager,
    parse_result: OHLCVParseResult,
) -> tuple[str, ...] | None:
    """Persist provider-produced Bars as typed evidence in this manager's run.

    Caller receipt fields remain attestations; this function proves only that the
    typed bar payloads were registered in this run and match their content hashes.
    """
    if not isinstance(manager, RunDatabaseManager) or not isinstance(parse_result, OHLCVParseResult):
        return None
    if not parse_result.analysis_eligible or parse_result.bar_set is None or parse_result.analysis_as_of is None:
        return None
    bars = tuple(parse_result.bar_set.bars)
    if not bars or tuple(parse_result.bars) != bars or len({bar.evidence_id for bar in bars}) != len(bars):
        return None
    cutoff = _pinned_cutoff(manager)
    if cutoff is None or cutoff != parse_result.analysis_as_of:
        return None
    try:
        if not manager.verify_contract_storage_integrity():
            return None
        existing = manager.fetch_evidence_rows()
        existing_ids = {row.get("evidence_id") for row in existing}
        if any(bar.evidence_id in existing_ids for bar in bars):
            return None
        # The manager owns run_id and performs the transaction/path checks; callers
        # cannot claim another run by passing a string.
        for bar in bars:
            manager.add_contract_evidence(
                evidence_id=bar.evidence_id,
                contract_envelope=encode_envelope("Bar", bar),
                source_uri=parse_result.source_url,
                content_hash=compute_content_hash(bar),
                evidence_type="technical_bar",
            )
        return tuple(bar.evidence_id for bar in bars)
    except Exception:
        return None


def verify_technical_run_binding(
    manager: RunDatabaseManager,
    parse_result: OHLCVParseResult,
    context: TechnicalBriefingContext,
) -> tuple[str, ...] | None:
    """Return evidence IDs only when run storage exactly matches the analyzed bars."""
    if not isinstance(manager, RunDatabaseManager) or not isinstance(parse_result, OHLCVParseResult):
        return None
    if not isinstance(context, TechnicalBriefingContext) or not parse_result.analysis_eligible:
        return None
    bar_set = parse_result.bar_set
    cutoff = parse_result.analysis_as_of
    if (
        bar_set is None or cutoff is None or cutoff.tzinfo is None
        or not isinstance(parse_result.source_url, str) or not parse_result.source_url.strip()
    ):
        return None
    bars = tuple(bar_set.bars)
    if (
        not bars
        or tuple(parse_result.bars) != bars
        or len({bar.evidence_id for bar in bars}) != len(bars)
        or context.instrument_id != bar_set.instrument_id
        or context.analysis_as_of != cutoff.isoformat()
        or context.input_fingerprint != _bar_fingerprint(bars)
    ):
        return None
    pinned = _pinned_cutoff(manager)
    if pinned is None or pinned != cutoff:
        return None
    try:
        if not manager.verify_contract_storage_integrity():
            return None
        rows = manager.fetch_evidence_rows()
        by_id: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_id.setdefault(row.get("evidence_id"), []).append(row)
        for expected in bars:
            matched = by_id.get(expected.evidence_id, [])
            if len(matched) != 1:
                return None
            row = matched[0]
            if (
                row.get("run_id") != manager.run_id
                or row.get("evidence_type") != "technical_bar"
                or row.get("source_uri") != parse_result.source_url
            ):
                return None
            metadata = json.loads(row.get("metadata_json") or "")
            envelope = metadata.get("contract_envelope")
            if not isinstance(envelope, dict):
                return None
            stored = decode_contract(envelope, expected_kind="Bar")
            if (
                not isinstance(stored, Bar)
                or stored != expected
                or metadata.get("contract_kind") != "Bar"
                or row.get("content_hash") != compute_content_hash(stored)
                or row.get("content_hash") != compute_content_hash(expected)
            ):
                return None
        return tuple(bar.evidence_id for bar in bars)
    except Exception:
        return None


__all__ = ["register_technical_bar_set", "verify_technical_run_binding"]
