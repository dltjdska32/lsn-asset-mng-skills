"""Deterministic event impact gate.

This does not score headlines, invent materiality thresholds, or change D12
entry prices. An event affects valuation or the investment thesis only when
the stored record explicitly says so.
"""

from __future__ import annotations

from dataclasses import dataclass


_CATEGORIES = frozenset({
    "guidance", "earnings", "capex", "major_contract", "credit",
    "regulation", "capacity", "management",
})
_IMPACTS = frozenset({"VALUATION", "THESIS", "NONE"})


@dataclass(frozen=True, slots=True)
class EventImpact:
    status: str
    category: str | None
    reason: str


def classify_event_impact(document: object) -> EventImpact:
    """Classify one stored event record. Missing proof stays WAIT."""
    if not isinstance(document, dict) or document.get("record_type") != "event_impact_v1":
        return EventImpact("WAIT", None, "event impact record is missing")
    category = str(document.get("category") or "").casefold()
    impact = str(document.get("impact") or "").upper()
    excerpt = document.get("source_excerpt")
    if category not in _CATEGORIES or impact not in _IMPACTS:
        return EventImpact("WAIT", None, "event category or impact is not explicit")
    if not isinstance(excerpt, str) or len(excerpt.strip()) < 24 or category not in excerpt.casefold() or impact not in excerpt:
        return EventImpact("WAIT", category, "event impact is not contained in a source excerpt")
    if impact == "NONE":
        return EventImpact("NOT_MATERIAL", category, "stored record says the event does not change valuation or the thesis")
    if impact == "VALUATION":
        return EventImpact("MATERIAL_TO_VALUATION", category, "stored record says the event affects valuation inputs")
    return EventImpact("MATERIAL_TO_THESIS", category, "stored record says the event affects the investment thesis")
