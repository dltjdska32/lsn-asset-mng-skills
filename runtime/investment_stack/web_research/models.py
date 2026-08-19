"""Typed web-research fallback contracts. No separate news database exists."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WebResearchIntent(StrEnum):
    LATEST_CURRENT_DATA = "LATEST_CURRENT_DATA"
    LATEST_RELEVANT_NEWS = "LATEST_RELEVANT_NEWS"


@dataclass(frozen=True, slots=True)
class WebResearchHit:
    source_name: str
    source_url: str
    title: str
    snippet: str | None = None
    value: Any = None
    unit: str | None = None
    currency: str | None = None
    observed_at: str | None = None
    published_at: str | None = None
    claimed_market_time: str | None = None
    updated_at: str | None = None
    event_time: str | None = None
    source_tier: int = 4
    source_kind: str = "web_page"
    official_confirmation_status: str | None = None
    event_cluster_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebResearchResponse:
    intent: WebResearchIntent
    hits: tuple[WebResearchHit, ...]
