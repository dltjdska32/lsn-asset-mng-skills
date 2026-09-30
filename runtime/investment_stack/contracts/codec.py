"""Strict stdlib-only codec, canonical JSON serialization, and content hashing."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable

from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    KindValidationError,
    TimezoneValidationError,
)

CONTRACT_VERSION = "0.2"
MAX_PAYLOAD_BYTES = 262144

ALLOWED_ENVELOPE_KEYS = frozenset({"contract_version", "kind", "payload"})

VALID_CONTRACT_KINDS = frozenset(
    {
        "RunContext",
        "PublicAvailability",
        "PinnedPersonalState",
        "SlotSpec",
        "EligibilityDecision",
        "BoundSlotInput",
        "ExcludedCandidate",
        "SelectedInputSet",
        "SelectionRequest",
        "CoverageDecision",
        "FinancialFact",
        "FinancialSet",
        "MarketQuote",
        "Bar",
        "BarSet",
        "Filing13F",
        "Holding13F",
        "HoldingSet13F",
        "CalculationAssumption",
        "CalculationRecord",
        "GateDecision",
        "ProviderObservation",
        "TypedOutput",
    }
)

_DECODERS: dict[str, Callable[[dict[str, Any]], Any]] = {}


def register_decoder(kind: str, decoder: Callable[[dict[str, Any]], Any]) -> None:
    """Register a typed decoder for a closed contract kind."""
    if kind not in VALID_CONTRACT_KINDS:
        raise KindValidationError(f"Cannot register decoder for non-contract kind: {kind}")
    _DECODERS[kind] = decoder


def parse_finite_decimal(val: Any) -> Decimal:
    """Parse a value into a finite Decimal.

    Strict rules:
    - Rejects booleans (isinstance(val, bool) is checked first).
    - Rejects floats (to prevent precision loss).
    - Rejects NaN, Infinity, -Infinity, and empty strings.
    - Accepts integers, canonical strings, and existing finite Decimals.
    """
    if isinstance(val, bool):
        raise DecimalValidationError("Boolean value cannot be parsed as Decimal")
    if isinstance(val, float):
        raise DecimalValidationError(
            "Float value is not permitted; pass integer, string, or Decimal to avoid precision loss"
        )
    if isinstance(val, Decimal):
        if not val.is_finite():
            raise DecimalValidationError(f"Non-finite Decimal is not allowed: {val}")
        return val
    if isinstance(val, (int, str)):
        s = str(val).strip()
        if not s:
            raise DecimalValidationError("Empty string cannot be parsed as Decimal")
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise DecimalValidationError(f"Invalid decimal string: {val!r}") from exc
        if not d.is_finite():
            raise DecimalValidationError(f"Non-finite Decimal is not allowed: {val}")
        return d
    raise DecimalValidationError(f"Unsupported type for Decimal conversion: {type(val).__name__}")


def format_decimal(d: Decimal) -> str:
    """Format a finite Decimal into a canonical base-10 string without scientific notation."""
    if not d.is_finite():
        raise DecimalValidationError(f"Cannot format non-finite Decimal: {d}")
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in {"-0", "-0."}:
        s = "0"
    return s


def parse_strict_bool(val: Any) -> bool:
    """Parse a strict boolean value, rejecting strings, numbers, and None."""
    if val is True:
        return True
    if val is False:
        return False
    raise ContractValidationError(
        f"Expected boolean True or False, got {type(val).__name__}: {val!r}"
    )


def parse_strict_int(val: Any) -> int:
    """Parse an integer value strictly, rejecting booleans, floats, and invalid strings."""
    if isinstance(val, bool):
        raise ContractValidationError("Boolean value cannot be parsed as int")
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
    raise ContractValidationError(
        f"Expected integer, got {type(val).__name__}: {val!r}"
    )


def parse_iso_date(val: Any) -> str:
    """Validate and return a canonical ISO YYYY-MM-DD date string."""
    from datetime import date
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, str):
        s = val.strip()
        try:
            d = date.fromisoformat(s)
            return d.isoformat()
        except ValueError as exc:
            raise ContractValidationError(f"Invalid ISO date string: {val!r}") from exc
    raise ContractValidationError(f"Expected ISO date string, got {type(val).__name__}")


def to_canonical_dict(obj: Any) -> Any:
    """Convert an arbitrary contract object into a canonical dict/list/scalar tree."""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        raise ContractValidationError("Float value is not permitted in canonical contracts")
    if isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, Decimal):
        return format_decimal(obj)
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise TimezoneValidationError(f"Naive datetime encountered: {obj}")
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            result[f.name] = to_canonical_dict(val)
        return result
    if isinstance(obj, (dict, Mapping, MappingProxyType)):
        # Reject non-string / non-scalar keys
        return {
            str(k): to_canonical_dict(v)
            for k, v in sorted(obj.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_canonical_dict(item) for item in obj]
    raise ContractValidationError(f"Unserializable object of type {type(obj).__name__}")


def to_canonical_json(obj: Any) -> str:
    """Serialize an object into deterministic canonical JSON (sorted keys, compact separators, no NaN)."""
    canonical_dict = to_canonical_dict(obj)
    return json.dumps(
        canonical_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def to_canonical_bytes(obj: Any) -> bytes:
    """Encode an object to UTF-8 canonical JSON bytes."""
    return to_canonical_json(obj).encode("utf-8")


def compute_content_hash(obj: Any) -> str:
    """Compute the SHA-256 hex digest of the canonical JSON representation of an object."""
    return hashlib.sha256(to_canonical_bytes(obj)).hexdigest()


NON_SEMANTIC_KEYS = frozenset(
    {
        "run_id",
        "created_at",
        "retrieved_at",
        "evidence_id",
        "observation_id",
        "calculation_id",
        "eligibility_id",
        "candidate_id",
        "snapshot_hash",
        "lineage_hash",
        "assessed_at",
    }
)


def _strip_non_semantic(obj: Any) -> Any:
    """Recursively strip run-local IDs and timestamps to compute semantic invariance hash."""
    if isinstance(obj, dict):
        return {
            k: _strip_non_semantic(v)
            for k, v in sorted(obj.items())
            if k not in NON_SEMANTIC_KEYS
        }
    if isinstance(obj, list):
        return [_strip_non_semantic(item) for item in obj]
    return obj


def compute_semantic_hash(obj: Any) -> str:
    """Compute semantic hash invariant to run-local identifiers and timestamps."""
    canonical = to_canonical_dict(obj)
    stripped = _strip_non_semantic(canonical)
    raw_json = json.dumps(
        stripped,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


def encode_envelope(
    kind: str, payload: Any, *, contract_version: str = CONTRACT_VERSION
) -> dict[str, Any]:
    """Wrap a payload into a versioned contract envelope with closed kind validation."""
    if kind not in VALID_CONTRACT_KINDS:
        raise KindValidationError(
            f"Unrecognized contract kind: {kind!r} (must be one of {sorted(VALID_CONTRACT_KINDS)})"
        )
    return {
        "contract_version": contract_version,
        "kind": kind,
        "payload": to_canonical_dict(payload),
    }


def decode_envelope(
    envelope: dict[str, Any], *, expected_kind: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Validate and unpack a contract envelope.

    Verifies:
    - Envelope is a dict with exactly {'contract_version', 'kind', 'payload'} (no extra fields).
    - contract_version matches CONTRACT_VERSION ('0.2').
    - kind is in VALID_CONTRACT_KINDS.
    - kind matches expected_kind if specified.
    - payload is a dict.
    """
    if not isinstance(envelope, dict):
        raise ContractValidationError(f"Envelope must be a dict, got {type(envelope).__name__}")

    keys = set(envelope.keys())
    if keys != ALLOWED_ENVELOPE_KEYS:
        extra = keys - ALLOWED_ENVELOPE_KEYS
        missing = ALLOWED_ENVELOPE_KEYS - keys
        errors: list[str] = []
        if extra:
            errors.append(f"unexpected fields: {sorted(extra)}")
        if missing:
            errors.append(f"missing fields: {sorted(missing)}")
        raise ContractValidationError(f"Invalid envelope structure: {', '.join(errors)}")

    version = envelope["contract_version"]
    if version != CONTRACT_VERSION:
        raise ContractValidationError(
            f"Unsupported contract version: {version!r} (expected {CONTRACT_VERSION!r})"
        )

    kind = envelope["kind"]
    if not isinstance(kind, str) or not kind:
        raise KindValidationError("Envelope kind missing or invalid")
    if kind not in VALID_CONTRACT_KINDS:
        raise KindValidationError(
            f"Unrecognized contract kind: {kind!r} (must be one of {sorted(VALID_CONTRACT_KINDS)})"
        )

    if expected_kind is not None and kind != expected_kind:
        raise KindValidationError(
            f"Envelope kind mismatch: expected {expected_kind!r}, got {kind!r}"
        )

    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise ContractValidationError(
            f"Envelope payload must be a dict, got {type(payload).__name__}"
        )

    return kind, payload


def encode_contract(value: Any) -> str:
    """Encode any registered contract DTO into a canonical JSON contract document."""
    kind = type(value).__name__
    if kind not in VALID_CONTRACT_KINDS:
        raise KindValidationError(f"Cannot encode unregistered contract type: {kind}")
    envelope = encode_envelope(kind, value)
    return to_canonical_json(envelope)


def _reject_duplicate_pairs(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    res: dict[Any, Any] = {}
    for k, v in pairs:
        if k in res:
            raise ContractValidationError(f"Duplicate key in JSON object: {k!r}")
        res[k] = v
    return res


def _reject_constant(c: str) -> None:
    raise ContractValidationError(f"Nonstandard JSON constant not permitted: {c!r}")


def parse_strict_json(raw: str | bytes) -> Any:
    """Parse JSON strictly: rejecting duplicate keys, NaN, Infinity, -Infinity."""
    if isinstance(raw, bytes):
        try:
            raw_str = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractValidationError(f"Invalid UTF-8 encoding in JSON: {exc}") from exc
    elif isinstance(raw, str):
        raw_str = raw
    else:
        raise ContractValidationError(f"Expected str or bytes, got {type(raw).__name__}")

    try:
        return json.loads(
            raw_str,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except ContractValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractValidationError(f"Invalid JSON document: {exc}") from exc


def decode_contract(
    document: str | bytes | dict[str, Any], *, expected_kind: str | None = None
) -> Any:
    """Decode a canonical JSON contract document or payload into its strongly-typed DTO."""
    if isinstance(document, (str, bytes)):
        raw = parse_strict_json(document)
    elif isinstance(document, dict):
        raw = document
    else:
        raise ContractValidationError(
            f"Document must be str, bytes, or dict, got {type(document).__name__}"
        )

    if not isinstance(raw, dict):
        raise ContractValidationError(f"Parsed document must be a dict, got {type(raw).__name__}")

    # If raw is a full envelope with contract_version and payload
    if "contract_version" in raw and "payload" in raw:
        kind, payload = decode_envelope(raw, expected_kind=expected_kind)
        decoder = _DECODERS.get(kind)
        if decoder is None:
            raise KindValidationError(f"No registered typed decoder for contract kind: {kind}")
        return decoder(payload)

    # If raw is a plain payload dict and expected_kind is specified
    if expected_kind is not None:
        decoder = _DECODERS.get(expected_kind)
        if decoder is None:
            raise KindValidationError(f"No registered typed decoder for contract kind: {expected_kind}")
        return decoder(raw)

    raise ContractValidationError("Envelope missing required 'contract_version' and 'payload' fields")
