from __future__ import annotations

import unittest

from investment_stack.materiality.event_gate import classify_event_impact


class EventMaterialityTests(unittest.TestCase):
    def test_headline_without_explicit_impact_stays_waiting(self) -> None:
        result = classify_event_impact({"record_type": "event_impact_v1", "category": "capex", "headline": "capex rose"})
        self.assertEqual("WAIT", result.status)

    def test_explicit_valuation_impact_does_not_create_a_price(self) -> None:
        result = classify_event_impact({
            "record_type": "event_impact_v1",
            "category": "capex",
            "impact": "VALUATION",
            "source_excerpt": "The filing says capex changes the VALUATION cash-flow inputs for this period.",
        })
        self.assertEqual("MATERIAL_TO_VALUATION", result.status)
        self.assertNotIn("price", result.reason.casefold())


if __name__ == "__main__":
    unittest.main()
