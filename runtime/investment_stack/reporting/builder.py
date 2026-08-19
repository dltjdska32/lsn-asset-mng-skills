"""Partial-aware, as-of pinned Phase 6 investment report builder."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime

from investment_stack.evidence import RunDatabaseManager
from investment_stack.reporting.models import (
    Availability,
    Confidence,
    InvestmentReport,
    ReportAsOf,
    ReportSection,
    ReportSectionInput,
)
from investment_stack.review.models import ReviewResult
from investment_stack.security.redaction import SecretRedactor


_BAD_CURRENT_FRESHNESS = {"STALE", "UNKNOWN", "UNAVAILABLE"}
_BAD_BASE_CASE_CONFIRMATION = {"RUMOR", "UNVERIFIED"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _latest(values: list[str]) -> str | None:
    parsed = [(stamp, _parse_time(stamp)) for stamp in values if stamp]
    parsed = [(stamp, dt) for stamp, dt in parsed if dt is not None]
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[1])[0]


class InvestmentReportBuilder:
    """Build and persist a derived report without mutating personal.db."""

    def __init__(self, run_db: RunDatabaseManager) -> None:
        self.run_db = run_db
        self.redactor = SecretRedactor()

    def build(
        self,
        *,
        title: str,
        sections: tuple[ReportSectionInput, ...],
        review: ReviewResult,
    ) -> InvestmentReport:
        if not title.strip():
            raise ValueError("report title is required")
        safe_title = self.redactor.text(title.strip())
        if len({section.name for section in sections}) != len(sections):
            raise ValueError("report section names must be unique")
        snapshot = self.run_db.fetch_phase6_context()
        metadata = snapshot["run_metadata"]
        if not metadata.get("analysis_as_of") or not metadata.get("analysis_timezone"):
            raise RuntimeError("report requires a pinned analysis_as_of and analysis_timezone")
        evidence_by_id = {row["evidence_id"]: row for row in snapshot["evidence"]}
        calculations_by_id = {row["calculation_id"]: row for row in snapshot["calculations"]}

        built: list[ReportSection] = []
        for section in sections:
            missing_evidence = [eid for eid in section.evidence_ids if eid not in evidence_by_id]
            if missing_evidence:
                raise ValueError(f"section {section.name} references missing evidence: {', '.join(missing_evidence)}")
            missing_calculations = [cid for cid in section.calculation_ids if cid not in calculations_by_id]
            if missing_calculations:
                raise ValueError(f"section {section.name} references missing calculations: {', '.join(missing_calculations)}")
            status = section.status
            cited = [evidence_by_id[eid] for eid in section.evidence_ids]
            if section.base_case:
                bad = [row for row in cited if row.get("official_confirmation_status") in _BAD_BASE_CASE_CONFIRMATION]
                if bad:
                    raise ValueError("rumor or unverified evidence cannot change the report base case")
                if any(row.get("official_confirmation_status") == "NEWS_REPORTED" for row in cited):
                    status = Availability.PARTIAL
            if section.current_value_claim:
                self._validate_current_value_claim(section, cited)
            built.append(
                ReportSection(
                    section.name,
                    section.title,
                    tuple(self.redactor.text(line) for line in section.lines),
                    status,
                    tuple(section.evidence_ids),
                    tuple(section.calculation_ids),
                    self.redactor.value(dict(section.metadata)),
                )
            )

        if review.findings:
            finding_status = Availability.PARTIAL if any(
                finding.severity.value in {"MEDIUM", "HIGH", "CRITICAL"} for finding in review.findings
            ) else Availability.AVAILABLE
            built.append(
                ReportSection(
                    "review_findings",
                    "Review Findings",
                    tuple(f"[{finding.severity.value}] {finding.code}: {finding.text}" for finding in review.findings),
                    finding_status,
                    (),
                    (),
                    {},
                )
            )

        base_availability = self._availability(tuple(built))
        unknowns = self._unknowns(snapshot)
        quality_status = Availability.PARTIAL if unknowns else Availability.AVAILABLE
        quality_lines = tuple(unknowns) if unknowns else ("No material stale, conflicting, missing-provider, or unavailable input was detected in the run evidence.",)
        built.append(ReportSection("data_quality", "Data Quality / Unknowns", quality_lines, quality_status, (), (), {}))

        if base_availability is Availability.UNAVAILABLE:
            availability = Availability.UNAVAILABLE
        elif unknowns or base_availability is Availability.PARTIAL:
            availability = Availability.PARTIAL
        else:
            availability = Availability.AVAILABLE
        confidence = self._report_confidence(review.confidence, availability)
        as_of = self._as_of(snapshot)
        report = InvestmentReport(
            title=safe_title,
            availability=availability,
            confidence=confidence,
            as_of=as_of,
            sections=tuple(built),
            review_required=review.required,
            review_triggers=tuple(trigger.value for trigger in review.triggers),
            unknowns=tuple(unknowns),
            markdown="",
        )
        markdown = self._render(replace(report, markdown=""), evidence_by_id)
        report = replace(report, markdown=markdown)
        self._persist(report)
        return report

    @staticmethod
    def _validate_current_value_claim(section: ReportSectionInput, cited: list[dict[str, object]]) -> None:
        if not cited:
            raise ValueError(f"current-value section {section.name} requires timestamped market evidence")
        for row in cited:
            if row.get("evidence_type") != "market":
                raise ValueError("current-value claim must cite market evidence")
            if row.get("selection_state") != "SELECTED":
                raise ValueError("current-value claim must cite selected evidence")
            if not row.get("observed_at"):
                raise ValueError("current-value claim requires observed_at; retrieved_at is not a substitute")
            if row.get("freshness_status") in _BAD_CURRENT_FRESHNESS:
                raise ValueError("stale/unknown/unavailable observation cannot be labeled current")

    @staticmethod
    def _unknowns(snapshot: dict[str, object]) -> list[str]:
        messages: list[str] = []
        provider_issues = [
            row for row in snapshot["provider_states"]
            if row.get("provider_status") in {"MISSING_CREDENTIAL", "UNAVAILABLE", "ERROR", "PARTIAL"}
        ]
        for row in provider_issues:
            capability = row.get("capability") or "general"
            messages.append(f"Provider {row.get('provider_name')} for {capability}: {row.get('provider_status')}.")
        selected_bad = [
            row for row in snapshot["evidence"]
            if row.get("selection_state") == "SELECTED" and row.get("freshness_status") in {"STALE", "UNKNOWN", "UNAVAILABLE"}
        ]
        for row in selected_bad:
            messages.append(f"Selected evidence {row.get('evidence_id')} freshness is {row.get('freshness_status')}.")
        open_conflicts = [row for row in snapshot["conflicts"] if row.get("status") == "OPEN"]
        if open_conflicts:
            messages.append(f"{len(open_conflicts)} unresolved source conflict(s) remain; values were not averaged.")
        return messages

    @staticmethod
    def _availability(sections: tuple[ReportSection, ...]) -> Availability:
        if not sections:
            return Availability.UNAVAILABLE
        if all(section.status is Availability.UNAVAILABLE for section in sections):
            return Availability.UNAVAILABLE
        if any(section.status is not Availability.AVAILABLE for section in sections):
            return Availability.PARTIAL
        return Availability.AVAILABLE

    @staticmethod
    def _report_confidence(review_confidence: Confidence, availability: Availability) -> Confidence:
        if availability is Availability.UNAVAILABLE:
            return Confidence.LOW
        if availability is Availability.PARTIAL and review_confidence is Confidence.HIGH:
            return Confidence.MEDIUM
        return review_confidence

    @staticmethod
    def _as_of(snapshot: dict[str, object]) -> ReportAsOf:
        metadata = snapshot["run_metadata"]
        selected_ids = {row["evidence_id"] for row in snapshot["evidence"] if row.get("selection_state") == "SELECTED"}
        market_times = [str(row["observed_at"]) for row in snapshot["market_observations"] if row.get("evidence_id") in selected_ids and row.get("observed_at")]
        financial_times = [str(row["period_end"]) for row in snapshot["financial_observations"] if row.get("evidence_id") in selected_ids and row.get("period_end")]
        macro_times = [str(row["observed_at"]) for row in snapshot["macro_observations"] if row.get("evidence_id") in selected_ids and row.get("observed_at")]
        pinned = snapshot.get("pinned_personal_state") or {}
        return ReportAsOf(
            analysis_as_of=str(metadata["analysis_as_of"]),
            analysis_timezone=str(metadata["analysis_timezone"]),
            market_data_as_of=_latest(market_times),
            financial_data_as_of=_latest(financial_times),
            macro_data_as_of=_latest(macro_times),
            portfolio_data_as_of=pinned.get("portfolio_data_as_of"),
        )

    @staticmethod
    def _render(report: InvestmentReport, evidence_by_id: dict[str, dict[str, object]]) -> str:
        def shown(value: str | None) -> str:
            return value if value else "UNKNOWN"

        lines = [
            f"# {report.title}",
            "",
            f"- Report Availability: **{report.availability.value}**",
            f"- Confidence: **{report.confidence.value}**",
            f"- Analysis As Of: {report.as_of.analysis_as_of} ({report.as_of.analysis_timezone})",
            f"- Market Data As Of: {shown(report.as_of.market_data_as_of)}",
            f"- Financial Data As Of: {shown(report.as_of.financial_data_as_of)}",
            f"- Macro Data As Of: {shown(report.as_of.macro_data_as_of)}",
            f"- Portfolio Data As Of: {shown(report.as_of.portfolio_data_as_of)}",
            f"- Conditional Review: {'REQUIRED' if report.review_required else 'NOT TRIGGERED'}",
        ]
        if report.review_triggers:
            lines.append("- Review Triggers: " + ", ".join(report.review_triggers))
        for section in report.sections:
            lines.extend(("", f"## {section.title}", f"Status: **{section.status.value}**"))
            if section.lines:
                lines.extend(f"- {line}" for line in section.lines)
            else:
                lines.append("- UNKNOWN")
            for evidence_id in section.evidence_ids:
                row = evidence_by_id[evidence_id]
                data_time = row.get("observed_at") or row.get("published_at") or row.get("event_time") or "UNKNOWN"
                source = row.get("source_name") or row.get("provider_id") or "UNKNOWN_SOURCE"
                lines.append(f"- Evidence `{evidence_id}` — {source}; data time: {data_time}; freshness: {row.get('freshness_status') or 'UNKNOWN'}")
            if section.calculation_ids:
                lines.append("- Calculation lineage: " + ", ".join(f"`{cid}`" for cid in section.calculation_ids))
        return "\n".join(lines) + "\n"

    def _persist(self, report: InvestmentReport) -> None:
        for section in report.sections:
            payload = {
                "title": section.title,
                "lines": list(section.lines),
                "evidence_ids": list(section.evidence_ids),
                "calculation_ids": list(section.calculation_ids),
                "metadata": dict(section.metadata),
                "report_availability": report.availability.value,
                "report_confidence": report.confidence.value,
                "analysis_as_of": report.as_of.analysis_as_of,
            }
            canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.run_db.upsert_report_section(
                section_id=f"section:{section.name}",
                section_name=section.name,
                section_status=section.status.value,
                content_reference=f"inline-sha256:{digest}",
                metadata=payload,
            )
