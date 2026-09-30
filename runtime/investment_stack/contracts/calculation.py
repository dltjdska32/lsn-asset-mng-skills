"""Calculation records, assumption lineage, gate decisions, and status separation contracts."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from investment_stack.contracts.codec import (
    compute_content_hash,
    format_decimal,
    parse_finite_decimal,
    parse_strict_bool,
    register_decoder,
    to_canonical_dict,
)
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    UnapprovedPolicyError,
)
from investment_stack.contracts.slots import BoundSlotInput


class DataAvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class ExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"


class CalculationStatus(StrEnum):
    CALCULATED = "CALCULATED"
    CONDITIONAL = "CONDITIONAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class InvestmentDecision(StrEnum):
    BUY = "BUY"
    ADD_BUY = "ADD_BUY"
    HOLD = "HOLD"
    WAIT = "WAIT"
    REDUCE = "REDUCE"
    INCONCLUSIVE = "INCONCLUSIVE"


class AssumptionKind(StrEnum):
    OFFICIAL_GUIDANCE = "OFFICIAL_GUIDANCE"
    DERIVED = "DERIVED"
    ANALYST_SCENARIO = "ANALYST_SCENARIO"
    USER = "USER"


class GateState(StrEnum):
    ENABLED = "ENABLED"
    CONDITIONAL = "CONDITIONAL"
    DISABLED = "DISABLED"


class OutputKind(StrEnum):
    PRICE = "PRICE"
    TARGET_PRICE = "TARGET_PRICE"
    SCORE = "SCORE"
    WEIGHT = "WEIGHT"
    VALUATION = "VALUATION"
    SCENARIO_VALUE = "SCENARIO_VALUE"
    ARITHMETIC_RESULT = "ARITHMETIC_RESULT"
    DIAGNOSTIC = "DIAGNOSTIC"


class FormulaRequirement(StrEnum):
    ARITHMETIC = "ARITHMETIC"
    ANALYST_SCENARIO = "ANALYST_SCENARIO"
    POLICY_APPROVAL = "POLICY_APPROVAL"
    POLICY_VERIFICATION = "POLICY_VERIFICATION"


@dataclass(frozen=True, slots=True)
class TypedOutput:
    """An explicit, typed numerical output of a calculation with unit and currency."""

    kind: OutputKind | str
    value: Decimal
    unit: str
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.unit:
            raise ContractValidationError("kind and unit must be non-empty strings")
        finite_val = parse_finite_decimal(self.value)
        if finite_val != self.value:
            object.__setattr__(self, "value", finite_val)


def _decode_typed_output(payload: dict[str, Any]) -> TypedOutput:
    allowed_keys = {"kind", "value", "unit", "currency"}
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"TypedOutput payload has extra keys: {sorted(extra)}")
    if "kind" not in payload or "value" not in payload or "unit" not in payload:
        raise ContractValidationError("TypedOutput missing required fields")
    return TypedOutput(
        kind=payload["kind"],
        value=parse_finite_decimal(payload["value"]),
        unit=payload["unit"],
        currency=payload.get("currency"),
    )


register_decoder("TypedOutput", _decode_typed_output)


def _freeze_payload(obj: Any) -> Any:
    if isinstance(obj, (dict, Mapping)):
        return MappingProxyType({str(k): _freeze_payload(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze_payload(v) for v in obj)
    return obj


def _has_numeric_content(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float, Decimal)):
        return True
    if isinstance(val, str):
        s = val.strip()
        if s:
            try:
                d = Decimal(s)
                if d.is_finite():
                    return True
            except InvalidOperation:
                pass
    elif isinstance(val, (dict, Mapping)):
        return any(_has_numeric_content(v) for v in val.values())
    elif isinstance(val, (list, tuple, set, frozenset)):
        return any(_has_numeric_content(v) for v in val)
    return False


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Explicit governance gate evaluation for an analytical or trading policy."""

    gate_id: str
    purpose: str
    policy_id: str
    policy_version: str
    policy_hash: str
    state: GateState | str
    approval_ref: str | None = None
    validation_ref: str | None = None
    prerequisites: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assessed_at: str = ""

    def __post_init__(self) -> None:
        if not self.gate_id or not self.policy_id or not self.policy_hash:
            raise ContractValidationError("gate_id, policy_id, policy_hash must be non-empty strings")
        if not self.purpose or not isinstance(self.purpose, str):
            raise ContractValidationError("purpose must be a non-empty string")
        if self.purpose.strip() != self.purpose:
            raise ContractValidationError(f"Invalid gate purpose with whitespace: {self.purpose!r}")
        try:
            st = GateState(self.state)
        except ValueError as exc:
            raise ContractValidationError(f"Invalid GateState: {self.state!r}") from exc
        if st != self.state:
            object.__setattr__(self, "state", st)

        norm_purpose = self.purpose.strip().upper()

        # Unapproved policy cannot be marked ENABLED without approval_ref
        if self.state == GateState.ENABLED and not self.approval_ref:
            raise UnapprovedPolicyError(
                f"Gate {self.gate_id}: ENABLED state requires explicit approval_ref; unapproved policy cannot be enabled"
            )

        # 13F aggregations require both approval_ref and validation_ref
        if norm_purpose in {"13F_AGGREGATE", "13F_WEIGHT"}:
            if not self.approval_ref or not self.validation_ref:
                if self.state != GateState.DISABLED:
                    object.__setattr__(self, "state", GateState.DISABLED)
        elif norm_purpose in {"TRADING", "ORDER", "INVESTMENT_DECISION"}:
            if not self.approval_ref:
                if self.state != GateState.DISABLED:
                    object.__setattr__(self, "state", GateState.DISABLED)


@dataclass(frozen=True, slots=True)
class CalculationAssumption:
    """An explicit, documented parameter or model assumption with approval tracking."""

    assumption_id: str
    name: str
    value: str
    unit: str | None = None
    kind: AssumptionKind | str = AssumptionKind.ANALYST_SCENARIO
    source_evidence_id: str | None = None
    applicable_period: str | None = None
    rationale: str = ""
    is_approved: bool = False

    def __post_init__(self) -> None:
        if not self.assumption_id or not self.name or not self.value:
            raise ContractValidationError("assumption_id, name, value must be non-empty strings")
        if str(self.value).strip().lower() in {"nan", "infinity", "-infinity", "+infinity", "inf", "-inf"}:
            raise ContractValidationError(f"Non-finite value {self.value!r} not allowed in CalculationAssumption")
        if not isinstance(self.is_approved, bool):
            raise ContractValidationError(f"is_approved must be bool, got {type(self.is_approved).__name__}")


@dataclass(frozen=True, slots=True)
class CalculationRecord:
    """An immutable, auditable calculation record with bound inputs and lineage hash."""

    calculation_id: str
    run_id: str
    calculation_name: str
    formula_id: str
    formula_version: str
    status: CalculationStatus | str
    bound_inputs: tuple[BoundSlotInput, ...]
    selection_snapshot_hash: str
    assumptions: tuple[CalculationAssumption, ...] = ()
    result_numeric: Decimal | None = None
    result_unit: str | None = None
    result_currency: str | None = None
    result_payload: Mapping[str, Any] = field(default_factory=dict)
    typed_outputs: tuple[TypedOutput, ...] = ()
    gate_refs: tuple[str, ...] = ()
    preceding_calculation_ids: tuple[str, ...] = ()
    purpose: str | None = None
    requirement: FormulaRequirement | str | None = None
    failure_reasons: tuple[str, ...] = ()
    lineage_hash: str = ""
    calculated_at: str = ""

    def __post_init__(self) -> None:
        if not self.calculation_id or not self.run_id or not self.calculation_name:
            raise ContractValidationError("calculation_id, run_id, calculation_name must be non-empty strings")

        try:
            st = CalculationStatus(self.status)
        except ValueError as exc:
            raise ContractValidationError(f"Invalid CalculationStatus: {self.status!r}") from exc
        if st != self.status:
            object.__setattr__(self, "status", st)

        # Enforce deep immutable copy for result_payload
        frozen_payload = _freeze_payload(self.result_payload)
        object.__setattr__(self, "result_payload", frozen_payload)

        # UNAVAILABLE or FAILED status must have result_numeric=None and no consumable output numbers
        if self.status in {CalculationStatus.UNAVAILABLE, CalculationStatus.FAILED}:
            if self.result_numeric is not None:
                raise ContractValidationError(
                    f"Calculation '{self.calculation_name}' status is {self.status} but result_numeric is {self.result_numeric}; "
                    "numeric result must be None when calculation is unavailable or failed"
                )
            if self.typed_outputs:
                raise ContractValidationError(
                    f"Calculation '{self.calculation_name}' status is {self.status} but typed_outputs is non-empty; "
                    "typed_outputs must be empty when calculation is unavailable or failed"
                )
            if _has_numeric_content(self.result_payload):
                raise ContractValidationError(
                    f"Calculation '{self.calculation_name}' status is {self.status} but result_payload contains numeric values or numbers"
                )

        if self.result_numeric is not None:
            finite_res = parse_finite_decimal(self.result_numeric)
            if finite_res != self.result_numeric:
                object.__setattr__(self, "result_numeric", finite_res)

        # Enforce requirement: unapproved assumptions cannot produce unconditionally CALCULATED status!
        has_unapproved = any(not a.is_approved for a in self.assumptions)
        if has_unapproved and self.status == CalculationStatus.CALCULATED:
            raise ContractValidationError(
                f"Calculation '{self.calculation_name}' has unapproved assumptions and cannot have status CALCULATED; "
                f"must be CONDITIONAL or UNAVAILABLE"
            )

    def _lineage_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "calculation_name": self.calculation_name,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "status": str(self.status),
            "selection_snapshot_hash": self.selection_snapshot_hash,
            "bound_inputs": [to_canonical_dict(s) for s in sorted(self.bound_inputs, key=lambda s: s.slot_id)],
            "assumptions": [to_canonical_dict(a) for a in sorted(self.assumptions, key=lambda a: a.assumption_id)],
            "gate_refs": sorted(self.gate_refs),
            "preceding_calculation_ids": sorted(self.preceding_calculation_ids),
            "purpose": self.purpose,
            "requirement": str(self.requirement) if self.requirement is not None else None,
            "typed_outputs": [to_canonical_dict(o) for o in self.typed_outputs],
            "result_numeric": format_decimal(self.result_numeric) if self.result_numeric is not None else None,
            "result_unit": self.result_unit,
            "result_currency": self.result_currency,
            "result_payload": to_canonical_dict(self.result_payload),
        }

    def compute_lineage_hash(self) -> str:
        return compute_content_hash(self._lineage_payload())

    def verify_lineage(self) -> bool:
        """Verify that the lineage_hash matches the computed content hash of inputs, formula, and outputs."""
        return self.lineage_hash == self.compute_lineage_hash()

    @classmethod
    def create(
        cls,
        calculation_id: str,
        run_id: str,
        calculation_name: str,
        formula_id: str,
        formula_version: str,
        status: CalculationStatus | str,
        bound_inputs: Iterable[BoundSlotInput],
        selection_snapshot_hash: str,
        *,
        assumptions: Iterable[CalculationAssumption] = (),
        result_numeric: Decimal | None = None,
        result_unit: str | None = None,
        result_currency: str | None = None,
        result_payload: Mapping[str, Any] | dict[str, Any] | None = None,
        typed_outputs: Iterable[TypedOutput] = (),
        gate_refs: Iterable[str] = (),
        preceding_calculation_ids: Iterable[str] = (),
        purpose: str | None = None,
        requirement: FormulaRequirement | str | None = None,
        failure_reasons: Iterable[str] = (),
        calculated_at: str | None = None,
    ) -> CalculationRecord:
        sorted_inputs = tuple(sorted(bound_inputs, key=lambda s: s.slot_id))
        sorted_assumptions = tuple(sorted(assumptions, key=lambda a: a.assumption_id))
        now = calculated_at or datetime.now(timezone.utc).isoformat()
        res_num = parse_finite_decimal(result_numeric) if result_numeric is not None else None
        clean_payload = copy.deepcopy(dict(result_payload or {}))
        outputs_tuple = tuple(typed_outputs)
        gate_tuple = tuple(gate_refs)
        preceding_tuple = tuple(preceding_calculation_ids)

        proto = cls(
            calculation_id=calculation_id,
            run_id=run_id,
            calculation_name=calculation_name,
            formula_id=formula_id,
            formula_version=formula_version,
            status=status,
            bound_inputs=sorted_inputs,
            selection_snapshot_hash=selection_snapshot_hash,
            assumptions=sorted_assumptions,
            result_numeric=res_num,
            result_unit=result_unit,
            result_currency=result_currency,
            result_payload=clean_payload,
            typed_outputs=outputs_tuple,
            gate_refs=gate_tuple,
            preceding_calculation_ids=preceding_tuple,
            purpose=purpose,
            requirement=requirement,
            failure_reasons=tuple(failure_reasons),
            lineage_hash="",
            calculated_at=now,
        )
        object.__setattr__(proto, "lineage_hash", proto.compute_lineage_hash())
        return proto


# Decoders
def _decode_calculation_assumption(payload: dict[str, Any]) -> CalculationAssumption:
    allowed_keys = {
        "assumption_id",
        "name",
        "value",
        "unit",
        "kind",
        "source_evidence_id",
        "applicable_period",
        "rationale",
        "is_approved",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"CalculationAssumption payload has extra keys: {sorted(extra)}")

    is_appr = parse_strict_bool(payload.get("is_approved", False))
    raw_kind = payload.get("kind", "ANALYST_SCENARIO")
    try:
        kind = AssumptionKind(raw_kind)
    except ValueError as exc:
        raise ContractValidationError(f"Invalid AssumptionKind: {raw_kind!r}") from exc

    return CalculationAssumption(
        assumption_id=payload["assumption_id"],
        name=payload["name"],
        value=str(payload["value"]),
        unit=payload.get("unit"),
        kind=kind,
        source_evidence_id=payload.get("source_evidence_id"),
        applicable_period=payload.get("applicable_period"),
        rationale=payload.get("rationale", ""),
        is_approved=is_appr,
    )


def _decode_gate_decision(payload: dict[str, Any]) -> GateDecision:
    allowed_keys = {
        "gate_id",
        "purpose",
        "policy_id",
        "policy_version",
        "policy_hash",
        "state",
        "approval_ref",
        "validation_ref",
        "prerequisites",
        "reasons",
        "assessed_at",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"GateDecision payload has extra keys: {sorted(extra)}")

    raw_state = payload["state"]
    try:
        state = GateState(raw_state)
    except ValueError as exc:
        raise ContractValidationError(f"Invalid GateState: {raw_state!r}") from exc

    return GateDecision(
        gate_id=payload["gate_id"],
        purpose=payload["purpose"],
        policy_id=payload["policy_id"],
        policy_version=payload["policy_version"],
        policy_hash=payload["policy_hash"],
        state=state,
        approval_ref=payload.get("approval_ref"),
        validation_ref=payload.get("validation_ref"),
        prerequisites=tuple(payload.get("prerequisites", ())),
        reasons=tuple(payload.get("reasons", ())),
        assessed_at=payload.get("assessed_at", ""),
    )


def _decode_calculation_record(payload: dict[str, Any]) -> CalculationRecord:
    allowed_keys = {
        "calculation_id",
        "run_id",
        "calculation_name",
        "formula_id",
        "formula_version",
        "status",
        "bound_inputs",
        "selection_snapshot_hash",
        "assumptions",
        "result_numeric",
        "result_unit",
        "result_currency",
        "result_payload",
        "typed_outputs",
        "gate_refs",
        "preceding_calculation_ids",
        "purpose",
        "requirement",
        "failure_reasons",
        "lineage_hash",
        "calculated_at",
    }
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise ContractValidationError(f"CalculationRecord payload has extra keys: {sorted(extra)}")

    from investment_stack.contracts.slots import _decode_bound_slot_input

    raw_inputs = payload.get("bound_inputs", [])
    inputs = tuple(_decode_bound_slot_input(s) for s in raw_inputs)
    raw_assumptions = payload.get("assumptions", [])
    assumptions = tuple(_decode_calculation_assumption(a) for a in raw_assumptions)
    raw_outputs = payload.get("typed_outputs", [])
    typed_outputs = tuple(_decode_typed_output(o) for o in raw_outputs)

    num_val = payload.get("result_numeric")
    res_num = parse_finite_decimal(num_val) if num_val is not None else None

    instance = CalculationRecord(
        calculation_id=payload["calculation_id"],
        run_id=payload["run_id"],
        calculation_name=payload["calculation_name"],
        formula_id=payload["formula_id"],
        formula_version=payload["formula_version"],
        status=CalculationStatus(payload["status"]),
        bound_inputs=inputs,
        selection_snapshot_hash=payload.get("selection_snapshot_hash", ""),
        assumptions=assumptions,
        result_numeric=res_num,
        result_unit=payload.get("result_unit"),
        result_currency=payload.get("result_currency"),
        result_payload=copy.deepcopy(payload.get("result_payload") or {}),
        typed_outputs=typed_outputs,
        gate_refs=tuple(payload.get("gate_refs", ())),
        preceding_calculation_ids=tuple(payload.get("preceding_calculation_ids", ())),
        purpose=payload.get("purpose"),
        requirement=payload.get("requirement"),
        failure_reasons=tuple(payload.get("failure_reasons", ())),
        lineage_hash=payload.get("lineage_hash", ""),
        calculated_at=payload.get("calculated_at", ""),
    )
    if not instance.verify_lineage():
        raise ContractValidationError(
            f"Tamper detected: calculation lineage hash does not match content for calculation {instance.calculation_id}"
        )
    return instance


@dataclass(frozen=True, slots=True)
class ValidatedCalculation:
    """Consumable calculation result protected by single governance validation boundary."""

    record: CalculationRecord
    requirement: FormulaRequirement
    is_consumable: bool
    outputs: tuple[TypedOutput, ...]
    diagnostics: Mapping[str, Any]


def get_formula_requirement(formula_id: str, explicit: FormulaRequirement | str | None = None) -> FormulaRequirement:
    """Resolve closed formula requirement, ensuring callers cannot bypass policy rules."""
    fid = formula_id.lower()
    if fid.startswith("13f") or "institutional" in fid:
        return FormulaRequirement.POLICY_VERIFICATION
    if fid.startswith("scenario") or "analyst" in fid:
        return FormulaRequirement.ANALYST_SCENARIO
    if fid in {"price_identity", "arithmetic", "sum", "diff", "count", "fixture-formula"}:
        return FormulaRequirement.ARITHMETIC
    if explicit is not None:
        try:
            return FormulaRequirement(explicit)
        except ValueError as exc:
            raise ContractValidationError(f"Invalid FormulaRequirement: {explicit!r}") from exc
    return FormulaRequirement.POLICY_APPROVAL


def validate_calculation_for_use(
    record: CalculationRecord,
    context: Any = None,
    registered_gates: Iterable[GateDecision] = (),
) -> ValidatedCalculation:
    """Single governance boundary validating CalculationRecord before downstream consumption."""
    if not record.verify_lineage():
        raise ContractValidationError(
            f"Calculation '{record.calculation_id}' failed lineage verification (tampered content)"
        )
    req = get_formula_requirement(record.formula_id, record.requirement)
    purpose = str(record.purpose or "").strip().upper()
    # Formula names and caller supplied requirements cannot downgrade policy
    # sensitive purposes.
    if purpose in {"13F_WEIGHT", "13F_AGGREGATE"}:
        req = FormulaRequirement.POLICY_VERIFICATION

    if record.status in {CalculationStatus.UNAVAILABLE, CalculationStatus.FAILED}:
        return ValidatedCalculation(
            record=record,
            requirement=req,
            is_consumable=False,
            outputs=(),
            diagnostics=record.result_payload,
        )

    gates_by_id = {g.gate_id: g for g in registered_gates}
    if req == FormulaRequirement.POLICY_VERIFICATION:
        if not record.gate_refs:
            raise UnapprovedPolicyError(
                f"Calculation '{record.calculation_id}' requires policy verification gate binding"
            )
        for gid in record.gate_refs:
            if gid not in gates_by_id:
                raise UnapprovedPolicyError(f"Gate '{gid}' referenced by calculation not registered")
            g = gates_by_id[gid]
            if g.purpose.strip().upper() != purpose:
                raise UnapprovedPolicyError(
                    f"Gate '{gid}' purpose '{g.purpose}' does not match calculation purpose '{purpose}'"
                )
            if g.state == GateState.DISABLED:
                raise UnapprovedPolicyError(f"Gate '{gid}' is in DISABLED state")
            if not g.approval_ref or not g.validation_ref:
                raise UnapprovedPolicyError(f"Gate '{gid}' lacks required approval or validation reference")

    elif req == FormulaRequirement.POLICY_APPROVAL:
        if not record.gate_refs:
            raise UnapprovedPolicyError(
                f"Calculation '{record.calculation_id}' requires policy approval gate binding"
            )
        for gid in record.gate_refs:
            if gid not in gates_by_id:
                raise UnapprovedPolicyError(f"Gate '{gid}' referenced by calculation not registered")
            g = gates_by_id[gid]
            if g.purpose.strip().upper() != purpose:
                raise UnapprovedPolicyError(
                    f"Gate '{gid}' purpose '{g.purpose}' does not match calculation purpose '{purpose}'"
                )
            if g.state == GateState.DISABLED:
                raise UnapprovedPolicyError(f"Gate '{gid}' is in DISABLED state")
            if not g.approval_ref:
                raise UnapprovedPolicyError(f"Gate '{gid}' lacks required approval reference")

    elif req == FormulaRequirement.ANALYST_SCENARIO:
        has_unapproved = any(not a.is_approved for a in record.assumptions)
        if has_unapproved and record.status != CalculationStatus.CONDITIONAL:
            raise ContractValidationError(
                f"Analyst scenario calculation '{record.calculation_id}' with unapproved assumptions must have CONDITIONAL status"
            )

    return ValidatedCalculation(
        record=record,
        requirement=req,
        is_consumable=True,
        outputs=record.typed_outputs,
        diagnostics=record.result_payload,
    )


register_decoder("CalculationAssumption", _decode_calculation_assumption)
register_decoder("GateDecision", _decode_gate_decision)
register_decoder("CalculationRecord", _decode_calculation_record)
