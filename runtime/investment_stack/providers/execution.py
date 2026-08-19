"""Deterministic provider fallback execution without a dynamic DAG."""

from __future__ import annotations

from dataclasses import dataclass

from investment_stack.providers.adapters import ProviderAdapter
from investment_stack.providers.models import ProviderRequest, ProviderResult, ProviderStatus


@dataclass(frozen=True, slots=True)
class FallbackResult:
    results: tuple[ProviderResult, ...]
    selected: ProviderResult | None

    @property
    def partial(self) -> bool:
        return self.selected is None or self.selected.status is ProviderStatus.PARTIAL


class ProviderFallbackExecutor:
    def __init__(self, adapters: list[ProviderAdapter] | tuple[ProviderAdapter, ...]) -> None:
        self._adapters = tuple(adapters)

    def execute(self, request: ProviderRequest) -> FallbackResult:
        results: list[ProviderResult] = []
        selected: ProviderResult | None = None
        for adapter in self._adapters:
            if request.capability not in adapter.capabilities:
                continue
            try:
                result = adapter.fetch(request)
            except Exception as exc:  # adapter boundary: normalize unexpected provider failure
                result = ProviderResult(adapter.name, request.capability, ProviderStatus.ERROR, reason=f"provider adapter failed: {type(exc).__name__}")
            results.append(result)
            if result.usable:
                selected = result
                break
        return FallbackResult(tuple(results), selected)
