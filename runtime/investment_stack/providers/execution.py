"""Deterministic provider fallback execution without a dynamic DAG."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic
from investment_stack.providers.health import BoundedProviderCalls, ProviderExecutionPolicy

from investment_stack.providers.adapters import ProviderAdapter
from investment_stack.providers.models import ProviderRequest, ProviderResult, ProviderStatus


def assess_current_price_observation(observation, *, analysis_as_of: str, engine=None):
    """Apply the shared pinned-calendar rule for equity closes and age rule for crypto."""
    from investment_stack.freshness import FreshnessEngine
    from investment_stack.freshness.calendar import get_pinned_calendar
    from investment_stack.freshness.models import FreshnessStatus

    engine = engine or FreshnessEngine()
    iid = str(observation.metadata.get("quote_listing_id") or observation.instrument_id or "").upper()
    prefix = iid.partition(":")[0]
    aliases = {"KS": "KRX", "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NASDAQGS": "NASDAQ"}
    exchange = aliases.get(prefix, prefix)
    if prefix == "CRYPTO":
        calendar = None
    elif exchange in {"NASDAQ", "KRX", "NYSE", "JPX"}:
        calendar = get_pinned_calendar(exchange)
        if calendar is None:
            from investment_stack.freshness import FreshnessAssessment
            return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, None, None, "pinned exchange calendar required")
    elif observation.market_session_date or observation.metadata.get("quote_kind"):
        # A dated equity close without a recognized exchange calendar is never inferred.
        from investment_stack.freshness import FreshnessAssessment
        return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, None, None, "pinned exchange calendar required")
    else:
        return engine.assess(observation, analysis_as_of=analysis_as_of)

    if calendar is not None:
        expected = {"NASDAQ": "USD", "KRX": "KRW", "NYSE": "USD", "JPX": "JPY"}[exchange]
        if (observation.currency or "").upper() != expected:
            from investment_stack.freshness import FreshnessAssessment
            return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, None, None, "quote currency does not match exchange")
        declared = str(observation.metadata.get("exchange", "")).upper()
        declared = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "TSE": "JPX", "KS": "KRX"}.get(declared, declared)
        if declared != exchange:
            from investment_stack.freshness import FreshnessAssessment
            return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, None, None, "quote exchange does not match instrument")
    from dataclasses import replace
    calendar_observation = replace(observation, instrument_id=iid)
    return engine.assess(calendar_observation, analysis_as_of=analysis_as_of, calendar=calendar)


def assess_fund_structure_observation(observation, *, analysis_as_of, engine):
    """Daily official KRX baskets use the pinned completed session, not quote age."""
    from datetime import date
    from zoneinfo import ZoneInfo
    from investment_stack.freshness import FreshnessAssessment, FreshnessStatus
    from investment_stack.freshness.calendar import get_pinned_calendar
    from investment_stack.freshness.engine import parse_timestamp, observation_time
    md = observation.metadata
    if (observation.provider_id != 'official_funds' or observation.source_tier != 1
            or not str(md.get('listing_id', '')).startswith('KRX:')):
        return engine.assess(observation, analysis_as_of=analysis_as_of)
    cutoff = parse_timestamp(analysis_as_of)
    if cutoff is None:
        raise ValueError('analysis_as_of is required')
    try:
        effective = observation_time(observation)
        published = parse_timestamp(observation.published_at)
        retrieved = parse_timestamp(observation.retrieved_at)
    except (TypeError, ValueError):
        return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, None, None,
            'invalid official fund timestamp')
    def assessment(status, reason):
        return FreshnessAssessment(status, effective.isoformat() if effective else None,
            int((cutoff-effective).total_seconds()) if effective else None, reason)
    if str(observation.currency or '').upper() != 'KRW':
        return assessment(FreshnessStatus.UNAVAILABLE, 'official KRX fund currency mismatch')
    if (effective is None or effective > cutoff or (published and published > cutoff)
            or retrieved is None or retrieved < max(effective, published or effective)):
        return assessment(FreshnessStatus.UNAVAILABLE, 'invalid official fund observation/publication/retrieval time')
    calendar = get_pinned_calendar('KRX')
    if calendar is None or not calendar.is_pinned:
        return assessment(FreshnessStatus.UNAVAILABLE, 'pinned KRX calendar unavailable')
    local_day = cutoff.astimezone(ZoneInfo(calendar.timezone)).date()
    dates = []
    try:
        for key in ('nav_as_of', 'holdings_as_of'):
            if md.get(key):
                dates.append(date.fromisoformat(md[key]))
    except (TypeError, ValueError):
        return assessment(FreshnessStatus.UNAVAILABLE, 'invalid official fund data date')
    latest = calendar.latest_completed_session(cutoff)
    if (not dates or latest is None or not calendar.covers(min(dates), local_day)
            or effective.astimezone(ZoneInfo(calendar.timezone)).date() != max(dates)):
        return assessment(FreshnessStatus.UNAVAILABLE, 'official fund dates cannot be bound to pinned KRX calendar')
    if any(day > latest.session_date for day in dates):
        return assessment(FreshnessStatus.UNAVAILABLE, 'official fund date is beyond latest completed session')
    if any(day != latest.session_date for day in dates):
        return assessment(FreshnessStatus.STALE, 'official fund NAV/basket is older than latest completed session')
    return assessment(FreshnessStatus.FRESH,
        'daily official fund NAV/basket matches pinned latest completed KRX session; not an intraday quote')


@dataclass(frozen=True, slots=True)
class FallbackResult:
    results: tuple[ProviderResult, ...]
    selected: ProviderResult | None

    @property
    def partial(self) -> bool:
        return self.selected is None or self.selected.status is ProviderStatus.PARTIAL


class ProviderFallbackExecutor:
    def __init__(self, adapters: list[ProviderAdapter] | tuple[ProviderAdapter, ...], *, freshness_engine=None, policy=None) -> None:
        self._adapters = tuple(adapters)
        self.freshness_engine = freshness_engine
        self.policy = policy or ProviderExecutionPolicy()
        self.health = BoundedProviderCalls()

    def _is_eligible_for_purpose(self, request: ProviderRequest, result: ProviderResult) -> bool:
        if not result.usable:
            return False

        from investment_stack.providers.registry import ProviderCapability
        
        if request.capability == ProviderCapability.CURRENT_PRICE:
            from investment_stack.freshness.models import FreshnessStatus
            from decimal import Decimal, InvalidOperation

            has_eligible = False
            for obs in result.observations:
                try:
                    assessment = assess_current_price_observation(obs, analysis_as_of=request.analysis_as_of, engine=self.freshness_engine)
                except ValueError:
                    return False
                if assessment.status not in {FreshnessStatus.FRESH, FreshnessStatus.LAST_VALID_CLOSE}:
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
        deadline = monotonic() + self.policy.total_timeout_seconds
        for adapter in self._adapters:
            if request.capability not in adapter.capabilities:
                continue
            key = (adapter.name, request.capability)
            blocked = self.health.blocked_reason(key)
            if blocked:
                results.append(ProviderResult(adapter.name, request.capability, ProviderStatus.UNAVAILABLE,
                    reason=blocked, metadata={"health_status": "SKIPPED"}))
                continue
            for attempt in range(self.policy.max_retries + 1):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    result = ProviderResult(adapter.name, request.capability, ProviderStatus.ERROR,
                        reason="provider execution total time budget exhausted", metadata={"health_status": "BUDGET_EXHAUSTED"})
                    results.append(result)
                    break
                try:
                    result = self.health.call(key, lambda: adapter.fetch(request),
                        min(remaining, self.policy.attempt_timeout_seconds))
                    if not isinstance(result, ProviderResult) or result.capability != request.capability:
                        raise ValueError("invalid provider result contract")
                except Exception as exc:  # never reflect potentially credential-bearing messages
                    result = ProviderResult(adapter.name, request.capability, ProviderStatus.ERROR,
                        reason=f"provider adapter failed: {type(exc).__name__}",
                        metadata={"health_status": "TIMEOUT" if isinstance(exc, TimeoutError) else "ERROR"})
                result = replace(result, metadata={**result.metadata, "attempt_number": attempt + 1})
                results.append(result)
                if result.status is not ProviderStatus.ERROR:
                    self.health.mark_healthy(key)
                    break
                if self.health.blocked_reason(key):  # timed-out work is never retried concurrently
                    break
            if result.status is ProviderStatus.ERROR:
                self.health.mark_failed(key, self.policy.cooldown_seconds)
            if self._is_eligible_for_purpose(request, result):
                selected = result
                break
        return FallbackResult(tuple(results), selected)
