from dataclasses import replace
import unittest
from investment_stack.freshness import FreshnessEngine
from investment_stack.providers.execution import assess_fund_structure_observation
from investment_stack.providers.models import ProviderObservation


class FundSessionFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.engine = FreshnessEngine()
        self.clock = '2026-10-05T12:00:00+09:00'
        self.obs = ProviderObservation(evidence_type='financial', source_name='Issuer',
            source_url='https://www.samsungfund.com/example', source_tier=1,
            provider_id='official_funds', instrument_id='alias', metric='fund_structure',
            value='100', unit='KRW/share', currency='KRW',
            observed_at='2026-10-02T23:59:59+09:00',
            retrieved_at='2026-10-05T12:01:00+09:00',
            metadata={'listing_id':'KRX:123ABC', 'nav_as_of':'2026-10-02',
                      'holdings_as_of':'2026-10-02'})

    def status(self, obs=None, clock=None):
        return assess_fund_structure_observation(obs or self.obs,
            analysis_as_of=clock or self.clock, engine=self.engine).status.value

    def test_weekend_latest_daily_basket_is_fresh_without_changing_observation_time(self):
        self.assertEqual(self.status(), 'FRESH')
        self.assertEqual(self.obs.observed_at, '2026-10-02T23:59:59+09:00')

    def test_old_basket_is_stale_even_if_nav_is_latest(self):
        self.assertEqual(self.status(replace(self.obs, metadata={**self.obs.metadata,
            'holdings_as_of':'2026-10-01'})), 'STALE')

    def test_future_publication_is_unavailable(self):
        self.assertEqual(self.status(replace(self.obs,
            published_at='2026-10-05T12:00:01+09:00')), 'UNAVAILABLE')

    def test_new_completed_session_makes_old_daily_basket_stale(self):
        self.assertEqual(self.status(clock='2026-10-06T16:00:00+09:00'), 'STALE')

    def test_wrong_provider_or_exchange_has_no_daily_override(self):
        self.assertEqual(self.status(replace(self.obs, provider_id='untrusted')), 'STALE')
        self.assertEqual(self.status(replace(self.obs,
            metadata={**self.obs.metadata, 'listing_id':'OTHER:123ABC'})), 'STALE')

    def test_future_or_unbound_data_dates_are_unavailable(self):
        for day in ('2026-10-06', 'invalid'):
            self.assertEqual(self.status(replace(self.obs,
                metadata={**self.obs.metadata, 'holdings_as_of':day})), 'UNAVAILABLE')
        self.assertEqual(self.status(replace(self.obs,
            observed_at='2026-10-01T23:59:59+09:00')), 'UNAVAILABLE')

    def test_malformed_source_times_fail_soft(self):
        for key, value in (('observed_at','invalid'), ('retrieved_at','invalid'),
                           ('published_at','2026-10-02T16:00:00')):
            self.assertEqual(self.status(replace(self.obs, **{key:value})), 'UNAVAILABLE')

    def test_krx_currency_mismatch_is_unavailable(self):
        self.assertEqual(self.status(replace(self.obs, currency='USD')), 'UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
