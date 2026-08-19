from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations import AllocationAnalyzer, AssetRiskInput, PortfolioRiskAnalyzer, PositionExposure
from investment_stack.materiality import LightweightAsset, MaterialityConfig, MaterialityDecision, MaterialityEngine

D = Decimal


class Phase5MaterialityAllocationRiskTests(unittest.TestCase):
    def setUp(self):
        self.engine = MaterialityEngine(MaterialityConfig("test-v1", D("0.05"), D("0.20"), D("0.75")))

    def test_user_specified_asset_auto_passes(self):
        result = self.engine.evaluate(LightweightAsset("FANUC", D("1"), D("0.001"), D("1"), D("0.01"), D("0"), user_specified=True))
        self.assertEqual(result.decision, MaterialityDecision.AUTO_PASS_USER_SPECIFIED)

    def test_material_weight_passes(self):
        result = self.engine.evaluate(LightweightAsset("A", D("1"), D("0.10"), D("1"), D("0.01"), D("0")))
        self.assertEqual(result.decision, MaterialityDecision.PASS)

    def test_unvalued_uncertain_confirmed_position_can_pass_uncertainty(self):
        result = self.engine.evaluate(LightweightAsset("A", D("2"), None, None, None, D("0.9")))
        self.assertEqual(result.decision, MaterialityDecision.PASS_UNCERTAINTY)

    def test_small_low_risk_position_fails_gate(self):
        result = self.engine.evaluate(LightweightAsset("A", D("1"), D("0.01"), D("1"), D("0.01"), D("0.1")))
        self.assertEqual(result.decision, MaterialityDecision.FAIL)

    def test_allocation_keeps_unvalued_positions_visible(self):
        result = AllocationAnalyzer().analyze((
            PositionExposure("EQ", D("700"), account="A", asset_class="EQUITY", country="JP", currency="JPY", liquidity="HIGH", custody="BROKER", leverage=D("1"), lookthrough=(("Industrial", D("0.8")),)),
            PositionExposure("BTC", D("300"), account="B", asset_class="BITCOIN", country="GLOBAL", currency="USD", liquidity="HIGH", custody="EXCHANGE", leverage=D("1")),
            PositionExposure("GOLD", None, account="C", asset_class="GOLD", country="GLOBAL", currency="USD"),
        ))
        self.assertEqual(result.valued_total, D("1000"))
        self.assertEqual(result.by_asset_class["EQUITY"], D("0.7"))
        self.assertEqual(result.by_asset_class["BITCOIN"], D("0.3"))
        self.assertEqual(result.unvalued_positions, ("GOLD",))
        self.assertEqual(result.by_custody["BROKER"], D("0.7"))
        self.assertEqual(result.lookthrough_exposure["Industrial"], D("0.56"))
        self.assertEqual(result.weighted_leverage, D("1"))

    def test_risk_uses_aligned_frequency_and_returns_partial_when_unaligned(self):
        result = PortfolioRiskAnalyzer().analyze((
            AssetRiskInput("A", D("0.5"), (D("100"), D("101"), D("102"))),
            AssetRiskInput("B", D("0.5"), (D("100"), D("99"))),
        ))
        self.assertTrue(result.partial)
        self.assertIsNone(result.volatility)

    def test_risk_calculates_contribution_for_aligned_series(self):
        result = PortfolioRiskAnalyzer().analyze((
            AssetRiskInput("A", D("0.6"), (D("100"), D("105"), D("103"), D("110"))),
            AssetRiskInput("B", D("0.4"), (D("100"), D("101"), D("99"), D("104"))),
        ))
        self.assertFalse(result.partial)
        self.assertIsNotNone(result.volatility)
        self.assertTrue(all(asset.contribution is not None for asset in result.assets))


if __name__ == "__main__":
    unittest.main()
