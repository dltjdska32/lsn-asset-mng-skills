"""Concrete single-asset and asset-comparison bundles over Phase 4/5/6 runtimes."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from itertools import combinations
from uuid import uuid4

from investment_stack.calculations import BusinessType
from investment_stack.calculations.common import AnalysisStatus
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


def equity_analysis_services(
    *,
    deep_research: LiveDeepResearchRuntime,
    phase6: Phase6ReportReviewRuntime,
    run_db: RunDatabaseManager,
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
        pinned_mode = run_db.fetch_phase6_context()["run_metadata"].get("request_mode")
        if pinned_mode != request.mode.value:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=(
                "run database request mode does not match the requested analysis mode",
            ))
        raw = request.payload.get("research_specs")
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
        evidence_ids = tuple(dict.fromkeys(
            evidence_id for result in context.values() for evidence_id in result.evidence_refs
        ))
        review_result = phase6.review.evaluate(ReviewContext(critical_evidence_ids=evidence_ids))
        return StepResult(Availability.COMPLETE, output={"review": review_result})

    def render_report(request: ModeRequest, context: StepContext) -> StepResult:
        research = context[PipelineStep.DEEP_RESEARCH_REQUESTED_ASSETS.value]
        outcomes: tuple[EquityResearchOutcome, ...] = research.output["outcomes"]
        sections: list[ReportSectionInput] = []
        for outcome in outcomes:
            sections.append(section_from_analysis_result(
                outcome.analysis.fundamental,
                name=f"{outcome.instrument_id}_fundamental",
                title=f"{outcome.instrument_id} Fundamentals",
            ))
            sections.append(section_from_analysis_result(
                outcome.analysis.valuation,
                name=f"{outcome.instrument_id}_valuation",
                title=f"{outcome.instrument_id} Valuation",
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
        report = phase6.report.build(
            title=str(request.payload.get("title") or _default_title(request)),
            sections=tuple(sections), review=review,
        )
        expected_names = {section.name for section in report.sections}
        persisted_sections = [
            row for row in run_db.fetch_phase6_context()["report_sections"]
            if row["section_name"] in expected_names
        ]
        if {row["section_name"] for row in persisted_sections} != expected_names:
            return StepResult(Availability.FAILED, output={"report_persisted": False})
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
        partial = report.availability is not ReportAvailability.AVAILABLE or research.availability is Availability.PARTIAL
        comparison_partial = comparison is not None and comparison.availability is Availability.PARTIAL
        status = Availability.PARTIAL if partial or comparison_partial else Availability.COMPLETE
        missing = []
        if research.availability is Availability.PARTIAL:
            missing.extend(research.missing_inputs)
        if comparison_partial and comparison is not None:
            missing.extend(comparison.missing_inputs)
        if status is Availability.PARTIAL and not missing:
            missing.append("partial_report_data_quality")
        return StepResult(
            status, output={"report": report, "report_availability": report.availability.value},
            evidence_refs=research.evidence_refs,
            calculation_refs=tuple(dict.fromkeys(
                (*research.calculation_refs, *(comparison.calculation_refs if comparison else ()))
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


def _default_title(request: ModeRequest) -> str:
    return "Single Asset Analysis" if request.mode is RequestMode.SINGLE_ASSET_ANALYSIS else "Asset Comparison"
