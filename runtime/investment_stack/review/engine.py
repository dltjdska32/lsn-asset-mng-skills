"""Deterministic Phase 6 review gate with optional independent reviewer callback."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from collections.abc import Callable, Iterable

from investment_stack.evidence import RunDatabaseManager
from investment_stack.reporting.models import Confidence
from investment_stack.security.redaction import SecretRedactor
from investment_stack.review.models import (
    FindingSeverity,
    ReviewContext,
    ReviewFinding,
    ReviewPacket,
    ReviewResult,
    ReviewTrigger,
)


ReviewerCallback = Callable[[ReviewPacket], Iterable[ReviewFinding]]


class ConditionalReviewEngine:
    """Run mandatory deterministic checks and conditionally invoke an optional reviewer."""

    def __init__(self, run_db: RunDatabaseManager) -> None:
        self.run_db = run_db
        self.redactor = SecretRedactor()

    def evaluate(
        self,
        context: ReviewContext | None = None,
        *,
        independent_reviewer: ReviewerCallback | None = None,
    ) -> ReviewResult:
        review_context = context or ReviewContext()
        snapshot = self.run_db.fetch_phase6_context()
        evidence_rows = tuple(snapshot["evidence"])
        evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
        triggers: list[ReviewTrigger] = []
        findings: list[ReviewFinding] = []

        def trigger(value: ReviewTrigger) -> None:
            if value not in triggers:
                triggers.append(value)

        material_decisions = {row.get("decision") for row in snapshot["materiality_decisions"]}
        if review_context.high_materiality or material_decisions.intersection({"PASS", "PASS_UNCERTAINTY"}):
            trigger(ReviewTrigger.HIGH_MATERIALITY)
        if review_context.requested_confidence is Confidence.LOW:
            trigger(ReviewTrigger.LOW_CONFIDENCE)
        if review_context.new_instrument:
            trigger(ReviewTrigger.NEW_INSTRUMENT)
        if review_context.large_net_worth_impact:
            trigger(ReviewTrigger.LARGE_NET_WORTH_IMPACT)
        if review_context.unsupported_in_kind_transfer:
            trigger(ReviewTrigger.UNSUPPORTED_IN_KIND_TRANSFER)
            findings.append(ReviewFinding(FindingSeverity.HIGH, "UNSUPPORTED_IN_KIND_TRANSFER", "Unsupported in-kind transfer must not change confirmed positions."))
        if review_context.high_impact_bootstrap_or_repair:
            trigger(ReviewTrigger.HIGH_IMPACT_BOOTSTRAP_OR_REPAIR)
        if review_context.strong_strategy_change:
            trigger(ReviewTrigger.STRONG_STRATEGY_CHANGE)
        if review_context.unsupported_model:
            trigger(ReviewTrigger.UNSUPPORTED_MODEL)
            findings.append(ReviewFinding(FindingSeverity.HIGH, "UNSUPPORTED_MODEL", "An unsupported valuation or analysis model was requested or detected."))

        open_conflicts = [row for row in snapshot["conflicts"] if row["status"] == "OPEN"]
        if open_conflicts:
            trigger(ReviewTrigger.SOURCE_CONFLICT)
            findings.append(ReviewFinding(FindingSeverity.HIGH, "SOURCE_CONFLICT", f"{len(open_conflicts)} unresolved source conflict(s) remain; conflicting values must not be averaged."))

        critical_ids = set(review_context.critical_evidence_ids)
        if not critical_ids:
            critical_ids = {row["evidence_id"] for row in evidence_rows if row.get("selection_state") == "SELECTED"}
        bad_freshness = []
        for evidence_id in sorted(critical_ids):
            row = evidence_by_id.get(evidence_id)
            if row is None:
                findings.append(ReviewFinding(FindingSeverity.HIGH, "MISSING_CRITICAL_EVIDENCE", f"Critical evidence {evidence_id} is missing from run lineage."))
                trigger(ReviewTrigger.LINEAGE_FAILURE)
                continue
            if row.get("freshness_status") in {"STALE", "UNKNOWN", "UNAVAILABLE"}:
                bad_freshness.append((evidence_id, row.get("freshness_status")))
        if bad_freshness:
            trigger(ReviewTrigger.STALE_OR_UNKNOWN_CRITICAL_DATA)
            findings.append(ReviewFinding(FindingSeverity.HIGH, "CRITICAL_DATA_FRESHNESS", "Critical selected evidence is stale, unknown, or unavailable: " + ", ".join(f"{eid}={status}" for eid, status in bad_freshness)))

        material_news_ids = set(review_context.base_case_evidence_ids) | critical_ids
        material_news = []
        for evidence_id in sorted(material_news_ids):
            row = evidence_by_id.get(evidence_id)
            if row is None:
                continue
            state = row.get("official_confirmation_status")
            if state in {"NEWS_REPORTED", "RUMOR", "UNVERIFIED"}:
                material_news.append((evidence_id, state))
        if material_news:
            trigger(ReviewTrigger.NEWS_REPORTED_OR_RUMOR_MATERIAL)
            severity = FindingSeverity.HIGH if any(state in {"RUMOR", "UNVERIFIED"} for _, state in material_news) else FindingSeverity.MEDIUM
            findings.append(ReviewFinding(severity, "MATERIAL_NEWS_CONFIRMATION", "Material evidence is not official/confirmed: " + ", ".join(f"{eid}={state}" for eid, state in material_news)))

        lineage_errors = self._calculation_lineage_errors(snapshot, evidence_by_id)
        if lineage_errors:
            trigger(ReviewTrigger.LINEAGE_FAILURE)
            findings.extend(ReviewFinding(FindingSeverity.HIGH, "CALCULATION_LINEAGE", error) for error in lineage_errors)

        required = bool(triggers)
        reviewer_used = False
        if required and independent_reviewer is not None:
            packet = ReviewPacket(self.run_db.run_id, tuple(triggers), tuple(findings), review_context)
            try:
                extra = tuple(independent_reviewer(packet))
            except Exception as exc:  # optional reviewer failure must not suppress deterministic report output
                findings.append(ReviewFinding(FindingSeverity.MEDIUM, "OPTIONAL_REVIEWER_FAILED", f"Optional independent reviewer failed: {type(exc).__name__}"))
            else:
                reviewer_used = True
                findings.extend(extra)

        findings = [
            replace(
                finding,
                text=self.redactor.text(finding.text),
                metadata=self.redactor.value(dict(finding.metadata)),
            )
            for finding in findings
        ]
        confidence = self._confidence(review_context, findings)
        for finding in findings:
            self.run_db.add_review_finding(
                finding_id=f"review:{uuid.uuid4().hex}",
                severity=finding.severity.value,
                status=finding.status,
                finding_text=f"[{finding.code}] {finding.text}",
            )
        return ReviewResult(required, tuple(triggers), tuple(findings), confidence, reviewer_used)

    @staticmethod
    def _calculation_lineage_errors(snapshot: dict[str, object], evidence_by_id: dict[str, dict[str, object]]) -> tuple[str, ...]:
        errors: list[str] = []
        for row in snapshot["calculations"]:
            try:
                inputs = json.loads(row["inputs_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                errors.append(f"Calculation {row['calculation_id']} has invalid inputs_json lineage.")
                continue
            if isinstance(inputs, dict):
                evidence_ids = inputs.get("evidence_ids", ())
                if "evidence_id" in inputs and inputs.get("evidence_id") is not None:
                    if evidence_ids in ((), []):
                        evidence_ids = (inputs.get("evidence_id"),)
                    elif isinstance(evidence_ids, (list, tuple)):
                        evidence_ids = tuple(evidence_ids) + (inputs.get("evidence_id"),)
            else:
                evidence_ids = ()
            if not isinstance(evidence_ids, (list, tuple)):
                errors.append(f"Calculation {row['calculation_id']} evidence_ids lineage is malformed.")
                continue
            missing = [str(eid) for eid in evidence_ids if eid is not None and str(eid) not in evidence_by_id]
            if missing:
                errors.append(f"Calculation {row['calculation_id']} references missing evidence: {', '.join(missing)}")
        return tuple(errors)

    @staticmethod
    def _confidence(context: ReviewContext, findings: list[ReviewFinding]) -> Confidence:
        if context.requested_confidence is Confidence.LOW:
            return Confidence.LOW
        if any(item.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH} for item in findings):
            return Confidence.LOW
        if context.requested_confidence is Confidence.MEDIUM or findings:
            return Confidence.MEDIUM
        return Confidence.HIGH
