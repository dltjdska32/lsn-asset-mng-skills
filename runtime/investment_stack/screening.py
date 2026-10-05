"""Bounded equity pre-screening before existing SINGLE_ASSET_ANALYSIS research.

Inputs are supplied evidence snapshots. This module fetches nothing and writes no DB.
Scores prioritize research; they are not investment recommendations.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Mapping

from investment_stack.routing.models import RequestMode


@dataclass(frozen=True, slots=True)
class ScreeningCandidate:
    instrument_id: str
    metrics: Mapping[str, Decimal | None]
    evidence_ids: tuple[str, ...]
    as_of: str
    asset_class: str = "EQUITY"


@dataclass(frozen=True, slots=True)
class ScreeningRow:
    instrument_id: str
    score: Decimal | None
    missing_metrics: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    ranked: tuple[ScreeningRow, ...]
    excluded: tuple[ScreeningRow, ...]
    deep_research: Mapping[str, object]
    mode: RequestMode = RequestMode.SINGLE_ASSET_ANALYSIS


def screen_equities(candidates: tuple[ScreeningCandidate, ...], *,
                    metric_weights: Mapping[str, Decimal], top_n: int,
                    as_of: str, deep_research: Callable[[str, RequestMode], object],
                    max_age_days: int = 45) -> ScreeningResult:
    """Rank 20-100 equities by cross-sectional percentiles, then research Top N.

    Positive weights prefer higher values, negative weights prefer lower values.
    All weighted metrics and dated evidence are required: absent values are never zero.
    """
    if not 20 <= len(candidates) <= 100:
        raise ValueError("screening universe must contain 20-100 equities")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= len(candidates):
        raise ValueError("top_n must be between one and universe size")
    if len({c.instrument_id for c in candidates}) != len(candidates):
        raise ValueError("duplicate screening instrument")
    if max_age_days < 0 or not metric_weights or any(not w.is_finite() or w == 0 for w in metric_weights.values()):
        raise ValueError("finite nonzero metric weights and nonnegative age required")
    run_date = date.fromisoformat(as_of[:10])
    eligible: list[ScreeningCandidate] = []
    excluded: list[ScreeningRow] = []
    for candidate in candidates:
        missing = tuple(sorted(k for k in metric_weights if candidate.metrics.get(k) is None))
        age = (run_date - date.fromisoformat(candidate.as_of[:10])).days
        reason = None
        if candidate.asset_class != "EQUITY":
            reason = "equity-only screening"
        elif not candidate.evidence_ids or not 0 <= age <= max_age_days:
            reason = "missing evidence or stale/future snapshot"
        elif missing:
            reason = "weighted metrics unavailable"
        elif any(not candidate.metrics[k].is_finite() for k in metric_weights):
            reason = "nonfinite metric"
        if reason:
            excluded.append(ScreeningRow(candidate.instrument_id, None, missing, candidate.evidence_ids, "UNAVAILABLE", reason))
        else:
            eligible.append(candidate)
    rows: list[ScreeningRow] = []
    total_weight = sum((abs(w) for w in metric_weights.values()), Decimal("0"))
    for candidate in eligible:
        score = Decimal("0")
        for key, weight in metric_weights.items():
            value = candidate.metrics[key]
            peers = [c.metrics[key] for c in eligible]
            lower = sum(p < value for p in peers)
            tied = sum(p == value for p in peers)
            percentile = ((Decimal(lower) + Decimal(tied - 1) / 2) / (len(peers) - 1)
                          if len(peers) > 1 else Decimal("0.5"))
            score += abs(weight) * (percentile if weight > 0 else 1 - percentile)
        rows.append(ScreeningRow(candidate.instrument_id, score / total_weight, (), candidate.evidence_ids, "RESEARCH_PRIORITY"))
    ranked = tuple(sorted(rows, key=lambda row: (-row.score, row.instrument_id)))
    results = {row.instrument_id: deep_research(row.instrument_id, RequestMode.SINGLE_ASSET_ANALYSIS)
               for row in ranked[:top_n]}
    return ScreeningResult(ranked, tuple(excluded), results)
