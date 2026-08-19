from __future__ import annotations

import json
import unittest

from investment_stack.providers import (
    EnvironmentCredentials,
    KrakenTickerAdapter,
    OpenDartAdapter,
    ProviderCapability,
    ProviderFallbackExecutor,
    ProviderRequest,
    ProviderStatus,
    SecCompanyFactsAdapter,
)


def transport_json(payload: object):
    encoded = json.dumps(payload).encode()
    return lambda url, headers, timeout: encoded


class Phase4ProviderTests(unittest.TestCase):
    def request(self, capability: ProviderCapability, **parameters: object) -> ProviderRequest:
        return ProviderRequest(capability, "2026-08-14T10:00:00+00:00", "Asia/Seoul", "TEST", parameters=parameters)

    def test_opendart_missing_key_is_partial_not_exception(self) -> None:
        adapter = OpenDartAdapter(EnvironmentCredentials({}), transport=transport_json({}))
        result = adapter.fetch(self.request(ProviderCapability.FUNDAMENTALS, corp_code="001", business_year="2025", report_code="11011"))
        self.assertEqual(result.status, ProviderStatus.MISSING_CREDENTIAL)

    def test_opendart_parses_free_structured_rows_without_logging_key(self) -> None:
        adapter = OpenDartAdapter(
            EnvironmentCredentials({"OPENDART_API_KEY": "super-secret"}),
            transport=transport_json({"status": "000", "list": [{"account_nm": "매출액", "account_id": "Revenue", "thstrm_amount": "100", "sj_div": "IS"}]}),
        )
        result = adapter.fetch(self.request(ProviderCapability.FUNDAMENTALS, corp_code="001", business_year="2025", report_code="11011"))
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertEqual(result.observations[0].value, "100")
        self.assertNotIn("super-secret", repr(result))
        self.assertNotIn("super-secret", result.observations[0].source_url or "")

    def test_sec_companyfacts_is_keyless_and_normalized(self) -> None:
        adapter = SecCompanyFactsAdapter(transport=transport_json({"facts": {"us-gaap": {"Revenue": {}}}}))
        result = adapter.fetch(self.request(ProviderCapability.FUNDAMENTALS, cik="320193"))
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertEqual(result.observations[0].source_tier, 1)

    def test_kraken_uses_venue_trade_time_not_retrieval_time(self) -> None:
        adapter = KrakenTickerAdapter(transport=transport_json({"error": [], "result": {"XXBTZUSD": [["123.45", "1", 1786701540.0, "b", "m", ""]], "last": "1"}}))
        result = adapter.fetch(self.request(ProviderCapability.CURRENT_PRICE, pair="XBTUSD", quote_currency="USD"))
        self.assertEqual(result.status, ProviderStatus.AVAILABLE)
        self.assertIsNotNone(result.observations[0].retrieved_at)
        self.assertIsNotNone(result.observations[0].observed_at)

    def test_fallback_normalizes_unexpected_adapter_error(self) -> None:
        class Broken:
            name = "broken"
            capabilities = frozenset({ProviderCapability.NEWS})
            def fetch(self, request):
                raise RuntimeError("boom")
        fallback = ProviderFallbackExecutor([Broken()]).execute(self.request(ProviderCapability.NEWS))
        self.assertEqual(fallback.results[0].status, ProviderStatus.ERROR)
        self.assertIsNone(fallback.selected)

    def test_transport_error_never_reflects_opendart_key(self) -> None:
        def broken(url, headers, timeout):
            raise RuntimeError(url)
        adapter = OpenDartAdapter(
            EnvironmentCredentials({"OPENDART_API_KEY": "never-leak-this"}),
            transport=broken,
        )
        result = adapter.fetch(self.request(
            ProviderCapability.FUNDAMENTALS,
            corp_code="001", business_year="2025", report_code="11011",
        ))
        self.assertEqual(result.status, ProviderStatus.ERROR)
        self.assertNotIn("never-leak-this", result.reason or "")


if __name__ == "__main__":
    unittest.main()
