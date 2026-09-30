"""Non-posting services for explicit thesis review and report refresh.

These services deliberately accept only typed user claims, point-in-time eligible
observations, and fixed-mode replay callbacks. They never discover a thesis, open a
personal database, or execute an asset update.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.routing import RequestMode


class ThesisVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    UNCONFIRMED = "UNCONFIRMED"


class DeltaStatus(StrEnum):
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    UNKNOWN = "UNKNOWN"


class RefreshStatus(StrEnum):
    COMPLETED = "COMPLETED"
    WAIT = "WAIT"


class ComparisonOperator(StrEnum):
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    EQ = "EQ"
    NE = "NE"


def _aware_datetime(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


@dataclass(frozen=True, slots=True)
class ObservableCountercondition:
    """A measurable condition that would falsify one user supplied claim."""

    metric: str
    operator: ComparisonOperator | str
    threshold: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not self.metric.strip() or not self.unit.strip():
            raise ValueError("countercondition metric and unit are required")
        try:
            operator = ComparisonOperator(self.operator)
        except ValueError as exc:
            raise ValueError(f"unsupported countercondition operator: {self.operator!r}") from exc
        object.__setattr__(self, "operator", operator)
        try:
            threshold = Decimal(self.threshold)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("countercondition threshold must be a finite decimal") from exc
        if not threshold.is_finite():
            raise ValueError("countercondition threshold must be a finite decimal")
        object.__setattr__(self, "threshold", threshold)

    def is_triggered(self, value: Decimal) -> bool:
        return {
            ComparisonOperator.GT: value > self.threshold,
            ComparisonOperator.GTE: value >= self.threshold,
            ComparisonOperator.LT: value < self.threshold,
            ComparisonOperator.LTE: value <= self.threshold,
            ComparisonOperator.EQ: value == self.threshold,
            ComparisonOperator.NE: value != self.threshold,
        }[self.operator]


@dataclass(frozen=True, slots=True)
class ThesisClaim:
    claim_id: str
    thesis_sentence: str
    countercondition: ObservableCountercondition | None
    prior_evidence_refs: tuple[str, ...] = ()
    support_condition: ObservableCountercondition | None = None


@dataclass(frozen=True, slots=True)
class ThesisReviewRequest:
    subject: str
    claims: tuple[ThesisClaim, ...]


@dataclass(frozen=True, slots=True)
class ThesisEvidence:
    """A typed observation returned by the caller's fixed evidence collection path."""

    evidence_id: str
    subject: str
    metric: str
    value: Decimal | None
    unit: str | None
    observed_at: str | None
    public_available_at: str | None
    freshness_status: str
    eligibility_status: str
    selected: bool

    def __post_init__(self) -> None:
        if self.value is not None:
            value = Decimal(self.value)
            if not value.is_finite():
                raise ValueError("evidence value must be finite")
            object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class ThesisAssessment:
    claim_id: str
    subject: str
    thesis_sentence: str
    falsifier: str
    verdict: ThesisVerdict
    evidence_ids: tuple[str, ...]
    prior_evidence_refs: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class ThesisReviewResult:
    status: RefreshStatus
    assessments: tuple[ThesisAssessment, ...]
    missing_inputs: tuple[str, ...]
    section: ReportSectionInput


def review_thesis(
    request: ThesisReviewRequest | None,
    evidence: tuple[ThesisEvidence, ...],
    *,
    analysis_as_of: str,
) -> ThesisReviewResult:
    """Assess a supplied claim against the latest matching eligible observation."""
    cutoff = _aware_datetime(analysis_as_of, "analysis_as_of")
    missing: list[str] = []
    if request is None:
        missing.append("사용자가 작성한 투자 논지 문장이 없습니다.")
    else:
        if not request.subject.strip():
            missing.append("대상 자산이 없습니다.")
        if not request.claims:
            missing.append("사용자가 작성한 투자 논지 문장이 없습니다.")
        claim_ids = [claim.claim_id for claim in request.claims if claim.claim_id.strip()]
        if len(claim_ids) != len(set(claim_ids)):
            missing.append("논지 식별자가 중복되었습니다.")
        for claim in request.claims:
            if not claim.claim_id.strip() or not claim.thesis_sentence.strip():
                missing.append("사용자 논지의 식별자 또는 문장이 없습니다.")
            if claim.countercondition is None:
                missing.append(f"{claim.claim_id or '식별자 없는 주장'}의 관측 가능한 반증 조건이 없습니다.")
            if not claim.prior_evidence_refs or any(not ref.strip() for ref in claim.prior_evidence_refs):
                missing.append(f"{claim.claim_id or '식별자 없는 주장'}의 기존 근거 reference가 없습니다.")

    if missing:
        section = ReportSectionInput(
            name="thesis_review", title="Thesis Review", status=Availability.UNAVAILABLE,
            lines=("WAIT: " + " ".join(missing),), metadata={"review_status": "WAIT"},
        )
        return ThesisReviewResult(RefreshStatus.WAIT, (), tuple(missing), section)

    assessments: list[ThesisAssessment] = []
    for claim in request.claims:
        condition = claim.countercondition
        assert condition is not None
        conditions = (condition,) + ((claim.support_condition,) if claim.support_condition is not None else ())
        observations: list[tuple[Decimal | None, tuple[str, ...], bool]] = []
        for current_condition in conditions:
            eligible: list[tuple[datetime, ThesisEvidence]] = []
            for item in evidence:
                if (
                    item.subject != request.subject
                    or item.metric != current_condition.metric
                    or item.unit != current_condition.unit
                    or item.value is None
                    or not item.selected
                    or item.eligibility_status.upper() != "ELIGIBLE"
                    or item.freshness_status.upper() not in {"FRESH", "CURRENT"}
                    or not item.observed_at
                    or not item.public_available_at
                ):
                    continue
                try:
                    observed_at = _aware_datetime(item.observed_at, "evidence observed_at")
                    available_at = _aware_datetime(item.public_available_at, "evidence public_available_at")
                except ValueError:
                    continue
                if observed_at <= cutoff and available_at <= cutoff:
                    eligible.append((observed_at, item))
            if not eligible:
                observations.append((None, (), False))
                continue
            newest_time = max(stamp for stamp, _ in eligible)
            newest = [item for stamp, item in eligible if stamp == newest_time]
            values = {item.value for item in newest}
            ids = tuple(sorted({item.evidence_id for item in newest}))
            observations.append((next(iter(values)) if len(values) == 1 else None, ids, len(values) > 1))

        falsifier_value, falsifier_ids, falsifier_conflict = observations[0]
        support_value, support_ids, support_conflict = observations[1] if len(observations) > 1 else (None, (), False)
        ids = tuple(sorted(set(falsifier_ids) | set(support_ids)))
        falsified = falsifier_value is not None and condition.is_triggered(falsifier_value)
        supported = (
            claim.support_condition is not None
            and support_value is not None
            and claim.support_condition.is_triggered(support_value)
        )
        if falsifier_conflict or support_conflict or (falsified and supported):
            verdict = ThesisVerdict.UNCONFIRMED
            explanation = "최신 적격 근거가 충돌하거나 서로 다른 조건이 상충하여 판단하지 않았습니다."
        elif falsified:
            verdict = ThesisVerdict.REFUTED
            explanation = f"최신 적격 관측값 {falsifier_value} {condition.unit}이 반증 조건을 충족했습니다."
        elif supported:
            verdict = ThesisVerdict.SUPPORTED
            explanation = "최신 적격 근거가 사용자가 지정한 지지 조건을 충족했습니다."
        else:
            verdict = ThesisVerdict.UNCONFIRMED
            explanation = "반증 조건은 확인되지 않았거나 명시적 지지 조건의 최신 적격 근거가 없습니다."
        falsifier_text = f"{condition.metric} {condition.operator.value} {condition.threshold} {condition.unit}"
        if claim.support_condition is not None:
            support = claim.support_condition
            falsifier_text += f"; 지지 조건: {support.metric} {support.operator.value} {support.threshold} {support.unit}"
        assessments.append(ThesisAssessment(
            claim.claim_id, request.subject, claim.thesis_sentence, falsifier_text,
            verdict, ids, claim.prior_evidence_refs, explanation,
        ))

    lines = tuple(
        f"{row.claim_id} — {row.verdict.value}: {row.thesis_sentence} | 반증 조건: {row.falsifier} | {row.explanation}"
        for row in assessments
    )
    section = ReportSectionInput(
        name="thesis_review", title="Thesis Review",
        status=Availability.PARTIAL if any(row.verdict is ThesisVerdict.UNCONFIRMED for row in assessments) else Availability.AVAILABLE,
        lines=lines, evidence_ids=tuple(sorted({eid for row in assessments for eid in row.evidence_ids})),
        metadata={"review_status": "COMPLETE" if all(row.verdict is not ThesisVerdict.UNCONFIRMED for row in assessments) else "PARTIAL"},
    )
    status = RefreshStatus.WAIT if any(row.verdict is ThesisVerdict.UNCONFIRMED for row in assessments) else RefreshStatus.COMPLETED
    return ThesisReviewResult(status, tuple(assessments), (), section)


REFRESHABLE_MODES = frozenset({
    RequestMode.PERSONAL_PORTFOLIO_ANALYSIS,
    RequestMode.SINGLE_ASSET_ANALYSIS,
    RequestMode.ASSET_COMPARISON,
    RequestMode.PORTFOLIO_SCENARIO,
})


@dataclass(frozen=True, slots=True)
class ReportRefreshRequest:
    prior_run_id: str
    prior_report_ref: str
    original_mode: RequestMode | str
    target: str
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    run_id: str
    report_ref: str
    mode: RequestMode | str
    target: str
    assumptions: tuple[str, ...]
    analysis_as_of: str
    section_fingerprints: Mapping[str, str | None]
    # Legacy seven-field runners have not attested replay completeness.
    availability: Availability = Availability.UNAVAILABLE
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PinnedRefreshContext:
    run_id: str
    analysis_as_of: str
    analysis_timezone: str
    state_version: int
    pinned_state_ref: str


@dataclass(frozen=True, slots=True)
class FixedModeReplay:
    context: PinnedRefreshContext
    mode: RequestMode
    target: str
    assumptions: tuple[str, ...]
    posting_enabled: bool = False
    allow_refresh: bool = False


@dataclass(frozen=True, slots=True)
class ReportDelta:
    section: str
    status: DeltaStatus
    previous_fingerprint: str | None
    current_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class ReportRefreshResult:
    status: RefreshStatus
    prior: ReportSnapshot
    current: ReportSnapshot | None
    deltas: tuple[ReportDelta, ...]
    section: ReportSectionInput
    missing_inputs: tuple[str, ...] = ()


PriorReportLoader = Callable[[str, str], ReportSnapshot]
StartPinnedRun = Callable[[ReportSnapshot, ReportRefreshRequest, RequestMode], PinnedRefreshContext]
ModeRunner = Callable[[FixedModeReplay], ReportSnapshot]


@dataclass(frozen=True, slots=True)
class ReportRefreshServices:
    load_prior_report: PriorReportLoader
    start_pinned_run: StartPinnedRun
    verify_pinned_run: Callable[[PinnedRefreshContext], bool]
    allowed_mode_runners: Mapping[RequestMode, ModeRunner]


def refresh_report(request: ReportRefreshRequest | None, services: ReportRefreshServices) -> ReportRefreshResult:
    """Create a separately pinned run, replay one allowlisted mode, and compare."""
    if request is None:
        raise ValueError("report refresh request is required")
    if not request.prior_run_id.strip() or not request.prior_report_ref.strip():
        raise ValueError("prior run ID and report reference are required")
    if not request.target.strip() or not request.assumptions or any(not item.strip() for item in request.assumptions):
        raise ValueError("original target and explicit assumptions are required")
    try:
        mode = RequestMode.parse(request.original_mode)
    except ValueError as exc:
        raise ValueError("original request mode is invalid") from exc
    if mode not in REFRESHABLE_MODES:
        raise ValueError(f"mode {mode.value} cannot be replayed by report refresh")
    runner = services.allowed_mode_runners.get(mode)
    if runner is None:
        raise ValueError(f"no fixed runner registered for original mode {mode.value}")

    prior = services.load_prior_report(request.prior_run_id, request.prior_report_ref)
    if prior.run_id != request.prior_run_id or prior.report_ref != request.prior_report_ref:
        raise ValueError("prior report reference did not resolve to the requested run/report")
    if RequestMode.parse(prior.mode) != mode or prior.target != request.target or prior.assumptions != request.assumptions:
        raise ValueError("refresh request differs from the original mode, target, or assumptions")
    prior_time = _aware_datetime(prior.analysis_as_of, "prior analysis_as_of")

    context = services.start_pinned_run(prior, request, mode)
    if (
        not context.run_id.strip() or context.run_id == prior.run_id
        or not context.pinned_state_ref.strip() or context.state_version <= 0
        or not context.analysis_timezone.strip()
    ):
        raise ValueError("refresh requires a new run with a pinned clock and state")
    try:
        ZoneInfo(context.analysis_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("refresh analysis_timezone must be a valid IANA timezone") from exc
    if not services.verify_pinned_run(context):
        raise ValueError("new run clock/state pin was not verified in run storage")
    new_time = _aware_datetime(context.analysis_as_of, "new analysis_as_of")
    if new_time <= prior_time:
        raise ValueError("refresh analysis clock must be later than the prior report clock")

    replay = FixedModeReplay(context, mode, request.target, request.assumptions)
    current = runner(replay)
    if current.run_id != context.run_id or not current.report_ref.strip():
        raise ValueError("fixed-mode replay returned a report from a different run")
    if RequestMode.parse(current.mode) != mode or current.target != request.target or current.assumptions != request.assumptions:
        raise ValueError("fixed-mode replay changed the requested mode, target, or assumptions")
    if _aware_datetime(current.analysis_as_of, "replay analysis_as_of") != new_time:
        raise ValueError("fixed-mode replay did not use the newly pinned analysis clock")

    previous = prior.section_fingerprints
    latest = current.section_fingerprints
    deltas: list[ReportDelta] = []
    for section in sorted(set(previous) | set(latest)):
        before = previous.get(section)
        after = latest.get(section)
        if not isinstance(before, str) or not before.strip() or not isinstance(after, str) or not after.strip():
            status = DeltaStatus.UNKNOWN
        elif before == after:
            status = DeltaStatus.UNCHANGED
        else:
            status = DeltaStatus.CHANGED
        deltas.append(ReportDelta(section, status, before, after))
    comparison_incomplete = not deltas or any(delta.status is DeltaStatus.UNKNOWN for delta in deltas)
    replay_incomplete = current.availability is not Availability.AVAILABLE or bool(current.missing_inputs)
    lines = tuple(f"{delta.status.value}: {delta.section}" for delta in deltas)
    if replay_incomplete:
        lines = ("WAIT: 새 기준으로 다시 수행한 분석이 일부만 완료되었습니다. 누락 자료를 확인하세요.", *lines)
    if not lines:
        lines = ("No comparable report sections were returned.",)
    section = ReportSectionInput(
        name="report_refresh_delta", title="Report Refresh Changes",
        status=Availability.PARTIAL if replay_incomplete or comparison_incomplete else Availability.AVAILABLE,
        lines=lines,
        metadata={"prior_run_id": prior.run_id, "prior_report_ref": prior.report_ref,
                  "current_run_id": current.run_id, "current_report_ref": current.report_ref,
                  "replay_availability": current.availability.value,
                  "missing_input_ids": list(current.missing_inputs)},
    )
    missing_inputs = list(current.missing_inputs)
    if comparison_incomplete:
        missing_inputs.append("report_refresh_comparison_incomplete")
    status = RefreshStatus.WAIT if replay_incomplete or comparison_incomplete else RefreshStatus.COMPLETED
    return ReportRefreshResult(status, prior, current, tuple(deltas), section,
                               tuple(dict.fromkeys(missing_inputs)))


__all__ = [
    "ComparisonOperator", "DeltaStatus", "FixedModeReplay", "ObservableCountercondition",
    "PinnedRefreshContext", "REFRESHABLE_MODES", "RefreshStatus", "ReportDelta",
    "ReportRefreshRequest", "ReportRefreshResult", "ReportRefreshServices", "ReportSnapshot",
    "ThesisAssessment", "ThesisClaim", "ThesisEvidence", "ThesisReviewRequest", "ThesisReviewResult",
    "ThesisVerdict", "refresh_report", "review_thesis",
]
