"""Freshness and market-session primitives for latest-as-of selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    LAST_VALID_CLOSE = "LAST_VALID_CLOSE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class MarketSession(StrEnum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    SESSION_BREAK = "SESSION_BREAK"
    AFTER_HOURS = "AFTER_HOURS"
    CLOSED = "CLOSED"
    HOLIDAY = "HOLIDAY"
    TWENTY_FOUR_SEVEN = "24_7"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    fresh_for: timedelta
    delayed_for: timedelta

    def __post_init__(self) -> None:
        if self.fresh_for < timedelta(0) or self.delayed_for < self.fresh_for:
            raise ValueError("freshness policy durations are invalid")


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    status: FreshnessStatus
    effective_time: str | None
    age_seconds: int | None
    reason: str
