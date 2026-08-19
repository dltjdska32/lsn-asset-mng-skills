from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations import (
    AlternativeAsset,
    AlternativeAssetAnalyzer,
    AlternativeAssetInput,
    FundAnalysisInput,
    FundAnalyzer,
    FundHolding,
    fund_overlap,
)

D = Decimal


class Phase5FundAlternativeTests(unittest.TestCase):
    def test_fund_nav_premium_and_lookthrough(self):
        data = FundAnalysisInput(
            "ETF",
            D("101"), D("100"), D("0.001"), D("1000000"), D("50000"),
            (
                FundHolding("A", D("0.6"), "Tech", "US", "USD"),
                FundHolding("B", D("0.4"), "Industrial", "JP", "JPY"),
            ),
            "2026-08-13", "INDEX",
        )
        result = FundAnalyzer().analyze(data)
        metrics = {m.name: m.value for m in result.metrics}
        self.assertEqual(metrics["nav_premium_discount"], D("0.01"))
        self.assertEqual(result.metadata["sector_exposure"]["Tech"], "0.6")
        self.assertEqual(result.status.value, "COMPLETE")

    def test_fund_holdings_without_date_is_partial(self):
        result = FundAnalyzer().analyze(FundAnalysisInput("ETF", None, None, None, None, None, (FundHolding("A", D("1")),)))
        self.assertEqual(result.status.value, "PARTIAL")
        self.assertIn("holdings_as_of", result.unknowns)

    def test_fund_overlap_is_minimum_common_weight(self):
        left = (FundHolding("A", D("0.5")), FundHolding("B", D("0.5")))
        right = (FundHolding("A", D("0.3")), FundHolding("C", D("0.7")))
        self.assertEqual(fund_overlap(left, right), D("0.3"))

    def test_bitcoin_has_no_corporate_valuation(self):
        result = AlternativeAssetAnalyzer().analyze(
            AlternativeAssetInput("BTC", AlternativeAsset.BITCOIN, "NATIVE_CRYPTO", "kraken", (D("100"), D("110"), D("90")), "USD", venue="KRAKEN")
        )
        self.assertFalse(result.metadata["corporate_valuation_allowed"])
        metric_names = {m.name for m in result.metrics}
        self.assertNotIn("pe", metric_names)
        self.assertNotIn("dcf", metric_names)

    def test_bitcoin_missing_venue_and_custody_is_partial(self):
        result = AlternativeAssetAnalyzer().analyze(
            AlternativeAssetInput("BTC", AlternativeAsset.BITCOIN, "NATIVE_CRYPTO", None, (D("100"), D("101"), D("102")), "USD")
        )
        self.assertEqual(result.status.value, "PARTIAL")
        self.assertIn("venue", result.unknowns)
        self.assertIn("custody_or_account", result.unknowns)

    def test_gold_uses_macro_and_physical_context_not_equity_ratios(self):
        result = AlternativeAssetAnalyzer().analyze(
            AlternativeAssetInput("GOLD", AlternativeAsset.GOLD, "PHYSICAL", "vault", (D("2000"), D("2100"), D("2050")), "USD", physical_premium=D("0.03"), real_rate=D("0.015"), usd_index_change=D("-0.02"))
        )
        names = {m.name for m in result.metrics}
        self.assertIn("real_rate_context", names)
        self.assertIn("physical_premium", names)
        self.assertNotIn("pe", names)

    def test_silver_tracks_industrial_demand_context(self):
        result = AlternativeAssetAnalyzer().analyze(
            AlternativeAssetInput("SILVER", AlternativeAsset.SILVER, "EXCHANGE_SPOT", "account", (D("30"), D("31"), D("29")), "USD", industrial_demand_change=D("0.08"))
        )
        self.assertEqual(next(m.value for m in result.metrics if m.name == "industrial_demand_change"), D("0.08"))


if __name__ == "__main__":
    unittest.main()
