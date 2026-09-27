"""Comprehensive unit tests covering CA01-CA07 findings and acceptance boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

import investment_stack.contracts as c
from investment_stack.contracts.errors import (
    ContractError,
    ContractValidationError,
    CorruptedStorageError,
    DecimalValidationError,
    KindValidationError,
    SlotCoherenceError,
)
import investment_stack.providers.contract_adapters as adapters


def _availability() -> c.PublicAvailability:
    return c.PublicAvailability.exact(
        datetime(2026, 9, 23, tzinfo=timezone.utc), locator="fixture"
    )


def _fact() -> c.FinancialFact:
    return c.FinancialFact(
        "f",
        "e",
        "TEST",
        "gaap",
        "Revenue",
        "revenue",
        Decimal("2"),
        "USD million",
        c.ScaleStatus.VALID,
        Decimal("1000000"),
        Decimal("2000000"),
        "MONEY",
        "USD",
        "DURATION",
        "2025-01-01",
        "2025-12-31",
        365,
        2025,
        "FY",
        "ANNUAL",
        "CONSOLIDATED",
        "US-GAAP",
        "REPORTED",
        _availability(),
    )


def _holding(**kwargs) -> c.Holding13F:
    return c.Holding13F(
        "h",
        "filing",
        "cusip",
        "Issuer",
        Decimal("1"),
        Decimal("2"),
        Decimal("2"),
        Decimal("1"),
        **kwargs,
    )


def _bar() -> c.Bar:
    return c.Bar(
        "b",
        "e",
        "TEST",
        "1h",
        "2026-09-23",
        datetime(2026, 9, 23, 9, tzinfo=timezone.utc),
        datetime(2026, 9, 23, 10, tzinfo=timezone.utc),
        "UTC",
        Decimal("1"),
        Decimal("2"),
        Decimal("1"),
        Decimal("2"),
        Decimal("0"),
        "USD",
        _availability(),
        is_complete=False,
    )


class ContractAuditProbesTests(unittest.TestCase):
    def test_string_false_approval(self) -> None:
        """String 'false' must not become approved True in CalculationAssumption."""
        with self.assertRaises(ContractError):
            c.decode_contract(
                c.encode_envelope(
                    "CalculationAssumption",
                    {
                        "assumption_id": "a",
                        "name": "unapproved",
                        "value": "1",
                        "is_approved": "false",
                    },
                ),
                expected_kind="CalculationAssumption",
            )

        # Positive case: boolean True and False roundtrip properly
        assump = c.CalculationAssumption("a", "approved", "1", is_approved=True)
        self.assertTrue(assump.is_approved)
        decoded = c.decode_contract(c.encode_contract(assump), expected_kind="CalculationAssumption")
        self.assertTrue(decoded.is_approved)

    def test_string_false_coverage(self) -> None:
        """String 'false' is not a wire bool for is_complete and extra keys are rejected."""
        with self.assertRaises(ContractError):
            c.decode_contract(
                c.encode_envelope(
                    "CoverageDecision",
                    {
                        "request_id": "r",
                        "fulfilled_slots": [],
                        "missing_slots": ["price"],
                        "is_complete": "false",
                        "unknown_rule": "ignore",
                    },
                ),
                expected_kind="CoverageDecision",
            )

    def test_contradictory_coverage(self) -> None:
        """Missing required slot and is_complete=True cannot coexist."""
        with self.assertRaises(ContractError):
            c.decode_contract(
                c.encode_envelope(
                    "CoverageDecision",
                    {
                        "request_id": "r",
                        "fulfilled_slots": [],
                        "missing_slots": ["price"],
                        "conflicted_slots": [],
                        "is_complete": True,
                    },
                ),
                expected_kind="CoverageDecision",
            )

        # Positive case: consistent complete coverage
        cov = c.CoverageDecision(
            request_id="r",
            fulfilled_slots=("price",),
            missing_slots=(),
            conflicted_slots=(),
            is_complete=True,
        )
        self.assertTrue(cov.is_complete)

    def test_wrong_nested_kind(self) -> None:
        """MarketQuote requires PublicAvailability, not another registered kind."""
        gate = c.GateDecision("g", "TRADING", "unapproved", "1", "hash", "CONDITIONAL")
        with self.assertRaises(ContractError):
            c.decode_contract(
                c.encode_envelope(
                    "MarketQuote",
                    {
                        "quote_id": "q",
                        "evidence_id": "e",
                        "instrument_id": "TEST",
                        "currency": "USD",
                        "price": "1",
                        "quote_kind": "REGULAR",
                        "retrieved_at": "2026-09-23T09:00:00+00:00",
                        "public_availability": c.encode_envelope("GateDecision", gate),
                    },
                ),
                expected_kind="MarketQuote",
            )

    def test_invalid_slot_wire(self) -> None:
        """Unknown enum/date and bool duration cannot form a valid SlotSpec."""
        with self.assertRaises(ContractError):
            c.decode_contract(
                c.encode_envelope(
                    "SlotSpec",
                    {
                        "slot_id": "s",
                        "purpose": "ALIEN",
                        "instrument_id": "TEST",
                        "metric": "revenue",
                        "dimension": "ALIEN",
                        "target_period_start": "bad",
                        "target_period_end": "worse",
                        "duration_days": True,
                    },
                ),
                expected_kind="SlotSpec",
            )

    def test_missing_instrument(self) -> None:
        """Required instrument identity must not match None."""
        s = c.SlotSpec("s", "FINANCIAL_CALC", "TEST", "revenue", "MONEY", "USD")
        matched, reason = s.matches_candidate(candidate_currency="USD", candidate_dimension="MONEY")
        self.assertFalse(matched)
        self.assertIn("Instrument missing", str(reason))

        # Positive case: exact instrument matches
        matched_ok, reason_ok = s.matches_candidate(
            candidate_currency="USD",
            candidate_dimension="MONEY",
            candidate_instrument_id="TEST",
        )
        self.assertTrue(matched_ok)
        self.assertIsNone(reason_ok)

    def test_unapproved_conditional_gate(self) -> None:
        """Unapproved TRADING policy needs disabled/rejected gate, not bare CONDITIONAL."""
        try:
            g = c.GateDecision("g", "TRADING", "unapproved", "1", "hash", "CONDITIONAL")
            self.assertEqual(str(g.state), "DISABLED")
        except c.ContractError:
            pass

    def test_unavailable_action_payload(self) -> None:
        """UNAVAILABLE must not carry a consumable action price."""
        with self.assertRaises(ContractError):
            c.CalculationRecord.create(
                "u",
                "run",
                "model",
                "f",
                "1",
                "UNAVAILABLE",
                [],
                "snapshot",
                result_payload={"buy_price": "100"},
            )

        # Positive case: UNAVAILABLE with reason payload only
        calc = c.CalculationRecord.create(
            "u2",
            "run",
            "model",
            "f",
            "1",
            "UNAVAILABLE",
            [],
            "snapshot",
            result_payload={"status_reason": "Data feed timed out"},
        )
        self.assertEqual(calc.status, c.CalculationStatus.UNAVAILABLE)

    def test_invalid_raw_promoted_to_coverage(self) -> None:
        """Raw invalid data may survive in collection, but cannot declare validated coverage."""
        invalid = replace(
            _fact(),
            explicit_scale=c.ScaleStatus.INVALID,
            normalized_value=Decimal("999"),
            currency="JPY",
            period_start=None,
            period_end="not-a-date",
            duration_days=None,
        )
        other = replace(
            _fact(),
            fact_id="g",
            evidence_id="e2",
            canonical_metric="operating_income",
            reporting_frequency="QUARTER",
            period_start="2026-04-01",
            period_end="2026-06-30",
            duration_days=91,
        )
        fs = c.FinancialSet.create("set", "TEST", "USD", [invalid, other])
        self.assertNotIn("revenue", fs.covered_metrics)
        self.assertIn("operating_income", fs.covered_metrics)
        self.assertEqual(len(fs.facts), 2)

    def test_unknown_storage_version(self) -> None:
        """Unsupported schema_version must be rejected."""
        with self.assertRaises(ContractError):
            c.extract_contract_storage(
                json.dumps(
                    {
                        c.CONTRACT_STORAGE_KEY: {
                            "schema_version": "999",
                            "latest_revision": 10,
                            "history": [],
                            "active_selections": {"PRICE": "missing"},
                        }
                    }
                )
            )

    def test_null_storage_namespace(self) -> None:
        """Present null namespace is corrupted, not an empty legacy ledger."""
        with self.assertRaises(ContractError):
            c.extract_contract_storage(json.dumps({c.CONTRACT_STORAGE_KEY: None}))

    def test_normalized_fact_unit(self) -> None:
        """Normalized value must carry canonical unit, not raw million unit."""
        obs = adapters.fact_to_observation(_fact())
        self.assertEqual(Decimal(obs.value), Decimal("2000000"))
        self.assertEqual(obs.unit, "USD")
        self.assertEqual(obs.metadata.get("raw_unit"), "USD million")

    def test_bar_price_unit(self) -> None:
        """Bar close is price; it must not carry volume unit SHARES."""
        obs = adapters.bar_to_observation(_bar())
        self.assertIn(obs.unit, {"USD", "USD/share", "PRICE"})
        self.assertEqual(obs.metadata.get("volume_unit"), "SHARES")

    def test_voting_roundtrip(self) -> None:
        """Non-null voting fields must survive encode/decode exactly."""
        h = _holding(
            value_scale=Decimal("1"),
            voting_sole=Decimal("1"),
            voting_shared=Decimal("2"),
            voting_none=Decimal("3"),
        )
        out = c.decode_contract(c.encode_contract(h), expected_kind="Holding13F")
        self.assertEqual(
            (out.voting_sole, out.voting_shared, out.voting_none),
            (Decimal("1"), Decimal("2"), Decimal("3")),
        )

    def test_quantity_type_preserved(self) -> None:
        """PRN/SH quantity basis must survive the provider bridge."""
        obs = adapters.holding_to_observation(
            _holding(quantity_type="PRN", value_scale=Decimal("1"))
        )
        self.assertEqual(obs.metadata.get("quantity_type"), "PRN")

    def test_no_implicit_13f_scale(self) -> None:
        """No source mapping means no invented scale=1000."""
        h = _holding()
        self.assertIsNone(h.value_scale)

    def test_bar_interval_scope(self) -> None:
        """A validated daily BarSet cannot contain hourly bars."""
        with self.assertRaises(ContractError):
            c.BarSet.create("TEST", "1d", "USD", "RAW", [_bar()])

    def test_snapshot_semantic_scope(self) -> None:
        """Purpose/public version/fingerprint changes must alter semantic identity."""
        s = c.BoundSlotInput("price", Decimal("1"), "USD", "USD", "e")
        one = c.SelectedInputSet.create("run", "CURRENT_PRICE", 1, [s])
        two = c.SelectedInputSet.create(
            "run",
            "FINANCIAL_CALC",
            1,
            [replace(s, public_available_at="2999-01-01T00:00:00Z", input_fingerprint="different")],
        )
        self.assertNotEqual(one.semantic_hash(), two.semantic_hash())

    def test_manager_import_boundary(self) -> None:
        """Evidence manager module must import cleanly without error."""
        import investment_stack.evidence.manager  # noqa: F401


if __name__ == "__main__":
    unittest.main()
