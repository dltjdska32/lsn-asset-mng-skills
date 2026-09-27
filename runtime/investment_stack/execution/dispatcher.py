"""Fixed, fail-closed dispatcher for the seven registered request modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from investment_stack.evidence import RunDatabaseManager
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.routing import RequestMode, RequestRouter, RoutingDecision

from .models import Availability, ModeRequest, ModeResult, StepContext, StepResult, StepState, UpdateThenAnalysisResult


StepHandler = Callable[[ModeRequest, StepContext], StepResult]
_REFRESH_REQUIRED = ("previous_report_id", "previous_run_id", "original_mode")


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    handlers: Mapping[PipelineStep, StepHandler] = field(default_factory=dict)
    run_db: RunDatabaseManager | None = None
    run_dbs: Mapping[str, RunDatabaseManager] = field(default_factory=dict)

    def __post_init__(self) -> None:
        registered = dict(self.handlers)
        if any(not isinstance(step, PipelineStep) for step in registered):
            raise ValueError("handlers may be registered only for fixed PipelineStep values")
        object.__setattr__(self, "handlers", MappingProxyType(registered))
        object.__setattr__(self, "run_dbs", MappingProxyType(dict(self.run_dbs)))


def _terminal(
    request: ModeRequest, availability: Availability, *, missing: tuple[str, ...] = (),
    unsupported: tuple[str, ...] = (), step: str = "preflight",
) -> ModeResult:
    state = StepState(step, availability, error="; ".join(unsupported) if unsupported else None)
    return ModeResult(request.run_id, request.mode, availability, (state,),
                      missing_inputs=missing, unsupported_reasons=unsupported)


def _run_db_for(services: RuntimeServices, run_id: str) -> RunDatabaseManager | None:
    return services.run_dbs.get(run_id) or (services.run_db if services.run_db and services.run_db.run_id == run_id else None)


def _preflight(request: ModeRequest, services: RuntimeServices) -> ModeResult | None:
    if request.routing_decision is not None and not request.routing_decision.supported:
        reason = request.routing_decision.unsupported_reason or request.routing_decision.reason
        return _terminal(request, Availability.UNSUPPORTED, unsupported=(reason,))
    if services.run_db is not None and services.run_db.run_id != request.run_id and request.run_id not in services.run_dbs:
        return _terminal(request, Availability.UNSUPPORTED, unsupported=("run_id does not match the supplied run database",))
    if request.refresh_replay and request.mode in {RequestMode.ASSET_UPDATE, RequestMode.REPORT_REFRESH}:
        return _terminal(request, Availability.UNSUPPORTED, unsupported=("refresh replay cannot post transactions or recurse",))
    if request.mode is RequestMode.REPORT_REFRESH:
        missing = tuple(name for name in _REFRESH_REQUIRED if not request.payload.get(name))
        if missing:
            return _terminal(request, Availability.PARTIAL, missing=missing)
        try:
            original = RequestMode.parse(str(request.payload["original_mode"]))
        except ValueError:
            return _terminal(request, Availability.UNSUPPORTED, unsupported=("original report mode is unsupported",))
        if original in {RequestMode.REPORT_REFRESH, RequestMode.ASSET_UPDATE}:
            return _terminal(request, Availability.UNSUPPORTED, unsupported=("refresh cannot recurse or replay an asset update",))
    return None


def _record_state(services: RuntimeServices, request: ModeRequest, state: StepState) -> None:
    run_db = _run_db_for(services, request.run_id)
    if run_db is None:
        return
    result = state.result
    # Run-local task logs contain statuses and references only; request/output payloads
    # may contain personal information and are never copied into run metadata.
    run_db.record_task_state(
        task_name=f"execute:{request.mode.value}:{state.step}",
        task_status=state.availability.value,
        metadata={
            "mode": request.mode.value,
            "step": state.step,
            "evidence_refs": list(result.evidence_refs) if result else [],
            "calculation_refs": list(result.calculation_refs) if result else [],
            "report_refs": list(result.report_refs) if result else [],
            "missing_inputs": list(result.missing_inputs) if result else [],
            "unsupported_reasons": list(result.unsupported_reasons) if result else [],
            "error": state.error,
        },
    )


def execute_mode(request: ModeRequest, services: RuntimeServices) -> ModeResult:
    rejected = _preflight(request, services)
    if rejected is not None:
        return rejected
    states: list[StepState] = []
    context: dict[str, StepResult] = {}
    refs: dict[str, list[str]] = {"evidence": [], "calculation": [], "report": []}
    missing: list[str] = []
    unsupported: list[str] = []
    status = Availability.COMPLETE
    mutation_receipt = None

    for step in FixedPipelinePlanner().plan(request.mode).steps:
        handler = services.handlers.get(step)
        if handler is None:
            reason = f"required runtime handler is not configured for {step.value}"
            state = StepState(step.value, Availability.UNSUPPORTED, error=reason)
            states.append(state)
            _record_state(services, request, state)
            status = Availability.UNSUPPORTED
            unsupported.append(reason)
            break
        try:
            result = handler(request, MappingProxyType(dict(context)))
            if not isinstance(result, StepResult):
                raise TypeError("handler must return StepResult")
            if request.mode is RequestMode.ASSET_UPDATE:
                if result.mutation_receipt is not None and step not in {PipelineStep.DECIDE_POSTING, PipelineStep.ADVANCE_STATE_VERSION}:
                    raise ValueError("mutation receipt returned outside the atomic posting boundary")
            elif result.mutation_receipt is not None:
                raise ValueError("only ASSET_UPDATE may return a mutation receipt")
            if request.mode is RequestMode.PORTFOLIO_SCENARIO and result.mutation_receipt is not None:
                raise ValueError("portfolio scenarios are non-posting")
            if request.mode is RequestMode.REPORT_REFRESH and result.mutation_receipt is not None:
                raise ValueError("report refresh is non-posting")
            if result.mutation_receipt is not None:
                if result.mutation_receipt.get("status") not in {"POSTED", "ALREADY_POSTED"}:
                    raise ValueError("mutation receipt must prove a posted or idempotently replayed transaction")
                if not result.mutation_receipt.get("transaction_ids") or not result.mutation_receipt.get("state_version"):
                    raise ValueError("mutation receipt must include transaction IDs and committed state version")
                mutation_receipt = result.mutation_receipt
        except Exception as exc:
            # Avoid serializing exception text because provider/db errors can include
            # source values or local paths. Preserve only the exception class.
            state = StepState(step.value, Availability.FAILED, error=f"{type(exc).__name__}")
            states.append(state)
            _record_state(services, request, state)
            status = Availability.FAILED
            break

        state = StepState(step.value, result.availability, result=result)
        try:
            _record_state(services, request, state)
        except Exception:
            # A ledger receipt proves an already committed side effect. A run-local
            # logging failure must fail the request without erasing that receipt.
            state = StepState(step.value, Availability.FAILED, result=result, error="RunStatePersistenceError")
            states.append(state)
            status = Availability.FAILED
            break
        states.append(state)
        context[step.value] = result
        refs["evidence"].extend(result.evidence_refs)
        refs["calculation"].extend(result.calculation_refs)
        refs["report"].extend(result.report_refs)
        missing.extend(result.missing_inputs)
        unsupported.extend(result.unsupported_reasons)
        if result.availability in {Availability.UNSUPPORTED, Availability.FAILED, Availability.WAITING_CONFIRMATION}:
            status = result.availability
            break
        if result.availability is Availability.PARTIAL:
            status = Availability.PARTIAL

    if status is Availability.COMPLETE:
        if request.mode is RequestMode.ASSET_UPDATE and mutation_receipt is None:
            status = Availability.UNSUPPORTED
            unsupported.append("ASSET_UPDATE completed without an atomic ledger receipt")
    if status in {Availability.COMPLETE, Availability.PARTIAL} and request.mode is not RequestMode.ASSET_UPDATE:
        rendered = context.get(PipelineStep.RENDER_PARTIAL_AWARE_REPORT.value)
        if rendered is None or not rendered.report_refs:
            status = Availability.UNSUPPORTED
            unsupported.append("mode result lacks a partial-aware report reference")

    return ModeResult(
        request.run_id, request.mode, status, tuple(states),
        tuple(dict.fromkeys(refs["evidence"])), tuple(dict.fromkeys(refs["calculation"])),
        tuple(dict.fromkeys(refs["report"])), tuple(dict.fromkeys(missing)),
        tuple(dict.fromkeys(unsupported)),
        pinned_state=next((result.output.get("pinned_state") for result in context.values() if result.output.get("pinned_state")), None),
        mutation_receipt=mutation_receipt,
    )


def execute_text_request(
    text: str, *, run_id: str, services: RuntimeServices,
    mode_hint: str | RequestMode | None = None,
) -> ModeResult:
    decision = RequestRouter().route(text, mode_hint=mode_hint)
    return execute_mode(
        ModeRequest(run_id, decision.mode, {"raw_request": text}, routing_decision=decision), services
    )


def execute_update_then_analysis(
    update: ModeRequest,
    analysis: ModeRequest,
    services: RuntimeServices,
    *,
    requires_posted_update: bool,
) -> UpdateThenAnalysisResult:
    if update.mode is not RequestMode.ASSET_UPDATE:
        raise ValueError("composite update request must use ASSET_UPDATE")
    if analysis.mode in {RequestMode.ASSET_UPDATE, RequestMode.REPORT_REFRESH}:
        raise ValueError("composite request allows one non-update, non-refresh analysis mode")
    if update.run_id == analysis.run_id:
        raise ValueError("composite subrequests must have separate run IDs")
    update_result = execute_mode(update, services)
    posted = update_result.mutation_receipt is not None
    # Once posted, a failed projection/version check must not be treated as an
    # unposted update and followed by analysis against an ambiguous state.
    if posted and update_result.availability is not Availability.COMPLETE:
        return UpdateThenAnalysisResult(
            update_result, None, update_result.availability,
            excluded_unconfirmed_update=False,
        )
    if requires_posted_update and not posted:
        waiting = update_result.availability in {Availability.PARTIAL, Availability.WAITING_CONFIRMATION}
        return UpdateThenAnalysisResult(
            update_result, None,
            Availability.WAITING_CONFIRMATION if waiting else update_result.availability,
        )
    payload = dict(analysis.payload)
    if posted:
        payload["confirmed_update_receipt"] = dict(update_result.mutation_receipt or {})
        payload["pinned_state_version"] = update_result.mutation_receipt["state_version"]
    else:
        payload["pending_update_excluded"] = True
    analysis_result = execute_mode(ModeRequest(analysis.run_id, analysis.mode, payload), services)
    final_status = analysis_result.availability
    return UpdateThenAnalysisResult(update_result, analysis_result, final_status, excluded_unconfirmed_update=not posted)
