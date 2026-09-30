"""Unit tests for domain models: Financial, Market, Institutional, and Calculation lineage."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.providers.contract_adapters import (
    bar_to_observation,
    fact_to_observation,
    holding_to_observation,
    quote_to_observation,
)
from investment_stack.contracts.calculation import (
    AssumptionKind,
    CalculationAssumption,
    CalculationRecord,
    CalculationStatus,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    TimezoneValidationError,
)
from investment_stack.contracts.financial import (
    AccountingStandard,
    AdjustmentBasis,
    ConsolidationKind,
    FinancialFact,
    FinancialSet,
    PeriodType,
    ReportingFrequency,
    ScaleStatus,
)
from investment_stack.contracts.institutional import (
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingSet13F,
    PutCall,
    QuantityType,
)
from investment_stack.contracts.market import (
    AdjustmentMode,
    Bar,
    BarSet,
    MarketQuote,
    QuoteKind,
)
from investment_stack.contracts.slots import BoundSlotInput, DimensionKind
from investment_stack.providers.models import ProviderObservation


class ContractDomainModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pub_avail = PublicAvailability.exact(datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc), locator="test_source")

    def test_financial_fact_validation_and_set(self) -> None:
        fact = FinancialFact(
            fact_id="fact-1",
            evidence_id="ev-1",
            instrument_id="AAPL",
            taxonomy="us-gaap",
            original_tag="Revenues",
            canonical_metric="revenue",
            raw_value=Decimal("100"),
            raw_unit="USD",
            explicit_scale=ScaleStatus.VALID,
            scale_multiplier=Decimal("1000000"),
            normalized_value=Decimal("100000000"),
            dimension=DimensionKind.MONEY,
            currency="USD",
            period_type=PeriodType.DURATION,
            period_start="2024-01-01",
            period_end="2024-12-31",
            duration_days=366,
            fiscal_year=2024,
            fiscal_period="FY",
            reporting_frequency=ReportingFrequency.ANNUAL,
            consolidation=ConsolidationKind.CONSOLIDATED,
            accounting_standard=AccountingStandard.US_GAAP,
            adjustment_basis=AdjustmentBasis.REPORTED,
            public_availability=self.pub_avail,
        )
        self.assertEqual(fact.normalized_value, Decimal("100000000"))

        # Negative scale multiplier rejected
        with self.assertRaises(DecimalValidationError):
            FinancialFact(
                fact_id="fact-bad",
                evidence_id="ev-1",
                instrument_id="AAPL",
                taxonomy="us-gaap",
                original_tag="Revenues",
                canonical_metric="revenue",
                raw_value=Decimal("100"),
                raw_unit="USD",
                explicit_scale=ScaleStatus.INVALID,
                scale_multiplier=Decimal("-1000"),
                normalized_value=Decimal("-100000"),
                dimension=DimensionKind.MONEY,
                currency="USD",
                period_type=PeriodType.DURATION,
                period_start="2024-01-01",
                period_end="2024-12-31",
                duration_days=366,
                fiscal_year=2024,
                fiscal_period="FY",
                reporting_frequency=ReportingFrequency.ANNUAL,
                consolidation=ConsolidationKind.CONSOLIDATED,
                accounting_standard=AccountingStandard.US_GAAP,
                adjustment_basis=AdjustmentBasis.REPORTED,
                public_availability=self.pub_avail,
            )

        f_set = FinancialSet.create("set-1", "AAPL", "USD", [fact])
        self.assertEqual(f_set.covered_metrics, ("revenue",))
        self.assertEqual(len(f_set.find_facts("revenue")), 1)

    def test_market_quote_invariants(self) -> None:
        quote = MarketQuote(
            quote_id="q-1",
            evidence_id="ev-q",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("150.50"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=datetime(2026, 9, 23, 9, 1, tzinfo=timezone.utc),
            public_availability=self.pub_avail,
        )
        self.assertEqual(quote.price, Decimal("150.50"))

        # Zero or negative price rejected
        with self.assertRaises(DecimalValidationError):
            MarketQuote(
                quote_id="q-bad",
                evidence_id="ev-q",
                instrument_id="AAPL",
                currency="USD",
                price=Decimal("0"),
                quote_kind=QuoteKind.REGULAR,
                retrieved_at=datetime(2026, 9, 23, 9, 1, tzinfo=timezone.utc),
                public_availability=self.pub_avail,
            )

    def test_bar_bounds_invariant(self) -> None:
        open_t = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        close_t = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)

        # Valid Bar: low <= min(open, close) <= max(open, close) <= high
        bar = Bar(
            bar_id="b-1",
            evidence_id="ev-b",
            instrument_id="AAPL",
            interval="1d",
            session_date="2026-09-23",
            open_time=open_t,
            close_time=close_t,
            timezone="America/New_York",
            open=Decimal("150"),
            high=Decimal("155"),
            low=Decimal("148"),
            close=Decimal("152"),
            volume=Decimal("1000000"),
            currency="USD",
            public_availability=self.pub_avail,
        )
        self.assertEqual(bar.close, Decimal("152"))

        # High lower than open -> Invariant violation!
        with self.assertRaises(ContractValidationError) as ctx:
            Bar(
                bar_id="b-bad",
                evidence_id="ev-b",
                instrument_id="AAPL",
                interval="1d",
                session_date="2026-09-23",
                open_time=open_t,
                close_time=close_t,
                timezone="America/New_York",
                open=Decimal("150"),
                high=Decimal("145"),  # invalid: high < open!
                low=Decimal("140"),
                close=Decimal("142"),
                volume=Decimal("1000"),
                currency="USD",
                public_availability=self.pub_avail,
            )
        self.assertIn("bounds invariant violated", str(ctx.exception))

    def test_bar_set_chronological_ordering(self) -> None:
        t1 = datetime(2026, 9, 22, 9, 30, tzinfo=timezone.utc)
        t1_c = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        t2_c = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)

        bar1 = Bar(
            "b-1", "ev-1", "AAPL", "1d", "2026-09-22", t1, t1_c, "UTC",
            Decimal("100"), Decimal("105"), Decimal("95"), Decimal("102"), Decimal("500"), "USD", self.pub_avail,
        )
        bar2 = Bar(
            "b-2", "ev-2", "AAPL", "1d", "2026-09-23", t2, t2_c, "UTC",
            Decimal("102"), Decimal("108"), Decimal("101"), Decimal("107"), Decimal("600"), "USD", self.pub_avail,
        )

        # Correct order
        bar_set = BarSet.create("AAPL", "1d", "USD", AdjustmentMode.RAW, [bar1, bar2])
        self.assertEqual(len(bar_set.bars), 2)

        # Reversed order raises ContractValidationError
        with self.assertRaises(ContractValidationError) as ctx:
            BarSet.create("AAPL", "1d", "USD", AdjustmentMode.RAW, [bar2, bar1])
        self.assertIn("must be strictly chronological", str(ctx.exception))

    def test_institutional_13f_holdings_and_set(self) -> None:
        h1 = Holding13F(
            holding_id="h-1",
            filing_id="f-1",
            cusip="037833100",
            issuer_name="APPLE INC",
            raw_quantity=Decimal("10000"),
            raw_value=Decimal("1500"),  # in thousands -> $1,500,000
            normalized_value=Decimal("1500000"),
            normalized_shares=Decimal("10000"),
            value_scale=Decimal("1000"),
        )
        h_set = HoldingSet13F.create("f-1", "0001166559", "2025-12-31", [h1])
        self.assertEqual(h_set.total_eligible_value, Decimal("1500000"))

    def test_calculation_record_and_unapproved_assumption_guard(self) -> None:
        slot = BoundSlotInput("s1", Decimal("100"), "USD", "USD", "ev-1")
        unapproved_assumption = CalculationAssumption(
            assumption_id="a1",
            name="terminal_growth_rate",
            value="0.03",
            is_approved=False,  # Unapproved!
        )

        # Unapproved assumption with CALCULATED status is strictly forbidden
        with self.assertRaises(ContractValidationError) as ctx:
            CalculationRecord.create(
                calculation_id="c-1",
                run_id="run-1",
                calculation_name="dcf_valuation",
                formula_id="formula_dcf",
                formula_version="1.0",
                status=CalculationStatus.CALCULATED,  # Invalid when assumption unapproved!
                bound_inputs=[slot],
                selection_snapshot_hash="hash_123",
                assumptions=[unapproved_assumption],
                result_numeric=Decimal("120"),
            )
        self.assertIn("cannot have status CALCULATED", str(ctx.exception))

        # Allowed with CONDITIONAL status
        valid_calc = CalculationRecord.create(
            calculation_id="c-1",
            run_id="run-1",
            calculation_name="dcf_valuation",
            formula_id="formula_dcf",
            formula_version="1.0",
            status=CalculationStatus.CONDITIONAL,
            bound_inputs=[slot],
            selection_snapshot_hash="hash_123",
            assumptions=[unapproved_assumption],
            result_numeric=Decimal("120"),
        )
        self.assertEqual(valid_calc.status, CalculationStatus.CONDITIONAL)
        self.assertTrue(valid_calc.verify_lineage())

    def test_provider_observation_adapters(self) -> None:
        quote = MarketQuote(
            quote_id="q-1",
            evidence_id="ev-q",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("150.50"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=datetime(2026, 9, 23, 9, 1, tzinfo=timezone.utc),
            public_availability=self.pub_avail,
        )
        obs = quote_to_observation(quote)
        self.assertEqual(obs.evidence_type, "MARKET_QUOTE")
        self.assertEqual(obs.value, "150.5")

        # ProviderObservation contract envelope roundtrip
        envelope = obs.to_contract_envelope()
        reconstructed = ProviderObservation.from_contract_envelope(envelope)
        self.assertEqual(reconstructed.evidence_type, obs.evidence_type)
        self.assertEqual(reconstructed.value, obs.value)
        self.assertEqual(reconstructed.currency, obs.currency)


if __name__ == "__main__":
    unittest.main()
