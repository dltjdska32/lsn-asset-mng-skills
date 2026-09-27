"""Fail-closed bindings from requested numbers to persisted calculation lineage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from investment_stack.contracts.calculation import CalculationStatus, OutputKind
from investment_stack.contracts.codec import compute_semantic_hash, decode_contract, decode_envelope
from investment_stack.contracts.storage import build_canonical_binding_projection
from investment_stack.evidence.manager import RunDatabaseManager


@dataclass(frozen=True, slots=True)
class PersistedNumericBinding:
    """A requested numeric value proven equal to a persisted typed calculation output."""

    calculation_id: str
    evidence_ids: tuple[str, ...]
    value: Decimal
    unit: str
    currency: str | None
    output_kind: OutputKind


def bind_persisted_numeric(
    manager: RunDatabaseManager,
    *,
    calculation_id: str,
    requested_value: Decimal | str | int,
    evidence_ids: tuple[str, ...],
    output_kind: OutputKind | str,
    analysis_as_of: datetime,
) -> PersistedNumericBinding | None:
    """Bind a number to verified persisted evidence/calculation values at a pinned cutoff.

    Missing, ambiguous, inconsistent, or corrupt persistence is reported as unavailable
    (`None`). This helper does not use a caller-provided number as calculation evidence.
    It checks persisted numeric equality, evidence projection consistency, and point-in-time
    availability. It does not validate eligibility policy or authorize a final briefing.
    """
    try:
        requested = Decimal(str(requested_value))
        kind = OutputKind(output_kind)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if (
        not requested.is_finite()
        or not calculation_id
        or not isinstance(analysis_as_of, datetime)
        or analysis_as_of.tzinfo is None
    ):
        return None
    if not evidence_ids or any(not isinstance(item, str) or not item for item in evidence_ids):
        return None
    requested_evidence = tuple(sorted(set(evidence_ids)))
    if len(requested_evidence) != len(evidence_ids):
        return None

    try:
        if not manager.verify_contract_storage_integrity():
            return None
        snapshots = manager.fetch_contract_snapshots()
        calculations = manager.fetch_contract_calculations()
        evidence_rows = manager.fetch_evidence_rows()
    except Exception:
        return None

    matching_calculations = [row for row in calculations if row.calculation_id == calculation_id]
    if len(matching_calculations) != 1:
        return None
    record = matching_calculations[0]
    if (
        record.run_id != manager.run_id
        or record.status not in {CalculationStatus.CALCULATED, CalculationStatus.CONDITIONAL}
        or not record.verify_lineage()
        or not record.bound_inputs
    ):
        return None

    matching_snapshots = [
        snapshot
        for snapshot in snapshots
        if snapshot.snapshot_hash == record.selection_snapshot_hash
        and snapshot.run_id == record.run_id
    ]
    if len(matching_snapshots) != 1:
        return None
    snapshot = matching_snapshots[0]
    selected_by_slot = {slot.slot_id: slot for slot in snapshot.slots}
    evidence_by_id = {row.get("evidence_id"): row for row in evidence_rows}
    bound_evidence: set[str] = set()
    for bound in record.bound_inputs:
        selected = selected_by_slot.get(bound.slot_id)
        if (
            selected is None
            or selected.evidence_id != bound.evidence_id
            or selected.canonical_value != bound.canonical_value
            or selected.canonical_unit != bound.canonical_unit
            or selected.canonical_currency != bound.canonical_currency
            or selected.input_fingerprint != bound.input_fingerprint
            or selected.eligibility_id != bound.eligibility_id
        ):
            return None
        evidence_row = evidence_by_id.get(bound.evidence_id)
        if evidence_row is None or evidence_row.get("run_id") != record.run_id:
            return None
        try:
            metadata = json.loads(evidence_row.get("metadata_json") or "")
            envelope = metadata.get("contract_envelope")
            canonical = metadata.get("canonical_payload")
            kind_name, payload = decode_envelope(envelope)
            dto = decode_contract(envelope, expected_kind=kind_name)
            projection = build_canonical_binding_projection(dto)
            if canonical != projection or evidence_row.get("content_hash") != compute_semantic_hash(payload):
                return None
            if (
                projection.get("evidence_id") != bound.evidence_id
                or Decimal(str(projection.get("canonical_value"))) != bound.canonical_value
                or projection.get("canonical_unit") != bound.canonical_unit
                or (projection.get("canonical_currency") or projection.get("currency"))
                != bound.canonical_currency
            ):
                return None
            available_text = projection.get("public_available_at")
            if not isinstance(available_text, str) or not available_text:
                return None
            available_at = datetime.fromisoformat(available_text.replace("Z", "+00:00"))
            if available_at.tzinfo is None or available_at > analysis_as_of:
                return None
            if bound.public_available_at != available_text:
                return None
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return None
        bound_evidence.add(bound.evidence_id)
    if tuple(sorted(bound_evidence)) != requested_evidence:
        return None

    try:
        outputs = [output for output in record.typed_outputs if OutputKind(output.kind) == kind]
    except (TypeError, ValueError):
        return None
    if len(outputs) != 1:
        return None
    output = outputs[0]
    if output.value != requested or (record.result_numeric is not None and record.result_numeric != output.value):
        return None
    return PersistedNumericBinding(
        calculation_id=record.calculation_id,
        evidence_ids=requested_evidence,
        value=output.value,
        unit=output.unit,
        currency=output.currency,
        output_kind=kind,
    )
