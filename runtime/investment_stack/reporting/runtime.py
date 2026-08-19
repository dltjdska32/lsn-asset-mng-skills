"""Phase 6 orchestration: deterministic conditional review followed by partial-aware report."""

from __future__ import annotations

from dataclasses import dataclass, replace

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus
from investment_stack.evidence import RunDatabaseManager
from investment_stack.reporting.builder import InvestmentReportBuilder
from investment_stack.reporting.models import Availability, Confidence, InvestmentReport, ReportSectionInput
from investment_stack.review.engine import ConditionalReviewEngine, ReviewerCallback
from investment_stack.review.models import ReviewContext, ReviewResult


@dataclass(frozen=True, slots=True)
class Phase6Result:
    review: ReviewResult
    report: InvestmentReport


def section_from_analysis_result(
    result: AnalysisResult,
    *,
    name: str | None = None,
    title: str | None = None,
    base_case: bool = False,
    current_value_claim: bool = False,
) -> ReportSectionInput:
    status = {
        AnalysisStatus.COMPLETE: Availability.AVAILABLE,
        AnalysisStatus.PARTIAL: Availability.PARTIAL,
        AnalysisStatus.UNAVAILABLE: Availability.UNAVAILABLE,
    }[result.status]
    lines: list[str] = []
    lines.extend(result.findings)
    lines.extend(f"Risk: {risk}" for risk in result.risks)
    lines.extend(f"Unknown: {unknown}" for unknown in result.unknowns)
    for metric in result.metrics:
        if metric.value is None:
            lines.append(f"{metric.name}: UNKNOWN" + (f" ({metric.reason})" if metric.reason else ""))
        else:
            unit = f" {metric.unit}" if metric.unit else ""
            lines.append(f"{metric.name}: {metric.value}{unit}")
    evidence_ids = tuple(sorted({eid for metric in result.metrics for eid in metric.evidence_ids}))
    calculation_id = result.metadata.get("calculation_id")
    calculation_ids = (str(calculation_id),) if calculation_id else ()
    return ReportSectionInput(
        name=name or result.analysis_type,
        title=title or result.analysis_type.replace("_", " ").title(),
        lines=tuple(lines),
        status=status,
        evidence_ids=evidence_ids,
        calculation_ids=calculation_ids,
        base_case=base_case,
        current_value_claim=current_value_claim,
        metadata={"subject": result.subject, "analysis_type": result.analysis_type},
    )


class Phase6ReportReviewRuntime:
    """Fixed Phase 6 flow. Independent reviewer callback is optional, never required."""

    def __init__(self, run_db: RunDatabaseManager) -> None:
        self.run_db = run_db
        self.review = ConditionalReviewEngine(run_db)
        self.report = InvestmentReportBuilder(run_db)

    def generate(
        self,
        *,
        title: str,
        sections: tuple[ReportSectionInput, ...],
        review_context: ReviewContext | None = None,
        independent_reviewer: ReviewerCallback | None = None,
    ) -> Phase6Result:
        effective_context = review_context or ReviewContext()
        if effective_context.requested_confidence is None and (
            not sections or all(section.status is Availability.UNAVAILABLE for section in sections)
        ):
            effective_context = replace(effective_context, requested_confidence=Confidence.LOW)
        review_result = self.review.evaluate(
            effective_context,
            independent_reviewer=independent_reviewer,
        )
        report = self.report.build(title=title, sections=sections, review=review_result)
        return Phase6Result(review_result, report)
