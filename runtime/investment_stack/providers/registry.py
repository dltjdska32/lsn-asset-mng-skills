"""Capability-first provider selection with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from investment_stack.providers.credentials import EnvironmentCredentials


class ProviderCapability(StrEnum):
    CURRENT_PRICE = "current_price"
    HISTORICAL_PRICE = "historical_price"
    FUNDAMENTALS = "fundamentals"
    FUND_HOLDINGS = "fund_holdings"
    MACRO = "macro"
    NEWS = "news"
    FX = "fx"


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    capabilities: frozenset[ProviderCapability]
    priority: int = 100
    credential_env: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Provider name must not be empty")
        if not self.capabilities:
            raise ValueError(f"Provider {self.name!r} must declare at least one capability")
        if self.credential_env is not None:
            EnvironmentCredentials.validate_name(self.credential_env)


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str
    eligible: bool
    reason: str

    def as_dict(self) -> dict[str, str | bool]:
        return {"provider": self.provider, "eligible": self.eligible, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    capability: ProviderCapability
    selected: ProviderSpec | None
    attempts: tuple[ProviderAttempt, ...]

    @property
    def available(self) -> bool:
        return self.selected is not None

    @property
    def partial_required(self) -> bool:
        return self.selected is None

    def as_dict(self) -> dict[str, str | bool | list[dict[str, str | bool]] | None]:
        return {
            "capability": self.capability.value,
            "available": self.available,
            "partial_required": self.partial_required,
            "selected": None if self.selected is None else self.selected.name,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


class ProviderRegistry:
    """Register providers once and resolve by priority without leaking secrets."""

    def __init__(
        self,
        providers: tuple[ProviderSpec, ...] | list[ProviderSpec] = (),
        *,
        credentials: EnvironmentCredentials | None = None,
    ) -> None:
        self._credentials = credentials or EnvironmentCredentials()
        names = [provider.name.casefold() for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("Provider names must be unique (case-insensitive)")
        self._providers = tuple(sorted(providers, key=lambda provider: (provider.priority, provider.name)))

    @property
    def providers(self) -> tuple[ProviderSpec, ...]:
        return self._providers

    def resolve(self, capability: str | ProviderCapability) -> ProviderResolution:
        parsed = ProviderCapability(capability)
        attempts: list[ProviderAttempt] = []
        selected: ProviderSpec | None = None

        for provider in self._providers:
            if parsed not in provider.capabilities:
                continue
            if not provider.enabled:
                attempts.append(ProviderAttempt(provider.name, False, "disabled"))
                continue
            if provider.credential_env and self._credentials.get(provider.credential_env) is None:
                attempts.append(ProviderAttempt(provider.name, False, "credential unavailable"))
                continue
            attempts.append(ProviderAttempt(provider.name, True, "eligible"))
            selected = provider
            break

        return ProviderResolution(parsed, selected, tuple(attempts))

