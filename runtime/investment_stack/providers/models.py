"""Typed provider contracts used by Phase 4 research flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from investment_stack.contracts.errors import ContractValidationError
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

    def __post_init__(self) -> None:
        if isinstance(self.source_tier, bool) or not isinstance(self.source_tier, int):
            raise ContractValidationError(
                f"source_tier must be integer, got {type(self.source_tier).__name__}"
            )
        if isinstance(self.metadata, dict):
            for k, v in self.metadata.items():
                if isinstance(v, float):
                    raise ContractValidationError(f"Float/non-finite value in metadata for key {k!r}: {v}")
                if isinstance(v, Decimal) and not v.is_finite():
                    raise ContractValidationError(f"Non-finite Decimal in metadata for key {k!r}: {v}")

    def to_contract_envelope(self) -> dict[str, Any]:
        """Wrap observation into a versioned contract envelope."""
        from investment_stack.providers.contract_adapters import observation_to_contract_envelope

        return observation_to_contract_envelope(self)

    @classmethod
    def from_contract_envelope(cls, envelope: dict[str, Any]) -> ProviderObservation:
        """Reconstruct a ProviderObservation from a versioned contract envelope."""
        from investment_stack.contracts.codec import decode_contract

        return decode_contract(envelope, expected_kind="ProviderObservation")


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
