"""Provider registry, concrete adapters, fallback execution, and credentials."""

from investment_stack.providers.adapters import KrakenTickerAdapter, OpenDartAdapter, SecCompanyFactsAdapter
from investment_stack.providers.credentials import CredentialMissing, EnvironmentCredentials
from investment_stack.providers.execution import FallbackResult, ProviderFallbackExecutor
from investment_stack.providers.factory import build_default_provider_executor
from investment_stack.providers.models import ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderAttempt, ProviderCapability, ProviderRegistry, ProviderResolution, ProviderSpec

__all__ = [
    "CredentialMissing", "EnvironmentCredentials", "FallbackResult", "KrakenTickerAdapter",
    "OpenDartAdapter", "ProviderAttempt", "ProviderCapability", "ProviderFallbackExecutor",
    "ProviderObservation", "ProviderRegistry", "ProviderRequest", "ProviderResolution", "ProviderResult",
    "ProviderSpec", "ProviderStatus", "SecCompanyFactsAdapter", "build_default_provider_executor",
]
