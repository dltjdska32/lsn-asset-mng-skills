import json
import threading
import time
import unittest
from types import SimpleNamespace

from investment_stack.providers.execution import ProviderFallbackExecutor
from investment_stack.providers.health import ProviderExecutionPolicy
from investment_stack.providers.models import ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability
from investment_stack.web_research.live_news import LiveNewsBackend
from investment_stack.web_research.models import WebResearchHit, WebResearchIntent, WebResearchResponse


class ProviderResilienceTests(unittest.TestCase):
    def request(self):
        return ProviderRequest(ProviderCapability.NEWS, '2026-10-05T00:00:00+00:00', 'Asia/Seoul', 'NASDAQ:TEST')

    def adapter(self, name, operation):
        return SimpleNamespace(name=name, capabilities={ProviderCapability.NEWS}, fetch=operation)

    def available(self, name):
        return ProviderResult(name, ProviderCapability.NEWS, ProviderStatus.AVAILABLE,
            (ProviderObservation('news', 'test', 'https://example.test', 3, name),))

    def test_hung_provider_falls_back_and_does_not_spawn_duplicate_worker(self):
        release, calls = threading.Event(), []
        def hang(request):
            calls.append(1); release.wait(5)
            return self.available('hung')
        executor = ProviderFallbackExecutor([self.adapter('hung', hang), self.adapter('good', lambda r: self.available('good'))],
            policy=ProviderExecutionPolicy(attempt_timeout_seconds=.02, total_timeout_seconds=.2))
        try:
            started = time.monotonic()
            result = executor.execute(self.request())
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(result.selected.provider, 'good')
            self.assertEqual(result.results[0].metadata['health_status'], 'TIMEOUT')
            second = executor.execute(self.request())
            self.assertEqual(second.results[0].metadata['health_status'], 'SKIPPED')
            self.assertEqual(calls, [1])
        finally:
            release.set()

    def test_transient_retry_and_contract_validation_are_bounded(self):
        calls = []
        def recover(request):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('secret URL')
            return self.available('recover')
        executor = ProviderFallbackExecutor([self.adapter('recover', recover)])
        result = executor.execute(self.request())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.selected.provider, 'recover')
        self.assertNotIn('secret URL', repr(result))

    def test_missing_credentials_and_bad_observation_do_not_retry(self):
        calls = []
        def missing(request):
            calls.append(1)
            return ProviderResult('missing', ProviderCapability.NEWS, ProviderStatus.MISSING_CREDENTIAL)
        result = ProviderFallbackExecutor([self.adapter('missing', missing)]).execute(self.request())
        self.assertIsNone(result.selected)
        self.assertEqual(calls, [1])

    def test_errors_open_health_circuit_and_never_expose_exception_text(self):
        calls = []
        def fail(request):
            calls.append(1)
            raise OSError('https://secret.test/?key=secret')
        executor = ProviderFallbackExecutor([self.adapter('fail', fail), self.adapter('good', lambda r: self.available('good'))])
        result = executor.execute(self.request())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.selected.provider, 'good')
        self.assertNotIn('secret', repr(result))
        result = executor.execute(self.request())
        self.assertEqual(result.results[0].reason, 'provider health cooldown')
        self.assertEqual(len(calls), 2)

    def test_stale_or_future_price_does_not_stop_fallback(self):
        from dataclasses import replace
        request = replace(self.request(), capability=ProviderCapability.CURRENT_PRICE, instrument_id='CRYPTO:BTC/USD')
        def quote(name, observed):
            return ProviderResult(name, request.capability, ProviderStatus.AVAILABLE,
                (ProviderObservation('market', 'test', 'https://example.test', 3, name, value='50000',
                    currency='USD', instrument_id=request.instrument_id, observed_at=observed),))
        for invalid in ('2026-10-04T00:00:00Z', '2026-10-05T00:00:01Z'):
            with self.subTest(observed=invalid):
                bad = SimpleNamespace(name='bad', capabilities={request.capability}, fetch=lambda r: quote('bad', invalid))
                good = SimpleNamespace(name='good', capabilities={request.capability}, fetch=lambda r: quote('good', request.analysis_as_of))
                result = ProviderFallbackExecutor([bad, good]).execute(request)
                self.assertEqual(result.selected.provider, 'good')
                self.assertEqual(len(result.results), 2)

    def test_total_budget_stops_remaining_adapter_fetches(self):
        release, later = threading.Event(), []
        executor = ProviderFallbackExecutor([
            self.adapter('hung', lambda r: release.wait(5)),
            self.adapter('later', lambda r: later.append(1))],
            policy=ProviderExecutionPolicy(attempt_timeout_seconds=.1, total_timeout_seconds=.02))
        try:
            result = executor.execute(self.request())
            self.assertIsNone(result.selected)
            self.assertEqual(later, [])
            self.assertEqual(result.results[-1].metadata['health_status'], 'BUDGET_EXHAUSTED')
        finally:
            release.set()


class NewsWindowTests(unittest.TestCase):
    intent = WebResearchIntent.LATEST_RELEVANT_NEWS
    upper = '2026-10-05T00:00:00+00:00'
    cutoff = '2026-10-04T00:00:00+00:00'
    iid = 'NASDAQ:TEST'

    def backend(self, transport, preferred=None, **kwargs):
        resolver = SimpleNamespace(resolved={self.iid: SimpleNamespace(ticker='TEST', exchange='NASDAQ')})
        return LiveNewsBackend(resolver, transport, preferred, previous_run_as_of=self.cutoff, **kwargs)

    def hit(self, title, url, published, event=None, iid=None):
        return WebResearchHit('test', url, title, published_at=published, event_cluster_id=event,
            metadata={'instrument_id': iid or self.iid})

    def test_preferred_window_identity_article_and_event_dedup(self):
        hits = (
            self.hit('Old', 'https://x.test/old', self.cutoff),
            self.hit('Future', 'https://x.test/future', '2026-10-06T00:00:00Z'),
            self.hit('Wrong asset', 'https://x.test/wrong', self.upper, iid='NASDAQ:OTHER'),
            self.hit('Contract', 'https://x.test/a?utm_source=one', self.upper, 'event-a'),
            self.hit('Contract syndicated', 'https://y.test/b', self.upper, 'event-a'),
            self.hit('Different title same article', 'https://x.test/a?utm_source=two', self.upper),
        )
        backend = self.backend(lambda *args: b'{}', lambda *args: WebResearchResponse(self.intent, hits))
        result = backend(self.intent, self.iid+' recent events', self.upper)
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].metadata['news_cutoff'], self.cutoff)
        aid = result.hits[0].metadata['article_id']
        backend.set_context(previous_run_as_of=self.cutoff, seen_article_ids=(aid,))
        result = backend(self.intent, self.iid+' recent events', self.upper)
        self.assertEqual([h.title for h in result.hits], ['Contract syndicated'])

    def test_yahoo_stale_first_endpoint_falls_back_and_materiality_remains_unverified(self):
        calls = []
        def transport(url, headers, timeout):
            calls.append(url)
            stamp = 1791072000 if len(calls) == 1 else 1791158400  # Oct 4, Oct 5 UTC
            return json.dumps({'news': [{'relatedTickers': ['TEST'], 'link': 'https://x.test/article',
                'title': 'New merger contract', 'providerPublishTime': stamp}]}).encode()
        result = self.backend(transport)(self.intent, self.iid+' recent events', self.upper)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result.hits), 1)
        self.assertFalse(result.hits[0].metadata['material_event'])
        self.assertTrue(result.hits[0].metadata['potential_material_event'])
        self.assertFalse(result.hits[0].metadata['calculation_input_approved'])

    def test_hung_preferred_reaches_yahoo_and_late_result_is_ignored(self):
        release, calls = threading.Event(), []
        def preferred(*args):
            release.wait(5)
            return WebResearchResponse(self.intent, (self.hit('Late', 'https://x.test/late', self.upper),))
        backend = self.backend(lambda *args: (calls.append(1) or b'{"news": []}'), preferred,
            policy=ProviderExecutionPolicy(attempt_timeout_seconds=.02, total_timeout_seconds=.2))
        try:
            self.assertEqual(backend(self.intent, self.iid+' recent events', self.upper).hits, ())
            self.assertEqual(len(calls), 2)
            self.assertEqual(backend.attempts[0]['status'], 'TIMEOUT')
        finally:
            release.set()

    def test_invalid_or_future_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            self.backend(lambda *args: b'{}').set_context(previous_run_as_of='2026-10-04')
        backend = self.backend(lambda *args: b'{}')
        backend.set_context(previous_run_as_of='2026-10-06T00:00:00Z')
        with self.assertRaises(ValueError):
            backend(self.intent, self.iid+' recent events', self.upper)

    def test_preferred_cannot_promote_unverified_material_event(self):
        from dataclasses import replace
        hit = self.hit('Reported contract', 'https://x.test/new', self.upper)
        hit = replace(hit, metadata={**hit.metadata, 'material_event': True, 'independent_verification': False})
        backend = self.backend(lambda *args: b'{}', lambda *args: WebResearchResponse(self.intent, (hit,)))
        result = backend(self.intent, self.iid+' recent events', self.upper)
        self.assertFalse(result.hits[0].metadata['material_event'])
        self.assertTrue(result.hits[0].metadata['potential_material_event'])


if __name__ == '__main__':
    unittest.main()
