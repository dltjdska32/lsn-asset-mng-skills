from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations import (
    AlternativeAsset, AlternativeAssetAnalyzer, AlternativeAssetInput,
    BusinessType, EconomicUnderlying, EquityValuationAnalyzer, EquityValuationInput,
    FundAnalysisInput, FundAnalyzer, FundHolding, InstrumentProfile, InstrumentWrapper,
    resolve_instrument,
)
from investment_stack.materiality import LightweightAsset, MaterialityConfig, MaterialityDecision, MaterialityEngine

D = Decimal


class Phase5AcceptanceTests(unittest.TestCase):
    def test_fanuc_routes_to_fundamental_and_valuation(self):
        route = resolve_instrument(InstrumentProfile("FANUC", EconomicUnderlying.COMPANY, InstrumentWrapper.LISTED_EQUITY))
        self.assertEqual(route.route.value, "EQUITY")

    def test_bitcoin_direct_never_receives_corporate_valuation(self):
        route = resolve_instrument(InstrumentProfile("BTC", EconomicUnderlying.BITCOIN, InstrumentWrapper.NATIVE_CRYPTO, "exchange"))
        self.assertEqual(route.route.value, "ALTERNATIVE")
        result = AlternativeAssetAnalyzer().analyze(AlternativeAssetInput("BTC", AlternativeAsset.BITCOIN, "NATIVE_CRYPTO", "exchange", (D("100"), D("105")), "USD", venue="KRAKEN"))
        self.assertFalse(result.metadata["corporate_valuation_allowed"])

    def test_gold_etf_is_fund_plus_alternative_context(self):
        route = resolve_instrument(InstrumentProfile("GLD", EconomicUnderlying.GOLD, InstrumentWrapper.ETF))
        self.assertEqual(route.route.value, "FUND")
        self.assertTrue(route.requires_alternative_context)

    def test_fund_holdings_without_asof_never_claim_complete_lookthrough(self):
        result = FundAnalyzer().analyze(FundAnalysisInput("ETF", D("10"), D("10"), D("0.001"), D("100"), D("10"), (FundHolding("A", D("1"), "Tech"),), None))
        self.assertEqual(result.status.value, "PARTIAL")

    def test_current_price_missing_keeps_valuation_partial(self):
        result = EquityValuationAnalyzer().analyze(EquityValuationInput("EQ", BusinessType.STABLE_CASH_FLOW, current_price=None, eps=D("5")))
        self.assertEqual(result.status.value, "PARTIAL")
        self.assertIsNone(next(m.value for m in result.metrics if m.name == "pe"))

    def test_direct_user_selected_asset_auto_passes_materiality(self):
        engine = MaterialityEngine(MaterialityConfig("cfg", D("0.99"), D("0.99"), D("0.99")))
        decision = engine.evaluate(LightweightAsset("FANUC", D("1"), D("0.001"), None, None, D("0"), user_specified=True))
        self.assertEqual(decision.decision, MaterialityDecision.AUTO_PASS_USER_SPECIFIED)


if __name__ == "__main__":
    unittest.main()
