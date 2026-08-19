"""Cut-off aware freshness assessment. Retrieval time is never data time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from investment_stack.freshness.models import FreshnessAssessment, FreshnessPolicy, FreshnessStatus, MarketSession
from investment_stack.providers.models import ProviderObservation


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def observation_time(observation: ProviderObservation) -> datetime | None:
    # observed/market/event/published are data-time candidates. retrieved_at is not.
    for value in (
        observation.observed_at,
        observation.claimed_market_time,
        observation.event_time,
        observation.published_at,
        observation.updated_at,
    ):
        parsed = parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


class FreshnessEngine:
    def __init__(self, default_policy: FreshnessPolicy | None = None) -> None:
        self.default_policy = default_policy or FreshnessPolicy(
            fresh_for=timedelta(minutes=20), delayed_for=timedelta(days=1)
        )

    def assess(
        self,
        observation: ProviderObservation,
        *,
        analysis_as_of: str,
        policy: FreshnessPolicy | None = None,
        market_session: MarketSession | None = None,
    ) -> FreshnessAssessment:
        cutoff = parse_timestamp(analysis_as_of)
        if cutoff is None:
            raise ValueError("analysis_as_of is required")
        effective = observation_time(observation)
        if effective is None:
            return FreshnessAssessment(FreshnessStatus.UNKNOWN, None, None, "observation time unavailable")
        if effective > cutoff:
            return FreshnessAssessment(FreshnessStatus.UNAVAILABLE, effective.isoformat(), None, "observation is after analysis_as_of")
        age = cutoff - effective
        selected_policy = policy or self.default_policy
        if market_session in {MarketSession.CLOSED, MarketSession.HOLIDAY} and observation.market_session_date:
            return FreshnessAssessment(FreshnessStatus.LAST_VALID_CLOSE, effective.isoformat(), int(age.total_seconds()), "latest completed market session")
        if age <= selected_policy.fresh_for:
            status = FreshnessStatus.FRESH
        elif age <= selected_policy.delayed_for:
            status = FreshnessStatus.DELAYED
        else:
            status = FreshnessStatus.STALE
        return FreshnessAssessment(status, effective.isoformat(), int(age.total_seconds()), f"age={int(age.total_seconds())}s")

    def latest_as_of(
        self,
        observations: Iterable[ProviderObservation],
        *,
        analysis_as_of: str,
    ) -> ProviderObservation | None:
        cutoff = parse_timestamp(analysis_as_of)
        if cutoff is None:
            raise ValueError("analysis_as_of is required")
        eligible: list[tuple[datetime, int, ProviderObservation]] = []
        for observation in observations:
            timestamp = observation_time(observation)
            if timestamp is None or timestamp > cutoff:
                continue
            # Lower source tier is more authoritative when effective timestamps tie.
            eligible.append((timestamp, -observation.source_tier, observation))
        if not eligible:
            return None
        eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return eligible[0][2]
