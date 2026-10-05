"""Concrete single-asset and asset-comparison bundles over Phase 4/5/6 runtimes."""

from __future__ import annotations
from investment_stack.calculations.position_policy import POLICY_B_GUIDANCE

from dataclasses import asdict, replace
from decimal import Decimal
from datetime import datetime
import hashlib
import json
from itertools import combinations
from typing import Mapping
from uuid import uuid4

from investment_stack.calculations import BusinessType
from investment_stack.calculations.common import AnalysisStatus
from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.contracts.calculation import (
    CalculationRecord,
    DataAvailabilityStatus,
    GateDecision,
    InvestmentDecision,
    OutputKind,
)
from investment_stack.contracts.slots import EligibilityDecision, EligibilityStatus, SelectedInputSet
from investment_stack.decisions.briefing import (
    InstitutionalBriefingContext,
    NonPostingBriefing,
    generate_briefing,
)
from investment_stack.reporting.auxiliary_context import build_auxiliary_context_section
from investment_stack.reporting.technical_section import build_technical_report_section
from investment_stack.deep_research import EquityResearchOutcome, EquityResearchSpec, LiveDeepResearchRuntime, _observation_metrics
from investment_stack.evidence import RunDatabaseManager
from investment_stack.pipelines import PipelineStep
from investment_stack.reporting.models import Availability as ReportAvailability, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime, section_from_analysis_result
from investment_stack.review.models import ReviewContext, ReviewResult
from investment_stack.routing import RequestMode

from .dispatcher import RuntimeServices
from .models import Availability, ModeRequest, StepContext, StepResult


_CURRENCY_METRICS = frozenset({
    "revenue", "prior_revenue", "operating_income", "net_income", "cash_from_operations",
    "capex", "total_debt", "cash", "equity", "average_equity", "invested_capital",
    "current_assets", "current_liabilities", "ebitda", "enterprise_value", "market_cap",
})
_REFRESH_REPLAY_MODES = frozenset({RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.ASSET_COMPARISON})


def equity_analysis_services(
    *,
    deep_research: LiveDeepResearchRuntime,
    phase6: Phase6ReportReviewRuntime,
    run_db: RunDatabaseManager,
    asset_resolver=None,
    portfolio_context_loader=None,
) -> RuntimeServices:
    """Return concrete handlers for SINGLE_ASSET_ANALYSIS and ASSET_COMPARISON.

    Callers inject resolved typed equity specs and the already-created, pinned run
    database. The returned whitelist contains no personal-ledger writer.
    """
    if deep_research.analysis.run_db is not run_db or phase6.run_db is not run_db:
        raise ValueError("Phase 4/5/6 services must share the same run database")
    run_metadata = run_db.fetch_phase6_context()["run_metadata"]
    if (run_metadata.get("analysis_as_of") != deep_research.analysis_as_of
            or run_metadata.get("analysis_timezone") != deep_research.analysis_timezone):
        raise ValueError("Phase 4/5 analysis clock must match the pinned run clock")

    def resolve_specs(request: ModeRequest, _context: StepContext) -> StepResult:
        snapshot = run_db.fetch_phase6_context()
        metadata = snapshot["run_metadata"]
        pinned_mode = metadata.get("request_mode")
        replay_context = request.payload.get("refresh_context")
        replay_run_id = getattr(replay_context, "run_id", None)
        replay_clock = getattr(replay_context, "analysis_as_of", None)
        replay_timezone = getattr(replay_context, "analysis_timezone", None)
        replay_state_version = getattr(replay_context, "state_version", None)
        replay_state_ref = getattr(replay_context, "pinned_state_ref", None)
        pin = snapshot["pinned_personal_state"]
        valid_refresh_replay = bool(
            request.refresh_replay
            and request.mode in _REFRESH_REPLAY_MODES
            and pinned_mode == RequestMode.REPORT_REFRESH.value
            and request.run_id == run_db.run_id == replay_run_id
            and replay_clock == metadata.get("analysis_as_of") == deep_research.analysis_as_of
            and replay_timezone == metadata.get("analysis_timezone") == deep_research.analysis_timezone
            and pin is not None
            and replay_state_version is not None
            and int(pin.get("state_version") or 0) == replay_state_version
            and pin.get("portfolio_snapshot_id") == replay_state_ref
        )
        if pinned_mode != request.mode.value and not valid_refresh_replay:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                "run database request mode does not match the requested analysis mode or verified refresh replay",
            ))
        raw = request.payload.get("research_specs")
        if raw is None and asset_resolver is not None:
            try:
                raw = asset_resolver(request)
            except ValueError as exc:
                return StepResult(Availability.UNSUPPORTED,
                    unsupported_reasons=("asset_resolution_failed: " + str(exc),))
        expected = 1 if request.mode is RequestMode.SINGLE_ASSET_ANALYSIS else 2
        if not isinstance(raw, (tuple, list)) or len(raw) < expected:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                "resolved research_specs are required; comparison requires at least two assets",
            ))
        if request.mode is RequestMode.SINGLE_ASSET_ANALYSIS and len(raw) != 1:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                "SINGLE_ASSET_ANALYSIS requires exactly one resolved asset",
            ))
        if not all(isinstance(spec, EquityResearchSpec) for spec in raw):
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                "each asset must have a resolved EquityResearchSpec",
            ))
        specs = tuple(raw)
        if len({spec.instrument_id for spec in specs}) != len(specs):
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=("asset identities must be unique",))
        for spec in specs:
            if not all(isinstance(value, str) and value.strip() for value in (
                spec.instrument_id, spec.display_name, spec.country, spec.currency,
            )):
                return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                    "asset identity, market country, and currency must be resolved explicitly",
                ))
            if not isinstance(spec.business_type, BusinessType):
                return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                    f"{spec.instrument_id}: a supported business type must be selected explicitly",
                ))
        return StepResult(Availability.COMPLETE, output={"specs": specs})

    def research_assets(_request: ModeRequest, context: StepContext) -> StepResult:
        specs = context[PipelineStep.AUTO_PASS_REQUESTED_ASSETS.value].output["specs"]
        outcomes = tuple(deep_research.analyze_equity(spec) for spec in specs)
        if not outcomes:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=("no supported assets were analyzed",))
        from .stage_ledger import verified_equity_outputs
        integrity = verified_equity_outputs(run_db, outcomes)
        if integrity:
            return StepResult(Availability.FAILED, output={'outcomes': outcomes},
                              unsupported_reasons=integrity)
        refs = tuple(dict.fromkeys(eid for outcome in outcomes for eid in outcome.evidence_ids))
        calculation_refs = tuple(dict.fromkeys(
            str(result.metadata["calculation_id"])
            for outcome in outcomes
            for result in (outcome.analysis.fundamental, outcome.analysis.valuation)
            if result.metadata.get("calculation_id")
        ))
        missing = tuple(
            f"{outcome.instrument_id}: {name}"
            for outcome in outcomes
            for name, result in (("fundamental_analysis", outcome.analysis.fundamental),
                                 ("valuation_analysis", outcome.analysis.valuation))
            if result.status is not AnalysisStatus.COMPLETE
        )
        for outcome in outcomes:
            market_provider_statuses = {result.status.value for result in outcome.market.provider_results}
            fundamentals_provider_statuses = {result.status.value for result in outcome.fundamentals.provider_results}
            provider_statuses = market_provider_statuses | fundamentals_provider_statuses
            has_any_observations = any(
                result.observations
                for result in (*outcome.market.provider_results, *outcome.fundamentals.provider_results)
            )
            if not outcome.evidence_ids and not has_any_observations and (
                not provider_statuses or provider_statuses <= {"MISSING_CREDENTIAL", "DISABLED"}
            ):
                return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                    f"{outcome.instrument_id}: required research providers are not configured",
                ))
        return StepResult(
            Availability.PARTIAL if missing else Availability.COMPLETE,
            output={"outcomes": outcomes}, evidence_refs=refs,
            calculation_refs=calculation_refs, missing_inputs=missing,
        )

    def pairwise_comparison(_request: ModeRequest, context: StepContext) -> StepResult:
        research = context[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS.value]
        if research.availability is Availability.UNSUPPORTED:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=research.unsupported_reasons)
        outcomes: tuple[EquityResearchOutcome, ...] = research.output["outcomes"]
        specs: tuple[EquityResearchSpec, ...] = context[PipelineStep.AUTO_PASS_REQUESTED_ASSETS.value].output["specs"]
        by_id = {outcome.instrument_id: outcome for outcome in outcomes}
        spec_by_id = {spec.instrument_id: spec for spec in specs}

        def periods(outcome: EquityResearchOutcome) -> tuple[str, ...]:
            found = {
                str(observation.metadata.get("period_end"))
                for observation in outcome.fundamentals.selected.selected_observations
                if observation.evidence_type == "financial" and observation.metadata.get("period_end")
            }
            return tuple(sorted(found))

        def reporting_context(outcome: EquityResearchOutcome) -> dict[str, list[str]]:
            """Collect the period and accounting dimensions of selected financial facts."""
            observations = tuple(
                observation
                for observation in outcome.fundamentals.selected.selected_observations
                if observation.evidence_type == "financial"
            )
            aliases = {
                "period_end": ("period_end", "end"),
                "period_start": ("start",),
                "reporting_frequency": ("reporting_frequency", "form"),
                "reporting_period": ("reporting_period", "fp"),
                "accounting_standard": ("accounting_standard", "basis"),
                "consolidation": ("consolidation",),
                "adjustment_basis": ("adjustment_basis",),
                "restatement": ("restatement",),
            }
            collected: dict[str, set[str]] = {name: set() for name in aliases}
            for observation in observations:
                metadata = observation.metadata
                for name, keys in aliases.items():
                    value = next((metadata.get(key) for key in keys if metadata.get(key) not in (None, "")), None)
                    if value is not None:
                        collected[name].add(str(value).strip().upper())
            return {name: sorted(values) for name, values in collected.items()}

        context_aliases = {
            "period_end": ("period_end", "end"),
            "period_start": ("start",),
            "reporting_frequency": ("reporting_frequency", "form"),
            "reporting_period": ("reporting_period", "fp"),
            "accounting_standard": ("accounting_standard", "basis"),
            "consolidation": ("consolidation",),
            "adjustment_basis": ("adjustment_basis",),
            "restatement": ("restatement",),
        }
        required_context = tuple(context_aliases)

        def context_signature(metadata) -> tuple[str, ...] | None:
            values = []
            for keys in context_aliases.values():
                value = next((metadata.get(key) for key in keys if metadata.get(key) not in (None, "")), None)
                if value is None:
                    return None
                values.append(str(value).strip().upper())
            return tuple(values)

        def metric_contexts(outcome: EquityResearchOutcome) -> dict[str, set[tuple[str, ...] | None]]:
            contexts: dict[str, set[tuple[str, ...] | None]] = {}
            for observation in outcome.fundamentals.selected.selected_observations:
                if observation.evidence_type != "financial":
                    continue
                signature = context_signature(observation.metadata)
                for canonical, _value in _observation_metrics(observation):
                    contexts.setdefault(canonical, set()).add(signature)
            return contexts

        rows = []
        all_compatible = True
        all_analyses_complete = True
        for left_id, right_id in combinations((spec.instrument_id for spec in specs), 2):
            left_spec, right_spec = spec_by_id[left_id], spec_by_id[right_id]
            left_periods, right_periods = periods(by_id[left_id]), periods(by_id[right_id])
            period_compatible = len(left_periods) == len(right_periods) == 1 and left_periods == right_periods
            left_context = reporting_context(by_id[left_id])
            right_context = reporting_context(by_id[right_id])
            context_well_formed = all(
                len(left_context[name]) == 1 and len(right_context[name]) == 1
                for name in required_context
            ) and all(len(values) == 1 for values in (left_context["period_end"], right_context["period_end"]))
            reporting_context_compatible = context_well_formed and left_context == right_context
            currency_compatible = left_spec.currency.upper() == right_spec.currency.upper()
            type_compatible = left_spec.business_type is right_spec.business_type
            missing_side = any(
                result.status is not AnalysisStatus.COMPLETE
                for outcome in (by_id[left_id], by_id[right_id])
                for result in (outcome.analysis.fundamental, outcome.analysis.valuation)
            )
            reasons = []
            if not period_compatible:
                reasons.append("financial periods are missing or differ")
            if not reporting_context_compatible:
                reasons.append("financial reporting frequency, period start, or accounting basis differs or is ambiguous")
            if not currency_compatible:
                reasons.append("currencies differ")
            if not type_compatible:
                reasons.append("business types differ")
            if missing_side:
                reasons.append("one or both asset analyses are incomplete")
            compatible = period_compatible and reporting_context_compatible and currency_compatible and type_compatible
            all_compatible = all_compatible and compatible
            all_analyses_complete = all_analyses_complete and not missing_side
            rows.append({
                "asset_a": left_id, "asset_b": right_id,
                "periods_a": list(left_periods), "periods_b": list(right_periods),
                "period_compatible": period_compatible,
                "reporting_context_a": left_context, "reporting_context_b": right_context,
                "reporting_context_compatible": reporting_context_compatible,
                "currency_compatible": currency_compatible,
                "type_compatible": type_compatible,
                "compatible": compatible, "analysis_complete": not missing_side,
                "reasons": reasons,
            })

        comparisons = []
        metric_context_checks: dict[str, dict[str, object]] = {}
        if all_compatible:
            comparison_values = []
            per_asset_contexts = [metric_contexts(outcome) for outcome in outcomes]
            for outcome in outcomes:
                values: dict[str, Decimal] = dict(outcome.normalized_metrics)
                values.update({
                    f"valuation.{metric.name}": metric.value
                    for metric in outcome.analysis.valuation.metrics
                    if metric.value is not None
                })
                comparison_values.append(values)
            metric_sets = [set(values) for values in comparison_values]
            common_metrics = sorted(set.intersection(*metric_sets)) if metric_sets else []
            valuation_dependencies = {
                "valuation.pe": ("eps",),
                "valuation.pb": ("equity", "shares_outstanding"),
                "valuation.ev_to_ebitda": ("total_debt", "cash", "shares_outstanding", "ebitda"),
                "valuation.price_to_sales": ("shares_outstanding", "revenue"),
                "valuation.dividend_yield": ("dividend_per_share",),
            }
            for metric_name in common_metrics:
                values = [asset_values[metric_name] for asset_values in comparison_values]
                if metric_name in _CURRENCY_METRICS and len({spec.currency.upper() for spec in specs}) != 1:
                    continue
                dependencies = valuation_dependencies.get(metric_name, (metric_name,))
                signatures = []
                context_reason = None
                for asset_contexts in per_asset_contexts:
                    for dependency in dependencies:
                        found = asset_contexts.get(dependency, set())
                        if len(found) != 1 or None in found:
                            context_reason = f"missing or conflicting context for {dependency}"
                            break
                        signatures.extend(found)
                    if context_reason:
                        break
                if context_reason is None and len(set(signatures)) != 1:
                    context_reason = "metric source contexts differ across assets or inputs"
                metric_context_checks[metric_name] = {
                    "compatible": context_reason is None,
                    "dependencies": list(dependencies),
                    "reason": context_reason,
                }
                if context_reason is not None:
                    continue
                if all(isinstance(value, Decimal) and value.is_finite() for value in values):
                    comparisons.append({
                        "metric": metric_name,
                        "values_by_asset": {outcome.instrument_id: str(value) for outcome, value in zip(outcomes, values)},
                        "delta_vs_first_requested": {
                            outcome.instrument_id: str(value - values[0])
                            for index, (outcome, value) in enumerate(zip(outcomes, values)) if index
                        },
                    })
        metric_context_complete = all(item["compatible"] for item in metric_context_checks.values())
        if not metric_context_complete:
            for row in rows:
                row["metric_context_compatible"] = False
                row["reasons"].append("one or more metric comparisons lack complete matching source context")
        else:
            for row in rows:
                row["metric_context_compatible"] = True
        matrix = {
            "assets": [{
                "instrument_id": spec.instrument_id,
                "currency": spec.currency.upper(),
                "business_type": spec.business_type.value,
                "financial_periods": list(periods(by_id[spec.instrument_id])),
                "financial_reporting_context": reporting_context(by_id[spec.instrument_id]),
            } for spec in specs],
            "pairwise_compatibility": rows,
            "complete": all_compatible and metric_context_complete,
            "metric_context_checks": metric_context_checks,
            "asset_analyses_complete": all_analyses_complete,
            "ranking_emitted": False,
            "ranking_reason": None if all_compatible and metric_context_complete else "comparison compatibility matrix or metric-level source contexts are incomplete; no total ranking was produced",
        }
        calculation_id = f"calc:comparison:{uuid4().hex}"
        run_db = deep_research.analysis.run_db
        run_db.add_calculation(
            calculation_id=calculation_id,
            calculation_name="asset_comparison",
            formula="compatible_asset_metrics_side_by_side_v1",
            inputs={
                "compatibility_matrix": matrix,
                "evidence_ids": list(research.evidence_refs),
                "source_calculation_ids": list(research.calculation_refs),
            },
            result={"comparisons": comparisons, "ranking_emitted": False,
                    "metric_context_checks": metric_context_checks},
        )
        missing_values = []
        if not all_compatible:
            missing_values.append("complete_period_currency_business_type_compatibility_matrix")
        if not metric_context_complete:
            missing_values.append("complete_metric_level_reporting_context")
        if not all_analyses_complete:
            missing_values.append("complete_asset_analysis_data")
        return StepResult(
            Availability.COMPLETE if all_compatible and all_analyses_complete else Availability.PARTIAL,
            output={"compatibility_matrix": matrix, "comparisons": comparisons,
                    "ranking_emitted": False, "calculation_id": calculation_id},
            evidence_refs=research.evidence_refs,
            calculation_refs=(*research.calculation_refs, calculation_id),
            missing_inputs=tuple(missing_values),
        )

    def conditional_review(_request: ModeRequest, context: StepContext) -> StepResult:
        from investment_stack.execution.capital_context import render_optional_capital_context
        outcomes=context[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS.value].output.get('outcomes',())
        candidates=tuple(o.instrument_id for o in outcomes)
        capital=render_optional_capital_context(run_db,_request,portfolio_context_loader,candidates)
        capital_sections=(capital,) if isinstance(capital,ReportSectionInput) else capital.sections if capital else ()
        triggers=capital.review_triggers if capital and not isinstance(capital,ReportSectionInput) else ()
        subjects=tuple(row.instrument_id for row in (*capital.result.ranked,*capital.result.unranked)) if triggers else ()
        evidence_ids = tuple(dict.fromkeys(
            evidence_id for result in context.values() for evidence_id in result.evidence_refs
        ))
        review_result = phase6.review.evaluate(ReviewContext(critical_evidence_ids=evidence_ids,large_net_worth_impact=bool(triggers)))
        from investment_stack.review.adversarial import review_valuation_outputs
        review_result = review_valuation_outputs(run_db, review_result,required_subjects=subjects,review_triggers=triggers)
        from investment_stack.reporting.adversarial import adversarial_sections
        sections = (*capital_sections,*adversarial_sections(run_db))
        partial=tuple(s.name+':review_data_gaps' for s in sections if s.status is not ReportAvailability.AVAILABLE)
        return StepResult(Availability.PARTIAL if partial else Availability.COMPLETE, output={"review": review_result, "sections": sections},
                          evidence_refs=tuple(dict.fromkeys(e for s in sections for e in s.evidence_ids)),
                          calculation_refs=tuple(c for s in sections for c in s.calculation_ids),missing_inputs=partial)

    def render_report(request: ModeRequest, context: StepContext) -> StepResult:
        research = context[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS.value]
        outcomes: tuple[EquityResearchOutcome, ...] = research.output["outcomes"]
        run_snapshot = run_db.fetch_phase6_context()
        pinned_clock = run_snapshot["run_metadata"].get("analysis_as_of")
        try:
            section_as_of = datetime.fromisoformat(str(pinned_clock).replace("Z", "+00:00"))
            if section_as_of.tzinfo is None:
                section_as_of = None
        except (TypeError, ValueError):
            section_as_of = None
        sections: list[ReportSectionInput] = []
        sections.extend(context[PipelineStep.CONDITIONAL_REVIEW.value].output.get("sections", ()))
        unverified_outputs: list[str] = []
        technical_sections: list[tuple[str, ReportSectionInput]] = []
        technical_sources = request.payload.get("technical_analysis")
        from investment_stack.reporting.news_delta import news_delta_section
        for outcome in outcomes:
            if outcome.news is not None:
                sections.append(news_delta_section(run_db, outcome.instrument_id))
            fundamental_section = _validated_analysis_section(
                outcome.analysis.fundamental,
                name=f"{outcome.instrument_id}_fundamental",
                title=f"{outcome.instrument_id} Fundamentals",
                stored_calculations=run_snapshot["calculations"],
                run_id=run_db.run_id,
            )
            if not fundamental_section.metadata.get("numeric_output_verified"):
                unverified_outputs.append(f"{outcome.instrument_id}:fundamental")
            sections.append(fundamental_section)
            valuation_result = outcome.analysis.valuation
            last_close_note = _persisted_last_valid_close_note(
                outcome, run_snapshot, run_id=run_db.run_id,
            )
            validation_result = valuation_result
            if last_close_note and valuation_result.findings and valuation_result.findings[-1] == last_close_note:
                # deep_research appends this separately verifiable market note after
                # Phase 5 persisted the calculation. Remove only the exact note we
                # can independently reconstruct from persisted run-local records.
                validation_result = replace(
                    valuation_result, findings=valuation_result.findings[:-1],
                )
            valuation_section = _validated_analysis_section(
                validation_result,
                name=f"{outcome.instrument_id}_valuation",
                title=f"{outcome.instrument_id} Valuation",
                stored_calculations=run_snapshot["calculations"],
                run_id=run_db.run_id,
            )
            if not valuation_section.metadata.get("numeric_output_verified"):
                unverified_outputs.append(f"{outcome.instrument_id}:valuation")
            # This runtime exposes model outputs for analysis, not policy-approved
            # entry prices. Keep assumptions-based values visibly conditional.
            if valuation_section.metadata.get("numeric_output_verified"):
                dcf_output_names = (
                    "dcf_scenario_", "dcf_value_per_share", "dcf_sensitivity_",
                    "high_growth_scenario", "scenario_",
                )
                has_scenario_value = any(
                    metric.value is not None and metric.name.startswith(dcf_output_names)
                    for metric in outcome.analysis.valuation.metrics
                )
                valuation_notes = [
                    (
                        "해석 제한: 유효 DCF/시나리오 결과는 명시 가정에 따른 조건부 가치이며 확정 적정가나 추가매수 기준이 아닙니다."
                        if has_scenario_value else
                        "DCF 가정 또는 근거가 연결된 유효 시나리오가 없어 적정가 범위를 산출하지 않았습니다."
                    ),
                    POLICY_B_GUIDANCE,
                    "적용 제한: 같은 시점의 개인 상태·적격 현재가·통화·거래 비용이 없으면 실행 가능한 진입가·금액·수량은 계산하지 않습니다.",
                    "브리핑 제한: 가격·가치 숫자에는 독립 검증 가능한 eligibility receipt와 종목 결속이 없어 최종 판단 브리핑에서 숨깁니다.",
                    f"기준시각: {section_as_of.isoformat()}" if section_as_of else "기준시각: 확인 불가",
                ]
                if last_close_note:
                    valuation_notes.append(last_close_note)
                valuation_notes.append(
                    "B 정책 진입 가격은 대기: DCF 가정값만으로는 기준 적정가·개인 상태·거래 비용을 결속할 수 없습니다."
                )
            else:
                valuation_notes = [
                    "저장 결과 검증 실패: 분석 본문·metric 또는 근거가 run.db와 일치하지 않아 내용을 숨겼습니다."
                ]
            sections.append(replace(valuation_section, lines=(*valuation_section.lines, *valuation_notes)))
            if isinstance(technical_sources, Mapping) and outcome.instrument_id in technical_sources:
                supplied = technical_sources[outcome.instrument_id]
                parsed = supplied.get("parse_result") if isinstance(supplied, Mapping) else None
                technical_result = supplied.get("analysis") if isinstance(supplied, Mapping) else None
                technical_section = build_technical_report_section(
                    parse_result=parsed, analysis=technical_result,
                    expected_instrument_id=outcome.instrument_id, run_db=run_db,
                )
                technical_section = replace(
                    technical_section, name=f"{outcome.instrument_id}_technical",
                    title=f"{outcome.instrument_id} 기술적 분석",
                )
                sections.append(technical_section)
                technical_sections.append((outcome.instrument_id, technical_section))
            sections.append(build_auxiliary_context_section(
                request.mode.value, outcome.instrument_id, run_db,
            ))
        comparison = context.get(PipelineStep.BUILD_COMPARISON.value)
        if comparison is not None:
            matrix = comparison.output["compatibility_matrix"]
            lines = [f"Compatibility complete: {matrix['complete']}", "Total ranking emitted: false"]
            lines.extend(
                f"{row['asset_a']} vs {row['asset_b']}: {'compatible' if row['compatible'] else '; '.join(row['reasons'])}"
                for row in matrix["pairwise_compatibility"]
            )
            for item in comparison.output["comparisons"]:
                lines.append(f"{item['metric']}: " + ", ".join(
                    f"{asset}={value}" for asset, value in item["values_by_asset"].items()
                ))
            sections.append(ReportSectionInput(
                name="asset_comparison", title="Pairwise Compatibility and Comparison",
                lines=tuple(lines),
                status=(ReportAvailability.AVAILABLE
                        if matrix["complete"] and matrix["asset_analyses_complete"]
                        else ReportAvailability.PARTIAL),
                evidence_ids=tuple(dict.fromkeys(comparison.evidence_refs)),
                calculation_ids=tuple(dict.fromkeys(comparison.calculation_refs)),
                metadata={"compatibility_matrix": matrix, "ranking_emitted": False},
            ))
        review = context[PipelineStep.CONDITIONAL_REVIEW.value].output["review"]
        if not isinstance(review, ReviewResult):
            return StepResult(Availability.FAILED, output={"review_type": type(review).__name__})
        pinned_clock = run_snapshot["run_metadata"].get("analysis_as_of")
        try:
            briefing_as_of = datetime.fromisoformat(str(pinned_clock).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            briefing_as_of = None
        if briefing_as_of is not None and briefing_as_of.tzinfo is None:
            briefing_as_of = None
        evidence_ids = {row["evidence_id"] for row in run_snapshot["evidence"]}
        calculation_ids = {row["calculation_id"] for row in run_snapshot["calculations"]}
        pin = run_snapshot["pinned_personal_state"]
        briefings: list[tuple[str, NonPostingBriefing]] = []
        sources = request.payload.get("briefing_contexts", {})
        for outcome in outcomes:
            source = sources.get(outcome.instrument_id) if isinstance(sources, Mapping) else None
            selected_inputs = source.get("selected_inputs") if isinstance(source, Mapping) else None
            calculations = source.get("calculations", {}) if isinstance(source, Mapping) else {}
            eligibility = source.get("eligibility_decisions", {}) if isinstance(source, Mapping) else {}
            registered_gates = source.get("registered_gates", ()) if isinstance(source, Mapping) else ()
            source_bound = (
                isinstance(selected_inputs, SelectedInputSet)
                and selected_inputs.run_id == run_db.run_id
                and selected_inputs.instrument_id == outcome.instrument_id
                and selected_inputs.verify_hash()
                and all(slot.evidence_id in evidence_ids for slot in selected_inputs.slots)
                and isinstance(calculations, Mapping)
                and all(isinstance(record, CalculationRecord)
                        and record.run_id == run_db.run_id
                        and record.selection_snapshot_hash == selected_inputs.snapshot_hash
                        and record.calculation_id in calculation_ids
                        for record in calculations.values())
                and isinstance(eligibility, Mapping)
                and all(isinstance(item, EligibilityDecision) for item in eligibility.values())
                and isinstance(registered_gates, tuple)
                and all(isinstance(gate, GateDecision) for gate in registered_gates)
                and briefing_as_of is not None
            )
            if source_bound:
                has_price = any(
                    decision.status is EligibilityStatus.ELIGIBLE
                    and decision.purpose.upper() == "CURRENT_PRICE"
                    and any(slot.eligibility_id == eligibility_id for slot in selected_inputs.slots)
                    for eligibility_id, decision in eligibility.items()
                )
                has_personal_snapshot = bool(
                    pin is not None
                    and int(pin.get("state_version") or 0) > 0
                    and pin.get("portfolio_snapshot_id")
                    and request.payload.get("pinned_state_version") == int(pin["state_version"])
                    and request.payload.get("pinned_snapshot_ref") == pin.get("portfolio_snapshot_id")
                )
            else:
                # No source is displayed unless its typed selection, calculations,
                # run identity, clock, and persisted evidence are all bound.
                selected_inputs = SelectedInputSet.create(
                    run_db.run_id, "EQUITY_BRIEFING", 1, (), instrument_id=outcome.instrument_id,
                )
                calculations, eligibility, registered_gates = {}, {}, ()
                has_price = has_personal_snapshot = False
            chart_lines = tuple(
                line for _, section in technical_sections
                if section.name.startswith(f"{outcome.instrument_id}_")
                and section.status is ReportAvailability.AVAILABLE
                for line in section.lines[:2]
            )
            if chart_lines:
                chart_lines = ("차트 지표는 저장된 봉과 재계산이 일치할 때만 표시하며 매매 수량이 아닙니다.", *chart_lines)
            institutional = source.get("institutional_context") if isinstance(source, Mapping) else None
            briefing = generate_briefing(
                selected_inputs, calculations, has_price=has_price,
                # D12 B is user-selected, but policy adoption does not verify
                # request-supplied price, valuation, or personal sizing inputs.
                has_policy=True, has_personal_snapshot=has_personal_snapshot,
                # Request-supplied typed records are not yet value-matched to the
                # persisted run.db calculation/eligibility payloads. Their IDs alone
                # cannot authorize a user-visible number in the final report.
                eligibility_decisions=None, analysis_as_of=briefing_as_of,
                registered_gates=registered_gates,
                institutional_context=institutional if isinstance(institutional, InstitutionalBriefingContext) else None,
                chart_lines=chart_lines,
            )
            # Incomplete analysis must leave the user with an explicit safe wait.
            if briefing.decision is not InvestmentDecision.WAIT:
                briefing = replace(
                    briefing, decision=InvestmentDecision.WAIT,
                    section_judgement="대기 — D12 B 정책은 확정됐지만 적격 가격·가치와 같은 시점의 개인 상태가 결속될 때까지 행동을 보류합니다.",
                    section_conditions=(
                        "같은 실행의 적격 가격·가치평가 계산과 근거가 결속되면 다시 평가합니다.",
                        "D12 B 정책과 같은 시점의 개인 상태·통화·비용이 확인되기 전에는 규모를 계산하지 않습니다.",
                    ),
                )
            briefing = replace(briefing, section_details=tuple(dict.fromkeys((
                *briefing.section_details,
                POLICY_B_GUIDANCE,
            ))))
            if not source_bound:
                briefing = replace(briefing, section_details=tuple(dict.fromkeys((
                    *briefing.section_details,
                    "브리핑 근거가 이 run의 typed selection·계산·evidence에 결속되지 않아 수치를 표시하지 않았습니다.",
                ))))
            else:
                # Persisted equality alone is insufficient: this request path has
                # no independently verifiable eligibility policy receipt bound to
                # the same instrument and cutoff, so user-visible numbers stay off.
                briefing = replace(briefing, section_details=tuple(dict.fromkeys((
                    *briefing.section_details,
                    "run.db 값 일치만으로는 적격성·종목·고정 cutoff 결속을 검증할 수 없어 가격·가치평가 수치를 표시하지 않았습니다.",
                ))))
            briefings.append((outcome.instrument_id, briefing))
        briefing = _combine_briefings(tuple(briefings))
        if technical_sections:
            technical_core = tuple(
                f"{instrument_id} 차트: " + (
                    "검증된 지표를 기술적 분석 섹션에 표시했습니다. 매매 신호나 규모 판단에는 사용하지 않았습니다."
                    if section.status is not ReportAvailability.UNAVAILABLE else
                    "자료와 실행 기록의 연결을 확인하지 못해 지표를 표시하지 않았습니다."
                )
                for instrument_id, section in technical_sections
            )
            briefing = replace(briefing, section_core=(*briefing.section_core, *technical_core))
        report = phase6.report.build(
            title=str(request.payload.get("title") or _default_title(request)),
            sections=tuple(sections), review=review, briefing=briefing,
        )
        briefing_section_id = None
        if report.briefing:
            briefing_payload = {
                "title": "최종 판단 브리핑",
                "analysis_as_of": report.as_of.analysis_as_of,
                "rendered_markdown": report.briefing,
                "typed_briefing": asdict(briefing),
            }
            canonical_briefing = json.dumps(
                briefing_payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"),
            )
            briefing_digest = hashlib.sha256(canonical_briefing.encode("utf-8")).hexdigest()
            briefing_section_id = f"section:final_briefing:{run_db.run_id}:{briefing_digest}"
            run_db.upsert_report_section(
                section_id=briefing_section_id,
                section_name="final_briefing",
                section_status=briefing.status.value,
                content_reference=f"inline-sha256:{briefing_digest}",
                metadata=briefing_payload,
            )
        expected_sections = {section.name: section for section in report.sections}
        refs = report.persisted_section_refs
        if (
            len(refs) != len(expected_sections)
            or len({name for name, _, _ in refs}) != len(refs)
            or {name for name, _, _ in refs} != set(expected_sections)
            or len({section_id for _, section_id, _ in refs}) != len(refs)
        ):
            return StepResult(Availability.FAILED, output={"report_persisted": False})
        stored_sections = run_db.fetch_phase6_context()["report_sections"]
        stored_by_id = {row["section_id"]: row for row in stored_sections}
        persisted_sections = []
        for name, section_id, content_ref in refs:
            row = stored_by_id.get(section_id)
            section = expected_sections[name]
            if row is None or row["section_name"] != name or row["section_status"] != section.status.value:
                return StepResult(Availability.FAILED, output={"report_persisted": False})
            try:
                payload = json.loads(row["metadata_json"] or "")
                canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
                expected_ref = "inline-sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            except (TypeError, ValueError):
                return StepResult(Availability.FAILED, output={"report_persisted": False})
            if (
                row["content_reference"] != content_ref
                or content_ref != expected_ref
                or payload.get("title") != section.title
                or payload.get("lines") != list(section.lines)
                or payload.get("evidence_ids") != list(section.evidence_ids)
                or payload.get("calculation_ids") != list(section.calculation_ids)
                or payload.get("section_status") != section.status.value
                or payload.get("analysis_as_of") != report.as_of.analysis_as_of
            ):
                return StepResult(Availability.FAILED, output={"report_persisted": False})
            persisted_sections.append(row)
        if briefing_section_id is not None:
            stored_briefing = next((row for row in stored_sections if row["section_id"] == briefing_section_id), None)
            if stored_briefing is None:
                return StepResult(Availability.FAILED, output={"briefing_persisted": False})
            persisted_sections.append(stored_briefing)
        manifest = {
            "title": report.title,
            "availability": report.availability.value,
            "analysis_as_of": report.as_of.analysis_as_of,
            "section_refs": [
                {"section_name": row["section_name"], "content_reference": row["content_reference"]}
                for row in sorted(persisted_sections, key=lambda row: row["section_name"])
            ],
        }
        canonical_manifest = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(canonical_manifest.encode("utf-8")).hexdigest()
        report_ref = f"run-report:{run_db.run_id}:sha256:{digest}"
        run_db.record_task_state(
            task_name=f"report:{digest}",
            task_status=report.availability.value,
            metadata={"report_ref": report_ref, **manifest},
        )
        partial = (report.availability is not ReportAvailability.AVAILABLE
                   or research.availability is Availability.PARTIAL or bool(unverified_outputs))
        comparison_partial = comparison is not None and comparison.availability is Availability.PARTIAL
        status = Availability.PARTIAL if partial or comparison_partial else Availability.COMPLETE
        missing = []
        if research.availability is Availability.PARTIAL:
            missing.extend(research.missing_inputs)
        missing.extend(f"unverified_analysis_result:{item}" for item in unverified_outputs)
        if comparison_partial and comparison is not None:
            missing.extend(comparison.missing_inputs)
        if status is Availability.PARTIAL and not missing:
            missing.append("partial_report_data_quality")
        return StepResult(
            status, output={"report": report, "report_availability": report.availability.value},
            evidence_refs=research.evidence_refs,
            calculation_refs=tuple(dict.fromkeys(
                (*research.calculation_refs,
                 *(comparison.calculation_refs if comparison else ()))
            )), report_refs=(report_ref,), missing_inputs=tuple(dict.fromkeys(missing)),
        )

    handlers = {
        PipelineStep.AUTO_PASS_REQUESTED_ASSETS: resolve_specs,
        PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS: research_assets,
        PipelineStep.CONDITIONAL_REVIEW: conditional_review,
        PipelineStep.RENDER_PARTIAL_AWARE_REPORT: render_report,
        PipelineStep.BUILD_COMPARISON: pairwise_comparison,
    }
    return RuntimeServices(handlers=handlers, run_db=run_db)


def _validated_analysis_section(
    result, *, name: str, title: str, stored_calculations: tuple[dict[str, object], ...], run_id: str,
) -> ReportSectionInput:
    """Render Phase 5 output only when it exactly matches its run-local ledger row."""
    calculation_id = result.metadata.get("calculation_id")
    matches = [
        row for row in stored_calculations
        if row.get("calculation_id") == calculation_id
        and row.get("run_id") == run_id
    ] if isinstance(calculation_id, str) and calculation_id else []
    reason = "저장된 run.db 계산 결과와 분석 결과의 일치 여부를 검증할 수 없어 수치를 숨겼습니다."
    if len(matches) != 1:
        return ReportSectionInput(
            name=name, title=title, lines=(reason,), status=ReportAvailability.UNAVAILABLE,
            metadata={"subject": result.subject, "analysis_type": result.analysis_type,
                      "numeric_output_verified": False},
        )

    row = matches[0]
    expected_inputs = {
        "subject": result.subject,
        "evidence_ids": sorted({evidence_id for metric in result.metrics for evidence_id in metric.evidence_ids}),
        "dcf_assumption_value_bindings": result.metadata.get("dcf_assumption_value_bindings", []),
    }
    expected_result = json.loads(json.dumps(
        Phase5AssetAnalysisRuntime._jsonable(result), sort_keys=True, default=str,
        separators=(",", ":"),
    ))
    if isinstance(expected_result.get("metadata"), dict):
        expected_result["metadata"].pop("calculation_id", None)
    try:
        stored_inputs = json.loads(str(row.get("inputs_json") or ""))
        stored_result = json.loads(str(row.get("result_json") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        stored_inputs = stored_result = None
    if row.get("calculation_name") != result.analysis_type or stored_inputs != expected_inputs or stored_result != expected_result:
        return ReportSectionInput(
            name=name, title=title, lines=(reason,), status=ReportAvailability.PARTIAL,
            metadata={"subject": result.subject, "analysis_type": result.analysis_type,
                      "numeric_output_verified": False},
        )
    section = section_from_analysis_result(result, name=name, title=title)
    return replace(section, metadata={**section.metadata, "numeric_output_verified": True})


def _persisted_last_valid_close_note(outcome, snapshot: Mapping[str, object], *, run_id: str) -> str | None:
    """Rebuild the non-live close note from selected, persisted run-local records."""
    selected = outcome.market.selected
    evidence_id = selected.evidence_id
    selected_observation = selected.observation
    selected_freshness = selected.freshness
    if (
        not isinstance(evidence_id, str) or not evidence_id
        or selected_observation is None or selected_freshness is None
        or selected_observation.evidence_type != "market"
        or selected_observation.metric != "current_price"
        or selected_observation.instrument_id != outcome.instrument_id
        or selected_freshness.status.value != "LAST_VALID_CLOSE"
    ):
        return None
    evidence_rows = [
        row for row in snapshot.get("evidence", ())
        if row.get("run_id") == run_id and row.get("evidence_id") == evidence_id
        and row.get("instrument_id") == outcome.instrument_id
        and row.get("evidence_type") == "market"
        and row.get("metric") == "current_price"
        and row.get("selection_state") == "SELECTED"
        and row.get("freshness_status") == "LAST_VALID_CLOSE"
    ]
    observations = [
        row for row in snapshot.get("market_observations", ())
        if row.get("run_id") == run_id and row.get("evidence_id") == evidence_id
        and row.get("instrument_id") == outcome.instrument_id
        and row.get("freshness_status") == "LAST_VALID_CLOSE"
    ]
    assessments = [
        row for row in snapshot.get("freshness_assessments", ())
        if row.get("run_id") == run_id and row.get("evidence_id") == evidence_id
    ]
    if (
        len(evidence_rows) != 1 or len(observations) != 1 or len(assessments) != 1
        or assessments[0].get("status") != "LAST_VALID_CLOSE"
        or selected.observation_id is None
    ):
        return None
    evidence, observation, assessment = evidence_rows[0], observations[0], assessments[0]
    try:
        details = json.loads(str(assessment.get("details_json") or ""))
        observation_metadata = json.loads(str(observation.get("metadata_json") or "{}"))
        evidence_value = json.loads(str(evidence.get("value_text") or ""))
        run_metadata = snapshot.get("run_metadata", {})
        cutoff_text = run_metadata.get("analysis_as_of") if isinstance(run_metadata, Mapping) else None
        cutoff = datetime.fromisoformat(str(cutoff_text).replace("Z", "+00:00"))
        public_at = datetime.fromisoformat(str(details.get("public_available_time")).replace("Z", "+00:00"))
        effective_at = datetime.fromisoformat(str(details.get("effective_time")).replace("Z", "+00:00"))
        observed_at = datetime.fromisoformat(str(observation.get("observed_at")).replace("Z", "+00:00"))
        claimed_at = datetime.fromisoformat(str(observation.get("claimed_market_time")).replace("Z", "+00:00"))
        persisted_value = Decimal(str(evidence_value))
        selected_value = Decimal(str(selected_observation.value))
        market_value = Decimal(str(observation.get("value_numeric")))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    session_date = details.get("market_session_date")
    public_time = details.get("public_available_time")
    calendar_id = details.get("calendar_id")
    currency = observation.get("currency") or evidence.get("currency")
    claimed_time = observation.get("claimed_market_time")
    freshness_projection = {
        "effective_time": selected_freshness.effective_time,
        "age_seconds": selected_freshness.age_seconds,
        "reason": selected_freshness.reason,
        "market_session_date": selected_freshness.market_session_date,
        "quote_kind": selected_freshness.quote_kind,
        "calendar_id": selected_freshness.calendar_id,
        "public_available_time": selected_freshness.public_available_time,
    }
    if (
        cutoff.tzinfo is None or public_at.tzinfo is None or effective_at.tzinfo is None
        or observed_at.tzinfo is None or claimed_at.tzinfo is None
        or any(timestamp > cutoff for timestamp in (public_at, effective_at, observed_at, claimed_at))
        or details != freshness_projection
        or observation.get("observation_id") != selected.observation_id
        or selected_observation.currency != (observation.get("currency") or evidence.get("currency"))
        or selected_observation.unit != observation.get("unit")
        or selected_observation.claimed_market_time != claimed_time
        or selected_observation.market_session_date != observation.get("market_session_date")
        or selected_observation.observed_at != observation.get("observed_at")
        or selected_observation.provider_id != observation.get("provider_id")
        or selected_observation.metadata != observation_metadata
        or selected_value != persisted_value or market_value != persisted_value
        or evidence.get("observed_at") != observation.get("observed_at")
        or selected_freshness.effective_time != details.get("effective_time")
    ):
        return None
    if not all(isinstance(value, str) and value for value in (
        session_date, public_time, calendar_id, currency, claimed_time,
    )):
        return None
    return (
        f"가격 입력 기준: {session_date} 마지막 유효 거래일 종가 ({currency}); "
        f"종가 시각 {claimed_time}; 공개시각 {public_time}; 달력 {calendar_id}. 실시간 시세가 아닙니다."
    )


def _default_title(request: ModeRequest) -> str:
    return "Single Asset Analysis" if request.mode is RequestMode.SINGLE_ASSET_ANALYSIS else "Asset Comparison"


def _combine_briefings(briefings: tuple[tuple[str, NonPostingBriefing], ...]) -> NonPostingBriefing:
    if len(briefings) == 1:
        return briefings[0][1]
    status = (DataAvailabilityStatus.UNAVAILABLE
              if any(item.status is DataAvailabilityStatus.UNAVAILABLE for _, item in briefings)
              else DataAvailabilityStatus.PARTIAL)
    table = {
        f"{instrument_id} · {key}": value
        for instrument_id, briefing in briefings
        for key, value in briefing.section_table.items()
    }
    core = tuple(f"{instrument_id}: {line}" for instrument_id, item in briefings for line in item.section_core)
    conditions = tuple(dict.fromkeys(line for _, item in briefings for line in item.section_conditions))
    details = tuple(f"{instrument_id}: {line}" for instrument_id, item in briefings for line in item.section_details)
    reasons = tuple(dict.fromkeys(line for _, item in briefings for line in item.reasons))
    digest = hashlib.sha256("|".join(
        f"{instrument_id}:{item.verified_hash}" for instrument_id, item in briefings
    ).encode("utf-8")).hexdigest()
    return NonPostingBriefing(
        status=status,
        decision=InvestmentDecision.WAIT,
        section_judgement="대기 — 자산별로 승인된 투자·위험 정책과 개인 상태를 확인할 때까지 행동 판단과 규모 산출을 보류합니다.",
        section_table=table,
        section_core=core,
        section_conditions=conditions,
        section_details=details,
        reasons=reasons,
        verified_hash=digest,
        numeric_bindings=tuple(binding for _, item in briefings for binding in item.numeric_bindings),
    )
