"""Slot specifications, candidate eligibility decisions, and bound input snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable

from investment_stack.contracts.codec import (
    compute_content_hash,
    compute_semantic_hash,
    format_decimal,
    parse_finite_decimal,
    parse_iso_date,
    parse_strict_bool,
    parse_strict_int,
    register_decoder,
    to_canonical_dict,
)
from investment_stack.contracts.errors import (
    ContractValidationError,
    SlotCoherenceError,
)


class CalculationPurpose(StrEnum):
    CURRENT_PRICE = "CURRENT_PRICE"
    FINANCIAL_CALC = "FINANCIAL_CALC"
    HISTORICAL_BAR = "HISTORICAL_BAR"
    INSTITUTIONAL_COMPARE = "INSTITUTIONAL_COMPARE"
    FX_CONVERSION = "FX_CONVERSION"
    VALUATION_MODEL = "VALUATION_MODEL"
    PORTFOLIO_DIAGNOSTIC = "PORTFOLIO_DIAGNOSTIC"


class DimensionKind(StrEnum):
    MONEY = "MONEY"
    SHARES = "SHARES"
    MONEY_PER_SHARE = "MONEY_PER_SHARE"
    RATIO = "RATIO"
    COUNT = "COUNT"
    PERCENT = "PERCENT"


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """Coherent contract specification for an individual calculation input slot."""

    slot_id: str
    purpose: CalculationPurpose | str
    instrument_id: str
    metric: str
    dimension: DimensionKind | str
    currency: str | None = None
    target_period_start: str | None = None
    target_period_end: str | None = None
    duration_days: int | None = None
    reporting_frequency: str | None = None
    accounting_standard: str | None = None
    consolidation: str | None = None
    adjustment_basis: str | None = None
    share_basis: str | None = None
    quote_kind: str | None = None
    coverage_requirement: str | None = None

    def __post_init__(self) -> None:
        if not self.slot_id or not isinstance(self.slot_id, str):
            raise ContractValidationError("slot_id must be a non-empty string")
        if not self.instrument_id or not isinstance(self.instrument_id, str):
            raise ContractValidationError("instrument_id must be a non-empty string")
        if not self.metric or not isinstance(self.metric, str):
            raise ContractValidationError("metric must be a non-empty string")

        if str(self.purpose) not in CalculationPurpose.__members__:
            try:
                object.__setattr__(self, "purpose", CalculationPurpose(self.purpose))
            except ValueError as exc:
                raise ContractValidationError(f"Invalid CalculationPurpose: {self.purpose!r}") from exc
        else:
            object.__setattr__(self, "purpose", CalculationPurpose(self.purpose))

        if str(self.dimension) not in DimensionKind.__members__:
            try:
                object.__setattr__(self, "dimension", DimensionKind(self.dimension))
            except ValueError as exc:
                raise ContractValidationError(f"Invalid DimensionKind: {self.dimension!r}") from exc
        else:
            object.__setattr__(self, "dimension", DimensionKind(self.dimension))

        dim = str(self.dimension)
        # Currency coherence
        if dim in {DimensionKind.MONEY, DimensionKind.MONEY_PER_SHARE}:
            if not self.currency or not self.currency.strip():
                raise SlotCoherenceError(
                    f"Slot {self.slot_id}: dimension {dim} requires currency to be specified"
                )
        elif dim in {DimensionKind.SHARES, DimensionKind.COUNT, DimensionKind.PERCENT}:
            if self.currency is not None:
                raise SlotCoherenceError(
                    f"Slot {self.slot_id}: dimension {dim} must not specify currency (got {self.currency})"
                )

        # Period coherence
        if self.target_period_start is not None:
            parse_iso_date(self.target_period_start)
        if self.target_period_end is not None:
            parse_iso_date(self.target_period_end)
        if self.target_period_start is not None and self.target_period_end is not None:
            if self.target_period_start > self.target_period_end:
                raise SlotCoherenceError(
                    f"Slot {self.slot_id}: target_period_start ({self.target_period_start}) cannot exceed target_period_end ({self.target_period_end})"
                )

        # Duration coherence
        if self.duration_days is not None:
            if isinstance(self.duration_days, bool) or not isinstance(self.duration_days, int):
                raise ContractValidationError(
                    f"Slot {self.slot_id}: duration_days must be int, got {type(self.duration_days).__name__}"
                )
            if self.duration_days <= 0:
                raise SlotCoherenceError(
                    f"Slot {self.slot_id}: duration_days must be positive (got {self.duration_days})"
                )

    def matches_candidate(
        self,
        candidate_currency: str | None = None,
        candidate_dimension: DimensionKind | str | None = None,
        candidate_period_end: str | None = None,
        *,
        candidate_instrument_id: str | None = None,
        candidate_period_start: str | None = None,
        candidate_duration_days: int | None = None,
        candidate_reporting_frequency: str | None = None,
        candidate_accounting_standard: str | None = None,
        candidate_consolidation: str | None = None,
        candidate_adjustment_basis: str | None = None,
        candidate_share_basis: str | None = None,
        candidate_quote_kind: str | None = None,
        candidate_metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Verify if candidate metadata matches this slot's hard constraints.

        Rule: If a slot requires a constraint, candidate having None (unknown) is a MISMATCH.
        """
        meta = candidate_metadata or {}
        curr = candidate_currency if candidate_currency is not None else meta.get("currency")
        dim = candidate_dimension if candidate_dimension is not None else meta.get("dimension")
        p_end = candidate_period_end if candidate_period_end is not None else meta.get("period_end")
        p_start = candidate_period_start if candidate_period_start is not None else meta.get("period_start")
        dur = candidate_duration_days if candidate_duration_days is not None else meta.get("duration_days")
        freq = candidate_reporting_frequency if candidate_reporting_frequency is not None else meta.get("reporting_frequency")
        acc = candidate_accounting_standard if candidate_accounting_standard is not None else meta.get("accounting_standard")
        cons = candidate_consolidation if candidate_consolidation is not None else meta.get("consolidation")
        adj = candidate_adjustment_basis if candidate_adjustment_basis is not None else meta.get("adjustment_basis")
        share = candidate_share_basis if candidate_share_basis is not None else meta.get("share_basis")
        q_kind = candidate_quote_kind if candidate_quote_kind is not None else meta.get("quote_kind")
        inst = candidate_instrument_id if candidate_instrument_id is not None else meta.get("instrument_id")

        if self.instrument_id is not None:
            if inst is None:
                return False, f"Instrument missing: expected {self.instrument_id}, got None"
            if inst != self.instrument_id:
                return False, f"Instrument mismatch: expected {self.instrument_id}, got {inst}"

        if self.currency is not None:
            if curr is None:
                return False, f"Currency missing: expected {self.currency}, got None"
            if curr != self.currency:
                return False, f"Currency mismatch: expected {self.currency}, got {curr}"

        if self.dimension is not None:
            if dim is None:
                return False, f"Dimension missing: expected {self.dimension}, got None"
            if str(dim) != str(self.dimension):
                return False, f"Dimension mismatch: expected {self.dimension}, got {dim}"

        if self.target_period_end is not None:
            if p_end is None:
                return False, f"Period end missing: expected {self.target_period_end}, got None"
            if p_end != self.target_period_end:
                return False, f"Period end mismatch: expected {self.target_period_end}, got {p_end}"

        if self.target_period_start is not None:
            if p_start is None:
                return False, f"Period start missing: expected {self.target_period_start}, got None"
            if p_start != self.target_period_start:
                return False, f"Period start mismatch: expected {self.target_period_start}, got {p_start}"

        if self.duration_days is not None:
            if dur is None:
                return False, f"Duration missing: expected {self.duration_days}, got None"
            if int(dur) != self.duration_days:
                return False, f"Duration mismatch: expected {self.duration_days}, got {dur}"

        if self.reporting_frequency is not None:
            if freq is None:
                return False, f"Reporting frequency missing: expected {self.reporting_frequency}, got None"
            if str(freq) != str(self.reporting_frequency):
                return False, f"Reporting frequency mismatch: expected {self.reporting_frequency}, got {freq}"

        if self.accounting_standard is not None:
            if acc is None:
                return False, f"Accounting standard missing: expected {self.accounting_standard}, got None"
            if str(acc) != str(self.accounting_standard):
                return False, f"Accounting standard mismatch: expected {self.accounting_standard}, got {acc}"

        if self.consolidation is not None:
            if cons is None:
                return False, f"Consolidation missing: expected {self.consolidation}, got None"
            if str(cons) != str(self.consolidation):
                return False, f"Consolidation mismatch: expected {self.consolidation}, got {cons}"

        if self.adjustment_basis is not None:
            if adj is None:
                return False, f"Adjustment basis missing: expected {self.adjustment_basis}, got None"
            if str(adj) != str(self.adjustment_basis):
                return False, f"Adjustment basis mismatch: expected {self.adjustment_basis}, got {adj}"

        if self.share_basis is not None:
            if share is None:
                return False, f"Share basis missing: expected {self.share_basis}, got None"
            if str(share) != str(self.share_basis):
                return False, f"Share basis mismatch: expected {self.share_basis}, got {share}"

        if self.quote_kind is not None:
            if q_kind is None:
                return False, f"Quote kind missing: expected {self.quote_kind}, got None"
            if str(q_kind) != str(self.quote_kind):
                return False, f"Quote kind mismatch: expected {self.quote_kind}, got {q_kind}"

        return True, None


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    CONDITIONAL = "CONDITIONAL"


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Explicit purpose-specific eligibility evaluation for an evidence candidate."""

    eligibility_id: str
    purpose: str
    status: EligibilityStatus
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    policy_version: str
    input_fingerprint: str
    assessed_at: str

    def __post_init__(self) -> None:
        if str(self.status) not in EligibilityStatus.__members__:
            try:
                st = EligibilityStatus(self.status)
                object.__setattr__(self, "status", st)
            except ValueError as exc:
                raise ContractValidationError(f"Invalid EligibilityStatus: {self.status!r}") from exc

    @classmethod
    def eligible(
        cls,
        eligibility_id: str,
        purpose: str,
        policy_version: str,
        input_fingerprint: str,
        *,
        assessed_at: str | None = None,
    ) -> EligibilityDecision:
        return cls(
            eligibility_id=eligibility_id,
            purpose=purpose,
            status=EligibilityStatus.ELIGIBLE,
            reason_codes=(),
            reasons=(),
            policy_version=policy_version,
            input_fingerprint=input_fingerprint,
            assessed_at=assessed_at or datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def ineligible(
        cls,
        eligibility_id: str,
        purpose: str,
        reason_codes: tuple[str, ...],
        reasons: tuple[str, ...],
        policy_version: str,
        input_fingerprint: str,
        *,
        assessed_at: str | None = None,
    ) -> EligibilityDecision:
        return cls(
            eligibility_id=eligibility_id,
            purpose=purpose,
            status=EligibilityStatus.INELIGIBLE,
            reason_codes=tuple(reason_codes),
            reasons=tuple(reasons),
            policy_version=policy_version,
            input_fingerprint=input_fingerprint,
            assessed_at=assessed_at or datetime.now(timezone.utc).isoformat(),
        )


@dataclass(frozen=True, slots=True)
class BoundSlotInput:
    """An immutable, verified input bound to a specific slot for downstream calculations."""

    slot_id: str
    canonical_value: Decimal
    canonical_unit: str
    canonical_currency: str | None
    evidence_id: str
    observation_id: str | None = None
    calculation_id: str | None = None
    eligibility_id: str = ""
    public_available_at: str | None = None
    input_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.slot_id or not isinstance(self.slot_id, str):
            raise ContractValidationError("slot_id must be a non-empty string")
        if not self.evidence_id or not isinstance(self.evidence_id, str):
            raise ContractValidationError("evidence_id must be a non-empty string")
        finite_val = parse_finite_decimal(self.canonical_value)
        if finite_val != self.canonical_value:
            object.__setattr__(self, "canonical_value", finite_val)


@dataclass(frozen=True, slots=True)
class ExcludedCandidate:
    """Candidate that was evaluated but excluded from selection, with reasons preserved."""

    candidate_id: str
    evidence_id: str
    reason_codes: tuple[str, ...]
    reason_detail: str

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.evidence_id:
            raise ContractValidationError("candidate_id and evidence_id must be non-empty strings")


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    """Formal request specification for selecting calculation inputs."""

    request_id: str
    purpose: CalculationPurpose | str
    instrument_id: str
    slots: tuple[SlotSpec, ...]
    policy_version: str = "1.0"
    as_of: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.instrument_id:
            raise ContractValidationError("request_id and instrument_id must be non-empty strings")

    def compute_request_hash(self) -> str:
        """Compute deterministic SHA-256 hash of this selection request."""
        payload = {
            "request_id": self.request_id,
            "purpose": str(self.purpose),
            "instrument_id": self.instrument_id,
            "policy_version": self.policy_version,
            "as_of": self.as_of,
            "slots": [to_canonical_dict(s) for s in self.slots],
        }
        return compute_semantic_hash(payload)


@dataclass(frozen=True, slots=True)
class CoverageDecision:
    """Outcome of evaluating coverage for a SelectionRequest against candidate inputs."""

    request_id: str
    fulfilled_slots: tuple[str, ...]
    missing_slots: tuple[str, ...]
    conflicted_slots: tuple[str, ...]
    is_complete: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id or not isinstance(self.request_id, str):
            raise ContractValidationError("request_id must be a non-empty string")
        if not isinstance(self.is_complete, bool):
            raise ContractValidationError(f"is_complete must be bool, got {type(self.is_complete).__name__}")
        if self.is_complete:
            if self.missing_slots:
                raise ContractValidationError(
                    f"CoverageDecision cannot be complete with missing slots: {self.missing_slots}"
                )
            if self.conflicted_slots:
                raise ContractValidationError(
                    f"CoverageDecision cannot be complete with conflicted slots: {self.conflicted_slots}"
                )
        overlap = set(self.fulfilled_slots) & set(self.missing_slots)
        if overlap:
            raise ContractValidationError(
                f"fulfilled_slots and missing_slots cannot overlap: {sorted(overlap)}"
            )


@dataclass(frozen=True, slots=True)
class SelectedInputSet:
    """Immutable snapshot of selected and bound calculation inputs for a specific purpose."""

    run_id: str
    purpose: str
    selection_version: int
    slots: tuple[BoundSlotInput, ...]
    excluded_candidates: tuple[ExcludedCandidate, ...] = ()
    instrument_id: str | None = None
    request_hash: str | None = None
    created_at: str = ""
    snapshot_hash: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.selection_version, bool) or not isinstance(self.selection_version, int):
            raise ContractValidationError("selection_version must be integer")
        if self.selection_version <= 0:
            raise ContractValidationError(f"selection_version must be positive: {self.selection_version}")

    @property
    def active_key(self) -> str:
        inst = self.instrument_id or "*"
        req = self.request_hash or "*"
        if inst == "*" and req == "*":
            return self.purpose
        if req == "*":
            return f"{self.purpose}:{inst}"
        return f"{self.purpose}:{inst}:{req}"

    @classmethod
    def create(
        cls,
        run_id: str,
        purpose: str,
        selection_version: int,
        slots: Iterable[BoundSlotInput],
        excluded_candidates: Iterable[ExcludedCandidate] = (),
        *,
        instrument_id: str | None = None,
        request_hash: str | None = None,
        created_at: str | None = None,
    ) -> SelectedInputSet:
        slot_list = list(slots)
        seen_slot_ids: set[str] = set()
        for s in slot_list:
            if s.slot_id in seen_slot_ids:
                raise ValueError(f"Duplicate slot_id in selection: {s.slot_id}")
            seen_slot_ids.add(s.slot_id)
        sorted_slots = tuple(sorted(slot_list, key=lambda s: s.slot_id))
        excluded_tuple = tuple(excluded_candidates)
        now = created_at or datetime.now(timezone.utc).isoformat()

        hash_payload = {
            "run_id": run_id,
            "purpose": purpose,
            "selection_version": selection_version,
            "instrument_id": instrument_id,
            "request_hash": request_hash,
            "slots": [to_canonical_dict(s) for s in sorted_slots],
        }
        computed_hash = compute_content_hash(hash_payload)

        return cls(
            run_id=run_id,
            purpose=purpose,
            selection_version=selection_version,
            slots=sorted_slots,
            excluded_candidates=excluded_tuple,
            instrument_id=instrument_id,
            request_hash=request_hash,
            created_at=now,
            snapshot_hash=computed_hash,
        )

    def verify_hash(self) -> bool:
        """Verify that snapshot_hash matches the computed content hash of the slots."""
        hash_payload = {
            "run_id": self.run_id,
            "purpose": self.purpose,
            "selection_version": self.selection_version,
            "instrument_id": self.instrument_id,
            "request_hash": self.request_hash,
            "slots": [to_canonical_dict(s) for s in self.slots],
        }
        return self.snapshot_hash == compute_content_hash(hash_payload)

    def semantic_hash(self) -> str:
        """Compute permutation-invariant semantic hash of bound values, units, currencies, purpose, and provenance."""
        payload = {
            "purpose": self.purpose,
            "instrument_id": self.instrument_id,
            "request_hash": self.request_hash,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "canonical_value": format_decimal(s.canonical_value),
                    "canonical_unit": s.canonical_unit,
                    "canonical_currency": s.canonical_currency,
                    "evidence_id": s.evidence_id,
                    "public_available_at": s.public_available_at,
                    "input_fingerprint": s.input_fingerprint,
                    "eligibility_id": s.eligibility_id,
                }
                for s in sorted(self.slots, key=lambda x: x.slot_id)
            ],
        }
        return compute_semantic_hash(payload)

    def get_slot(self, slot_id: str) -> BoundSlotInput | None:
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None


# Decoders
def _decode_slot_spec(payload: dict[str, Any]) -> SlotSpec:
    allowed_keys = {
        "slot_id",
        "purpose",
        "instrument_id",
        "metric",
        "dimension",
        "currency",
        "target_period_start",
        "target_period_end",
        "duration_days",
        "reporting_frequency",
        "accounting_standard",
        "consolidation",
        "adjustment_basis",
        "share_basis",
        "quote_kind",
        "coverage_requirement",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"SlotSpec payload has extra keys: {sorted(extra)}")

    raw_dur = payload.get("duration_days")
    dur = parse_strict_int(raw_dur) if raw_dur is not None else None
    return SlotSpec(
        slot_id=payload["slot_id"],
        purpose=payload["purpose"],
        instrument_id=payload["instrument_id"],
        metric=payload["metric"],
        dimension=payload["dimension"],
        currency=payload.get("currency"),
        target_period_start=payload.get("target_period_start"),
        target_period_end=payload.get("target_period_end"),
        duration_days=dur,
        reporting_frequency=payload.get("reporting_frequency"),
        accounting_standard=payload.get("accounting_standard"),
        consolidation=payload.get("consolidation"),
        adjustment_basis=payload.get("adjustment_basis"),
        share_basis=payload.get("share_basis"),
        quote_kind=payload.get("quote_kind"),
        coverage_requirement=payload.get("coverage_requirement"),
    )


def _decode_eligibility_decision(payload: dict[str, Any]) -> EligibilityDecision:
    allowed_keys = {
        "eligibility_id",
        "purpose",
        "status",
        "reason_codes",
        "reasons",
        "policy_version",
        "input_fingerprint",
        "assessed_at",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"EligibilityDecision payload has extra keys: {sorted(extra)}")

    return EligibilityDecision(
        eligibility_id=payload["eligibility_id"],
        purpose=payload["purpose"],
        status=payload["status"],
        reason_codes=tuple(payload.get("reason_codes", ())),
        reasons=tuple(payload.get("reasons", ())),
        policy_version=payload["policy_version"],
        input_fingerprint=payload["input_fingerprint"],
        assessed_at=payload["assessed_at"],
    )


def _decode_bound_slot_input(payload: dict[str, Any]) -> BoundSlotInput:
    allowed_keys = {
        "slot_id",
        "canonical_value",
        "canonical_unit",
        "canonical_currency",
        "evidence_id",
        "observation_id",
        "calculation_id",
        "eligibility_id",
        "public_available_at",
        "input_fingerprint",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"BoundSlotInput payload has extra keys: {sorted(extra)}")

    return BoundSlotInput(
        slot_id=payload["slot_id"],
        canonical_value=parse_finite_decimal(payload["canonical_value"]),
        canonical_unit=payload["canonical_unit"],
        canonical_currency=payload.get("canonical_currency"),
        evidence_id=payload["evidence_id"],
        observation_id=payload.get("observation_id"),
        calculation_id=payload.get("calculation_id"),
        eligibility_id=payload.get("eligibility_id", ""),
        public_available_at=payload.get("public_available_at"),
        input_fingerprint=payload.get("input_fingerprint", ""),
    )


def _decode_excluded_candidate(payload: dict[str, Any]) -> ExcludedCandidate:
    allowed_keys = {"candidate_id", "evidence_id", "reason_codes", "reason_detail"}
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"ExcludedCandidate payload has extra keys: {sorted(extra)}")

    return ExcludedCandidate(
        candidate_id=payload["candidate_id"],
        evidence_id=payload["evidence_id"],
        reason_codes=tuple(payload.get("reason_codes", ())),
        reason_detail=payload.get("reason_detail", ""),
    )


def _decode_selected_input_set(payload: dict[str, Any]) -> SelectedInputSet:
    allowed_keys = {
        "run_id",
        "purpose",
        "selection_version",
        "instrument_id",
        "request_hash",
        "slots",
        "excluded_candidates",
        "created_at",
        "snapshot_hash",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"SelectedInputSet payload has extra keys: {sorted(extra)}")

    raw_slots = payload.get("slots", [])
    slots = tuple(_decode_bound_slot_input(s) for s in raw_slots)
    raw_excluded = payload.get("excluded_candidates", [])
    excluded = tuple(_decode_excluded_candidate(e) for e in raw_excluded)

    snap = SelectedInputSet(
        run_id=payload["run_id"],
        purpose=payload["purpose"],
        selection_version=int(payload["selection_version"]),
        slots=slots,
        excluded_candidates=excluded,
        instrument_id=payload.get("instrument_id"),
        request_hash=payload.get("request_hash"),
        created_at=payload.get("created_at", ""),
        snapshot_hash=payload.get("snapshot_hash", ""),
    )
    if not snap.verify_hash():
        raise ContractValidationError(
            f"Tamper detected: snapshot_hash does not match payload content for run {snap.run_id}, purpose {snap.purpose}"
        )
    return snap


def _decode_selection_request(payload: dict[str, Any]) -> SelectionRequest:
    allowed_keys = {
        "request_id",
        "purpose",
        "instrument_id",
        "slots",
        "policy_version",
        "as_of",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"SelectionRequest payload has extra keys: {sorted(extra)}")

    raw_slots = payload.get("slots", [])
    slots = tuple(_decode_slot_spec(s) for s in raw_slots)
    return SelectionRequest(
        request_id=payload["request_id"],
        purpose=payload["purpose"],
        instrument_id=payload["instrument_id"],
        slots=slots,
        policy_version=payload.get("policy_version", "1.0"),
        as_of=payload.get("as_of"),
    )


def _decode_coverage_decision(payload: dict[str, Any]) -> CoverageDecision:
    allowed_keys = {
        "request_id",
        "fulfilled_slots",
        "missing_slots",
        "conflicted_slots",
        "is_complete",
        "reasons",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"CoverageDecision payload has extra keys: {sorted(extra)}")

    raw_comp = payload.get("is_complete", False)
    is_comp = parse_strict_bool(raw_comp)

    return CoverageDecision(
        request_id=payload["request_id"],
        fulfilled_slots=tuple(payload.get("fulfilled_slots", ())),
        missing_slots=tuple(payload.get("missing_slots", ())),
        conflicted_slots=tuple(payload.get("conflicted_slots", ())),
        is_complete=is_comp,
        reasons=tuple(payload.get("reasons", ())),
    )


register_decoder("SlotSpec", _decode_slot_spec)
register_decoder("EligibilityDecision", _decode_eligibility_decision)
register_decoder("BoundSlotInput", _decode_bound_slot_input)
register_decoder("ExcludedCandidate", _decode_excluded_candidate)
register_decoder("SelectedInputSet", _decode_selected_input_set)
register_decoder("SelectionRequest", _decode_selection_request)
register_decoder("CoverageDecision", _decode_coverage_decision)
