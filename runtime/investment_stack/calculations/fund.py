"""ETF/fund structure, concentration and look-through calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping

from investment_stack.calculations.common import AnalysisResult, AnalysisStatus, MetricResult


def _after_cutoff(stamp: str, cutoff: str) -> bool:
    """Compare exact aware timestamps when supplied; dates retain day precision."""
    if len(stamp) > 10 and len(cutoff) > 10:
        observed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        pinned = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
        if observed.tzinfo is None or pinned.tzinfo is None:
            raise ValueError('fund observation timestamps must include timezones')
        return observed > pinned
    return date.fromisoformat(stamp[:10]) > date.fromisoformat(cutoff[:10])


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
    market_price_as_of: str | None = None
    nav_as_of: str | None = None
    analysis_as_of: str | None = None
    holdings_max_age_days: int = 90


class FundAnalyzer:
    def analyze(self, data: FundAnalysisInput) -> AnalysisResult:
        metrics: list[MetricResult] = []
        unknowns: list[str] = []
        for name in ('market_price', 'nav_per_share', 'expense_ratio', 'aum', 'average_daily_value', 'tracking_difference'):
            value = getattr(data, name)
            if value is not None and (not value.is_finite() or (name != 'tracking_difference' and value < 0)):
                raise ValueError(name + ' must be finite and nonnegative (tracking difference may be signed)')
            if name in {'market_price', 'nav_per_share'} and value is not None and value <= 0:
                raise ValueError(name + ' must be strictly positive')
        if data.holdings_max_age_days < 0:
            raise ValueError("holdings maximum age must be nonnegative")
        ids = [item.instrument_id for item in data.holdings]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate fund holdings")
        if any(not item.weight.is_finite() or not Decimal("0") <= item.weight <= Decimal("1") for item in data.holdings):
            raise ValueError("fund weights must be finite fractions between zero and one")
        coverage = sum((item.weight for item in data.holdings), Decimal("0"))
        if coverage > Decimal("1"):
            raise ValueError("fund holdings exceed full portfolio weight")
        holdings_current = bool(data.holdings_as_of)
        if data.analysis_as_of and data.holdings_as_of:
            age = (date.fromisoformat(data.analysis_as_of[:10]) - date.fromisoformat(data.holdings_as_of[:10])).days
            holdings_current = 0 <= age <= data.holdings_max_age_days and not _after_cutoff(data.holdings_as_of, data.analysis_as_of)
            if not holdings_current:
                unknowns.append("current_holdings")
        nav_aligned = bool(
            data.market_price_as_of and data.nav_as_of and data.market_price_as_of[:10] == data.nav_as_of[:10])
        if not nav_aligned:
            unknowns.append("aligned_nav_price")
        if data.analysis_as_of and nav_aligned:
            if (_after_cutoff(data.nav_as_of, data.analysis_as_of)
                    or _after_cutoff(data.market_price_as_of, data.analysis_as_of)):
                nav_aligned = False
                unknowns.append('future_nav_or_price')
        premium = None
        if nav_aligned and data.market_price is not None and data.nav_per_share is not None and data.nav_per_share > 0:
            premium = (data.market_price / data.nav_per_share) - Decimal("1")
        metrics.append(MetricResult("nav_premium_discount", premium, "ratio", "market_price / nav_per_share - 1", AnalysisStatus.COMPLETE if premium is not None else AnalysisStatus.UNAVAILABLE, None if premium is not None else "market price or NAV unavailable", data.evidence_ids))
        metrics.append(MetricResult("expense_ratio", data.expense_ratio, "ratio", "issuer_reported", AnalysisStatus.COMPLETE if data.expense_ratio is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("aum", data.aum, "currency", "issuer_reported", AnalysisStatus.COMPLETE if data.aum is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("average_daily_value", data.average_daily_value, "currency/day", "market_reported", AnalysisStatus.COMPLETE if data.average_daily_value is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))
        metrics.append(MetricResult("tracking_difference", data.tracking_difference, "ratio", "fund_return - benchmark_return", AnalysisStatus.COMPLETE if data.tracking_difference is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=data.evidence_ids))

        if data.holdings and holdings_current:
            total = sum((item.weight for item in data.holdings), Decimal("0"))
            if total <= 0:
                raise ValueError("fund holding weights must sum to a positive value")
            top10 = sum(sorted((item.weight for item in data.holdings), reverse=True)[:10], Decimal("0"))
            hhi = sum((item.weight ** 2 for item in data.holdings), Decimal("0"))
            metrics.append(MetricResult("top10_concentration", top10, "ratio", "sum(top 10 holding weights)", evidence_ids=data.evidence_ids))
            metrics.append(MetricResult("holding_hhi", hhi, "index", "sum(weight^2)", evidence_ids=data.evidence_ids))
            metadata = {
                "holdings_as_of": data.holdings_as_of,
                "holdings_weight_coverage": str(coverage),
                "uncovered_holdings_weight": str(max(Decimal('0'), Decimal('1') - coverage)),
                "exposure_denominator": 'full fund weight; partial holdings are not renormalized',
                "sector_exposure": self._aggregate(data.holdings, "sector"),
                "country_exposure": self._aggregate(data.holdings, "country"),
                "currency_exposure": self._aggregate(data.holdings, "currency"),
            }
            if coverage < Decimal("0.999999"):
                unknowns.append("uncovered_holdings_exposure")
            for field in ('sector', 'country', 'currency'):
                missing_classification = sum((item.weight for item in data.holdings if not getattr(item, field)), Decimal('0'))
                metadata[field + '_unknown_weight'] = str(missing_classification + max(Decimal('0'), Decimal('1') - coverage))
                if missing_classification:
                    unknowns.append('unclassified_' + field + '_exposure')
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
        metadata.update({"benchmark": data.benchmark, "distribution_policy": data.distribution_policy,
                         "nav_as_of": data.nav_as_of, "market_price_as_of": data.market_price_as_of,
                         "holdings_current": holdings_current})
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
    _validate_holdings(left)
    _validate_holdings(right)
    a = {item.instrument_id: item.weight for item in left}
    b = {item.instrument_id: item.weight for item in right}
    return sum((min(a[key], b[key]) for key in a.keys() & b.keys()), Decimal("0"))


def _validate_holdings(holdings: tuple[FundHolding, ...]) -> Decimal:
    if len({item.instrument_id for item in holdings}) != len(holdings):
        raise ValueError('duplicate fund holdings')
    if any(not item.weight.is_finite() or not Decimal('0') <= item.weight <= Decimal('1') for item in holdings):
        raise ValueError('fund weights must be finite fractions')
    coverage = sum((item.weight for item in holdings), Decimal('0'))
    if coverage > Decimal('1'):
        raise ValueError('fund holdings exceed full portfolio weight')
    return coverage


def portfolio_fund_lookthrough(funds: Mapping[str, tuple[Decimal, FundAnalysisInput]]) -> dict[str, object]:
    """Fund weights are full portfolio fractions, not renormalized to selected funds.

    Only dated current holdings participate. Missing funds/holdings/classifications
    remain explicit unknown exposure; overlap is a lower bound for partial holdings.
    """
    total = Decimal('0')
    exposures: dict[str, Decimal] = {}
    classifications = {field: {} for field in ('sector', 'country', 'currency')}
    covered = Decimal('0')
    gaps = []
    refs = []
    analyzed_funds = {}
    for fund_id, (portfolio_weight, data) in funds.items():
        if fund_id != data.instrument_id or not portfolio_weight.is_finite() or not Decimal('0') <= portfolio_weight <= Decimal('1'):
            raise ValueError('fund identity and finite portfolio weight required')
        total += portfolio_weight
        result = FundAnalyzer().analyze(data)
        _validate_holdings(data.holdings)
        if (not result.metadata.get('holdings_current') or not data.analysis_as_of
                or not data.holdings or not data.evidence_ids):
            gaps.append(fund_id + ':current_official_holdings_unavailable')
            continue
        analyzed_funds[fund_id] = data
        refs.extend(data.evidence_ids)
        for holding in data.holdings:
            value = portfolio_weight * holding.weight
            covered += value
            exposures[holding.instrument_id] = exposures.get(holding.instrument_id, Decimal('0')) + value
            for field, buckets in classifications.items():
                key = getattr(holding, field) or 'UNKNOWN'
                buckets[key] = buckets.get(key, Decimal('0')) + value
        if result.unknowns:
            gaps.extend(fund_id + ':' + gap for gap in result.unknowns if 'holdings' in gap or 'exposure' in gap)
    if total > Decimal('1'):
        raise ValueError('selected funds exceed full portfolio weight')
    pairs = {}
    for index, left in enumerate(sorted(analyzed_funds)):
        for right in sorted(analyzed_funds)[index + 1:]:
            pairs[left + '|' + right] = {'overlap_lower_bound': str(fund_overlap(analyzed_funds[left].holdings, analyzed_funds[right].holdings)),
                'partial_holdings': any(_validate_holdings(analyzed_funds[key].holdings) < Decimal('1') for key in (left, right))}
    unobserved = max(Decimal('0'), total - covered)
    for buckets in classifications.values():
        if unobserved:
            buckets['UNKNOWN'] = buckets.get('UNKNOWN', Decimal('0')) + unobserved
    return {'status': 'UNAVAILABLE' if not analyzed_funds else 'PARTIAL' if gaps or unobserved else 'COMPLETE',
        'denominator': 'full portfolio weight', 'selected_fund_weight': str(total),
        'covered_portfolio_weight': str(covered), 'unknown_fund_portfolio_weight': str(unobserved),
        'outside_selected_funds_weight': str(Decimal('1') - total),
        'holding_exposure': {key: str(value) for key, value in sorted(exposures.items())},
        **{field + '_exposure': {key: str(value) for key, value in sorted(buckets.items())} for field, buckets in classifications.items()},
        'fund_pair_overlap': pairs, 'gaps': tuple(gaps), 'evidence_ids': tuple(dict.fromkeys(refs))}
