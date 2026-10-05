import unittest
from decimal import Decimal
from investment_stack.providers.models import ProviderObservation
from investment_stack.evidence.research import SelectedEvidence
from investment_stack.research import ResearchOutcome
from investment_stack.deep_research import LiveDeepResearchRuntime
from investment_stack.freshness import FreshnessEngine


class FinancialSourceSelectionTests(unittest.TestCase):
    def observation(self, metric, value, start, published, end='2026-03-31', basis='QUARTERLY'):
        return ProviderObservation('financial', 'synthetic official filing', 'https://example.test/filing', 1, 'sec_companyfacts', value=Decimal(value), unit='USD', currency='USD', instrument_id='TEST', metric=metric, published_at=published, retrieved_at=published, metadata={'canonical_metric':metric,'period_end':end,'start':start,'form':'10-Q','fp':'Q1','flow_basis':basis})

    def normalize(self, observations):
        runtime = object.__new__(LiveDeepResearchRuntime)
        runtime.analysis_as_of = '2026-08-01T00:00:00+00:00'
        runtime.freshness = FreshnessEngine()
        selected = SelectedEvidence(observations[0], None, 'synthetic', None, False, 'test', tuple(observations))
        sources = {}
        values, _ = runtime._normalize_financials(ResearchOutcome(selected, (), False), target_currency='USD', sources_out=sources)
        return values, sources

    def test_unselected_fact_cannot_overwrite_winning_duration(self):
        chosen = self.observation('revenue','100','2026-01-01','2026-05-01T00:00:00+00:00')
        older = self.observation('revenue','900','2025-04-01','2026-04-01T00:00:00+00:00',basis='ANNUAL')
        cfo = self.observation('cash_from_operations','20','2026-01-01','2026-05-01T00:00:00+00:00')
        capex = self.observation('capex','1','2026-01-01','2026-05-01T00:00:00+00:00')
        values, sources = self.normalize([chosen, older, cfo, capex])
        self.assertEqual(values['revenue'], Decimal('100'))
        self.assertIs(sources['revenue'], chosen)

    def test_latest_annual_fact_keeps_its_own_basis_despite_historical_quarter(self):
        annual = self.observation('revenue','1000','2025-01-01','2026-02-01T00:00:00+00:00',end='2025-12-31',basis='ANNUAL')
        quarter = self.observation('revenue','200','2025-01-01','2025-05-01T00:00:00+00:00',end='2025-03-31')
        values, sources = self.normalize([annual, quarter])
        self.assertEqual(values['revenue'], Decimal('1000'))
        self.assertEqual(sources['revenue'].metadata['flow_basis'], 'ANNUAL')
