"""Contract storage helpers, CAS revision control, and JSON payload size enforcement."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

from investment_stack.contracts.calculation import (
    CalculationAssumption,
    CalculationRecord,
    CalculationStatus,
)
from investment_stack.contracts.codec import (
    decode_envelope,
    encode_envelope,
    to_canonical_bytes,
    to_canonical_dict,
)
from investment_stack.contracts.errors import (
    CorruptedStorageError,
    HistoryPreservationError,
    PayloadSizeExceededError,
    TamperDetectionError,
)
from investment_stack.contracts.slots import (
    BoundSlotInput,
    ExcludedCandidate,
    SelectedInputSet,
)

CONTRACT_STORAGE_KEY = "_contract_storage_v2"
MAX_PAYLOAD_SIZE_BYTES = 262144  # 256 KB per individual snapshot/calc payload budget
MAX_PAYLOAD_BYTES = MAX_PAYLOAD_SIZE_BYTES


def empty_contract_storage() -> dict[str, Any]:
    """Create a pristine contract storage container."""
    return {
        "schema_version": "0.2",
        "latest_revision": 0,
        "latest_snapshot_hash": "",
        "active_selections": {},
        "history": [],
        "calculations": [],
        "requests": [],
    }


def build_canonical_binding_projection(dto: Any) -> dict[str, Any]:
    """Extract canonical binding projection from a verified contract DTO."""
    from investment_stack.contracts.financial import FinancialFact
    from investment_stack.contracts.institutional import Holding13F
    from investment_stack.contracts.market import Bar, MarketQuote

    def availability_fields(availability: Any) -> dict[str, Any]:
        if availability is None:
            return {}
        return {
            "availability_kind": str(availability.kind),
            "public_available_at": (
                availability.public_available_at or availability.interval_end
            ).isoformat() if (availability.public_available_at or availability.interval_end) else None,
            "availability_interval_start": availability.interval_start.isoformat()
            if availability.interval_start else None,
            "availability_interval_end": availability.interval_end.isoformat()
            if availability.interval_end else None,
            "availability_source_timezone": availability.source_timezone,
            "availability_source_locator": availability.source_locator,
        }

    if isinstance(dto, MarketQuote):
        return {
            "evidence_id": dto.evidence_id,
            "instrument_id": dto.instrument_id,
            "canonical_value": str(dto.price),
            "canonical_unit": "CURRENCY",
            "canonical_currency": dto.currency,
            "dimension": "MONEY_PER_SHARE",
            **availability_fields(dto.public_availability),
            "contract_kind": "MarketQuote",
            "metric": "price",
        }
    if isinstance(dto, FinancialFact):
        proj = {
            "evidence_id": dto.evidence_id,
            "instrument_id": dto.instrument_id,
            "canonical_value": str(dto.normalized_value),
            "canonical_unit": dto.raw_unit,
            "canonical_currency": dto.currency,
            "dimension": str(dto.dimension),
            **availability_fields(dto.public_availability),
            "contract_kind": "FinancialFact",
            "metric": dto.canonical_metric,
        }
        for attr in (
            "period_type",
            "period_start",
            "period_end",
            "duration_days",
            "fiscal_year",
            "fiscal_period",
            "reporting_frequency",
            "consolidation",
            "accounting_standard",
            "adjustment_basis",
            "share_basis",
        ):
            val = getattr(dto, attr, None)
            if val is not None:
                proj[attr] = val if isinstance(val, int) and not isinstance(val, bool) else str(val)
        return proj
    if isinstance(dto, Bar):
        return {
            "evidence_id": dto.evidence_id,
            "instrument_id": dto.instrument_id,
            "canonical_value": str(dto.close),
            "canonical_unit": "CURRENCY",
            "canonical_currency": dto.currency,
            "dimension": "MONEY_PER_SHARE",
            **availability_fields(dto.public_availability),
            "contract_kind": "Bar",
            "metric": "close",
        }
    if isinstance(dto, Holding13F):
        return {
            "evidence_id": dto.holding_id,
            "instrument_id": dto.mapped_instrument_id or dto.cusip,
            "canonical_value": str(dto.normalized_value),
            "canonical_unit": "CURRENCY",
            "canonical_currency": dto.value_currency,
            "dimension": "MONEY",
            "contract_kind": "Holding13F",
            "metric": "holding_value",
        }

    # Generic projection fallback
    proj: dict[str, Any] = {"contract_kind": type(dto).__name__}
    for attr in ("evidence_id", "instrument_id", "currency", "canonical_metric", "metric"):
        if hasattr(dto, attr) and getattr(dto, attr) is not None:
            proj[attr] = getattr(dto, attr)
    if hasattr(dto, "price") and getattr(dto, "price") is not None:
        proj["canonical_value"] = str(getattr(dto, "price"))
    elif hasattr(dto, "normalized_value") and getattr(dto, "normalized_value") is not None:
        proj["canonical_value"] = str(getattr(dto, "normalized_value"))
    elif hasattr(dto, "value") and getattr(dto, "value") is not None:
        proj["canonical_value"] = str(getattr(dto, "value"))
    if hasattr(dto, "currency") and getattr(dto, "currency") is not None:
        proj["canonical_currency"] = getattr(dto, "currency")
    if hasattr(dto, "public_availability") and getattr(dto, "public_availability") is not None:
        pa = getattr(dto, "public_availability")
        proj.update(availability_fields(pa))
    return proj


def validate_contract_storage_ledger(
    storage: dict[str, Any], *, expected_run_id: str | None = None
) -> None:
    """Strictly validate contract storage ledger integrity, schema version, counter tail, envelope presence, and pointers."""
    if not isinstance(storage, dict):
        raise CorruptedStorageError(f"Contract storage is not a dictionary: {type(storage).__name__}")

    schema_version = storage.get("schema_version") or storage.get("contract_version")
    if schema_version != "0.2":
        raise CorruptedStorageError(
            f"Unsupported contract storage schema_version: {schema_version!r} (expected '0.2')"
        )

    latest_rev = storage.get("latest_revision")
    if latest_rev is None or isinstance(latest_rev, bool) or not isinstance(latest_rev, int) or latest_rev < 0:
        raise CorruptedStorageError(f"Corrupted contract storage: invalid latest_revision {latest_rev!r}")

    latest_hash = storage.get("latest_snapshot_hash", "")
    if not isinstance(latest_hash, str):
        raise CorruptedStorageError("Corrupted contract storage: latest_snapshot_hash must be a string")

    history = storage.get("history")
    if history is None or not isinstance(history, list):
        raise CorruptedStorageError("Corrupted contract storage: history must be a list")

    calcs = storage.get("calculations", [])
    if not isinstance(calcs, list):
        raise CorruptedStorageError("Corrupted contract storage: calculations must be a list")

    requests = storage.get("requests", [])
    if not isinstance(requests, list):
        raise CorruptedStorageError("Corrupted contract storage: requests must be a list")

    active_selections = storage.get("active_selections", {})
    if not isinstance(active_selections, dict):
        raise CorruptedStorageError("Corrupted contract storage: active_selections must be a dict")

    # Validate counter tail match with history
    if len(history) == 0:
        if latest_rev != 0 or latest_hash != "":
            raise CorruptedStorageError(
                f"Counter tail mismatch: empty history requires revision 0 and empty hash, got revision {latest_rev}, hash {latest_hash!r}"
            )
    else:
        tail = history[-1]
        if not isinstance(tail, dict):
            raise CorruptedStorageError("Corrupted contract storage: history entry is not a dict")
        tail_rev = tail.get("revision")
        tail_hash = tail.get("snapshot_hash", "")
        if latest_rev != tail_rev or latest_hash != tail_hash:
            raise CorruptedStorageError(
                f"Counter tail mismatch: latest_revision={latest_rev}, latest_snapshot_hash={latest_hash!r} "
                f"does not match tail entry revision={tail_rev}, snapshot_hash={tail_hash!r}"
            )

    # Validate history chain and envelopes
    known_snapshot_hashes: set[str] = set()
    snapshots_by_hash: dict[str, SelectedInputSet] = {}
    expected_prev_hash = ""
    for idx, entry in enumerate(history):
        if not isinstance(entry, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} is not a dict")
        if "envelope" not in entry or not entry["envelope"]:
            raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} missing 'envelope'")
        rev = entry.get("revision")
        if rev != idx + 1:
            raise CorruptedStorageError(
                f"Corrupted contract storage: history entry {idx} has revision {rev}, expected {idx + 1}"
            )
        snap_hash = entry.get("snapshot_hash")
        if not snap_hash or not isinstance(snap_hash, str):
            raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} missing snapshot_hash")
        prev_h = entry.get("previous_snapshot_hash", "")
        if prev_h != expected_prev_hash:
            raise CorruptedStorageError(
                f"Corrupted contract storage: history entry {idx} previous_snapshot_hash '{prev_h}' != expected '{expected_prev_hash}'"
            )

        envelope = entry["envelope"]
        if not isinstance(envelope, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} envelope is not a dict")
        try:
            snap = deserialize_snapshot_envelope(envelope)
            if snap.snapshot_hash != snap_hash:
                raise CorruptedStorageError(
                    f"Corrupted contract storage: history entry {idx} envelope hash '{snap.snapshot_hash}' != entry hash '{snap_hash}'"
                )
            if not snap.verify_hash():
                raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} hash verification failed")
            if expected_run_id is not None and snap.run_id != expected_run_id:
                raise CorruptedStorageError(
                    f"Corrupted contract storage: history entry {idx} run_id '{snap.run_id}' != expected '{expected_run_id}'"
                )
        except CorruptedStorageError:
            raise
        except Exception as exc:
            raise CorruptedStorageError(f"Corrupted contract storage: history entry {idx} invalid snapshot: {exc}") from exc

        expected_prev_hash = snap_hash
        known_snapshot_hashes.add(snap_hash)
        snapshots_by_hash[snap_hash] = snap

    # Validate active_selections pointers
    for pointer_key, target_hash in active_selections.items():
        if not isinstance(pointer_key, str) or not isinstance(target_hash, str):
            raise CorruptedStorageError("Corrupted contract storage: active_selections keys and values must be strings")
        if target_hash not in known_snapshot_hashes:
            raise CorruptedStorageError(
                f"Dangling active selection pointer for '{pointer_key}': target hash '{target_hash}' not in history"
            )

    # Validate calculations
    for c_idx, c_entry in enumerate(calcs):
        if not isinstance(c_entry, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: calculation entry {c_idx} is not a dict")
        c_envelope = c_entry.get("envelope")
        if not c_envelope or not isinstance(c_envelope, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: calculation entry {c_idx} missing envelope")
        try:
            calc = deserialize_calculation_envelope(c_envelope)
            if not calc.verify_lineage():
                raise CorruptedStorageError(
                    f"Corrupted contract storage: calculation '{calc.calculation_id}' lineage verification failed"
                )
            if expected_run_id is not None and calc.run_id != expected_run_id:
                raise CorruptedStorageError(
                    f"Corrupted contract storage: calculation '{calc.calculation_id}' run_id '{calc.run_id}' != expected '{expected_run_id}'"
                )
            if calc.selection_snapshot_hash not in known_snapshot_hashes:
                raise CorruptedStorageError(
                    f"Corrupted contract storage: calculation '{calc.calculation_id}' references unknown snapshot hash '{calc.selection_snapshot_hash}'"
                )
            snap = snapshots_by_hash[calc.selection_snapshot_hash]
            snap_slots = {slot.slot_id: slot for slot in snap.slots}
            seen: set[str] = set()
            for bound in calc.bound_inputs:
                if bound.slot_id in seen or bound.slot_id not in snap_slots:
                    raise CorruptedStorageError(
                        f"Calculation '{calc.calculation_id}' has duplicate or unknown snapshot input '{bound.slot_id}'"
                    )
                seen.add(bound.slot_id)
                if to_canonical_dict(bound) != to_canonical_dict(snap_slots[bound.slot_id]):
                    raise CorruptedStorageError(
                        f"Calculation '{calc.calculation_id}' input '{bound.slot_id}' differs from referenced snapshot"
                    )
        except CorruptedStorageError:
            raise
        except Exception as exc:
            raise CorruptedStorageError(f"Corrupted contract storage: calculation entry {c_idx} invalid calculation: {exc}") from exc

    # Validate requests
    for r_idx, r_entry in enumerate(requests):
        if not isinstance(r_entry, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: request entry {r_idx} is not a dict")
        r_envelope = r_entry.get("envelope")
        if not r_envelope or not isinstance(r_envelope, dict):
            raise CorruptedStorageError(f"Corrupted contract storage: request entry {r_idx} missing envelope")
        try:
            req = deserialize_request_envelope(r_envelope)
            req_hash = req.compute_request_hash()
            if r_entry.get("request_hash") != req_hash:
                raise CorruptedStorageError(
                    f"Corrupted contract storage: request entry hash '{r_entry.get('request_hash')}' != expected '{req_hash}'"
                )
        except CorruptedStorageError:
            raise
        except Exception as exc:
            raise CorruptedStorageError(f"Corrupted contract storage: request entry {r_idx} invalid request: {exc}") from exc


def extract_contract_storage(
    metadata_json_str: str | None, *, expected_run_id: str | None = None
) -> dict[str, Any]:
    """Safely extract and strictly validate contract storage ledger from run_metadata JSON.

    Never silently resets corrupted data to empty.
    """
    if not metadata_json_str or not metadata_json_str.strip():
        return empty_contract_storage()
    try:
        data = json.loads(metadata_json_str)
    except Exception as exc:
        raise CorruptedStorageError(f"Corrupted metadata JSON in database: {exc}") from exc

    if not isinstance(data, dict):
        raise CorruptedStorageError(f"metadata_json root is not a dict: {type(data).__name__}")

    if CONTRACT_STORAGE_KEY not in data:
        return empty_contract_storage()

    storage = data[CONTRACT_STORAGE_KEY]
    if storage is None or not isinstance(storage, dict):
        raise CorruptedStorageError(
            f"Contract storage {CONTRACT_STORAGE_KEY} is present but corrupted/null: {type(storage).__name__}"
        )

    validate_contract_storage_ledger(storage, expected_run_id=expected_run_id)
    return storage


def validate_metadata_update_preservation(
    existing_metadata_json: str | None, new_metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """Ensure update_metadata preserves contract history and rejects illegal mutation, tampering, or injection.

    Rules:
    - If contract storage already exists: general update_metadata cannot alter, append, or tamper with it.
      If new_metadata specifies CONTRACT_STORAGE_KEY, it must match existing storage exactly.
    - If contract storage does NOT exist: external callers cannot inject a fake contract storage via update_metadata.
    """
    existing_storage: dict[str, Any] | None = None
    if existing_metadata_json and existing_metadata_json.strip():
        try:
            parsed = json.loads(existing_metadata_json)
            if isinstance(parsed, dict) and CONTRACT_STORAGE_KEY in parsed:
                existing_storage = parsed[CONTRACT_STORAGE_KEY]
                if not isinstance(existing_storage, dict):
                    raise CorruptedStorageError("Existing contract storage is not a dictionary")
        except CorruptedStorageError:
            raise
        except Exception as exc:
            raise CorruptedStorageError(f"Corrupted metadata JSON: {exc}") from exc

    incoming = dict(new_metadata or {})

    if existing_storage is None:
        # Protected namespace does not exist yet. Reject injection of fake ledger!
        if CONTRACT_STORAGE_KEY in incoming:
            raise HistoryPreservationError(
                f"Cannot inject contract storage '{CONTRACT_STORAGE_KEY}' via general update_metadata"
            )
        return incoming

    # Protected namespace exists.
    if CONTRACT_STORAGE_KEY in incoming:
        # Must match EXACTLY; any difference is a forbidden tamper/mutation.
        if incoming[CONTRACT_STORAGE_KEY] != existing_storage:
            raise HistoryPreservationError(
                "update_metadata cannot modify, append, or tamper with protected contract storage"
            )
    else:
        # Preserve existing storage automatically
        incoming[CONTRACT_STORAGE_KEY] = copy.deepcopy(existing_storage)

    return incoming


def serialize_snapshot_envelope(snapshot: SelectedInputSet) -> dict[str, Any]:
    """Serialize a SelectedInputSet to an envelope, verifying hash and payload size."""
    if not snapshot.verify_hash():
        raise TamperDetectionError(
            f"SelectedInputSet hash verification failed for run {snapshot.run_id}, purpose {snapshot.purpose}"
        )
    envelope = encode_envelope("SelectedInputSet", snapshot)
    size = len(to_canonical_bytes(envelope))
    if size > MAX_PAYLOAD_SIZE_BYTES:
        raise PayloadSizeExceededError(
            f"SelectedInputSet payload size ({size} bytes) exceeds limit ({MAX_PAYLOAD_SIZE_BYTES} bytes)"
        )
    return envelope


def deserialize_snapshot_envelope(envelope: dict[str, Any]) -> SelectedInputSet:
    """Deserialize and strictly verify a SelectedInputSet from an envelope."""
    kind, payload = decode_envelope(envelope, expected_kind="SelectedInputSet")
    from investment_stack.contracts.slots import _decode_selected_input_set

    return _decode_selected_input_set(payload)


def serialize_calculation_envelope(record: CalculationRecord) -> dict[str, Any]:
    """Serialize a CalculationRecord to an envelope, verifying lineage and payload size."""
    if not record.verify_lineage():
        raise TamperDetectionError(
            f"CalculationRecord lineage verification failed for calculation {record.calculation_id}"
        )
    envelope = encode_envelope("CalculationRecord", record)
    size = len(to_canonical_bytes(envelope))
    if size > MAX_PAYLOAD_SIZE_BYTES:
        raise PayloadSizeExceededError(
            f"CalculationRecord payload size ({size} bytes) exceeds limit ({MAX_PAYLOAD_SIZE_BYTES} bytes)"
        )
    return envelope


def deserialize_calculation_envelope(envelope: dict[str, Any]) -> CalculationRecord:
    """Deserialize and strictly verify a CalculationRecord from an envelope."""
    kind, payload = decode_envelope(envelope, expected_kind="CalculationRecord")
    from investment_stack.contracts.calculation import _decode_calculation_record

    return _decode_calculation_record(payload)


def serialize_request_envelope(request: Any) -> dict[str, Any]:
    """Serialize a SelectionRequest to an envelope and check payload size."""
    # Local import to avoid circular dependency
    from investment_stack.contracts.slots import SelectionRequest

    if not isinstance(request, SelectionRequest):
        raise TypeError("Expected a SelectionRequest instance")

    envelope = encode_envelope("SelectionRequest", request)
    size = len(to_canonical_bytes(envelope))
    if size > MAX_PAYLOAD_SIZE_BYTES:
        raise PayloadSizeExceededError(
            f"SelectionRequest payload size ({size} bytes) exceeds limit ({MAX_PAYLOAD_SIZE_BYTES} bytes)"
        )
    return envelope


def deserialize_request_envelope(envelope: dict[str, Any]) -> Any:
    """Deserialize and strictly verify a SelectionRequest from an envelope."""
    kind, payload = decode_envelope(envelope, expected_kind="SelectionRequest")
    from investment_stack.contracts.slots import _decode_selection_request

    return _decode_selection_request(payload)
