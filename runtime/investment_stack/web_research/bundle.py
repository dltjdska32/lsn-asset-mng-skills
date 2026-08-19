"""Serializable Web Research backend bridge for Codex/local-tool supplied hits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from investment_stack.web_research.models import WebResearchHit, WebResearchIntent, WebResearchResponse


class WebResearchBundleBackend:
    """Serve already-retrieved web hits to the existing WebResearchAdapter.

    Codex can perform the external web lookup, save only structured source facts
    into this bundle, and then let the Python runtime enforce as-of/freshness and
    evidence rules.  This keeps web search as an adapter boundary instead of
    letting an LLM bypass run.db lineage.
    """

    def __init__(self, payload: Mapping[str, object]) -> None:
        entries = payload.get("responses")
        if not isinstance(entries, list):
            raise ValueError("web research bundle must contain a responses list")
        self._responses: dict[tuple[str, str], WebResearchResponse] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("web research response entry must be an object")
            intent = WebResearchIntent(str(entry.get("intent")))
            query = str(entry.get("query", "")).strip()
            if not query:
                raise ValueError("web research response query is required")
            raw_hits = entry.get("hits")
            if not isinstance(raw_hits, list):
                raise ValueError("web research response hits must be a list")
            hits = tuple(self._hit(item) for item in raw_hits)
            key = (intent.value, query)
            if key in self._responses:
                raise ValueError(f"duplicate web research response for {intent.value}: {query}")
            self._responses[key] = WebResearchResponse(intent, hits)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "WebResearchBundleBackend":
        with Path(path).open("r", encoding="utf-8") as source:
            payload = json.load(source)
        if not isinstance(payload, Mapping):
            raise ValueError("web research bundle root must be an object")
        return cls(payload)

    def __call__(self, intent: WebResearchIntent, query: str, analysis_as_of: str) -> WebResearchResponse:
        del analysis_as_of  # cutoff enforcement belongs to WebResearchAdapter/FreshnessEngine
        return self._responses.get((intent.value, query), WebResearchResponse(intent, ()))

    @staticmethod
    def _hit(item: object) -> WebResearchHit:
        if not isinstance(item, Mapping):
            raise ValueError("web research hit must be an object")
        required = {"source_name", "source_url", "title"}
        missing = [field for field in required if not str(item.get(field, "")).strip()]
        if missing:
            raise ValueError("web research hit missing required fields: " + ", ".join(sorted(missing)))
        metadata = item.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ValueError("web research hit metadata must be an object")
        return WebResearchHit(
            source_name=str(item["source_name"]),
            source_url=str(item["source_url"]),
            title=str(item["title"]),
            snippet=None if item.get("snippet") is None else str(item.get("snippet")),
            value=item.get("value"),
            unit=None if item.get("unit") is None else str(item.get("unit")),
            currency=None if item.get("currency") is None else str(item.get("currency")),
            observed_at=None if item.get("observed_at") is None else str(item.get("observed_at")),
            published_at=None if item.get("published_at") is None else str(item.get("published_at")),
            claimed_market_time=None if item.get("claimed_market_time") is None else str(item.get("claimed_market_time")),
            updated_at=None if item.get("updated_at") is None else str(item.get("updated_at")),
            event_time=None if item.get("event_time") is None else str(item.get("event_time")),
            source_tier=int(item.get("source_tier", 4)),
            source_kind=str(item.get("source_kind", "web_page")),
            official_confirmation_status=None if item.get("official_confirmation_status") is None else str(item.get("official_confirmation_status")),
            event_cluster_id=None if item.get("event_cluster_id") is None else str(item.get("event_cluster_id")),
            metadata=dict(metadata),
        )
