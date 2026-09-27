"""Test suite for R05 fallback eligibility logic."""

import unittest
from datetime import datetime, timezone, timedelta
from typing import Any

from investment_stack.providers.adapters import ProviderAdapter
from investment_stack.providers.execution import ProviderFallbackExecutor, FallbackResult
from investment_stack.providers.models import ProviderRequest, ProviderResult, ProviderStatus, ProviderObservation
from investment_stack.providers.registry import ProviderCapability

class MockAdapter(ProviderAdapter):
    def __init__(self, name: str, capability: ProviderCapability, result: ProviderResult | Exception):
        self.name = name
        self.capabilities = frozenset({capability})
        self._result = result

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

MISSING = object()

def _obs(val: Any, metric: str = "metric", approved: bool = True, obs_at: Any = MISSING,
         currency: str | None = None, instrument_id: str | None = None, period_end: str | None = None) -> ProviderObservation:
    # Use a fixed default obs_at to ensure tests are deterministic
    default_obs_at = "2024-03-31T20:00:00+00:00"
    actual_obs_at = default_obs_at if obs_at is MISSING else obs_at
    return ProviderObservation(
        evidence_type="test",
        source_name="test",
        source_url="http://test",
        source_tier=1,
        provider_id="test",
        value=val,
        metric=metric,
        currency=currency,
        instrument_id=instrument_id,
        observed_at=actual_obs_at,
        metadata={"calculation_input_approved": approved, "period_end": period_end or "2024-03-31"}
    )

class FallbackEligibilityTests(unittest.TestCase):
    def test_two_ineligible_then_third_selected(self):
        req = ProviderRequest(
            capability=ProviderCapability.CURRENT_PRICE,
            analysis_as_of="2024-04-01T00:00:00+00:00",
            analysis_timezone="UTC",
            instrument_id="AAPL"
        )
        
        # 1. Stale price (obs_at is too old, assuming default policy delay)
        stale_time = "2024-01-01T00:00:00+00:00"
        res1 = ProviderResult("p1", req.capability, ProviderStatus.AVAILABLE, (_obs(100, obs_at=stale_time, instrument_id="AAPL"),))
        
        # 2. Negative price
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(-50, obs_at="2024-03-31T20:00:00+00:00", instrument_id="AAPL"),))
        
        # 3. Valid fresh price
        res3 = ProviderResult("p3", req.capability, ProviderStatus.AVAILABLE, (_obs(150, obs_at="2024-03-31T23:50:00+00:00", instrument_id="AAPL"),))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2),
            MockAdapter("p3", req.capability, res3)
        ])
        
        res = executor.execute(req)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.provider, "p3")
        self.assertEqual(len(res.results), 3)

    def test_all_ineligible(self):
        req = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-04-01T00:00:00+00:00",
            analysis_timezone="UTC",
            parameters={"required_metrics": ["revenue", "eps"]}
        )
        
        # Missing eps
        res1 = ProviderResult("p1", req.capability, ProviderStatus.AVAILABLE, (_obs(100, metric="revenue"),))
        # Missing revenue
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(5, metric="eps"),))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2)
        ])
        
        res = executor.execute(req)
        self.assertIsNone(res.selected)
        self.assertEqual(len(res.results), 2)

    def test_sec_partial_then_new(self):
        req = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-04-01T00:00:00+00:00",
            analysis_timezone="UTC"
        )
        
        # SEC partial (0 calculation_input_approved)
        res1 = ProviderResult("p1", req.capability, ProviderStatus.PARTIAL, (_obs(100, approved=False),))
        # Valid
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(200),))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2)
        ])
        
        res = executor.execute(req)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.provider, "p2")

    def test_required_metric_missing_then_completed(self):
        req = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-04-01T00:00:00+00:00",
            analysis_timezone="UTC",
            parameters={"required_metrics": ["revenue", "eps"]}
        )
        
        # Missing eps
        res1 = ProviderResult("p1", req.capability, ProviderStatus.AVAILABLE, (_obs(100, metric="revenue"),))
        # Complete
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(200, metric="revenue", period_end="2023-12-31", currency="USD"), _obs(5, metric="eps", period_end="2023-12-31", currency="USD")))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2)
        ])
        
        res = executor.execute(req)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.provider, "p2")
        
    def test_future_observation(self):
        req = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-01-01T00:00:00+00:00",
            analysis_timezone="UTC"
        )
        
        future_time = "2024-01-02T00:00:00+00:00"
        res1 = ProviderResult("p1", req.capability, ProviderStatus.AVAILABLE, (_obs(100, obs_at=future_time),))
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(200, obs_at="2023-12-31T00:00:00+00:00"),))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2)
        ])
        
        res = executor.execute(req)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.provider, "p2")

    def test_fundamentals_skip_missing_observation_time(self):
        req = ProviderRequest(
            capability=ProviderCapability.FUNDAMENTALS,
            analysis_as_of="2024-04-01T00:00:00+00:00",
            analysis_timezone="UTC"
        )
        # obs_at=None means observation_time is None (missing), which should be rejected.
        res1 = ProviderResult("p1", req.capability, ProviderStatus.AVAILABLE, (_obs(100, obs_at=None),))
        res2 = ProviderResult("p2", req.capability, ProviderStatus.AVAILABLE, (_obs(200, obs_at="2024-03-31T00:00:00+00:00"),))
        
        executor = ProviderFallbackExecutor([
            MockAdapter("p1", req.capability, res1),
            MockAdapter("p2", req.capability, res2)
        ])
        
        res = executor.execute(req)
        self.assertIsNotNone(res.selected)
        self.assertEqual(res.selected.provider, "p2")

if __name__ == "__main__":
    unittest.main()
