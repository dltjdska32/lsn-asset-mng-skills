"""The complete immutable mapping from request mode to fixed pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from investment_stack.routing import RequestMode


class PipelineStep(StrEnum):
    EXTRACT_TRANSACTION_INTENT = "extract_transaction_intent"
    VALIDATE_EVENT_TIME = "validate_event_time"
    ASSESS_AMBIGUITY_AND_IMPACT = "assess_ambiguity_and_impact"
    DECIDE_POSTING = "decide_posting"
    PROJECT_PERSONAL_STATE = "project_personal_state"
    ADVANCE_STATE_VERSION = "advance_state_version"
    PIN_PERSONAL_STATE = "pin_personal_state"
    LIGHTWEIGHT_ALL_ASSETS = "lightweight_all_assets"
    APPLY_MATERIALITY_GATE = "apply_materiality_gate"
    DEEP_RESEARCH_SELECTED_ASSETS = "deep_research_selected_assets"
    CALCULATE_ALLOCATION_AND_RISK = "calculate_allocation_and_risk"
    AUTO_PASS_REQUESTED_ASSETS = "auto_pass_requested_assets"
    DEEP_RESEARCH_REQUESTED_ASSETS = "deep_research_requested_assets"
    BUILD_COMPARISON = "build_comparison"
    BUILD_SCENARIO_BASELINE = "build_scenario_baseline"
    RUN_NON_POSTING_SCENARIO = "run_non_posting_scenario"
    LOAD_THESIS = "load_thesis"
    COLLECT_LATEST_EVIDENCE = "collect_latest_evidence"
    REVIEW_THESIS = "review_thesis"
    START_NEW_RUN_CLOCK = "start_new_run_clock"
    REEXECUTE_REQUIRED_PIPELINE = "reexecute_required_pipeline"
    CONDITIONAL_REVIEW = "conditional_review"
    RENDER_PARTIAL_AWARE_REPORT = "render_partial_aware_report"


@dataclass(frozen=True, slots=True)
class PipelinePlan:
    mode: RequestMode
    steps: tuple[PipelineStep, ...]

    def as_dict(self) -> dict[str, str | list[str]]:
        return {
            "mode": self.mode.value,
            "steps": [step.value for step in self.steps],
        }


_PIPELINES: dict[RequestMode, tuple[PipelineStep, ...]] = {
    RequestMode.ASSET_UPDATE: (
        PipelineStep.EXTRACT_TRANSACTION_INTENT,
        PipelineStep.VALIDATE_EVENT_TIME,
        PipelineStep.ASSESS_AMBIGUITY_AND_IMPACT,
        PipelineStep.DECIDE_POSTING,
        PipelineStep.PROJECT_PERSONAL_STATE,
        PipelineStep.ADVANCE_STATE_VERSION,
    ),
    RequestMode.PERSONAL_PORTFOLIO_ANALYSIS: (
        PipelineStep.PIN_PERSONAL_STATE,
        PipelineStep.LIGHTWEIGHT_ALL_ASSETS,
        PipelineStep.APPLY_MATERIALITY_GATE,
        PipelineStep.DEEP_RESEARCH_SELECTED_ASSETS,
        PipelineStep.CALCULATE_ALLOCATION_AND_RISK,
        PipelineStep.CONDITIONAL_REVIEW,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
    RequestMode.SINGLE_ASSET_ANALYSIS: (
        PipelineStep.AUTO_PASS_REQUESTED_ASSETS,
        PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS,
        PipelineStep.CONDITIONAL_REVIEW,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
    RequestMode.ASSET_COMPARISON: (
        PipelineStep.AUTO_PASS_REQUESTED_ASSETS,
        PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS,
        PipelineStep.BUILD_COMPARISON,
        PipelineStep.CONDITIONAL_REVIEW,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
    RequestMode.PORTFOLIO_SCENARIO: (
        PipelineStep.PIN_PERSONAL_STATE,
        PipelineStep.BUILD_SCENARIO_BASELINE,
        PipelineStep.APPLY_MATERIALITY_GATE,
        PipelineStep.RUN_NON_POSTING_SCENARIO,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
    RequestMode.THESIS_REVIEW: (
        PipelineStep.LOAD_THESIS,
        PipelineStep.AUTO_PASS_REQUESTED_ASSETS,
        PipelineStep.COLLECT_LATEST_EVIDENCE,
        PipelineStep.REVIEW_THESIS,
        PipelineStep.CONDITIONAL_REVIEW,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
    RequestMode.REPORT_REFRESH: (
        PipelineStep.START_NEW_RUN_CLOCK,
        PipelineStep.PIN_PERSONAL_STATE,
        PipelineStep.REEXECUTE_REQUIRED_PIPELINE,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT,
    ),
}

PIPELINES = MappingProxyType(_PIPELINES)


class FixedPipelinePlanner:
    """Return a predefined plan and reject unsupported modes."""

    def __init__(self) -> None:
        if set(PIPELINES) != set(RequestMode):
            missing = set(RequestMode) - set(PIPELINES)
            extra = set(PIPELINES) - set(RequestMode)
            raise RuntimeError(f"Pipeline registry mismatch; missing={missing}, extra={extra}")

    def plan(self, mode: str | RequestMode) -> PipelinePlan:
        try:
            parsed = RequestMode.parse(mode)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return PipelinePlan(mode=parsed, steps=PIPELINES[parsed])

