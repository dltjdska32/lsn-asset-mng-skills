from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.calculations import (
    BusinessType, DcfAssumptions, EconomicUnderlying, EquityValuationAnalyzer,
    EquityValuationInput, InstrumentProfile, InstrumentWrapper,
    PortfolioRiskAnalyzer, AssetRiskInput, resolve_instrument,
)
from investment_stack.calculations.common import decimal

D = Decimal


class Phase5FailureTests(unittest.TestCase):
    def test_binary_float_is_not_accepted_by_numeric_normalizer(self):
        with self.assertRaises(TypeError):
            decimal(1.5)

    def test_unsupported_instrument_combination_is_not_guessed(self):
        with self.assertRaises(ValueError):
            resolve_instrument(InstrumentProfile("X", EconomicUnderlying.OTHER, InstrumentWrapper.EXCHANGE_SPOT))

    def test_dcf_never_invents_invalid_terminal_spread(self):
        with self.assertRaises(ValueError):
            EquityValuationAnalyzer().analyze(EquityValuationInput(
                "X", BusinessType.STABLE_CASH_FLOW,
                dcf=DcfAssumptions(D("100"), D("0.05"), D("0.03"), D("0.03"), 5, D("0"), D("10")),
            ))

    def test_unaligned_market_series_never_get_forward_filled(self):
        result = PortfolioRiskAnalyzer().analyze((
            AssetRiskInput("BTC", D("0.5"), (D("100"), D("101"), D("102"), D("103"))),
            AssetRiskInput("EQ", D("0.5"), (D("100"), D("101"), D("102"))),
        ))
        self.assertTrue(result.partial)
        self.assertIsNone(result.volatility)


if __name__ == "__main__":
    unittest.main()
