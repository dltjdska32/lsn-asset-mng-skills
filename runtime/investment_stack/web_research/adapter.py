"""Existing Web Research Adapter: latest/current fallback and relevant news."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from investment_stack.freshness import FreshnessEngine, FreshnessStatus
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability
from investment_stack.web_research.models import WebResearchHit, WebResearchIntent, WebResearchResponse

SearchBackend = Callable[[WebResearchIntent, str, str], WebResearchResponse]

_CURRENT_FORBIDDEN_KINDS = {"news_article", "search_snippet", "blog", "analyst_report", "undated_page"}


class WebResearchAdapter:
    name = "web_research"

    def __init__(self, backend: SearchBackend, *, freshness: FreshnessEngine | None = None) -> None:
        self._backend = backend
        self._freshness = freshness or FreshnessEngine()

    def fetch_current(self, query: str, *, analysis_as_of: str, instrument_id: str | None = None, metric: str = "current_price") -> ProviderResult:
        response = self._backend(WebResearchIntent.LATEST_CURRENT_DATA, query, analysis_as_of)
        observations: list[ProviderObservation] = []
        retrieved = datetime.now(timezone.utc).isoformat()
        for hit in response.hits:
            if hit.source_kind in _CURRENT_FORBIDDEN_KINDS:
                continue
            if hit.observed_at is None and hit.claimed_market_time is None:
                continue
            observation = self._to_observation(hit, retrieved=retrieved, evidence_type="market", instrument_id=instrument_id, metric=metric)
            assessment = self._freshness.assess(observation, analysis_as_of=analysis_as_of)
            if assessment.status is FreshnessStatus.UNAVAILABLE:
                continue
            observations.append(observation)
        selected = self._freshness.latest_as_of(observations, analysis_as_of=analysis_as_of)
        if selected is None:
            return ProviderResult(self.name, ProviderCapability.CURRENT_PRICE, ProviderStatus.UNAVAILABLE, reason="no timestamped current-data web observation")
        return ProviderResult(self.name, ProviderCapability.CURRENT_PRICE, ProviderStatus.AVAILABLE, (selected,))

    def fetch_latest_data(
        self,
        query: str,
        *,
        capability: ProviderCapability,
        analysis_as_of: str,
        instrument_id: str | None = None,
        evidence_type: str = "financial",
        metric: str = "latest_data",
    ) -> ProviderResult:
        """Timestamp-verified Web Research fallback for non-price metrics."""
        if capability is ProviderCapability.CURRENT_PRICE:
            return self.fetch_current(
                query, analysis_as_of=analysis_as_of, instrument_id=instrument_id, metric=metric
            )
        response = self._backend(WebResearchIntent.LATEST_CURRENT_DATA, query, analysis_as_of)
        retrieved = datetime.now(timezone.utc).isoformat()
        observations: list[ProviderObservation] = []
        for hit in response.hits:
            if hit.observed_at is None and hit.published_at is None and hit.updated_at is None:
                continue
            hit_metric = hit.metadata.get("metric") if isinstance(hit.metadata.get("metric"), str) else metric
            observation = self._to_observation(
                hit, retrieved=retrieved, evidence_type=evidence_type,
                instrument_id=instrument_id, metric=hit_metric,
            )
            if hit.source_kind == "news_article" and evidence_type in {"financial", "macro"}:
                observation = replace(
                    observation,
                    official_confirmation_status=hit.official_confirmation_status or "NEWS_REPORTED",
                    metadata={**observation.metadata, "calculation_input_approved": False},
                )
            assessment = self._freshness.assess(observation, analysis_as_of=analysis_as_of)
            if assessment.status is FreshnessStatus.UNAVAILABLE:
                continue
            observations.append(observation)
        selected = self._freshness.latest_as_of(observations, analysis_as_of=analysis_as_of)
        if selected is None:
            return ProviderResult(self.name, capability, ProviderStatus.UNAVAILABLE, reason="no timestamped web observation as of cutoff")
        status = ProviderStatus.PARTIAL if selected.metadata.get("calculation_input_approved") is False else ProviderStatus.AVAILABLE
        return ProviderResult(self.name, capability, status, tuple(observations))

    def fetch_news(self, query: str, *, analysis_as_of: str, instrument_id: str | None = None) -> ProviderResult:
        response = self._backend(WebResearchIntent.LATEST_RELEVANT_NEWS, query, analysis_as_of)
        retrieved = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        observations: list[ProviderObservation] = []
        for hit in response.hits:
            cluster = hit.event_cluster_id or f"{hit.source_url}|{hit.title.casefold()}"
            if cluster in seen:
                continue
            seen.add(cluster)
            observation = self._to_observation(hit, retrieved=retrieved, evidence_type="news", instrument_id=instrument_id, metric="latest_relevant_news")
            assessment = self._freshness.assess(observation, analysis_as_of=analysis_as_of)
            if assessment.status is FreshnessStatus.UNAVAILABLE:
                continue
            observations.append(observation)
        observations.sort(key=lambda item: item.published_at or item.event_time or item.updated_at or "", reverse=True)
        if not observations:
            return ProviderResult(self.name, ProviderCapability.NEWS, ProviderStatus.UNAVAILABLE, reason="no relevant news as of cutoff")
        return ProviderResult(self.name, ProviderCapability.NEWS, ProviderStatus.AVAILABLE, tuple(observations))

    @staticmethod
    def _to_observation(hit: WebResearchHit, *, retrieved: str, evidence_type: str, instrument_id: str | None, metric: str) -> ProviderObservation:
        return ProviderObservation(
            evidence_type=evidence_type,
            source_name=hit.source_name,
            source_url=hit.source_url,
            source_tier=hit.source_tier,
            provider_id="web_research",
            value=hit.value,
            unit=hit.unit,
            currency=hit.currency,
            instrument_id=instrument_id,
            metric=metric,
            retrieved_at=retrieved,
            observed_at=hit.observed_at,
            published_at=hit.published_at,
            claimed_market_time=hit.claimed_market_time,
            updated_at=hit.updated_at,
            event_time=hit.event_time,
            headline=hit.title,
            official_confirmation_status=hit.official_confirmation_status,
            event_cluster_id=hit.event_cluster_id,
            metadata={"source_kind": hit.source_kind, "snippet": hit.snippet, **hit.metadata},
        )
