"""Typed contracts for fixed request-mode execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from investment_stack.routing import RequestMode, RoutingDecision


class Availability(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModeRequest:
    run_id: str
    mode: RequestMode
    payload: Mapping[str, Any] = field(default_factory=dict)
    routing_decision: RoutingDecision | None = None
    refresh_replay: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id is required")
        object.__setattr__(self, "mode", RequestMode.parse(self.mode))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class StepResult:
    availability: Availability
    output: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    calculation_refs: tuple[str, ...] = ()
    report_refs: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    unsupported_reasons: tuple[str, ...] = ()
    mutation_receipt: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, Availability):
            object.__setattr__(self, "availability", Availability(self.availability))
        object.__setattr__(self, "output", MappingProxyType(dict(self.output)))
        if self.mutation_receipt is not None:
            object.__setattr__(self, "mutation_receipt", MappingProxyType(dict(self.mutation_receipt)))
        if self.availability is Availability.COMPLETE and not (
            self.output or self.evidence_refs or self.calculation_refs or self.report_refs or self.mutation_receipt
        ):
            raise ValueError("a complete step must provide a result or reference")
        if self.availability in {Availability.PARTIAL, Availability.WAITING_CONFIRMATION} and not self.missing_inputs:
            raise ValueError("partial and confirmation-waiting steps must name missing inputs")
        if self.availability is Availability.UNSUPPORTED and not self.unsupported_reasons:
            raise ValueError("an unsupported step must explain why")


@dataclass(frozen=True, slots=True)
class StepState:
    step: str
    availability: Availability
    result: StepResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ModeResult:
    run_id: str
    mode: RequestMode
    availability: Availability
    step_states: tuple[StepState, ...]
    evidence_refs: tuple[str, ...] = ()
    calculation_refs: tuple[str, ...] = ()
    report_refs: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    unsupported_reasons: tuple[str, ...] = ()
    pinned_state: Mapping[str, Any] | None = None
    mutation_receipt: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode.value,
            "availability": self.availability.value,
            "step_states": [
                {"step": state.step, "availability": state.availability.value, "error": state.error}
                for state in self.step_states
            ],
            "evidence_refs": list(self.evidence_refs),
            "calculation_refs": list(self.calculation_refs),
            "report_refs": list(self.report_refs),
            "missing_inputs": list(self.missing_inputs),
            "unsupported_reasons": list(self.unsupported_reasons),
            "pinned_state": dict(self.pinned_state) if self.pinned_state else None,
            "mutation_receipt": dict(self.mutation_receipt) if self.mutation_receipt else None,
        }


@dataclass(frozen=True, slots=True)
class UpdateThenAnalysisResult:
    update: ModeResult
    analysis: ModeResult | None
    availability: Availability
    excluded_unconfirmed_update: bool = False


StepContext = Mapping[str, StepResult]
