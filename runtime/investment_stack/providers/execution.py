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

    def _is_eligible_for_purpose(self, request: ProviderRequest, result: ProviderResult) -> bool:
        if not result.usable:
            return False

        from investment_stack.providers.registry import ProviderCapability
        
        if request.capability == ProviderCapability.CURRENT_PRICE:
            from investment_stack.freshness.engine import FreshnessEngine
            from investment_stack.freshness.models import FreshnessStatus
            from decimal import Decimal, InvalidOperation

            engine = FreshnessEngine()
            has_eligible = False
            for obs in result.observations:
                try:
                    assessment = engine.assess(obs, analysis_as_of=request.analysis_as_of)
                except ValueError:
                    return False
                if assessment.status != FreshnessStatus.FRESH:
                    return False
                if request.instrument_id and obs.instrument_id != request.instrument_id:
                    return False
                expected_currency = request.parameters.get("quote_currency")
                if expected_currency and obs.currency != expected_currency:
                    return False
                
                if isinstance(obs.value, bool):
                    return False
                try:
                    val = Decimal(str(obs.value))
                    if not val.is_finite() or val <= 0:
                        return False
                except (ValueError, TypeError, InvalidOperation):
                    return False
                has_eligible = True
            return has_eligible

        elif request.capability == ProviderCapability.FUNDAMENTALS:
            from investment_stack.freshness.engine import parse_timestamp, observation_time
            from decimal import Decimal, InvalidOperation
            
            try:
                cutoff = parse_timestamp(request.analysis_as_of)
            except ValueError:
                return False
            if not cutoff:
                return False

            required_metrics = request.parameters.get("required_metrics")
            req_set = set()
            if required_metrics is not None:
                if not isinstance(required_metrics, (list, tuple, set)):
                    return False
                if not all(isinstance(m, str) and m.strip() for m in required_metrics):
                    return False
                req_set = set(m.strip() for m in required_metrics)

            found_metrics_by_group: dict[tuple, set[str]] = {}
            has_approved_numeric = False

            for obs in result.observations:
                if not obs.metadata.get("calculation_input_approved", True):
                    continue
                
                if request.instrument_id and obs.instrument_id != request.instrument_id:
                    continue
                
                try:
                    eff = observation_time(obs)
                except ValueError:
                    continue
                    
                if not eff or eff > cutoff:
                    continue
                
                if isinstance(obs.value, bool):
                    continue
                try:
                    val = Decimal(str(obs.value))
                    if not val.is_finite():
                        continue
                except (ValueError, TypeError, InvalidOperation):
                    continue
                
                has_approved_numeric = True
                if obs.metric:
                    group_key = (
                        str(obs.metadata.get("period_end", "")),
                        str(obs.metadata.get("start", "")),
                        str(obs.currency or ""),
                        str(obs.metadata.get("reporting_frequency", "")),
                        str(obs.metadata.get("accounting_standard", "")),
                        str(obs.metadata.get("consolidation", "")),
                        str(obs.metadata.get("adjustment_basis", ""))
                    )
                    found_metrics_by_group.setdefault(group_key, set()).add(obs.metric)

            if not has_approved_numeric:
                return False

            if req_set:
                satisfies_requirements = False
                for group_key, group_metrics in found_metrics_by_group.items():
                    period_end = group_key[0]
                    if not period_end:
                        continue
                    if req_set.issubset(group_metrics):
                        satisfies_requirements = True
                        break
                if not satisfies_requirements:
                    return False

            return True

        return True

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
            if self._is_eligible_for_purpose(request, result):
                selected = result
                break
        return FallbackResult(tuple(results), selected)
