"""ETF/fund structure, concentration and look-through calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult


@dataclass(frozen=True, slots=True)
class FundHolding:
    instrument_id: str
    weight: Decimal
    sector: str | None = None
    country: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class FundAnalysisInput:
    instrument_id: str
    market_price: Decimal | None
    nav_per_share: Decimal | None
    expense_ratio: Decimal | None
    aum: Decimal | None
    average_daily_value: Decimal | None
    holdings: tuple[FundHolding, ...] = ()
    holdings_as_of: str | None = None
    benchmark: str | None = None
    distribution_policy: str | None = None
    tracking_difference: Decimal | None = None
    leveraged: bool = False
    inverse: bool = False
    evidence_ids: tuple[str, ...] = ()


class FundAnalyzer:
    def analyze(self, data: FundAnalysisInput) -> AnalysisResult:
        metrics: list[MetricResult] = []
        unknowns: list[str] = []
        premium = None
        if data.market_price is not None and data.nav_per_share not in (None, Decimal("0")):
            premium = (data.market_price / data.nav_per_share) - Decimal("1")
        metrics.append(MetricResult("nav_premium_discount", premium, "ratio", "market_price / nav_per_share - 1", AnalysisStatus.COMPLETE if premium is not None else AnalysisStatus.UNAVAILABLE, None if premium is not None else "market price or NAV unavailable", data.evidence_ids))
        metrics.append(MetricResult("expense_ratio", data.expense_ratio, "ratio", "issuer_reported", AnalysisStatus.COMPLETE if data.expense_ratio is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("aum", data.aum, "currency", "issuer_reported", AnalysisStatus.COMPLETE if data.aum is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("average_daily_value", data.average_daily_value, "currency/day", "market_reported", AnalysisStatus.COMPLETE if data.average_daily_value is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("tracking_difference", data.tracking_difference, "ratio", "fund_return - benchmark_return", AnalysisStatus.COMPLETE if data.tracking_difference is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))

        if data.holdings and data.holdings_as_of:
            total = sum((item.weight for item in data.holdings), Decimal("0"))
            if total <= 0:
                raise ValueError("fund holding weights must sum to a positive value")
            top10 = sum(sorted((item.weight for item in data.holdings), reverse=True)[:10], Decimal("0"))
            hhi = sum((item.weight ** 2 for item in data.holdings), Decimal("0"))
            metrics.append(MetricResult("top10_concentration", top10, "ratio", "sum(top 10 holding weights)", evidence_ids=data.evidence_ids))
            metrics.append(MetricResult("holding_hhi", hhi, "index", "sum(weight^2)", evidence_ids=data.evidence_ids))
            metadata = {
                "holdings_as_of": data.holdings_as_of,
                "sector_exposure": self._aggregate(data.holdings, "sector"),
                "country_exposure": self._aggregate(data.holdings, "country"),
                "currency_exposure": self._aggregate(data.holdings, "currency"),
            }
        else:
            unknowns.append("look_through_exposure")
            metadata = {"holdings_as_of": data.holdings_as_of}
        risks: list[str] = []
        if data.leveraged:
            risks.append("leveraged fund exposure")
        if data.inverse:
            risks.append("inverse fund exposure")
        if data.holdings and not data.holdings_as_of:
            risks.append("holdings date unavailable; look-through is not treated as current")
            unknowns.append("holdings_as_of")
        available = sum(metric.value is not None for metric in metrics)
        has_structure_context = bool(data.holdings or data.benchmark or data.distribution_policy)
        status = AnalysisStatus.COMPLETE if not unknowns else (AnalysisStatus.PARTIAL if available or has_structure_context else AnalysisStatus.UNAVAILABLE)
        metadata.update({"benchmark": data.benchmark, "distribution_policy": data.distribution_policy})
        return AnalysisResult(data.instrument_id, "FUND", status, tuple(metrics), (), tuple(risks), tuple(sorted(set(unknowns))), metadata)

    @staticmethod
    def _aggregate(holdings: tuple[FundHolding, ...], field: str) -> dict[str, str]:
        result: dict[str, Decimal] = {}
        for item in holdings:
            key = getattr(item, field)
            if key:
                result[key] = result.get(key, Decimal("0")) + item.weight
        return {key: str(value) for key, value in sorted(result.items())}


def fund_overlap(left: tuple[FundHolding, ...], right: tuple[FundHolding, ...]) -> Decimal | None:
    if not left or not right:
        return None
    a = {item.instrument_id: item.weight for item in left}
    b = {item.instrument_id: item.weight for item in right}
    return sum((min(a[key], b[key]) for key in a.keys() & b.keys()), Decimal("0"))
