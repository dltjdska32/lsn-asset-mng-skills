"""Synthetic incomplete holdings and descriptive-risk regression tests."""
import unittest
from dataclasses import replace
from decimal import Decimal as D

from investment_stack.calculations.fund import FundAnalysisInput, FundHolding, FundAnalyzer, portfolio_fund_lookthrough
from investment_stack.calculations.risk_proxy import ProxyExposure, ProxyPriceSeries, analyze_risk_proxy
from investment_stack.reporting.portfolio_modes import (
    PinnedPortfolioState, PortfolioPosition, PortfolioAnalysisRequest, HistoricalPriceSeries,
    RiskObservation, analyze_portfolio,
)


class FundRiskCompletionTests(unittest.TestCase):
    def fund(self, instrument='ETF', holdings=None):
        return FundAnalysisInput(instrument, D('101'), D('100'), D('.001'), D('1000'), D('100'),
            holdings if holdings is not None else (FundHolding('A', D('.4'), sector='TECH', country='US', currency='USD'),
                         FundHolding('B', D('.2'))), '2026-10-01', evidence_ids=('synthetic-issuer-holdings',),
            market_price_as_of='2026-10-01', nav_as_of='2026-10-01', analysis_as_of='2026-10-05')

    def test_partial_holdings_classification_has_explicit_unknown_not_renormalized(self):
        result = FundAnalyzer().analyze(self.fund())
        self.assertEqual(result.metadata['sector_exposure'], {'TECH': '0.4'})
        self.assertEqual(D(result.metadata['sector_unknown_weight']), D('.6'))
        self.assertEqual(D(result.metadata['uncovered_holdings_weight']), D('.4'))
        self.assertIn('unclassified_sector_exposure', result.unknowns)

    def test_future_aligned_nav_is_not_usable(self):
        result = FundAnalyzer().analyze(replace(self.fund(), market_price_as_of='2026-10-06', nav_as_of='2026-10-06'))
        self.assertIsNone(next(metric.value for metric in result.metrics if metric.name == 'nav_premium_discount'))
        self.assertIn('future_nav_or_price', result.unknowns)

    def test_same_day_future_nav_and_holdings_are_not_usable(self):
        data = replace(self.fund(), analysis_as_of='2026-10-05T12:00:00+00:00',
            market_price_as_of='2026-10-05T13:00:00+00:00', nav_as_of='2026-10-05T13:00:00+00:00',
            holdings_as_of='2026-10-05T13:00:00+00:00')
        result = FundAnalyzer().analyze(data)
        self.assertIn('future_nav_or_price', result.unknowns)
        self.assertFalse(result.metadata['holdings_current'])
        self.assertEqual(portfolio_fund_lookthrough({'ETF': (D('.5'), data)})['status'], 'UNAVAILABLE')

    def test_invalid_fund_numbers_block(self):
        for field, value in [('market_price', D('NaN')), ('market_price', D('0')), ('nav_per_share', D('-1')),
                             ('nav_per_share', D('0')), ('aum', D('Infinity'))]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                FundAnalyzer().analyze(replace(self.fund(), **{field: value}))

    def test_weighted_lookthrough_and_overlap_keep_missing_weight_unknown(self):
        left = self.fund('LEFT')
        right = self.fund('RIGHT', (FundHolding('A', D('.2'), 'TECH', 'US', 'USD'),))
        result = portfolio_fund_lookthrough({'LEFT': (D('.5'), left), 'RIGHT': (D('.25'), right)})
        self.assertEqual(D(result['holding_exposure']['A']), D('.25'))
        self.assertEqual(D(result['covered_portfolio_weight']), D('.35'))
        self.assertEqual(D(result['unknown_fund_portfolio_weight']), D('.4'))
        self.assertEqual(D(result['sector_exposure']['UNKNOWN']), D('.5'))
        self.assertEqual(result['fund_pair_overlap']['LEFT|RIGHT']['overlap_lower_bound'], '0.2')
        self.assertEqual(result['status'], 'PARTIAL')

    def test_missing_holdings_or_evidence_is_unavailable(self):
        for data in (self.fund(holdings=()), replace(self.fund(), evidence_ids=()),
                     replace(self.fund(), holdings_as_of='2024-01-01')):
            result = portfolio_fund_lookthrough({'ETF': (D('.5'), data)})
            self.assertEqual(result['status'], 'UNAVAILABLE')
            self.assertEqual(result['holding_exposure'], {})
            self.assertEqual(D(result['sector_exposure']['UNKNOWN']), D('.5'))

    def test_known_subset_coverage_is_count_not_invented_monetary_total(self):
        result = analyze_risk_proxy((ProxyExposure('A', D('75'), 'USD', 'EQUITY'),
                                    ProxyExposure('B', D('25'), 'KRW', 'FUND'),
                                    ProxyExposure('C', None, 'USD')), evaluation_currency='USD')
        metrics = {item.name: item.value for item in result.metrics}
        self.assertEqual(metrics['known_subset_hhi'], D('.625'))
        self.assertEqual(metrics['known_item_count_coverage'], D(2) / D(3))
        self.assertIsNone(result.metadata['value_coverage'])
        self.assertEqual(result.metadata['native_currency_exposure'], {'KRW': '0.25', 'USD': '0.75'})
        self.assertFalse(result.metadata['policy_approved'])
        self.assertIsNone(result.metadata['portfolio_covariance'])

    def test_report_retains_proxy_without_risk_policy_and_excludes_future_price(self):
        state = PinnedPortfolioState(1, 'synthetic-snapshot', '2026-10-05T12:00:00+00:00', '2026-10-05T11:00:00+00:00')
        observations = tuple(RiskObservation(day, D(price), 'USD', 'synthetic:' + day,
            day + 'T00:00:00+00:00', 'ELIGIBLE', 'FRESH', True)
            for day, price in [('2026-10-01','100'), ('2026-10-02','90'), ('2026-10-03','95'), ('2026-10-06','1')])
        request = PortfolioAnalysisRequest(state, 'USD', (PortfolioPosition('A', D('100'), 'USD', 'EQUITY'),), (), (),
            price_series=(HistoricalPriceSeries('A', 'DAILY', observations),))
        result = analyze_portfolio(request)
        self.assertIsNone(result.risk)
        self.assertTrue(all(item.status.value == 'UNKNOWN' for item in result.risk_limits))
        proxy = result.risk_proxy
        self.assertEqual(next(item.value for item in proxy.metrics if item.name == 'A:maximum_drawdown'), D('-.1'))
        self.assertEqual(proxy.metadata['asset_price_proxies']['A']['observation_count'], 3)
        self.assertIn('risk_proxy', result.section.metadata)
        self.assertTrue(any('Risk proxy A:maximum_drawdown=-0.1' in line for line in result.section.lines))
        self.assertNotIn('synthetic:2026-10-06', proxy.metadata['evidence_ids'])

    def test_cash_needs_no_dated_price_series(self):
        result = analyze_risk_proxy((ProxyExposure('cash:test', D('1'), 'USD', 'CASH'),), evaluation_currency='USD')
        self.assertEqual(result.unknowns, ())

    def test_undated_or_invalid_proxy_series_cannot_be_used(self):
        with self.assertRaises(ValueError):
            analyze_risk_proxy((ProxyExposure('A', D('1'), 'USD'),), evaluation_currency='USD',
                series=(ProxyPriceSeries('A','DAILY','USD',(),(D('1'),D('2')),('synthetic',)),))


if __name__ == '__main__':
    unittest.main()
