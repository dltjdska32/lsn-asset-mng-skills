"""Explicit, fixed composition for the seven request-mode runtime services.

The host owns creation and pinning of both databases and all research providers.
This module never opens either database or selects a mode dynamically.
"""

from __future__ import annotations

from types import MappingProxyType

from investment_stack.evidence import RunDatabaseManager
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.routing import RequestMode

from .asset_update import asset_update_services
from .dispatcher import RuntimeServices
from .models import Availability, StepResult


_UPDATE_STEPS = frozenset({
    PipelineStep.EXTRACT_TRANSACTION_INTENT,
    PipelineStep.VALIDATE_EVENT_TIME,
    PipelineStep.ASSESS_AMBIGUITY_AND_IMPACT,
    PipelineStep.DECIDE_POSTING,
    PipelineStep.PROJECT_PERSONAL_STATE,
    PipelineStep.ADVANCE_STATE_VERSION,
})


def compose_seven_mode_services(
    *,
    run_db: RunDatabaseManager,
    ledger: PersonalLedgerService,
    equity_services: RuntimeServices,
    portfolio_thesis_services: RuntimeServices,
) -> RuntimeServices:
    """Compose explicit equity, portfolio/thesis, and ledger service bundles.

    ``portfolio_thesis_services`` must already have been built with
    ``base_services=equity_services``. All three bundles must be bound to this
    exact run database. The personal ledger is supplied explicitly; it is never
    opened or inferred here. Only ASSET_UPDATE plans can reach ledger handlers.
    """
    if run_db.status.value != "VALID":
        raise ValueError("seven-mode composition requires an initialized valid run database")
    if ledger is None:
        raise ValueError("personal ledger must be explicitly injected")
    if equity_services.run_db is not run_db or portfolio_thesis_services.run_db is not run_db:
        raise ValueError("all mode bundles must use the same run database instance")

    planner = FixedPipelinePlanner()
    required_analysis_steps = {
        step for mode in RequestMode if mode is not RequestMode.ASSET_UPDATE
        for step in planner.plan(mode).steps
    }
    missing = required_analysis_steps - portfolio_thesis_services.handlers.keys()
    if missing:
        raise ValueError("portfolio/thesis bundle is incomplete for the fixed mode plans")
    missing_equity = {
        step for mode in (RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.ASSET_COMPARISON)
        for step in planner.plan(mode).steps
    } - equity_services.handlers.keys()
    if missing_equity:
        raise ValueError("equity bundle is incomplete for the fixed equity mode plans")

    update_services = asset_update_services(ledger, run_db=run_db)
    if _UPDATE_STEPS & portfolio_thesis_services.handlers.keys():
        raise ValueError("portfolio/thesis bundle must not expose personal-ledger writer steps")

    handlers = {}
    for step, handler in portfolio_thesis_services.handlers.items():

        def run_bound(request, context, *, selected=handler):
            if request.run_id != run_db.run_id:
                return StepResult(Availability.UNSUPPORTED,
                                  unsupported_reasons=("request run_id does not match the composed run database",))
            return selected(request, context)

        handlers[step] = run_bound
    for step, handler in update_services.handlers.items():
        if step not in _UPDATE_STEPS:
            raise ValueError("asset-update bundle contains a handler outside its fixed plan")

        def guarded(request, context, *, selected=handler, step_name=step.value):
            if request.mode is not RequestMode.ASSET_UPDATE:
                return StepResult(Availability.UNSUPPORTED,
                                  unsupported_reasons=(f"{step_name} is restricted to ASSET_UPDATE",))
            if request.run_id != run_db.run_id:
                return StepResult(Availability.UNSUPPORTED,
                                  unsupported_reasons=("request run_id does not match the composed run database",))
            return selected(request, context)

        handlers[step] = guarded

    registry = dict(portfolio_thesis_services.run_dbs)
    for run_id, manager in equity_services.run_dbs.items():
        if run_id in registry and registry[run_id] is not manager:
            raise ValueError("service bundles contain conflicting run database registrations")
        registry[run_id] = manager
    registry[run_db.run_id] = run_db
    return RuntimeServices(handlers=MappingProxyType(handlers), run_db=run_db, run_dbs=registry)
