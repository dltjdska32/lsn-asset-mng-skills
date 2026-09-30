"""Cut-off aware freshness assessment. Retrieval time is never data time."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from investment_stack.freshness.calendar import ExchangeCalendarSchedule
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
        calendar: ExchangeCalendarSchedule | None = None,
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
        metadata = observation.metadata if isinstance(observation.metadata, dict) else {}
        quote_kind = str(metadata.get("quote_kind", "")).upper()
        session_date_text = observation.market_session_date
        if market_session == MarketSession.TWENTY_FOUR_SEVEN:
            calendar = None
        elif calendar is not None:
            close_result = self._assess_calendar_close(
                observation, cutoff, effective, calendar, quote_kind, session_date_text, age
            )
            if close_result is not None:
                return close_result
        elif market_session in {MarketSession.CLOSED, MarketSession.HOLIDAY}:
            return FreshnessAssessment(
                FreshnessStatus.UNAVAILABLE, effective.isoformat(), int(age.total_seconds()),
                "trusted exchange calendar schedule required to classify a last valid close",
                market_session_date=session_date_text, quote_kind=quote_kind or None,
            )
        if age <= selected_policy.fresh_for:
            status = FreshnessStatus.FRESH
        elif age <= selected_policy.delayed_for:
            status = FreshnessStatus.DELAYED
        else:
            status = FreshnessStatus.STALE
        return FreshnessAssessment(status, effective.isoformat(), int(age.total_seconds()), f"age={int(age.total_seconds())}s")

    @staticmethod
    def _assess_calendar_close(
        observation: ProviderObservation,
        cutoff: datetime,
        effective: datetime,
        calendar: ExchangeCalendarSchedule,
        quote_kind: str,
        session_date_text: str | None,
        age: timedelta,
    ) -> FreshnessAssessment | None:
        def unavailable(reason: str) -> FreshnessAssessment:
            return FreshnessAssessment(
                FreshnessStatus.UNAVAILABLE, effective.isoformat(), int(age.total_seconds()), reason,
                market_session_date=session_date_text, quote_kind=quote_kind or None,
                calendar_id=calendar.schedule_id,
            )

        if not calendar.is_pinned:
            return unavailable("calendar schedule is caller-supplied and not in the pinned trusted registry")
        aliases = {"NMS": "NASDAQ", "NASDAQGS": "NASDAQ", "NYQ": "NYSE", "KS": "KRX", "KQ": "KOSDAQ", "TSE": "JPX"}
        observed_exchange = aliases.get(str(observation.metadata.get("exchange", "")).upper(), str(observation.metadata.get("exchange", "")).upper())
        instrument_prefix = (observation.instrument_id or "").partition(":")[0].upper()
        expected_exchange = aliases.get(instrument_prefix, instrument_prefix)
        if observed_exchange != calendar.exchange.upper() or expected_exchange != calendar.exchange.upper():
            return unavailable("exchange identity does not match the trusted session calendar")
        if str(observation.currency or "").upper() != calendar.currency.upper():
            return unavailable("quote currency does not match the trusted session calendar")
        if not session_date_text or not observation.claimed_market_time:
            return unavailable("market_session_date and claimed_market_time are required")
        try:
            session_date = date.fromisoformat(session_date_text)
            claimed = parse_timestamp(observation.claimed_market_time)
        except (TypeError, ValueError):
            return unavailable("invalid market session date or claimed timestamp")
        if claimed is None:
            return unavailable("claimed market timestamp is unavailable")
        local_claimed = claimed.astimezone(ZoneInfo(calendar.timezone))
        if local_claimed.date() != session_date:
            return unavailable("claimed timestamp local date does not match market_session_date")
        observed = parse_timestamp(observation.observed_at)
        if observed is None or observed != claimed:
            return unavailable("observed_at and claimed_market_time must identify the same quote time")
        published = parse_timestamp(observation.published_at)
        scheduled_session = calendar.session_for_date(session_date)
        cutoff_local = cutoff.astimezone(ZoneInfo(calendar.timezone))
        if not calendar.covers(session_date, cutoff_local.date()):
            return unavailable("trusted calendar schedule does not cover quote and analysis dates")
        active_session = calendar.is_regular_session_open(cutoff)
        if (active_session and scheduled_session is not None and session_date == cutoff_local.date()
                and quote_kind == "REGULAR"):
            if observation.metadata.get("bar_complete") is False or observation.metadata.get("is_complete") is False:
                return unavailable("incomplete same-day bar cannot qualify as a completed close")
            if scheduled_session.opens_at <= claimed <= cutoff:
                return None
            return unavailable("regular-session quote timestamp is outside the open session")
        if observation.metadata.get("bar_complete") is False or observation.metadata.get("is_complete") is False:
            return unavailable("incomplete same-day bar cannot qualify as a last valid close")
        if quote_kind not in {"REGULAR", "LAST_VALID_CLOSE"}:
            return unavailable(f"quote kind {quote_kind or 'UNKNOWN'} cannot qualify as a last valid close")
        if published is None:
            return unavailable("close price publication time is unknown")
        if published < claimed:
            return unavailable("close price publication time precedes the claimed close")
        if published > cutoff:
            return unavailable("close price was not yet published at analysis_as_of")
        if scheduled_session is None:
            return unavailable("quote date is not a trading session in the trusted calendar")
        close_delta = claimed - scheduled_session.closes_at.astimezone(timezone.utc)
        if close_delta < timedelta(0) or close_delta > calendar.close_timestamp_tolerance:
            return unavailable("claimed timestamp does not match the scheduled session close")
        latest = calendar.latest_completed_session(cutoff)
        if latest is None:
            return unavailable("calendar cannot establish a latest completed session at cutoff")
        if active_session:
            return None
        if latest.session_date != session_date:
            return None
        local_close = scheduled_session.closes_at.astimezone(ZoneInfo(calendar.timezone))
        current_session = calendar.session_for_date(cutoff_local.date())
        pre_open = current_session is not None and cutoff < current_session.opens_at
        context = "개장 전 직전 유효 거래일 종가" if pre_open else "휴장 중 마지막 유효 거래일 종가"
        return FreshnessAssessment(
            FreshnessStatus.LAST_VALID_CLOSE, claimed.isoformat(), int(age.total_seconds()),
            f"{context}: {calendar.exchange} {session_date.isoformat()} 종가 시각 {local_close.isoformat()}; 공개가능시각 {published.astimezone(ZoneInfo(calendar.timezone)).isoformat()}",
            market_session_date=session_date.isoformat(), quote_kind=quote_kind,
            calendar_id=calendar.schedule_id, public_available_time=published.isoformat(),
        )

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
