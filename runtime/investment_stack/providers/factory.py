"""Default free-first Phase 4 provider stack."""

from __future__ import annotations

from investment_stack.providers.adapters import KrakenTickerAdapter, OpenDartAdapter, SecCompanyFactsAdapter
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.execution import ProviderFallbackExecutor
from investment_stack.providers.http import Transport, urllib_transport
from investment_stack.providers.market_quotes import MarketQuoteProvider, MarketQuoteProviderAdapter


def _market_transport(transport: Transport):
    def fetch(url, headers, timeout):
        return 200, transport(url, headers or {}, timeout), {}
    return fetch


def build_default_provider_executor(
    *,
    credentials: EnvironmentCredentials | None = None,
    transport: Transport = urllib_transport,
) -> ProviderFallbackExecutor:
    env = credentials or EnvironmentCredentials()
    from investment_stack.freshness import FreshnessEngine, get_pinned_calendar

    freshness = FreshnessEngine()
    market_quotes = MarketQuoteProvider(transport=_market_transport(transport))
    return ProviderFallbackExecutor(
        [
            MarketQuoteProviderAdapter(
                market_quotes,
                calendars={"NASDAQ": get_pinned_calendar("NASDAQ"), "KRX": get_pinned_calendar("KRX")},
                engine=freshness,
            ),
            OpenDartAdapter(env, transport=transport),
            SecCompanyFactsAdapter(transport=transport),
            KrakenTickerAdapter(transport=transport),
        ],
        freshness_engine=freshness,
    )
