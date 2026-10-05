"""Explicit scenario returns and freshness-gated equity grades."""
from dataclasses import dataclass
from decimal import Decimal, localcontext


@dataclass(frozen=True)
class FiveYearScenario:
    name: str
    current_earnings_per_share: Decimal
    normalized_earnings_growth: Decimal
    terminal_multiple: Decimal
    total_dividends_per_share: Decimal
    evidence_bindings: dict[str, str]


def expected_five_year_cagr(price, scenarios, *, price_verified, price_evidence_id):
    """No growth, multiple, dividend or quality assumption is inferred."""
    if not price_verified or not price_evidence_id or price is None:
        return {'status': 'UNAVAILABLE', 'reason': 'validated price required', 'scenarios': {}}
    if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
        raise ValueError('positive finite Decimal price required')
    if {s.name.casefold() for s in scenarios} != {'bear', 'base', 'bull'} or len(scenarios) != 3:
        return {'status': 'UNAVAILABLE', 'reason': 'explicit Bear/Base/Bull scenarios required', 'scenarios': {}}
    fields = {'current_earnings_per_share', 'normalized_earnings_growth', 'terminal_multiple', 'total_dividends_per_share'}
    results = {}
    for s in scenarios:
        if set(s.evidence_bindings) != fields or any(not v for v in s.evidence_bindings.values()):
            return {'status': 'UNAVAILABLE', 'reason': 'each assumption requires evidence', 'scenarios': {}}
        values = [getattr(s, f) for f in fields]
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
            raise ValueError('finite Decimal assumptions required')
        if s.current_earnings_per_share <= 0 or s.normalized_earnings_growth <= -1 or s.terminal_multiple <= 0 or s.total_dividends_per_share < 0:
            raise ValueError('unsupported earnings scenario')
        with localcontext() as ctx:
            ctx.prec = 34
            terminal = s.current_earnings_per_share * (1 + s.normalized_earnings_growth) ** 5 * s.terminal_multiple
            cagr = ((terminal + s.total_dividends_per_share) / price) ** (Decimal(1) / 5) - 1
        results[s.name.casefold()] = {'terminal_price': str(terminal), 'cagr': str(cagr), 'evidence_bindings': s.evidence_bindings}
    return {'status': 'AVAILABLE', 'price_evidence_id': price_evidence_id,
            'formula': '((EPS*(1+growth)^5*terminal_multiple+dividends)/price)^(1/5)-1', 'scenarios': results}


def equity_buy_grade(price, fair_value, *, price_verified, fundamental_quality_passed,
                     valuation_passed, evidence_ids):
    if not price_verified or not fundamental_quality_passed or not valuation_passed or not evidence_ids or price is None or fair_value is None:
        return {'status': 'UNAVAILABLE', 'grade': None, 'reason': 'price, quality and valuation gates required'}
    if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in (price, fair_value)):
        raise ValueError('positive finite Decimal values required')
    upside = fair_value / price - 1
    grade = '강력매수' if upside >= Decimal('.25') else '분할매수' if upside >= Decimal('.10') else '적정가' if upside >= Decimal('-.10') else '비쌈'
    return {'status': 'AVAILABLE', 'grade': grade, 'upside': str(upside), 'evidence_ids': tuple(evidence_ids)}
