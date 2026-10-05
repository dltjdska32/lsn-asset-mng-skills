import gzip
import json
import unittest
from investment_stack.providers.adapters import SecCompanyFactsAdapter
from investment_stack.providers.models import ProviderRequest, ProviderStatus
from investment_stack.providers.registry import ProviderCapability


class SecRecoveryTests(unittest.TestCase):
    def facts(self):
        annual = dict(start='2023-01-01', end='2023-12-31', val=100, form='10-K', filed='2024-02-01', fp='FY')
        quarter = dict(start='2024-01-01', end='2024-03-31', val=30, form='10-Q', filed='2024-05-01', fp='Q1')
        shares = dict(end='2024-04-15', val=10, form='10-Q', filed='2024-05-01', fp='Q1')
        return {'cik': 320193, 'facts': {
            'us-gaap': {'RevenueFromContractWithCustomerExcludingAssessedTax': {'units': {'USD': [annual, quarter]}}},
            'dei': {'EntityCommonStockSharesOutstanding': {'units': {'shares': [shares]}}}}}

    def collect(self, data, latest=False):
        payload = gzip.compress(json.dumps(data).encode())
        request = ProviderRequest(ProviderCapability.FUNDAMENTALS, '2024-06-01T00:00:00+00:00', 'UTC', 'AAPL', parameters={'cik': '320193', 'latest_period_only': latest})
        return SecCompanyFactsAdapter(transport=lambda *_: payload).fetch(request)

    def test_compressed_modern_revenue_and_flow_basis(self):
        result = self.collect(self.facts())
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        revenue = [o for o in result.observations if o.metric == 'revenue']
        self.assertEqual({o.metadata['flow_basis'] for o in revenue}, {'ANNUAL', 'QUARTERLY'})
        self.assertEqual({o.value for o in revenue}, {100, 30})

    def test_latest_period_is_not_replaced_by_later_share_count_date(self):
        result = self.collect(self.facts(), latest=True)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].metadata['period_end'], '2024-03-31')
        self.assertEqual(result.observations[0].value, 30)

    def test_wrong_issuer_and_future_period_are_not_approved(self):
        data = self.facts()
        data['cik'] = 789019
        self.assertEqual(self.collect(data).status, ProviderStatus.UNAVAILABLE)
        data = self.facts()
        data['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax']['units']['USD'][1]['end'] = '2025-03-31'
        result = self.collect(data)
        bad = next(o for o in result.observations if o.metadata['period_end'] == '2025-03-31')
        self.assertFalse(bad.metadata['calculation_input_approved'])
