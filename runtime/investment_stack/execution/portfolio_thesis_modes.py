"""Fixed RuntimeServices bundle for portfolio, scenario, thesis, and refresh modes.

The bundle adapts existing typed reporting services to the existing dispatcher. It
does not open personal.db, fetch data, invent policy, post transactions, or choose a
dynamic pipeline. Hosts provide already pinned and selected typed inputs through
callbacks or the request payload.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext
import hashlib
import json
import re
from typing import Callable, Mapping
from uuid import uuid4

from investment_stack.evidence import RunDatabaseManager
from investment_stack.pipelines import PipelineStep
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput
from investment_stack.reporting.portfolio_modes import (
    FxEvidence,
    PortfolioAnalysisRequest,
    PortfolioScenario,
    PortfolioAnalysisResult,
    ScenarioStatus,
    analyze_portfolio,
    simulate_portfolio_scenario,
)
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.reporting.thesis_refresh import (
    FixedModeReplay,
    PinnedRefreshContext,
    RefreshStatus,
    ReportRefreshRequest,
    ReportRefreshServices,
    ReportSnapshot,
    ThesisEvidence,
    ThesisReviewRequest,
    refresh_report,
    review_thesis,
)
from investment_stack.review.models import ReviewContext
from investment_stack.routing import RequestMode

from .dispatcher import RuntimeServices, execute_mode
from .models import Availability, ModeRequest, StepContext, StepResult


@dataclass(frozen=True, slots=True)
class SelectedAssetResearchResult:
    """Typed Phase 4/5 output supplied by the host's selected-asset pipeline."""

    sections: tuple[ReportSectionInput, ...]
    evidence_refs: tuple[str, ...]
    calculation_refs: tuple[str, ...]
    missing_inputs: tuple[str, ...]

    def __init__(
        self, sections: tuple[ReportSectionInput, ...], *,
        evidence_refs: tuple[str, ...] = (), calculation_refs: tuple[str, ...] = (),
        missing_inputs: tuple[str, ...] = (),
    ) -> None:
        if any(not isinstance(section, ReportSectionInput) for section in sections):
            raise TypeError("asset research sections must be ReportSectionInput values")
        object.__setattr__(self, "sections", tuple(sections))
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(evidence_refs)))
        object.__setattr__(self, "calculation_refs", tuple(dict.fromkeys(calculation_refs)))
        object.__setattr__(self, "missing_inputs", tuple(dict.fromkeys(missing_inputs)))


PortfolioLoader = Callable[[ModeRequest], PortfolioAnalysisRequest | None]
MaterialitySelector = Callable[[PortfolioAnalysisRequest, ModeRequest], tuple[str, ...] | None]
SelectedAssetResearch = Callable[[tuple[str, ...], ModeRequest], SelectedAssetResearchResult]
ScenarioGateVerifier = Callable[[object], bool]
ThesisEvidenceCollector = Callable[[ThesisReviewRequest, ModeRequest], tuple[ThesisEvidence, ...]]
RefreshPayloadResolver = Callable[[FixedModeReplay], Mapping[str, object]]


def portfolio_thesis_services(
    *,
    run_db: RunDatabaseManager,
    run_dbs: Mapping[str, RunDatabaseManager] | None = None,
    base_services: RuntimeServices | None = None,
    portfolio_loader: PortfolioLoader | None = None,
    materiality_selector: MaterialitySelector | None = None,
    selected_asset_research: SelectedAssetResearch | None = None,
    scenario_gate_verifier: ScenarioGateVerifier | None = None,
    thesis_evidence_collector: ThesisEvidenceCollector | None = None,
    report_refresh_services: ReportRefreshServices | None = None,
    refresh_payload_resolver: RefreshPayloadResolver | None = None,
) -> RuntimeServices:
    """Build fixed handlers for PERSONAL_PORTFOLIO_ANALYSIS, PORTFOLIO_SCENARIO,
    THESIS_REVIEW, and REPORT_REFRESH.

    A host can inject a state loader, approved materiality selector, existing
    Phase 4/5 selected-asset runtime, scenario registry verifier, typed evidence
    collector, the other analysis mode bundle for fixed-step delegation, and the
    refresh service's run.db resolver/fixed-mode runners. The
    run database passed here must already have its immutable run clock and state
    pin. ``run_dbs`` is only a run-local logger registry.
    """
    if run_db.status.value != "VALID":
        raise ValueError("portfolio/thesis runtime requires an initialized valid run database")
    if base_services is not None and base_services.run_db is not run_db:
        raise ValueError("base analysis handlers must use the same run database")
    phase6 = Phase6ReportReviewRuntime(run_db)
    service_holder: dict[str, RuntimeServices] = {}
    registry = dict(run_dbs or {})
    registry[run_db.run_id] = run_db

    def read_report_snapshot(source_run_id: str, report_ref: str) -> ReportSnapshot:
        manager = registry.get(source_run_id)
        if manager is None:
            raise ValueError("prior report run is not registered")
        snapshot = manager.fetch_phase6_context()
        match = None
        for row in snapshot["task_states"]:
            try:
                item = json.loads(row.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if item.get("report_ref") == report_ref:
                match = item
        if match is None or not isinstance(match.get("section_refs"), list):
            raise ValueError("prior report reference or section manifest is missing from run.db")
        fingerprints = {
            str(item["section_name"]): str(item["content_reference"])
            for item in match["section_refs"]
            if isinstance(item, dict) and item.get("section_name") and item.get("content_reference")
        }
        return ReportSnapshot(
            source_run_id, report_ref, RequestMode.parse(str(match.get("mode"))),
            str(match.get("target") or ""), tuple(match.get("assumptions") or ()),
            str(match.get("analysis_as_of") or ""), fingerprints,
            ReportAvailability(str(match.get("availability") or ReportAvailability.UNAVAILABLE.value)),
            tuple(str(item) for item in match.get("missing_inputs", ()) if str(item).strip()),
        )

    def start_existing_pinned_run(_prior: ReportSnapshot, _request: ReportRefreshRequest,
                                  _mode: RequestMode) -> PinnedRefreshContext:
        snapshot = run_db.fetch_phase6_context()
        metadata = snapshot["run_metadata"]
        pin = snapshot["pinned_personal_state"]
        if not metadata.get("analysis_as_of") or not metadata.get("analysis_timezone") or pin is None:
            raise ValueError("request run lacks its new clock or pinned personal state")
        return PinnedRefreshContext(
            run_db.run_id, str(metadata["analysis_as_of"]), str(metadata["analysis_timezone"]),
            int(pin["state_version"]), str(pin["portfolio_snapshot_id"]),
        )

    def rerun_fixed_mode(replay: FixedModeReplay) -> ReportSnapshot:
        if refresh_payload_resolver is None:
            raise ValueError("refresh input resolver is not configured")
        payload = dict(refresh_payload_resolver(replay))
        payload["refresh_context"] = replay.context
        request = ModeRequest(replay.context.run_id, replay.mode, payload, refresh_replay=True)
        result = execute_mode(request, service_holder["services"])
        if result.availability not in {Availability.COMPLETE, Availability.PARTIAL} or not result.report_refs:
            raise ValueError("fixed mode replay did not produce a report")
        snapshot = read_report_snapshot(replay.context.run_id, result.report_refs[-1])
        effective_availability = snapshot.availability
        if result.availability is Availability.PARTIAL and effective_availability is ReportAvailability.AVAILABLE:
            effective_availability = ReportAvailability.PARTIAL
        return replace(
            snapshot, availability=effective_availability,
            missing_inputs=tuple(dict.fromkeys((*snapshot.missing_inputs, *result.missing_inputs))),
        )

    def load_portfolio(request: ModeRequest) -> PortfolioAnalysisRequest | None:
        value = portfolio_loader(request) if portfolio_loader is not None else request.payload.get("portfolio_request")
        return value if isinstance(value, PortfolioAnalysisRequest) else None

    def check_mode_pin(request: ModeRequest, portfolio: PortfolioAnalysisRequest) -> str | None:
        if request.run_id != run_db.run_id:
            return "run database does not match the request run_id"
        run_context = run_db.fetch_phase6_context()
        metadata = run_context["run_metadata"]
        state = portfolio.pinned_state
        pin = run_context["pinned_personal_state"]
        mode_matches = metadata.get("request_mode") == request.mode.value
        if request.refresh_replay and metadata.get("request_mode") == RequestMode.REPORT_REFRESH.value:
            mode_matches = True
        if not mode_matches:
            return "run database request mode does not match the requested mode"
        if (metadata.get("analysis_as_of") != state.analysis_as_of
                or metadata.get("analysis_timezone") is None):
            return "portfolio input clock does not match the pinned run clock"
        if (pin is None or int(pin.get("state_version") or 0) != state.state_version
                or pin.get("portfolio_snapshot_id") != state.snapshot_ref
                or pin.get("portfolio_data_as_of") != state.portfolio_data_as_of):
            return "portfolio input does not match the run.db pinned personal state"
        return None

    def portfolio_value(request: ModeRequest, *, stage: str) -> tuple[PortfolioAnalysisRequest | None, StepResult | None]:
        portfolio = load_portfolio(request)
        if portfolio is None:
            return None, StepResult(Availability.PARTIAL,
                                    missing_inputs=("typed_portfolio_request",),
                                    output={"stage": stage})
        problem = check_mode_pin(request, portfolio)
        if problem:
            return None, StepResult(Availability.UNSUPPORTED,
                                    unsupported_reasons=(problem,), output={"stage": stage})
        return portfolio, None

    def pin_portfolio(request: ModeRequest, _context: StepContext) -> StepResult:
        portfolio, failure = portfolio_value(request, stage="pin")
        if failure:
            return failure
        assert portfolio is not None
        return StepResult(Availability.COMPLETE, output={"portfolio_request": portfolio,
                                                         "pinned_state": {
                                                             "state_version": portfolio.pinned_state.state_version,
                                                             "snapshot_ref": portfolio.pinned_state.snapshot_ref,
                                                             "analysis_as_of": portfolio.pinned_state.analysis_as_of,
                                                             "portfolio_data_as_of": portfolio.pinned_state.portfolio_data_as_of,
                                                         }})

    def pin_state(request: ModeRequest, context: StepContext) -> StepResult:
        if request.mode is RequestMode.REPORT_REFRESH:
            return pin_refresh_state(request, context)
        return pin_portfolio(request, context)

    def lightweight(request: ModeRequest, context: StepContext) -> StepResult:
        portfolio = context[PipelineStep.PIN_PERSONAL_STATE.value].output.get("portfolio_request")
        if not isinstance(portfolio, PortfolioAnalysisRequest):
            return StepResult(Availability.PARTIAL, output={"section": ReportSectionInput(
                "portfolio_snapshot", "Pinned Portfolio Snapshot", ("WAIT: typed pinned portfolio state is missing.",),
                status=ReportAvailability.UNAVAILABLE)},
                missing_inputs=("typed_portfolio_request",))
        section = ReportSectionInput(
            "portfolio_snapshot", "Pinned Portfolio Snapshot",
            (f"state_version={portfolio.pinned_state.state_version}; snapshot={portfolio.pinned_state.snapshot_ref}.",
             f"position_count={len(portfolio.positions)}; cash_balance_count={len(portfolio.cash)}; liability_count={len(portfolio.liabilities)}."),
            status=ReportAvailability.AVAILABLE,
            metadata={"state_version": portfolio.pinned_state.state_version,
                      "snapshot_ref": portfolio.pinned_state.snapshot_ref,
                      "portfolio_data_as_of": portfolio.pinned_state.portfolio_data_as_of},
        )
        return StepResult(Availability.COMPLETE, output={"section": section})

    def materiality(request: ModeRequest, context: StepContext) -> StepResult:
        portfolio = context[PipelineStep.PIN_PERSONAL_STATE.value].output.get("portfolio_request")
        if not isinstance(portfolio, PortfolioAnalysisRequest):
            return StepResult(Availability.PARTIAL, output={"selected_instrument_ids": ()},
                              missing_inputs=("typed_portfolio_request",))
        if materiality_selector is None:
            return StepResult(Availability.PARTIAL, output={"selected_instrument_ids": ()},
                              missing_inputs=("approved_materiality_selector",))
        selected = materiality_selector(portfolio, request)
        if selected is None:
            return StepResult(Availability.PARTIAL, output={"selected_instrument_ids": ()},
                              missing_inputs=("materiality_selection",))
        selected = tuple(selected)
        known = {position.instrument_id for position in portfolio.positions}
        if len(selected) != len(set(selected)) or any(item not in known for item in selected):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("materiality selector returned duplicate or unknown instruments",))
        return StepResult(Availability.COMPLETE, output={"selected_instrument_ids": selected})

    def research_selected(request: ModeRequest, context: StepContext) -> StepResult:
        selected = context[PipelineStep.APPLY_MATERIALITY_GATE.value].output["selected_instrument_ids"]
        if not selected:
            return StepResult(Availability.PARTIAL, output={"sections": ()},
                              missing_inputs=("selected_assets_for_deep_research",))
        if selected_asset_research is None:
            return StepResult(Availability.PARTIAL, output={"sections": ()},
                              missing_inputs=("selected_asset_research_handler",))
        result = selected_asset_research(tuple(selected), request)
        if not isinstance(result, SelectedAssetResearchResult):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("selected asset research must return SelectedAssetResearchResult",))
        refs_missing = _missing_run_refs(run_db, result.evidence_refs, result.calculation_refs)
        missing = (*result.missing_inputs, *refs_missing)
        return StepResult(Availability.PARTIAL if missing else Availability.COMPLETE,
                          output={"sections": result.sections},
                          evidence_refs=result.evidence_refs,
                          calculation_refs=result.calculation_refs,
                          missing_inputs=tuple(dict.fromkeys(missing)))

    def calculate_portfolio(_request: ModeRequest, context: StepContext) -> StepResult:
        portfolio = context[PipelineStep.PIN_PERSONAL_STATE.value].output.get("portfolio_request")
        if not isinstance(portfolio, PortfolioAnalysisRequest):
            return StepResult(Availability.PARTIAL, output={},
                              missing_inputs=("typed_portfolio_request",))
        result = analyze_portfolio(portfolio)
        calc_id = f"calc:portfolio-analysis:{uuid4().hex}"
        evidence_refs, provenance = _portfolio_provenance(portfolio, result)
        missing_refs = _missing_run_refs(run_db, evidence_refs, ())
        run_db.add_calculation(
            calculation_id=calc_id, calculation_name="portfolio_analysis",
            formula="pinned_portfolio_allocation_and_risk_v1",
            inputs={"evidence_ids": [ref for ref in evidence_refs if _run_has_evidence(run_db, ref)],
                    "missing_evidence_refs": list(missing_refs),
                    "state_version": result.state_version, "snapshot_ref": result.snapshot_ref,
                    "evaluation_currency": result.evaluation_currency,
                    "fx_evidence_refs": provenance["fx_evidence_refs"],
                    "risk_evidence_refs": provenance["risk_evidence_refs"],
                    "fx_provenance": provenance["fx_pairs"],
                    "risk_provenance": provenance["risk_series"],
                    "risk_policy_ref": portfolio.risk_policy.policy_ref if portfolio.risk_policy else None,
                    "risk_policy_approval_ref": portfolio.risk_policy.approval_ref if portfolio.risk_policy else None,
                    "risk_policy_validation_ref": portfolio.risk_policy.validation_ref if portfolio.risk_policy else None,
                    "risk_period_policy_ref": portfolio.period_policy.policy_ref if portfolio.period_policy else None},
            result={"gross_assets": _s(result.gross_assets), "total_cash": _s(result.total_cash),
                    "total_liabilities": _s(result.total_liabilities), "net_worth": _s(result.net_worth),
                    "allocation_by_asset_class": {k: str(v) for k, v in result.allocation.by_asset_class.items()},
                    "allocation_by_currency": {k: str(v) for k, v in result.allocation.by_currency.items()},
                    "risk_volatility": _s(result.risk.volatility if result.risk else None),
                    "risk_limits": [{"metric": item.metric, "value": _s(item.value), "limit": _s(item.limit),
                                     "status": item.status.value} for item in result.risk_limits],
                    "missing_inputs": list(result.missing_inputs)},
        )
        section = replace(result.section, calculation_ids=(calc_id,))
        missing = (*result.missing_inputs, *missing_refs)
        return StepResult(Availability.PARTIAL if missing else Availability.COMPLETE,
                          output={"analysis": result, "section": section},
                          evidence_refs=evidence_refs, calculation_refs=(calc_id,),
                          missing_inputs=tuple(dict.fromkeys(missing)))

    def scenario_baseline(request: ModeRequest, context: StepContext) -> StepResult:
        portfolio, failure = portfolio_value(request, stage="scenario_baseline")
        if failure:
            if failure.availability is Availability.PARTIAL:
                section = _wait_section("portfolio_scenario", "Portfolio Scenario", failure.missing_inputs)
                return StepResult(Availability.PARTIAL, output={"section": section},
                                  missing_inputs=failure.missing_inputs)
            return failure
        scenario = request.payload.get("scenario")
        if not isinstance(scenario, PortfolioScenario):
            missing = ("typed_portfolio_scenario",)
            return StepResult(Availability.PARTIAL,
                              output={"section": _wait_section("portfolio_scenario", "Portfolio Scenario", missing)},
                              missing_inputs=missing)
        return StepResult(Availability.COMPLETE, output={"portfolio_request": portfolio, "scenario": scenario})

    def run_scenario(_request: ModeRequest, context: StepContext) -> StepResult:
        baseline = context[PipelineStep.BUILD_SCENARIO_BASELINE.value].output
        portfolio = baseline.get("portfolio_request")
        scenario = baseline.get("scenario")
        if not isinstance(portfolio, PortfolioAnalysisRequest) or not isinstance(scenario, PortfolioScenario):
            missing = context[PipelineStep.BUILD_SCENARIO_BASELINE.value].missing_inputs
            return StepResult(Availability.PARTIAL, output={"sections": ()},
                              missing_inputs=missing or ("typed_portfolio_scenario_baseline",))
        result = simulate_portfolio_scenario(portfolio, scenario,
                                             gate_verifier=scenario_gate_verifier)
        evidence_refs, provenance = _portfolio_provenance(portfolio, result.before)
        if result.status is ScenarioStatus.WAIT:
            return StepResult(Availability.PARTIAL, output={"scenario_result": result, "section": result.section},
                              evidence_refs=evidence_refs, missing_inputs=result.missing_inputs)
        calc_id = f"calc:portfolio-scenario:{uuid4().hex}"
        missing_refs = _missing_run_refs(run_db, evidence_refs, ())
        run_db.add_calculation(
            calculation_id=calc_id, calculation_name="portfolio_scenario",
            formula="explicit_non_posting_portfolio_scenario_v1",
            inputs={"evidence_ids": [ref for ref in evidence_refs if _run_has_evidence(run_db, ref)],
                    "missing_evidence_refs": list(missing_refs),
                    "fx_evidence_refs": provenance["fx_evidence_refs"],
                    "risk_evidence_refs": provenance["risk_evidence_refs"],
                    "fx_provenance": provenance["fx_pairs"],
                    "risk_provenance": provenance["risk_series"],
                    "scenario_id": scenario.scenario_id, "description": scenario.description,
                    "approval": ({"gate_id": scenario.approval.gate_id,
                                  "policy_ref": scenario.approval.policy_ref,
                                  "approval_ref": scenario.approval.approval_ref,
                                  "validation_ref": scenario.approval.validation_ref}
                                 if scenario.approval else None),
                    "assumption_refs": [item.assumption_ref for item in scenario.adjustments]
                    + [item.assumption_ref for item in scenario.fx_assumptions]
                    + [item.assumption_ref for item in scenario.risk_shocks]},
            result={"status": result.status.value, "gross_assets_delta": _s(result.gross_assets_delta),
                    "liabilities_delta": _s(result.liabilities_delta), "net_worth_delta": _s(result.net_worth_delta),
                    "risk_volatility_delta": _s(result.risk_volatility_delta),
                    "missing_inputs": list(result.missing_inputs), "posting_enabled": False},
        )
        section = replace(result.section, calculation_ids=(calc_id,))
        missing = (*result.missing_inputs, *missing_refs)
        if result.status is ScenarioStatus.PARTIAL and not missing:
            missing = tuple(dict.fromkeys(
                (*((result.before.missing_inputs if result.before else ())),
                 *((result.after.missing_inputs if result.after else ())),
                 "portfolio_scenario_partial_data_quality")
            ))
        return StepResult(Availability.PARTIAL if result.status is ScenarioStatus.PARTIAL or missing else Availability.COMPLETE,
                          output={"scenario_result": result, "section": section},
                          evidence_refs=evidence_refs, calculation_refs=(calc_id,),
                          missing_inputs=tuple(dict.fromkeys(missing)))

    def load_thesis(request: ModeRequest, _context: StepContext) -> StepResult:
        run_mismatch = _thesis_run_mismatch(run_db, request)
        if run_mismatch is not None:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(run_mismatch,))
        thesis = request.payload.get("thesis_request")
        if thesis is None:
            return StepResult(Availability.PARTIAL, output={"thesis_request": None},
                              missing_inputs=("user_authored_thesis_claims",))
        if not isinstance(thesis, ThesisReviewRequest):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("thesis_request must be a typed ThesisReviewRequest",))
        return StepResult(Availability.COMPLETE, output={"thesis_request": thesis})

    def auto_pass_thesis(request: ModeRequest, context: StepContext) -> StepResult:
        thesis = context[PipelineStep.LOAD_THESIS.value].output["thesis_request"]
        if thesis is None or not thesis.subject.strip():
            return StepResult(Availability.PARTIAL, output={"subject": None},
                              missing_inputs=("thesis_subject",))
        return StepResult(Availability.COMPLETE, output={"subject": thesis.subject})

    def collect_thesis_evidence(request: ModeRequest, context: StepContext) -> StepResult:
        thesis = context[PipelineStep.LOAD_THESIS.value].output["thesis_request"]
        if thesis is None:
            return StepResult(Availability.PARTIAL, output={"evidence": ()},
                              missing_inputs=("thesis_evidence_without_claims_is_not_used",))
        if thesis_evidence_collector is not None:
            evidence = thesis_evidence_collector(thesis, request)
        else:
            evidence = request.payload.get("thesis_evidence", ())
        if not isinstance(evidence, (tuple, list)) or not all(isinstance(item, ThesisEvidence) for item in evidence):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("thesis evidence collector must return typed ThesisEvidence values",))
        evidence = tuple(evidence)
        ids = [item.evidence_id for item in evidence]
        if any(not item.strip() for item in ids) or len(ids) != len(set(ids)):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("thesis evidence IDs must be nonempty and unique",))
        try:
            for item in evidence:
                if item.subject != thesis.subject:
                    continue
                _persist_thesis_evidence(run_db, item)
        except (ValueError, RuntimeError):
            missing = ("conflicting_or_unpersistable_thesis_evidence",)
            return StepResult(Availability.PARTIAL, output={"evidence": ()}, missing_inputs=missing)
        return StepResult(Availability.COMPLETE if evidence else Availability.PARTIAL,
                          output={"evidence": evidence},
                          evidence_refs=tuple(item.evidence_id for item in evidence if item.subject == thesis.subject),
                          missing_inputs=() if evidence else ("latest_selected_thesis_evidence",))

    def review_thesis_handler(request: ModeRequest, context: StepContext) -> StepResult:
        thesis = context[PipelineStep.LOAD_THESIS.value].output["thesis_request"]
        evidence = context[PipelineStep.COLLECT_LATEST_EVIDENCE.value].output["evidence"]
        metadata = run_db.fetch_phase6_context()["run_metadata"]
        cutoff = metadata.get("analysis_as_of")
        if not cutoff:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=("pinned run clock is missing",))
        result = review_thesis(thesis, tuple(evidence), analysis_as_of=str(cutoff))
        calc_id = f"calc:thesis-review:{uuid4().hex}"
        refs = tuple(eid for eid in result.section.evidence_ids if _run_has_evidence(run_db, eid))
        missing_refs = tuple(f"run_db_evidence:{eid}" for eid in result.section.evidence_ids if eid not in refs)
        run_db.add_calculation(
            calculation_id=calc_id, calculation_name="thesis_review",
            formula="latest_eligible_user_thesis_countercondition_v1",
            inputs={"evidence_ids": list(refs), "missing_evidence_refs": list(missing_refs),
                    "claim_ids": [claim.claim_id for claim in thesis.claims] if thesis else [],
                    "analysis_as_of": cutoff},
            result={"status": result.status.value,
                    "assessments": [{"claim_id": row.claim_id, "verdict": row.verdict.value,
                                     "evidence_ids": list(row.evidence_ids), "falsifier": row.falsifier}
                                    for row in result.assessments],
                    "missing_inputs": list(result.missing_inputs)},
        )
        section = replace(result.section, calculation_ids=(calc_id,))
        missing = (*result.missing_inputs, *missing_refs)
        return StepResult(Availability.PARTIAL if result.status is RefreshStatus.WAIT or missing else Availability.COMPLETE,
                          output={"review_result": result, "section": section},
                          evidence_refs=tuple(dict.fromkeys((*refs, *missing_refs))),
                          calculation_refs=(calc_id,), missing_inputs=tuple(dict.fromkeys(missing)))

    def begin_refresh(request: ModeRequest, _context: StepContext) -> StepResult:
        external = report_refresh_services
        refresh_request = request.payload.get("refresh_request")
        if refresh_request is None:
            try:
                refresh_request = ReportRefreshRequest(
                    str(request.payload["previous_run_id"]), str(request.payload["previous_report_id"]),
                    str(request.payload["original_mode"]), str(request.payload.get("target") or ""),
                    tuple(request.payload.get("assumptions") or ()),
                )
            except (KeyError, TypeError):
                return StepResult(Availability.PARTIAL, missing_inputs=("typed_or_complete_report_refresh_request",))
        if not isinstance(refresh_request, ReportRefreshRequest):
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("refresh_request must be a typed ReportRefreshRequest",))

        def verify(context: PinnedRefreshContext) -> bool:
            if context.run_id != request.run_id or run_db.run_id != request.run_id:
                return False
            snapshot = run_db.fetch_phase6_context()
            metadata = snapshot["run_metadata"]
            pin = snapshot["pinned_personal_state"]
            return bool(
                metadata.get("analysis_as_of") == context.analysis_as_of
                and metadata.get("analysis_timezone") == context.analysis_timezone
                and pin is not None
                and int(pin.get("state_version") or 0) == context.state_version
                and pin.get("portfolio_snapshot_id") == context.pinned_state_ref
                and (external is None or external.verify_pinned_run(context))
            )

        runners = dict(external.allowed_mode_runners) if external else {}
        if refresh_payload_resolver is not None:
            runners[RequestMode.PERSONAL_PORTFOLIO_ANALYSIS] = rerun_fixed_mode
            runners[RequestMode.PORTFOLIO_SCENARIO] = rerun_fixed_mode
        if not runners:
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("fixed non-posting refresh runners are not configured",))
        wrapped = ReportRefreshServices(
            external.load_prior_report if external else read_report_snapshot,
            external.start_pinned_run if external else start_existing_pinned_run,
            verify,
            runners,
        )
        try:
            result = refresh_report(refresh_request, wrapped)
        except (ValueError, RuntimeError, KeyError):
            # Keep provider and database exception text out of run.db/report output.
            return StepResult(Availability.PARTIAL, missing_inputs=("verified_report_refresh_inputs_or_runner",))
        if result.current is None or result.current.run_id != run_db.run_id:
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("refresh runner did not return a report from the new request run",))
        refresh_missing = result.missing_inputs or (
            ("report_refresh_incomplete",) if result.status is RefreshStatus.WAIT else ()
        )
        return StepResult(Availability.PARTIAL if result.status is RefreshStatus.WAIT else Availability.COMPLETE,
                          output={"refresh_result": result, "section": result.section,
                                  "refresh_context": result.current},
                          evidence_refs=tuple(result.section.evidence_ids),
                          calculation_refs=tuple(result.section.calculation_ids),
                          missing_inputs=refresh_missing)

    def pin_refresh_state(_request: ModeRequest, context: StepContext) -> StepResult:
        first = context[PipelineStep.START_NEW_RUN_CLOCK.value]
        result = first.output.get("refresh_result")
        if result is None or result.current is None or result.current.run_id != run_db.run_id:
            if first.availability is Availability.PARTIAL:
                return StepResult(Availability.PARTIAL,
                                  output={"section": _wait_section("report_refresh_delta", "Report Refresh Changes", first.missing_inputs)},
                                  missing_inputs=first.missing_inputs or ("verified_report_refresh_inputs_or_runner",))
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("new run clock/state pin was not verified",))
        return StepResult(Availability.COMPLETE, output={"refresh_context": result.current})

    def reexecute_refresh(_request: ModeRequest, context: StepContext) -> StepResult:
        first = context[PipelineStep.START_NEW_RUN_CLOCK.value]
        if "refresh_result" not in first.output:
            section = first.output.get("section")
            return StepResult(first.availability,
                              output={"sections": (section,) if isinstance(section, ReportSectionInput) else ()},
                              missing_inputs=first.missing_inputs,
                              unsupported_reasons=first.unsupported_reasons)
        result = first.output["refresh_result"]
        return StepResult(first.availability, output={"sections": (result.section,)},
                          evidence_refs=first.evidence_refs,
                          calculation_refs=first.calculation_refs,
                          missing_inputs=first.missing_inputs,
                          unsupported_reasons=first.unsupported_reasons)

    def conditional_review(request: ModeRequest, context: StepContext) -> StepResult:
        evidence = tuple(dict.fromkeys(eid for step in context.values() for eid in step.evidence_refs
                                       if _run_has_evidence(run_db, eid)))
        review = phase6.review.evaluate(ReviewContext(critical_evidence_ids=evidence))
        return StepResult(Availability.COMPLETE, output={"review": review})

    def render_report(request: ModeRequest, context: StepContext) -> StepResult:
        sections: list[ReportSectionInput] = []
        for step_result in context.values():
            section = step_result.output.get("section")
            if isinstance(section, ReportSectionInput):
                sections.append(section)
            for child in step_result.output.get("sections", ()):
                if isinstance(child, ReportSectionInput):
                    sections.append(child)
        incomplete_steps = tuple(sorted(
            name for name, item in context.items() if item.availability is Availability.PARTIAL
        ))
        missing_ids = tuple(dict.fromkeys(
            value for item in context.values() for value in item.missing_inputs
        ))
        if incomplete_steps or missing_ids:
            sections.append(ReportSectionInput(
                "analysis_completeness", "분석 범위와 누락 자료",
                ("분석 일부가 완료되지 않았습니다. 결과를 확정 판단에 사용하기 전에 누락된 자료나 단계를 확인해 주세요.",),
                status=ReportAvailability.PARTIAL,
                metadata={"missing_input_ids": list(missing_ids),
                          "partial_step_ids": list(incomplete_steps)},
            ))
        # Stage outputs can intentionally share a section; the last typed version
        # carries the final calculation reference, while duplicate names are invalid.
        by_name: dict[str, ReportSectionInput] = {}
        for section in sections:
            by_name[section.name] = section
        if not by_name:
            return StepResult(Availability.UNSUPPORTED,
                              unsupported_reasons=("mode has no typed report section to render",))
        review_step = context.get(PipelineStep.CONDITIONAL_REVIEW.value)
        review = review_step.output.get("review") if review_step is not None else None
        if review is None:
            evidence_ids = tuple(dict.fromkeys(
                eid for item in context.values() for eid in item.evidence_refs
                if _run_has_evidence(run_db, eid)
            ))
            review = phase6.review.evaluate(ReviewContext(critical_evidence_ids=evidence_ids))
        phase6_result = phase6.generate(
            title=str(request.payload.get("title") or _title(request.mode)),
            sections=tuple(by_name.values()),
            review_context=ReviewContext(critical_evidence_ids=tuple(
                eid for item in context.values() for eid in item.evidence_refs
                if _run_has_evidence(run_db, eid)
            )),
        )
        report = _localize_portfolio_thesis_report(
            phase6_result.report, phase6.report._render,
            {row["evidence_id"]: row for row in run_db.fetch_phase6_context()["evidence"]},
            incomplete=bool(incomplete_steps or missing_ids),
        )
        run_context = run_db.fetch_phase6_context()
        expected = {section.name for section in report.sections}
        persisted = [row for row in run_context["report_sections"] if row["section_name"] in expected]
        if {row["section_name"] for row in persisted} != expected:
            return StepResult(Availability.FAILED, output={"report_persisted": False})
        pinned_request = next((step.output.get("portfolio_request") for step in context.values()
                               if isinstance(step.output.get("portfolio_request"), PortfolioAnalysisRequest)), None)
        target, assumptions = _report_identity(request, pinned_request)
        manifest = {
            "mode": request.mode.value, "title": report.title,
            "availability": report.availability.value, "analysis_as_of": report.as_of.analysis_as_of,
            "missing_inputs": list(missing_ids),
            "target": target, "assumptions": list(assumptions),
            "section_refs": [{"section_name": row["section_name"],
                              "content_reference": row["content_reference"]}
                             for row in sorted(persisted, key=lambda value: value["section_name"])],
        }
        encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        report_ref = f"run-report:{run_db.run_id}:sha256:{digest}"
        run_db.record_task_state(
            task_name=f"report:{digest}", task_status=report.availability.value,
            metadata={"report_ref": report_ref, **manifest},
        )
        prior_missing = tuple(dict.fromkeys(
            value for step in context.values() for value in step.missing_inputs
        ))
        partial = report.availability is not ReportAvailability.AVAILABLE or any(
            step.availability is Availability.PARTIAL for step in context.values()
        )
        missing = prior_missing or (("partial_report_data_quality",) if partial else ())
        return StepResult(Availability.PARTIAL if partial else Availability.COMPLETE,
                          output={"report": report}, report_refs=(report_ref,),
                          evidence_refs=tuple(dict.fromkeys(eid for item in context.values() for eid in item.evidence_refs)),
                          calculation_refs=tuple(dict.fromkeys(cid for item in context.values() for cid in item.calculation_refs)),
                          missing_inputs=missing)

    handlers = {
        PipelineStep.PIN_PERSONAL_STATE: pin_state,
        PipelineStep.LIGHTWEIGHT_ALL_ASSETS: lightweight,
        PipelineStep.APPLY_MATERIALITY_GATE: materiality,
        PipelineStep.DEEP_RESEARCH_SELECTED_ASSETS: research_selected,
        PipelineStep.CALCULATE_ALLOCATION_AND_RISK: calculate_portfolio,
        PipelineStep.BUILD_SCENARIO_BASELINE: scenario_baseline,
        PipelineStep.RUN_NON_POSTING_SCENARIO: run_scenario,
        PipelineStep.LOAD_THESIS: load_thesis,
        PipelineStep.AUTO_PASS_REQUESTED_ASSETS: auto_pass_thesis,
        PipelineStep.COLLECT_LATEST_EVIDENCE: collect_thesis_evidence,
        PipelineStep.REVIEW_THESIS: review_thesis_handler,
        PipelineStep.START_NEW_RUN_CLOCK: begin_refresh,
        PipelineStep.REEXECUTE_REQUIRED_PIPELINE: reexecute_refresh,
        PipelineStep.CONDITIONAL_REVIEW: conditional_review,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT: render_report,
    }
    local_modes = frozenset({
        RequestMode.PERSONAL_PORTFOLIO_ANALYSIS, RequestMode.PORTFOLIO_SCENARIO,
        RequestMode.THESIS_REVIEW, RequestMode.REPORT_REFRESH,
    })
    combined: dict[PipelineStep, Callable[[ModeRequest, StepContext], StepResult]] = {}
    all_steps = set(handlers) | (set(base_services.handlers) if base_services is not None else set())
    for step in all_steps:
        own_handler = handlers.get(step)
        base_handler = base_services.handlers.get(step) if base_services is not None else None

        def dispatch_step(request: ModeRequest, context: StepContext, *,
                          local: Callable[[ModeRequest, StepContext], StepResult] | None = own_handler,
                          delegated: Callable[[ModeRequest, StepContext], StepResult] | None = base_handler,
                          step_name: str = step.value,
                          current_step: PipelineStep = step) -> StepResult:
            if request.mode in local_modes:
                if local is None:
                    return StepResult(Availability.UNSUPPORTED,
                                      unsupported_reasons=(f"portfolio/thesis handler is not configured for {step_name}",))
                return local(request, context)
            if delegated is None:
                return StepResult(Availability.UNSUPPORTED,
                                  unsupported_reasons=(f"base fixed-mode handler is not configured for {step_name}",))
            result = delegated(request, context)
            if current_step is PipelineStep.RENDER_PARTIAL_AWARE_REPORT and result.report_refs:
                result = _attach_refresh_identity(run_db, request, result)
            return result

        combined[step] = dispatch_step
    services = RuntimeServices(handlers=combined, run_db=run_db, run_dbs=registry)
    service_holder["services"] = services
    return services


def _portfolio_provenance(request: PortfolioAnalysisRequest,
                          result: PortfolioAnalysisResult | None) -> tuple[tuple[str, ...], dict[str, object]]:
    """Return only point-in-time FX/risk inputs that the typed calculator could consume."""
    as_of = datetime.fromisoformat(request.pinned_state.analysis_as_of.replace("Z", "+00:00"))
    currency_pairs = {
        (currency.upper(), request.evaluation_currency.upper())
        for currency in (
            *(item.currency for item in request.positions if item.market_value is not None),
            *(item.currency for item in request.cash if item.amount is not None),
            *(item.currency for item in request.liabilities if item.amount is not None),
        )
        if currency.upper() != request.evaluation_currency.upper()
    }
    fx_pairs: list[dict[str, object]] = []
    refs: list[str] = []
    for source, target in sorted(currency_pairs):
        candidates: list[tuple[datetime, FxEvidence]] = []
        for quote in request.fx_evidence:
            if ((quote.from_currency.upper(), quote.to_currency.upper()) != (source, target)
                    or not quote.selected or quote.eligibility_status.upper() != "ELIGIBLE"
                    or quote.freshness_status.upper() not in {"FRESH", "CURRENT"}):
                continue
            try:
                observed = datetime.fromisoformat(quote.observed_at.replace("Z", "+00:00"))
                published = datetime.fromisoformat(quote.public_available_at.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            if observed.tzinfo is None or published.tzinfo is None or observed > as_of or published > as_of:
                continue
            candidates.append((observed, quote))
        if not candidates:
            continue
        latest = max(stamp for stamp, _ in candidates)
        latest_quotes = [quote for stamp, quote in candidates if stamp == latest]
        rates = {quote.rate for quote in latest_quotes}
        if len(rates) == 1:
            used = sorted({quote.evidence_id for quote in latest_quotes})
            refs.extend(used)
            fx_pairs.append({"from_currency": source, "to_currency": target,
                             "rate": str(next(iter(rates))), "observed_at": latest.isoformat(),
                             "evidence_ids": used})

    risk_rows: list[dict[str, object]] = []
    period = request.period_policy
    if result is not None and result.risk is not None and period is not None:
        start, end = datetime.fromisoformat(period.period_start), datetime.fromisoformat(period.period_end)
        for position in request.positions:
            series = next((item for item in request.price_series if item.instrument_id == position.instrument_id), None)
            if series is None or series.frequency != period.frequency:
                continue
            selected: list[str] = []
            for observation in series.observations:
                day = datetime.fromisoformat(observation.period).date()
                if (day < start.date() or day > end.date() or day > as_of.date()
                        or observation.currency.upper() != request.evaluation_currency.upper()
                        or observation.eligibility_status.upper() != "ELIGIBLE"
                        or observation.freshness_status.upper() not in {"FRESH", "CURRENT"}
                        or not observation.selected):
                    continue
                try:
                    published = datetime.fromisoformat(observation.public_available_at.replace("Z", "+00:00"))
                except (AttributeError, ValueError):
                    continue
                if published.tzinfo is None or published > as_of:
                    continue
                selected.append(observation.evidence_id)
            if selected:
                refs.extend(selected)
                risk_rows.append({"instrument_id": position.instrument_id,
                                  "frequency": series.frequency,
                                  "period_policy_ref": period.policy_ref,
                                  "evidence_ids": selected})
    distinct_refs = tuple(dict.fromkeys(refs))
    return distinct_refs, {
        "fx_evidence_refs": tuple(ref for row in fx_pairs for ref in row["evidence_ids"]),
        "risk_evidence_refs": tuple(ref for row in risk_rows for ref in row["evidence_ids"]),
        "fx_pairs": fx_pairs,
        "risk_series": risk_rows,
    }


def _missing_run_refs(run_db: RunDatabaseManager, evidence_refs: tuple[str, ...], calculation_refs: tuple[str, ...]) -> tuple[str, ...]:
    snapshot = run_db.fetch_phase6_context()
    evidence = {row["evidence_id"] for row in snapshot["evidence"]}
    calculations = {row["calculation_id"] for row in snapshot["calculations"]}
    return tuple([f"run_db_evidence:{ref}" for ref in evidence_refs if ref not in evidence]
                 + [f"run_db_calculation:{ref}" for ref in calculation_refs if ref not in calculations])


def _run_has_evidence(run_db: RunDatabaseManager, evidence_id: str) -> bool:
    return any(row["evidence_id"] == evidence_id for row in run_db.fetch_phase6_context()["evidence"])


def _persist_thesis_evidence(run_db: RunDatabaseManager, item: ThesisEvidence) -> None:
    snapshot = run_db.fetch_phase6_context()
    existing = next((row for row in snapshot["evidence"] if row["evidence_id"] == item.evidence_id), None)
    metadata = {"subject": item.subject, "metric": item.metric,
                "value": str(item.value) if item.value is not None else None, "unit": item.unit,
                "observed_at": item.observed_at, "public_available_at": item.public_available_at,
                "freshness_status": item.freshness_status, "eligibility_status": item.eligibility_status,
                "selected": item.selected}
    if existing is not None:
        try:
            prior = json.loads(existing.get("metadata_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            raise ValueError("thesis evidence ID conflicts with an unreadable run.db record")
        if existing.get("evidence_type") != "thesis_observation" or prior != metadata:
            raise ValueError("thesis evidence ID conflicts with a different run.db record")
        return
    run_db.add_evidence(evidence_id=item.evidence_id, evidence_type="thesis_observation", metadata=metadata)


def _attach_refresh_identity(run_db: RunDatabaseManager, request: ModeRequest,
                             result: StepResult) -> StepResult:
    """Add explicit target/assumptions to delegated report manifests for refresh lookup."""
    target, assumptions = _report_identity(request)
    snapshot = run_db.fetch_phase6_context()
    refreshed_refs: list[str] = []
    for report_ref in result.report_refs:
        manifest = None
        for row in snapshot["task_states"]:
            try:
                value = json.loads(row.get("metadata_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if value.get("report_ref") == report_ref:
                manifest = value
        if manifest is None:
            refreshed_refs.append(report_ref)
            continue
        manifest = dict(manifest)
        manifest.update({"source_report_ref": report_ref, "mode": request.mode.value,
                         "target": target, "assumptions": list(assumptions)})
        encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        enriched_ref = f"run-report:{run_db.run_id}:sha256:{digest}"
        run_db.record_task_state(
            task_name=f"report-refresh-identity:{digest}",
            task_status=str(manifest.get("availability") or result.availability.value),
            metadata={**manifest, "report_ref": enriched_ref},
        )
        refreshed_refs.append(enriched_ref)
    return replace(result, report_refs=tuple(refreshed_refs))


def _thesis_run_mismatch(run_db: RunDatabaseManager, request: ModeRequest) -> str | None:
    """Fail closed before thesis evidence or calculations can reach another run.db."""
    if request.run_id != run_db.run_id:
        return "thesis request run_id does not match the bound run database"
    metadata = run_db.fetch_phase6_context()["run_metadata"]
    if metadata.get("request_mode") != RequestMode.THESIS_REVIEW.value:
        return "bound run database is not initialized for THESIS_REVIEW"
    clock = metadata.get("analysis_as_of")
    if not isinstance(clock, str) or not clock:
        return "thesis run database has no pinned analysis clock"
    try:
        parsed_clock = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    except ValueError:
        return "thesis run database has an invalid pinned analysis clock"
    if parsed_clock.tzinfo is None or parsed_clock.utcoffset() is None:
        return "thesis run database analysis clock must include a timezone"
    return None


def _localize_portfolio_thesis_report(report, renderer, evidence_by_id, *, incomplete: bool):
    """Keep the user-facing fixed-mode report readable; run.db retains raw refs."""
    titles = {
        "portfolio_snapshot": "보유 자산 현황",
        "portfolio_analysis": "자산 배분과 위험",
        "allocation_and_risk": "자산 배분과 위험",
        "portfolio_allocation": "자산 배분",
        "portfolio_risk": "포트폴리오 위험",
        "selected_asset_research": "선택 자산 조사",
        "thesis_review": "투자 논지 검토",
        "portfolio_scenario": "포트폴리오 가정 분석",
        "report_refresh_delta": "이전 보고서와 달라진 점",
        "data_quality": "자료 확인 상태",
        "review_findings": "추가 검토 결과",
        "analysis_completeness": "분석 범위와 누락 자료",
    }
    verdicts = {
        "SUPPORTED": "지지됨", "REFUTED": "반증됨", "UNCONFIRMED": "판단 보류",
        "COMPLETE": "완료", "PARTIAL": "일부 완료", "UNAVAILABLE": "확인 불가",
    }
    sections = []
    for section in report.sections:
        title = titles.get(section.name, section.title)
        lines = list(section.lines)
        if section.name == "portfolio_snapshot":
            lines = ["고정된 보유 현황 스냅샷을 기준으로 분석했습니다."]
        elif section.name == "portfolio_analysis":
            lines = ["고정된 보유 현황과 분석 기준시각을 바탕으로 자산 배분과 위험을 계산했습니다."
                     if "state_version=" in line or "snapshot=" in line else line for line in lines]
        elif section.name == "portfolio_scenario":
            lines = ["시나리오 결과는 사용자가 입력한 가정을 적용한 모의 분석입니다."
                     if "가정 refs:" in line else line for line in lines]
        elif section.name == "thesis_review":
            cleaned = []
            for line in lines:
                match = re.match(r"^[^—]+ — ([A-Z_]+): (.*)$", line)
                if match:
                    cleaned.append(f"{verdicts.get(match.group(1), '검토')}: {match.group(2)}")
                else:
                    cleaned.append(line)
            lines = cleaned
        elif section.name == "data_quality" and incomplete:
            lines = ["일부 분석 단계가 완료되지 않아 자료 품질을 전체적으로 확인할 수 없습니다."]
            section = replace(section, status=ReportAvailability.PARTIAL)
        elif section.name == "data_quality":
            lines = ["저장된 자료에서 오래되거나 서로 충돌하는 값, 제공자 누락을 확인하지 못했습니다."]
        sections.append(replace(section, title=title,
                                lines=tuple(_format_user_numbers(line) for line in lines)))
    localized = replace(report, sections=tuple(sections), markdown="")
    markdown = renderer(localized, evidence_by_id)
    markdown = markdown.replace("- 계산 근거:", "- 상세 계산 근거:")
    markdown = markdown.replace("- 근거 `", "- 상세 근거 `")
    return replace(localized, markdown=markdown)


def _format_user_numbers(line: str) -> str:
    def format_match(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            number = Decimal(raw)
            places = 2 if number.adjusted() >= 8 or number.adjusted() <= -5 else 4
            with localcontext() as context:
                context.prec = max(context.prec, len(number.as_tuple().digits) + places + 2)
                rounded = number.quantize(Decimal(1).scaleb(-places))
        except Exception:
            return raw
        text = f"{rounded:,.{places}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text

    return re.sub(r"(?<![\w.])[-+]?\d+\.\d{7,}(?![\w])|(?<![\w.])[-+]?\d{16,}(?![\w])",
                  format_match, line)


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _title(mode: RequestMode) -> str:
    return {
        RequestMode.PERSONAL_PORTFOLIO_ANALYSIS: "Personal Portfolio Analysis",
        RequestMode.PORTFOLIO_SCENARIO: "Portfolio Scenario",
        RequestMode.THESIS_REVIEW: "Thesis Review",
        RequestMode.REPORT_REFRESH: "Report Refresh",
    }[mode]


def _wait_section(name: str, title: str, missing: tuple[str, ...]) -> ReportSectionInput:
    causes = missing or ("required_inputs",)
    return ReportSectionInput(
        name, title, tuple(f"WAIT: {item}" for item in causes),
        status=ReportAvailability.UNAVAILABLE,
        metadata={"missing_inputs": list(causes)},
    )


def _report_identity(request: ModeRequest,
                     portfolio_request: PortfolioAnalysisRequest | None = None) -> tuple[str, tuple[str, ...]]:
    target = str(request.payload.get("target") or "")
    assumptions = tuple(str(item) for item in request.payload.get("assumptions", ()) if str(item).strip())
    if request.mode is RequestMode.PERSONAL_PORTFOLIO_ANALYSIS:
        portfolio = portfolio_request or request.payload.get("portfolio_request")
        if isinstance(portfolio, PortfolioAnalysisRequest):
            target = target or "personal_portfolio"
            assumptions = assumptions or (
                "scope=pinned_portfolio_snapshot",
                f"evaluation_currency={portfolio.evaluation_currency}",
            )
    elif request.mode is RequestMode.PORTFOLIO_SCENARIO:
        scenario = request.payload.get("scenario")
        if isinstance(scenario, PortfolioScenario):
            target = target or scenario.scenario_id
            scenario_assumptions = tuple(item.assumption_ref for item in (
                *scenario.adjustments, *scenario.fx_assumptions, *scenario.risk_shocks
            ))
            assumptions = assumptions or scenario_assumptions
    elif request.mode is RequestMode.THESIS_REVIEW:
        thesis = request.payload.get("thesis_request")
        if isinstance(thesis, ThesisReviewRequest):
            target = target or thesis.subject
            assumptions = assumptions or tuple(claim.claim_id for claim in thesis.claims)
    return target or request.mode.value.lower(), assumptions


__all__ = ["SelectedAssetResearchResult", "portfolio_thesis_services"]
