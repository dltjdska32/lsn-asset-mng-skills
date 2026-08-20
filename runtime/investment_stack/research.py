"""Fixed Phase 4 provider -> web fallback -> freshness -> run.db evidence flow."""

from __future__ import annotations

from dataclasses import dataclass

from investment_stack.evidence import EvidenceResearchStore, SelectedEvidence
from investment_stack.freshness import FreshnessStatus
from investment_stack.providers import ProviderFallbackExecutor, ProviderRequest
from investment_stack.providers.models import ProviderResult
from investment_stack.providers.registry import ProviderCapability
from investment_stack.web_research import WebResearchAdapter


@dataclass(frozen=True, slots=True)
class ResearchOutcome:
    selected: SelectedEvidence
    provider_results: tuple[ProviderResult, ...]
    used_web_fallback: bool


class Phase4ResearchRuntime:
    """A fixed research flow, deliberately not a general task graph."""

    def __init__(
        self,
        *,
        providers: ProviderFallbackExecutor,
        evidence: EvidenceResearchStore,
        web_research: WebResearchAdapter | None = None,
    ) -> None:
        self.providers = providers
        self.evidence = evidence
        self.web_research = web_research

    def collect(self, request: ProviderRequest, *, web_query: str | None = None) -> ResearchOutcome:
        fallback = self.providers.execute(request)
        results = list(fallback.results)
        selected = self.evidence.persist_and_select(results, analysis_as_of=request.analysis_as_of)
        used_web = False
        current_price_needs_retry = (
            request.capability is ProviderCapability.CURRENT_PRICE
            and (
                selected.observation is None
                or selected.freshness is None
                or selected.freshness.status in {FreshnessStatus.STALE, FreshnessStatus.UNKNOWN, FreshnessStatus.UNAVAILABLE}
            )
        )
        if (selected.observation is None or current_price_needs_retry) and self.web_research is not None and web_query:
            if request.capability is ProviderCapability.CURRENT_PRICE:
                web_result = self.web_research.fetch_current(
                    web_query,
                    analysis_as_of=request.analysis_as_of,
                    instrument_id=request.instrument_id,
                    metric=request.metric or "current_price",
                )
            elif request.capability is ProviderCapability.NEWS:
                web_result = self.web_research.fetch_news(
                    web_query,
                    analysis_as_of=request.analysis_as_of,
                    instrument_id=request.instrument_id,
                )
            else:
                evidence_type = {
                    ProviderCapability.FUNDAMENTALS: "financial",
                    ProviderCapability.MACRO: "macro",
                    ProviderCapability.FX: "market",
                    ProviderCapability.HISTORICAL_PRICE: "market",
                    ProviderCapability.FUND_HOLDINGS: "financial",
                }.get(request.capability, "evidence")
                web_result = self.web_research.fetch_latest_data(
                    web_query,
                    capability=request.capability,
                    analysis_as_of=request.analysis_as_of,
                    instrument_id=request.instrument_id,
                    evidence_type=evidence_type,
                    metric=request.metric or request.capability.value,
                )
            if web_result is not None:
                used_web = True
                results.append(web_result)
                selected = self.evidence.persist_and_select((web_result,), analysis_as_of=request.analysis_as_of)
        return ResearchOutcome(selected, tuple(results), used_web)
