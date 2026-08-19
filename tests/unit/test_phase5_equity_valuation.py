from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations import (
    BusinessType,
    DcfAssumptions,
    EconomicUnderlying,
    EquityFundamentalAnalyzer,
    EquityFundamentalInput,
    EquityValuationAnalyzer,
    EquityValuationInput,
    HighGrowthScenario,
    InstrumentProfile,
    InstrumentWrapper,
    ValuationModel,
    resolve_instrument,
    select_model,
)


D = Decimal


class Phase5EquityValuationTests(unittest.TestCase):
    def test_equity_fundamentals_are_deterministic_and_partial_on_missing_inputs(self):
        result = EquityFundamentalAnalyzer().analyze(
            EquityFundamentalInput(
                instrument_id="FANUC",
                currency="JPY",
                revenue=D("1000"),
                prior_revenue=D("800"),
                operating_income=D("150"),
                net_income=D("100"),
                cash_from_operations=D("180"),
                capex=D("80"),
                total_debt=D("200"),
                equity=D("500"),
                average_equity=D("480"),
                reported_period="FY2026Q1",
                basis="CONSOLIDATED_REPORTED",
            )
        )
        metrics = {m.name: m.value for m in result.metrics}
        self.assertEqual(metrics["revenue_growth"], D("0.25"))
        self.assertEqual(metrics["operating_margin"], D("0.15"))
        self.assertEqual(metrics["free_cash_flow"], D("100"))
        self.assertEqual(metrics["debt_to_equity"], D("0.4"))
        self.assertIn("roic", result.unknowns)
        self.assertEqual(result.status.value, "PARTIAL")

    def test_dcf_has_no_hidden_assumptions(self):
        analyzer = EquityValuationAnalyzer()
        missing = analyzer.analyze(EquityValuationInput("X", BusinessType.STABLE_CASH_FLOW, current_price=D("100")))
        self.assertIsNone(next(m.value for m in missing.metrics if m.name == "dcf_value_per_share"))
        explicit = analyzer.analyze(
            EquityValuationInput(
                "X",
                BusinessType.STABLE_CASH_FLOW,
                current_price=D("100"),
                eps=D("5"),
                dcf=DcfAssumptions(D("100"), D("0.05"), D("0.10"), D("0.02"), 5, D("50"), D("10")),
            )
        )
        self.assertIsNotNone(next(m.value for m in explicit.metrics if m.name == "dcf_value_per_share"))

    def test_dcf_rejects_invalid_discount_terminal_relationship(self):
        with self.assertRaises(ValueError):
            EquityValuationAnalyzer().analyze(
                EquityValuationInput(
                    "X",
                    BusinessType.STABLE_CASH_FLOW,
                    dcf=DcfAssumptions(D("10"), D("0.03"), D("0.02"), D("0.03"), 5, D("0"), D("1")),
                )
            )


    def test_high_growth_valuation_requires_explicit_scenarios(self):
        analyzer = EquityValuationAnalyzer()
        missing = analyzer.analyze(EquityValuationInput("GROWTH", BusinessType.HIGH_GROWTH_OR_LOSS))
        self.assertIsNone(next(m.value for m in missing.metrics if m.name == "high_growth_scenario"))
        result = analyzer.analyze(EquityValuationInput(
            "GROWTH", BusinessType.HIGH_GROWTH_OR_LOSS, currency="USD",
            high_growth_scenarios=(HighGrowthScenario("base", D("1000"), D("4"), D("100"), D("100")),),
            unit_economics={"gross_margin": D("0.6")},
        ))
        self.assertEqual(next(m.value for m in result.metrics if m.name == "scenario_base"), D("39"))
        self.assertEqual(result.metadata["unit_economics"]["gross_margin"], D("0.6"))

    def test_model_selector_matches_frozen_architecture(self):
        self.assertEqual(select_model(BusinessType.STABLE_CASH_FLOW), ValuationModel.DCF_MULTIPLES)
        self.assertEqual(select_model(BusinessType.FINANCIAL), ValuationModel.FINANCIAL_PB_ROE_DIVIDEND)
        self.assertEqual(select_model(BusinessType.HIGH_GROWTH_OR_LOSS), ValuationModel.HIGH_GROWTH_SCENARIO)
        self.assertEqual(select_model(BusinessType.CONGLOMERATE), ValuationModel.SOTP)
        self.assertEqual(select_model(BusinessType.ASSET_HEAVY), ValuationModel.NAV_ASSET_BASED)

    def test_instrument_resolution_routes_gold_miner_as_equity(self):
        resolution = resolve_instrument(InstrumentProfile("MINER", EconomicUnderlying.COMPANY, InstrumentWrapper.LISTED_EQUITY))
        self.assertEqual(resolution.route.value, "EQUITY")

    def test_bitcoin_etf_routes_fund_with_alternative_context(self):
        resolution = resolve_instrument(InstrumentProfile("BTCETF", EconomicUnderlying.BITCOIN, InstrumentWrapper.ETF))
        self.assertEqual(resolution.route.value, "FUND")
        self.assertTrue(resolution.requires_alternative_context)

    def test_direct_bitcoin_routes_alternative(self):
        resolution = resolve_instrument(InstrumentProfile("BTC", EconomicUnderlying.BITCOIN, InstrumentWrapper.NATIVE_CRYPTO, "exchange"))
        self.assertEqual(resolution.route.value, "ALTERNATIVE")


if __name__ == "__main__":
    unittest.main()
