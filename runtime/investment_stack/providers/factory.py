"""Default free-first Phase 4 provider stack."""

from __future__ import annotations

from investment_stack.providers.adapters import KrakenTickerAdapter, OpenDartAdapter, SecCompanyFactsAdapter
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.execution import ProviderFallbackExecutor
from investment_stack.providers.http import Transport, urllib_transport
from investment_stack.providers.market_quotes import MarketQuoteProvider, MarketQuoteProviderAdapter


def _market_transport(transport: Transport):
    def fetch(url, headers, timeout):
        body=transport(url, headers or {}, timeout)
        retrieved=transport.retrieved_at_for(url) if hasattr(transport,"retrieved_at_for") else None
        return 200, body, {"captured-retrieved-at":retrieved} if retrieved else {}
    return fetch


def build_default_provider_executor(
    *,
    credentials: EnvironmentCredentials | None = None,
    transport: Transport = urllib_transport,
    listings: dict[str, str] | None = None,
    instrument_resolver=None,
    official_fund_sources=None,
    policy=None,
) -> ProviderFallbackExecutor:
    env = credentials or EnvironmentCredentials()
    from investment_stack.freshness import FreshnessEngine, get_pinned_calendar

    freshness = FreshnessEngine()
    market_quotes = MarketQuoteProvider(transport=_market_transport(transport), enable_secondary=listings is not None or instrument_resolver is not None)
    from investment_stack.providers.fx import FXProvider
    from investment_stack.providers.listings import ListingQuoteAdapter
    from investment_stack.providers.official_funds import OfficialFundAdapter
    adapter = MarketQuoteProviderAdapter(
                market_quotes,
                calendars={exchange: get_pinned_calendar(exchange) for exchange in ("NASDAQ", "NYSE", "KRX", "JPX")},
                engine=freshness,
            )
    return ProviderFallbackExecutor(
        [
            ListingQuoteAdapter(adapter, listings or {}, instrument_resolver) if listings is not None or instrument_resolver is not None else adapter,
            OfficialFundAdapter(transport, listings=listings, resolver=instrument_resolver, source_manifests=official_fund_sources),
            FXProvider(transport),
            OpenDartAdapter(env, transport=transport),
            SecCompanyFactsAdapter(transport=transport),
            KrakenTickerAdapter(transport=transport),
        ],
        freshness_engine=freshness,
        policy=policy,
    )
