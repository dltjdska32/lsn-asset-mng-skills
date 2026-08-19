"""Typed provider contracts used by Phase 4 research flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from investment_stack.providers.registry import ProviderCapability


class ProviderStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    capability: ProviderCapability
    analysis_as_of: str
    analysis_timezone: str
    instrument_id: str | None = None
    metric: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    evidence_type: str
    source_name: str
    source_url: str | None
    source_tier: int
    provider_id: str
    value: Any = None
    unit: str | None = None
    currency: str | None = None
    instrument_id: str | None = None
    metric: str | None = None
    retrieved_at: str | None = None
    observed_at: str | None = None
    published_at: str | None = None
    claimed_market_time: str | None = None
    market_session_date: str | None = None
    updated_at: str | None = None
    event_time: str | None = None
    headline: str | None = None
    official_confirmation_status: str | None = None
    event_cluster_id: str | None = None
    relevance_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: str
    capability: ProviderCapability
    status: ProviderStatus
    observations: tuple[ProviderObservation, ...] = ()
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL} and bool(
            self.observations
        )
