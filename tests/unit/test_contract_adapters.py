"""Unit tests for providers contract adapters and ProviderObservation interoperability."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.codec import CONTRACT_VERSION, decode_contract
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.financial import (
    AccountingStandard,
    AdjustmentBasis,
    ConsolidationKind,
    FinancialFact,
    PeriodType,
    ReportingFrequency,
    ScaleStatus,
)
from investment_stack.contracts.institutional import Holding13F, PutCall, QuantityType
from investment_stack.contracts.market import Bar, MarketQuote, QuoteKind
from investment_stack.contracts.slots import DimensionKind
from investment_stack.providers.contract_adapters import (
    bar_to_observation,
    fact_to_observation,
    holding_to_observation,
    observation_to_contract_envelope,
    quote_to_observation,
)
from investment_stack.providers.models import ProviderObservation


class ContractAdaptersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        self.avail = PublicAvailability.exact(self.now, locator="test_source")

    def test_fact_adapter_roundtrip(self) -> None:
        fact = FinancialFact(
            fact_id="fact-101",
            evidence_id="ev-f101",
            instrument_id="AAPL",
            taxonomy="us-gaap",
            original_tag="OperatingIncomeLoss",
            canonical_metric="operating_income",
            raw_value=Decimal("30000000000"),
            raw_unit="USD",
            explicit_scale=ScaleStatus.VALID,
            scale_multiplier=Decimal("1"),
            normalized_value=Decimal("30000000000"),
            dimension=DimensionKind.MONEY,
            currency="USD",
            period_type=PeriodType.DURATION,
            period_start="2025-10-01",
            period_end="2025-12-31",
            duration_days=92,
            fiscal_year=2026,
            fiscal_period="Q1",
            reporting_frequency=ReportingFrequency.QUARTER,
            consolidation=ConsolidationKind.CONSOLIDATED,
            accounting_standard=AccountingStandard.US_GAAP,
            adjustment_basis=AdjustmentBasis.REPORTED,
            public_availability=self.avail,
            accession="0000320193-26-000001",
        )
        obs = fact_to_observation(fact, provider_id="sec_edgar")
        self.assertEqual(obs.metadata["fact_id"], "fact-101")
        self.assertEqual(obs.instrument_id, "AAPL")
        self.assertEqual(obs.value, "30000000000")

    def test_quote_adapter_roundtrip(self) -> None:
        quote = MarketQuote(
            quote_id="q-101",
            evidence_id="ev-q101",
            instrument_id="BTC-USD",
            currency="USD",
            price=Decimal("95000.50"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=self.now,
            public_availability=self.avail,
            venue="COINBASE",
        )
        obs = quote_to_observation(quote, provider_id="coinbase")
        self.assertEqual(obs.metadata["quote_id"], "q-101")
        self.assertEqual(obs.value, "95000.5")

    def test_bar_adapter_roundtrip(self) -> None:
        bar = Bar(
            bar_id="bar-101",
            evidence_id="ev-b101",
            instrument_id="AAPL",
            interval="1d",
            session_date="2026-09-23",
            open_time=self.now,
            close_time=self.now,
            timezone="UTC",
            open=Decimal("150.00"),
            high=Decimal("152.00"),
            low=Decimal("149.50"),
            close=Decimal("151.25"),
            volume=Decimal("1000000"),
            currency="USD",
            public_availability=self.avail,
        )
        obs = bar_to_observation(bar, provider_id="polygon")
        self.assertEqual(obs.metadata["bar_id"], "bar-101")
        self.assertEqual(obs.value, "151.25")

    def test_holding_adapter_roundtrip(self) -> None:
        holding = Holding13F(
            holding_id="h-101",
            filing_id="filing-101",
            cusip="037833100",
            issuer_name="APPLE INC",
            raw_quantity=Decimal("300000"),
            raw_value=Decimal("50000"),
            normalized_value=Decimal("50000000"),
            normalized_shares=Decimal("300000"),
            put_call=PutCall.NONE,
            quantity_type=QuantityType.SH,
        )
        obs = holding_to_observation(holding, provider_id="sec_13f")
        self.assertEqual(obs.metadata["holding_id"], "h-101")
        self.assertEqual(obs.value, "50000000")

    def test_observation_envelope_roundtrip(self) -> None:
        obs = ProviderObservation(
            evidence_type="MARKET_QUOTE",
            source_name="Coinbase",
            source_url="https://api.coinbase.com",
            source_tier=1,
            provider_id="coinbase_crypto",
            value="95000.5",
            unit="PRICE",
            currency="USD",
            instrument_id="BTC-USD",
            metric="price",
            metadata={"observation_id": "obs-roundtrip-1"},
        )
        envelope = obs.to_contract_envelope()
        self.assertEqual(envelope["contract_version"], CONTRACT_VERSION)
        self.assertEqual(envelope["kind"], "ProviderObservation")

        decoded = decode_contract(envelope, expected_kind="ProviderObservation")
        self.assertEqual(decoded.metadata["observation_id"], "obs-roundtrip-1")
        self.assertEqual(decoded.value, "95000.5")
        self.assertEqual(decoded.instrument_id, "BTC-USD")


if __name__ == "__main__":
    unittest.main()
