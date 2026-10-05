"""Descriptive risk proxies; never an approved covariance or limit assessment."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from investment_stack.calculations.common import (
    AnalysisResult, AnalysisStatus, MetricResult, max_drawdown, sample_stddev, simple_returns,
)


@dataclass(frozen=True, slots=True)
class ProxyExposure:
    instrument_id: str
    value: Decimal | None
    currency: str
    asset_class: str | None = None
    sector: str | None = None


@dataclass(frozen=True, slots=True)
class ProxyPriceSeries:
    instrument_id: str
    frequency: str
    currency: str
    dates: tuple[str, ...]
    prices: tuple[Decimal, ...]
    evidence_ids: tuple[str, ...] = ()


def analyze_risk_proxy(exposures: tuple[ProxyExposure, ...], *, evaluation_currency: str,
                       series: tuple[ProxyPriceSeries, ...] = (),
                       full_denominator: Decimal | None = None,
                       evidence_ids: tuple[str, ...] = ()) -> AnalysisResult:
    """Use only known values; native currency is denomination, not economic FX sensitivity."""
    if len({item.instrument_id for item in exposures}) != len(exposures):
        raise ValueError('duplicate proxy exposure')
    if len({item.instrument_id for item in series}) != len(series):
        raise ValueError('duplicate proxy price series')
    for item in exposures:
        if item.value is not None and (not item.value.is_finite() or item.value < 0):
            raise ValueError('proxy values must be finite and nonnegative')
    known = tuple(item for item in exposures if item.value is not None)
    subtotal = sum((item.value for item in known), Decimal('0'))
    if full_denominator is not None and (not full_denominator.is_finite() or full_denominator < subtotal):
        raise ValueError('full denominator cannot be below known subtotal')
    weights = {item.instrument_id: item.value / subtotal for item in known} if subtotal > 0 else {}
    coverage = Decimal(len(known)) / Decimal(len(exposures)) if exposures else None
    gaps = ['unvalued:' + item.instrument_id for item in exposures if item.value is None]
    aggregate: dict[str, dict[str, str]] = {}
    for field in ('currency', 'asset_class', 'sector'):
        buckets: dict[str, Decimal] = {}
        for item in known:
            key = getattr(item, field) or 'UNKNOWN'
            buckets[key] = buckets.get(key, Decimal('0')) + weights.get(item.instrument_id, Decimal('0'))
        aggregate[field] = {key: str(value) for key, value in sorted(buckets.items())}
    metrics = [
        MetricResult('known_subset_hhi', sum((value ** 2 for value in weights.values()), Decimal('0')) if weights else None,
                     'index', 'sum((known_value / known_subtotal)^2)', AnalysisStatus.PARTIAL if weights else AnalysisStatus.UNAVAILABLE,
                     'descriptive known subset; no covariance or risk approval', evidence_ids),
        MetricResult('known_subset_largest_weight', max(weights.values()) if weights else None, 'ratio',
                     'max(known_value / known_subtotal)', AnalysisStatus.PARTIAL if weights else AnalysisStatus.UNAVAILABLE,
                     'known subset denominator', evidence_ids),
        MetricResult('known_item_count_coverage', coverage, 'ratio', 'known_asset_count / asset_count',
                     AnalysisStatus.PARTIAL if coverage is not None else AnalysisStatus.UNAVAILABLE, evidence_ids=evidence_ids),
    ]
    price_metadata = {}
    refs = list(evidence_ids)
    for item in series:
        if item.instrument_id not in {position.instrument_id for position in exposures}:
            raise ValueError('proxy series must belong to supplied exposures')
        if (len(item.prices) != len(item.dates) or tuple(sorted(set(item.dates))) != item.dates
                or any(not value.is_finite() or value <= 0 for value in item.prices)
                or (item.prices and not item.evidence_ids)):
            raise ValueError('proxy prices require positive finite values, ordered dates and evidence')
        for stamp in item.dates:
            date.fromisoformat(stamp)
        volatility = sample_stddev(simple_returns(item.prices)) if len(item.prices) >= 3 else None
        drawdown = max_drawdown(item.prices) if len(item.prices) >= 2 else None
        refs.extend(item.evidence_ids)
        for name, value, formula in [('volatility_per_observation', volatility, 'sample_stddev(simple_returns)'),
                                      ('maximum_drawdown', drawdown, 'min(price / prior_peak - 1)')]:
            metrics.append(MetricResult(item.instrument_id + ':' + name, value, 'ratio', formula,
                AnalysisStatus.PARTIAL if value is not None else AnalysisStatus.UNAVAILABLE,
                'asset-only dated price proxy; not portfolio risk', item.evidence_ids))
        price_metadata[item.instrument_id] = {'frequency': item.frequency, 'currency': item.currency,
            'dates': item.dates, 'prices': tuple(str(value) for value in item.prices),
            'annualized': False, 'observation_count': len(item.prices), 'evidence_ids': item.evidence_ids}
    series_ids = {item.instrument_id for item in series if len(item.prices) >= 2}
    gaps.extend('dated_price_series:' + item.instrument_id for item in exposures
                if item.instrument_id not in series_ids and item.asset_class != 'CASH')
    return AnalysisResult('portfolio', 'RISK_PROXY', AnalysisStatus.PARTIAL if weights or price_metadata else AnalysisStatus.UNAVAILABLE,
        tuple(metrics), risks=('descriptive proxies do not establish approved portfolio risk limits',),
        unknowns=tuple(gaps), metadata={'denominator_kind': 'KNOWN_VALUED_SUBSET', 'denominator_value': str(subtotal),
            'evaluation_currency': evaluation_currency, 'known_count': len(known), 'total_count': len(exposures),
            'exposure_inputs': {item.instrument_id: {'evaluation_value': str(item.value) if item.value is not None else None,
                'native_currency': item.currency, 'asset_class': item.asset_class, 'sector': item.sector} for item in exposures},
            'value_coverage': str(subtotal / full_denominator) if full_denominator and full_denominator > 0 else None,
            'native_currency_exposure': aggregate['currency'], 'asset_class_exposure': aggregate['asset_class'],
            'sector_exposure': aggregate['sector'], 'currency_scope': 'native denomination, not economic FX sensitivity',
            'asset_price_proxies': price_metadata, 'policy_approved': False, 'portfolio_covariance': None,
            'evidence_ids': tuple(dict.fromkeys(refs))})
