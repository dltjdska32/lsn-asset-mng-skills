import unittest
from decimal import Decimal as D

from investment_stack.calculations.personal import actual_cost_basis, project_cash
from investment_stack.calculations.risk import AssetRiskInput, PortfolioRiskAnalyzer
from investment_stack.calculations.fund import FundAnalysisInput, FundHolding, FundAnalyzer
from investment_stack.calculations.instruments import EconomicUnderlying, InstrumentWrapper, InstrumentProfile, resolve_instrument
from investment_stack.calculations.alternative import AlternativeAsset, AlternativeAssetInput, AlternativeAssetAnalyzer
from investment_stack.screening import ScreeningCandidate, screen_equities
from investment_stack.routing.models import RequestMode


class CalculationRemediationTests(unittest.TestCase):
    def test_missing_historic_fx_preserves_unavailable_base_gain(self):
        result = actual_cost_basis(native_cost=D('100'), native_currency='USD', base_currency='KRW', current_base_value=D('140000'))
        self.assertIsNone(result.base_cost)
        self.assertIsNone(result.base_gain)
        actual = actual_cost_basis(native_cost=D('100'), native_currency='USD', base_currency='KRW', current_base_value=D('140000'), acquisition_fx=D('1200'))
        self.assertEqual(actual.base_gain, D('20000'))

    def test_cash_deficit_is_signed_and_future_income_is_not_available(self):
        result = project_cash(confirmed_cash=D('100'), monthly_income=D('50'), monthly_expense=D('90'), months=3, reserved_cash=D('10'))
        self.assertEqual(result.available_cash, D('90'))
        self.assertEqual(result.projected_cash, D('-30'))
        self.assertEqual(result.status, 'CONDITIONAL')

    def test_equal_length_risk_series_with_different_dates_not_aligned(self):
        prices = (D('100'), D('110'), D('105'))
        result = PortfolioRiskAnalyzer().analyze((
            AssetRiskInput('A', D('.5'), prices, price_dates=('2026-01-01', '2026-01-02', '2026-01-03')),
            AssetRiskInput('B', D('.5'), prices, price_dates=('2026-01-02', '2026-01-03', '2026-01-04'))))
        self.assertTrue(result.partial)
        self.assertIsNone(result.volatility)

    def test_proxy_is_labeled_and_partial(self):
        result = PortfolioRiskAnalyzer().analyze((AssetRiskInput('A', D('1'), (D('100'), D('110'), D('105')), proxy_instrument_id='INDEX', proxy_reason='history unavailable'),))
        self.assertTrue(result.partial)
        self.assertEqual(result.assets[0].proxy_instrument_id, 'INDEX')

    def test_stale_holdings_and_misaligned_nav_not_used(self):
        data = FundAnalysisInput('ETF', D('101'), D('100'), None, None, None,
                                 (FundHolding('A', D('.5')),), '2025-01-01',
                                 market_price_as_of='2026-10-05', nav_as_of='2026-10-01', analysis_as_of='2026-10-05')
        result = FundAnalyzer().analyze(data)
        self.assertIsNone(result.metrics[0].value)
        self.assertNotIn('sector_exposure', result.metadata)
        self.assertIn('current_holdings', result.unknowns)

    def test_partial_holdings_remain_unscaled(self):
        result = FundAnalyzer().analyze(FundAnalysisInput('ETF', None, None, None, None, None, (FundHolding('A', D('.5'), sector='TECH'),), '2026-10-05'))
        self.assertEqual(result.metadata['sector_exposure']['TECH'], '0.5')
        self.assertIn('uncovered_holdings_exposure', result.unknowns)

    def test_eth_is_alternative_with_explicit_protocol_unknowns(self):
        route = resolve_instrument(InstrumentProfile('ETH', EconomicUnderlying.ETHEREUM, InstrumentWrapper.NATIVE_CRYPTO))
        self.assertEqual(route.route.value, 'ALTERNATIVE')
        result = AlternativeAssetAnalyzer().analyze(AlternativeAssetInput('ETH', AlternativeAsset.ETHEREUM, 'NATIVE_CRYPTO', 'exchange', (), 'USD', venue='EXCHANGE'))
        self.assertFalse(result.metadata['corporate_valuation_allowed'])
        self.assertIn('staking_context', result.unknowns)

    def test_screening_missing_data_excluded_and_only_top_n_researched(self):
        universe = tuple(ScreeningCandidate(f'E{i:02}', {'growth': D(i), 'pe': D(40-i)}, (f'ev{i}',), '2026-10-05') for i in range(20))
        calls = []
        result = screen_equities(universe, metric_weights={'growth': D('1'), 'pe': D('-1')}, top_n=3, as_of='2026-10-05', deep_research=lambda instrument, mode: calls.append((instrument, mode)))
        self.assertEqual([c[0] for c in calls], ['E19', 'E18', 'E17'])
        self.assertTrue(all(c[1] is RequestMode.SINGLE_ASSET_ANALYSIS for c in calls))
        bad = universe[:-1] + (ScreeningCandidate('BAD', {'growth': None}, ('ev',), '2026-10-05'),)
        partial = screen_equities(bad, metric_weights={'growth': D('1')}, top_n=2, as_of='2026-10-05', deep_research=lambda *_: None)
        self.assertEqual(partial.excluded[0].instrument_id, 'BAD')
        self.assertEqual(len(partial.ranked), 19)


if __name__ == '__main__':
    unittest.main()
