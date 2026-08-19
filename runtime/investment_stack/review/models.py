"""Typed Phase 6 conditional-review contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from investment_stack.reporting.models import Confidence


class FindingSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewTrigger(StrEnum):
    HIGH_MATERIALITY = "HIGH_MATERIALITY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    STALE_OR_UNKNOWN_CRITICAL_DATA = "STALE_OR_UNKNOWN_CRITICAL_DATA"
    NEW_INSTRUMENT = "NEW_INSTRUMENT"
    LARGE_NET_WORTH_IMPACT = "LARGE_NET_WORTH_IMPACT"
    UNSUPPORTED_IN_KIND_TRANSFER = "UNSUPPORTED_IN_KIND_TRANSFER"
    HIGH_IMPACT_BOOTSTRAP_OR_REPAIR = "HIGH_IMPACT_BOOTSTRAP_OR_REPAIR"
    NEWS_REPORTED_OR_RUMOR_MATERIAL = "NEWS_REPORTED_OR_RUMOR_MATERIAL"
    STRONG_STRATEGY_CHANGE = "STRONG_STRATEGY_CHANGE"
    LINEAGE_FAILURE = "LINEAGE_FAILURE"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    severity: FindingSeverity
    code: str
    text: str
    status: str = "OPEN"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewContext:
    critical_evidence_ids: tuple[str, ...] = ()
    base_case_evidence_ids: tuple[str, ...] = ()
    high_materiality: bool = False
    requested_confidence: Confidence | None = None
    new_instrument: bool = False
    large_net_worth_impact: bool = False
    unsupported_in_kind_transfer: bool = False
    high_impact_bootstrap_or_repair: bool = False
    strong_strategy_change: bool = False
    unsupported_model: bool = False


@dataclass(frozen=True, slots=True)
class ReviewPacket:
    run_id: str
    triggers: tuple[ReviewTrigger, ...]
    findings: tuple[ReviewFinding, ...]
    context: ReviewContext


@dataclass(frozen=True, slots=True)
class ReviewResult:
    required: bool
    triggers: tuple[ReviewTrigger, ...]
    findings: tuple[ReviewFinding, ...]
    confidence: Confidence
    independent_reviewer_used: bool = False
