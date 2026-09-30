"""Unit tests for strict codec, Decimal parsing, canonical JSON, and envelopes."""

from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.contracts.codec import (
    CONTRACT_VERSION,
    VALID_CONTRACT_KINDS,
    compute_content_hash,
    compute_semantic_hash,
    decode_contract,
    decode_envelope,
    encode_contract,
    encode_envelope,
    format_decimal,
    parse_finite_decimal,
    to_canonical_bytes,
    to_canonical_dict,
    to_canonical_json,
)
from investment_stack.contracts.errors import (
    ContractValidationError,
    DecimalValidationError,
    KindValidationError,
)
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.financial import FinancialFact
from investment_stack.contracts.institutional import Holding13F


class ContractCodecTests(unittest.TestCase):
    def test_finite_decimal_parsing_success(self) -> None:
        self.assertEqual(parse_finite_decimal(10), Decimal("10"))
        self.assertEqual(parse_finite_decimal("123.456"), Decimal("123.456"))
        self.assertEqual(parse_finite_decimal("-0.01"), Decimal("-0.01"))
        self.assertEqual(parse_finite_decimal(Decimal("42")), Decimal("42"))

    def test_non_finite_and_invalid_decimal_rejection(self) -> None:
        invalid_cases = [
            "NaN",
            "Infinity",
            "-Infinity",
            float("nan"),
            float("inf"),
            1.23,  # floats explicitly forbidden to avoid precision loss
            True,  # booleans forbidden
            False,
            "",
            "   ",
            "abc",
            [],
            {},
        ]
        for val in invalid_cases:
            with self.subTest(val=val):
                with self.assertRaises(DecimalValidationError):
                    parse_finite_decimal(val)

    def test_format_decimal_canonical_string(self) -> None:
        self.assertEqual(format_decimal(Decimal("10.00")), "10")
        self.assertEqual(format_decimal(Decimal("123.4500")), "123.45")
        self.assertEqual(format_decimal(Decimal("0.0")), "0")
        self.assertEqual(format_decimal(Decimal("-0.0")), "0")
        self.assertEqual(format_decimal(Decimal("1000000")), "1000000")
        # Roundtrip equality
        d = Decimal("3.1415926535")
        self.assertEqual(Decimal(format_decimal(d)), d)

    def test_canonical_json_determinism_and_hashing(self) -> None:
        data1 = {"b": 2, "a": 1, "c": [3, 2, 1], "d": Decimal("10.50")}
        data2 = {"c": [3, 2, 1], "d": Decimal("10.5"), "a": 1, "b": 2}
        json1 = to_canonical_json(data1)
        json2 = to_canonical_json(data2)
        self.assertEqual(json1, json2)
        self.assertEqual(json1, '{"a":1,"b":2,"c":[3,2,1],"d":"10.5"}')

        hash1 = compute_content_hash(data1)
        hash2 = compute_content_hash(data2)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_envelope_encode_decode_success(self) -> None:
        payload = {"instrument_id": "AAPL", "price": Decimal("150.25")}
        envelope = encode_envelope("MarketQuote", payload)
        self.assertEqual(envelope["contract_version"], CONTRACT_VERSION)
        self.assertEqual(envelope["kind"], "MarketQuote")
        self.assertEqual(envelope["payload"]["price"], "150.25")

        kind, decoded_payload = decode_envelope(envelope, expected_kind="MarketQuote")
        self.assertEqual(kind, "MarketQuote")
        self.assertEqual(decoded_payload["instrument_id"], "AAPL")
        self.assertEqual(decoded_payload["price"], "150.25")

    def test_counterexample_1_unrecognized_kind_rejected(self) -> None:
        """Counterexample 1: decode_envelope(UNRECOGNIZED) must be rejected with KindValidationError."""
        bad_envelope = {
            "contract_version": "0.2",
            "kind": "UNRECOGNIZED",
            "payload": {},
        }
        with self.assertRaises(KindValidationError) as ctx:
            decode_envelope(bad_envelope)
        self.assertIn("Unrecognized contract kind", str(ctx.exception))

    def test_envelope_extra_keys_rejected(self) -> None:
        """Envelopes containing unknown/extra fields must be rejected."""
        extra_envelope = {
            "contract_version": "0.2",
            "kind": "MarketQuote",
            "payload": {},
            "injected_extra_field": "bad",
        }
        with self.assertRaises(ContractValidationError) as ctx:
            decode_envelope(extra_envelope)
        self.assertIn("unexpected fields", str(ctx.exception))

    def test_envelope_decode_version_and_kind_enforcement(self) -> None:
        # Invalid version
        bad_ver = {"contract_version": "0.1", "kind": "MarketQuote", "payload": {}}
        with self.assertRaises(ContractValidationError) as ctx:
            decode_envelope(bad_ver)
        self.assertIn("Unsupported contract version", str(ctx.exception))

        # Kind mismatch
        envelope = encode_envelope("MarketQuote", {"key": "val"})
        with self.assertRaises(ContractValidationError) as ctx:
            decode_envelope(envelope, expected_kind="FinancialFact")
        self.assertIn("Envelope kind mismatch", str(ctx.exception))

        # Malformed envelope
        with self.assertRaises(ContractValidationError):
            decode_envelope("not_a_dict")  # type: ignore[arg-type]
        with self.assertRaises(ContractValidationError):
            decode_envelope({"contract_version": CONTRACT_VERSION, "kind": "MarketQuote", "payload": "not_a_dict"})

    def test_typed_roundtrip_domain_dtos(self) -> None:
        from datetime import datetime, timezone
        from investment_stack.contracts.context import PublicAvailability
        from investment_stack.contracts.financial import (
            AccountingStandard,
            AdjustmentBasis,
            ConsolidationKind,
            PeriodType,
            ReportingFrequency,
            ScaleStatus,
        )
        from investment_stack.contracts.institutional import PutCall, QuantityType
        from investment_stack.contracts.slots import DimensionKind

        now = datetime(2026, 9, 23, 9, 30, tzinfo=timezone.utc)
        avail = PublicAvailability.exact(now, locator="test")

        # 1. MarketQuote
        quote = MarketQuote(
            quote_id="q-1",
            evidence_id="ev-q1",
            instrument_id="AAPL",
            currency="USD",
            price=Decimal("150.25"),
            quote_kind=QuoteKind.REGULAR,
            retrieved_at=now,
            public_availability=avail,
            venue="NASDAQ",
        )
        encoded_quote = encode_contract(quote)
        decoded_quote = decode_contract(encoded_quote, expected_kind="MarketQuote")
        self.assertEqual(decoded_quote, quote)

        # 2. FinancialFact
        fact = FinancialFact(
            fact_id="fact-1",
            evidence_id="ev-f1",
            instrument_id="AAPL",
            taxonomy="us-gaap",
            original_tag="Revenues",
            canonical_metric="revenue",
            raw_value=Decimal("94836000000"),
            raw_unit="USD",
            explicit_scale=ScaleStatus.VALID,
            scale_multiplier=Decimal("1"),
            normalized_value=Decimal("94836000000"),
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
            public_availability=avail,
            accession="0000320193-26-000001",
        )
        encoded_fact = encode_contract(fact)
        decoded_fact = decode_contract(encoded_fact, expected_kind="FinancialFact")
        self.assertEqual(decoded_fact, fact)

        # 3. Holding13F
        holding = Holding13F(
            holding_id="h-1",
            filing_id="filing-1",
            cusip="037833100",
            issuer_name="APPLE INC",
            raw_quantity=Decimal("1000000"),
            raw_value=Decimal("150000"),
            normalized_value=Decimal("150000000"),
            normalized_shares=Decimal("1000000"),
            put_call=PutCall.NONE,
            quantity_type=QuantityType.SH,
        )
        encoded_holding = encode_contract(holding)
        decoded_holding = decode_contract(encoded_holding, expected_kind="Holding13F")
        self.assertEqual(decoded_holding, holding)


if __name__ == "__main__":
    unittest.main()
