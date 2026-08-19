"""Default free-first Phase 4 provider stack."""

from __future__ import annotations

from investment_stack.providers.adapters import KrakenTickerAdapter, OpenDartAdapter, SecCompanyFactsAdapter
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.providers.execution import ProviderFallbackExecutor
from investment_stack.providers.http import Transport, urllib_transport


def build_default_provider_executor(
    *,
    credentials: EnvironmentCredentials | None = None,
    transport: Transport = urllib_transport,
) -> ProviderFallbackExecutor:
    env = credentials or EnvironmentCredentials()
    return ProviderFallbackExecutor(
        [
            OpenDartAdapter(env, transport=transport),
            SecCompanyFactsAdapter(transport=transport),
            KrakenTickerAdapter(transport=transport),
        ]
    )
