"""The Phase 5 bridge must consume only selected compatible financial facts."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from investment_stack.deep_research import LiveDeepResearchRuntime, _normalize_metric_value
from investment_stack.freshness import FreshnessEngine
from investment_stack.providers.models import ProviderObservation, ProviderResult, ProviderStatus
from investment_stack.providers.registry import ProviderCapability


def _fact(metric: str, value: str, period: str, *, unit: str = "USD", extra=None):
    return ProviderObservation(
        evidence_type="financial", source_name="fixture", source_url=None, source_tier=1,
        provider_id="fixture", value=Decimal(value), unit=unit, currency="USD", instrument_id="X",
        metric=metric, observed_at=f"{period}T23:59:59+00:00",
        metadata={"period_end": period, "form": "10-K", "fp": "FY", **(extra or {})},
    )


class FinancialSelectionConsumptionTests(unittest.TestCase):
    def test_only_selected_same_period_facts_reach_phase5(self):
        runtime = object.__new__(LiveDeepResearchRuntime)
        runtime.analysis_as_of = "2026-01-01T00:00:00+00:00"
        runtime.freshness = FreshnessEngine()
        selected_revenue = _fact("revenue", "100", "2025-12-31")
        prior_period_debt = _fact("total_debt", "40", "2024-12-31")
        raw_unselected = _fact("cash", "30", "2026-01-01")
        outcome = SimpleNamespace(
            selected=SimpleNamespace(
                selected_observations=(selected_revenue, prior_period_debt),
                observation=selected_revenue,
            ),
            provider_results=(ProviderResult("fixture", ProviderCapability.FUNDAMENTALS,
                                             ProviderStatus.AVAILABLE, (raw_unselected,)),),
        )

        values, _warnings = runtime._normalize_financials(outcome, target_currency="USD")
        self.assertEqual(values, {"revenue": Decimal("100")})

    def test_invalid_explicit_scale_is_not_replaced_by_base_unit(self):
        observation = _fact("revenue", "10", "2025-12-31", extra={"unit_multiplier": "0"})
        normalized, warning = _normalize_metric_value(
            "revenue", Decimal("10"), observation, target_currency="USD"
        )
        self.assertIsNone(normalized)
        self.assertEqual(warning, "revenue: invalid unit scale")


if __name__ == "__main__":
    unittest.main()
