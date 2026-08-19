"""Phase 4 deterministic evidence persistence, freshness, selection, and conflict lineage."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Iterable

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.freshness import FreshnessAssessment, FreshnessEngine, FreshnessStatus, observation_time
from investment_stack.providers.models import ProviderObservation, ProviderResult


@dataclass(frozen=True, slots=True)
class SelectedEvidence:
    observation: ProviderObservation | None
    freshness: FreshnessAssessment | None
    evidence_id: str | None
    observation_id: str | None
    partial: bool
    reason: str


def _id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _comparable_key(observation: ProviderObservation) -> tuple[object, ...]:
    md = observation.metadata
    return (
        observation.metric,
        observation.unit,
        observation.currency,
        md.get("period_end"),
        md.get("reporting_period"),
        md.get("basis"),
        md.get("consolidation"),
        md.get("adjustment_basis"),
        md.get("restatement"),
    )


def _value_token(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _selection_key(observation: ProviderObservation) -> tuple[object, ...]:
    """Group equivalent metric candidates across periods for latest-as-of selection."""
    md = observation.metadata
    return (
        observation.metric,
        observation.unit,
        observation.currency,
        md.get("basis"),
        md.get("consolidation"),
        md.get("adjustment_basis"),
        md.get("restatement"),
    )


class EvidenceResearchStore:
    """Persist provider observations in run.db; never touches personal.db."""

    def __init__(self, run_db: RunDatabaseManager, *, freshness: FreshnessEngine | None = None) -> None:
        self.run_db = run_db
        self.freshness = freshness or FreshnessEngine()

    def record_provider_result(self, result: ProviderResult) -> None:
        self.run_db.record_provider_state(
            provider_name=result.provider,
            provider_status=result.status.value,
            capability=result.capability.value,
            error_reason=result.reason,
            metadata=result.metadata,
        )

    def persist_and_select(
        self,
        results: Iterable[ProviderResult],
        *,
        analysis_as_of: str,
    ) -> SelectedEvidence:
        candidates: list[tuple[ProviderObservation, FreshnessAssessment, str, str | None]] = []
        for result in results:
            self.record_provider_result(result)
            for observation in result.observations:
                assessment = self.freshness.assess(observation, analysis_as_of=analysis_as_of)
                evidence_id = _id("evidence")
                self.run_db.add_phase4_evidence(
                    evidence_id=evidence_id,
                    evidence_type=observation.evidence_type,
                    source_uri=observation.source_url,
                    retrieved_at=observation.retrieved_at,
                    instrument_id=observation.instrument_id,
                    metric=observation.metric,
                    value=observation.value,
                    unit=observation.unit,
                    currency=observation.currency,
                    source_name=observation.source_name,
                    source_tier=observation.source_tier,
                    observed_at=observation.observed_at,
                    published_at=observation.published_at,
                    freshness_status=assessment.status.value,
                    provider_id=observation.provider_id,
                    headline=observation.headline,
                    updated_at=observation.updated_at,
                    event_time=observation.event_time,
                    official_confirmation_status=observation.official_confirmation_status,
                    event_cluster_id=observation.event_cluster_id,
                    relevance_reason=observation.relevance_reason,
                    metadata=observation.metadata,
                )
                freshness_id = _id("freshness")
                self.run_db.add_freshness_assessment(
                    freshness_id=freshness_id,
                    evidence_id=evidence_id,
                    status=assessment.status.value,
                    details={
                        "effective_time": assessment.effective_time,
                        "age_seconds": assessment.age_seconds,
                        "reason": assessment.reason,
                    },
                )
                observation_id: str | None = None
                value = observation.value if isinstance(observation.value, (str, int, float)) else None
                if observation.evidence_type == "market":
                    observation_id = _id("market")
                    self.run_db.add_market_observation(
                        observation_id=observation_id, evidence_id=evidence_id,
                        instrument_id=observation.instrument_id, observed_at=observation.observed_at,
                        value=value, unit=observation.unit, currency=observation.currency,
                        claimed_market_time=observation.claimed_market_time,
                        market_session_date=observation.market_session_date,
                        provider_id=observation.provider_id, freshness_status=assessment.status.value,
                        metadata=observation.metadata,
                    )
                elif observation.evidence_type == "financial":
                    self.run_db.add_financial_observation(
                        observation_id=_id("financial"), evidence_id=evidence_id,
                        metric_name=observation.metric or "unknown",
                        period_end=observation.metadata.get("period_end"), value=value,
                        unit=observation.unit, currency=observation.currency,
                        provider_id=observation.provider_id, metadata=observation.metadata,
                    )
                elif observation.evidence_type == "macro":
                    self.run_db.add_macro_observation(
                        observation_id=_id("macro"), evidence_id=evidence_id,
                        series_name=observation.metric or "unknown", observed_at=observation.observed_at,
                        value=value, unit=observation.unit, currency=observation.currency,
                        provider_id=observation.provider_id, metadata=observation.metadata,
                    )
                approved = observation.metadata.get("calculation_input_approved", True) is not False
                if (
                    approved
                    and assessment.status is not FreshnessStatus.UNAVAILABLE
                    and observation_time(observation) is not None
                ):
                    candidates.append((observation, assessment, evidence_id, observation_id))

        if not candidates:
            return SelectedEvidence(None, None, None, None, True, "no usable timestamped observation as of cutoff")

        self._record_conflicts(candidates)
        # Select one winner per comparable metric/period group. This is essential for
        # multi-metric filing results: revenue, operating income, EPS, etc. must each
        # retain their own evidence lineage instead of a single arbitrary row winning
        # for the whole filing. Conflicting values inside one comparable group are
        # never averaged.
        grouped: dict[tuple[object, ...], list[tuple[ProviderObservation, FreshnessAssessment, str, str | None]]] = {}
        for candidate in candidates:
            grouped.setdefault(_selection_key(candidate[0]), []).append(candidate)

        winners: list[tuple[ProviderObservation, FreshnessAssessment, str, str | None]] = []
        selection_reason = "latest-as-of per comparable metric; source authority used as tie-breaker; no averaging"
        for group in grouped.values():
            group.sort(
                key=lambda item: (observation_time(item[0]), -item[0].source_tier),
                reverse=True,
            )
            winner = group[0]
            winners.append(winner)
            self.run_db.mark_evidence_selected(evidence_id=winner[2], reason=selection_reason)
            if winner[3] is not None:
                self.run_db.add_observation_selection(
                    selection_id=_id("selection"),
                    observation_id=winner[3],
                    selection_reason=selection_reason,
                )

        winners.sort(
            key=lambda item: (observation_time(item[0]), -item[0].source_tier),
            reverse=True,
        )
        selected = winners[0]
        is_partial = selected[1].status is FreshnessStatus.STALE
        reason = "selected stale latest-as-of observation" if is_partial else "selected latest usable observation as of cutoff"
        return SelectedEvidence(selected[0], selected[1], selected[2], selected[3], is_partial, reason)

    def _record_conflicts(
        self,
        candidates: list[tuple[ProviderObservation, FreshnessAssessment, str, str | None]],
    ) -> None:
        grouped: dict[tuple[object, ...], list[ProviderObservation]] = {}
        for observation, _, _, _ in candidates:
            grouped.setdefault(_comparable_key(observation), []).append(observation)
        for key, observations in grouped.items():
            values = {_value_token(item.value) for item in observations}
            if len(observations) < 2 or len(values) < 2:
                continue
            self.run_db.add_conflict(
                conflict_id=_id("conflict"),
                conflict_type="SOURCE_VALUE_CONFLICT",
                status="OPEN",
                details={
                    "comparability_key": [None if value is None else str(value) for value in key],
                    "candidates": [
                        {
                            "provider": item.provider_id,
                            "source": item.source_name,
                            "source_tier": item.source_tier,
                            "value": item.value,
                            "observed_at": item.observed_at,
                            "published_at": item.published_at,
                        }
                        for item in observations
                    ],
                    "resolution": "not averaged; deterministic selection occurs separately",
                },
            )
