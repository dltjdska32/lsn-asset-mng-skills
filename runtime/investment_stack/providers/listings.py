"""Explicit host identity mapping; never inferred from a screenshot price."""
from dataclasses import replace
from investment_stack.providers.models import ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability

class ListingQuoteAdapter:
    name = "portfolio_listing_quotes"
    capabilities = frozenset({ProviderCapability.CURRENT_PRICE})
    def __init__(self, delegate, listings, resolver=None):
        self.delegate, self.listings = delegate, dict(listings)
        self.resolver = resolver
    def fetch(self, request):
        listing = self.listings.get(request.instrument_id)
        if not listing and self.resolver is not None:
            try:
                listing = self.resolver.resolve(request.instrument_id).listing_id
            except ValueError as exc:
                return ProviderResult(self.name, request.capability, ProviderStatus.UNAVAILABLE,
                    reason='instrument_resolution_failed: '+str(exc))
        if not listing:
            return self.delegate.fetch(request)
        result = self.delegate.fetch(replace(request, instrument_id=listing))
        observations = tuple(replace(obs, instrument_id=request.instrument_id,
            metadata={**obs.metadata, "quote_listing_id": listing,
                      "canonical_instrument_id": request.instrument_id}) for obs in result.observations)
        return replace(result, observations=observations)
