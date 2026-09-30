"""Comprehensive unit tests for gate decisions, strict codec, typed outputs, and calculation validation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import (
    AssumptionKind,
    CalculationAssumption,
    CalculationRecord,
    CalculationStatus,
    FormulaRequirement,
    GateDecision,
    GateState,
    OutputKind,
    TypedOutput,
    ValidatedCalculation,
    validate_calculation_for_use,
)
from investment_stack.contracts.codec import (
    CONTRACT_VERSION,
    decode_contract,
    encode_contract,
    encode_envelope,
    parse_strict_json,
    to_canonical_dict,
)
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.errors import (
    ContractValidationError,
    UnapprovedPolicyError,
)
from investment_stack.contracts.financial import (
    AccountingStandard,
    AdjustmentBasis,
    ConsolidationKind,
    FinancialFact,
    PeriodType,
    ReportingFrequency,
    ScaleStatus,
)
from investment_stack.contracts.institutional import Holding13F, HoldingSet13F
from investment_stack.contracts.market import MarketQuote, QuoteKind
from investment_stack.contracts.slots import BoundSlotInput, DimensionKind
from investment_stack.providers.contract_adapters import (
    fact_to_observation,
    quote_to_observation,
)
from investment_stack.providers.models import ProviderObservation


class ContractGateAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        self.pub = PublicAvailability.exact(self.now, locator="fixture://release")

    def test_strict_json_duplicate_keys_rejected(self) -> None:
        doc = (
            '{"contract_version":"'
            + CONTRACT_VERSION
            + '","kind":"CalculationAssumption",'
            '"payload":{"assumption_id":"a","name":"rate","value":"1",'
            '"is_approved":false,"is_approved":true}}'
        )
        with self.assertRaises(ContractValidationError) as ctx:
            decode_contract(doc, expected_kind="CalculationAssumption")
        self.assertIn("Duplicate key", str(ctx.exception))

    def test_strict_json_nonfinite_token_rejected(self) -> None:
        doc = (
            '{"contract_version":"'
            + CONTRACT_VERSION
            + '","kind":"CalculationAssumption",'
            '"payload":{"assumption_id":"a","name":"rate","value":NaN,"unit":"ratio",'
            '"is_approved":true}}'
        )
        with self.assertRaises(ContractValidationError) as ctx:
            decode_contract(doc, expected_kind="CalculationAssumption")
        self.assertIn("Nonstandard JSON constant", str(ctx.exception))

    def test_market_quote_string_bool_rejected(self) -> None:
        payload = {
            "quote_id": "q",
            "evidence_id": "e",
            "instrument_id": "TEST",
            "currency": "USD",
            "price": "100",
            "quote_kind": "REGULAR",
            "retrieved_at": self.now.isoformat(),
            "public_availability": to_canonical_dict(self.pub),
            "is_trade": "false",
        }
        with self.assertRaises(ContractValidationError):
            decode_contract(payload, expected_kind="MarketQuote")

    def test_holding_set_string_bool_rejected(self) -> None:
        payload = {
            "filing_id": "f",
            "manager_cik": "cik-1",
            "report_period": "2026-06-30",
            "holdings": [],
            "total_eligible_value": "0",
            "is_amended": "false",
        }
        with self.assertRaises(ContractValidationError):
            decode_contract(payload, expected_kind="HoldingSet13F")

    def test_provider_observation_bool_source_tier_rejected(self) -> None:
        payload = {
            "evidence_type": "MARKET_QUOTE",
            "source_name": "src",
            "source_url": "test://src",
            "source_tier": True,
            "provider_id": "p1",
            "value": "10",
        }
        with self.assertRaises(ContractValidationError):
            decode_contract(payload, expected_kind="ProviderObservation")

    def test_gate_purpose_whitespace_rejected(self) -> None:
        with self.assertRaises(ContractValidationError):
            GateDecision(
                gate_id="g1",
                purpose="TRADING ",
                policy_id="p1",
                policy_version="1",
                policy_hash="h1",
                state=GateState.CONDITIONAL,
            )

    def test_13f_gate_requires_both_approval_and_validation(self) -> None:
        g = GateDecision(
            gate_id="g13f",
            purpose="13F_AGGREGATE",
            policy_id="policy-13f",
            policy_version="1.0",
            policy_hash="h-13f",
            state=GateState.ENABLED,
            approval_ref="approved-13f",
            validation_ref=None,
        )
        self.assertEqual(g.state, GateState.DISABLED)

        g_valid = GateDecision(
            gate_id="g13f_valid",
            purpose="13F_AGGREGATE",
            policy_id="policy-13f",
            policy_version="1.0",
            policy_hash="h-13f",
            state=GateState.ENABLED,
            approval_ref="approved-13f",
            validation_ref="validated-13f",
        )
        self.assertEqual(g_valid.state, GateState.ENABLED)

    def test_policy_id_word_unapproved_does_not_false_positive(self) -> None:
        g = GateDecision(
            gate_id="g_approved",
            purpose="13F_AGGREGATE",
            policy_id="previously-unapproved-policy",
            policy_version="1.0",
            policy_hash="hash-1",
            state=GateState.ENABLED,
            approval_ref="appr-ref",
            validation_ref="val-ref",
        )
        self.assertEqual(g.state, GateState.ENABLED)

    def test_calculation_record_payload_immutability(self) -> None:
        record = CalculationRecord.create(
            calculation_id="c1",
            run_id="run-1",
            calculation_name="test_immutability",
            formula_id="price_identity",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[],
            selection_snapshot_hash="snap-hash-1",
            result_numeric=Decimal("100"),
            result_payload={"details": {"nested_key": "initial_value"}},
        )
        with self.assertRaises(TypeError):
            record.result_payload["details"]["nested_key"] = "tampered_value"  # type: ignore[index]
        self.assertEqual(record.result_payload["details"]["nested_key"], "initial_value")
        self.assertTrue(record.verify_lineage())

    def test_unavailable_calculation_cannot_hide_numerics(self) -> None:
        with self.assertRaises(ContractValidationError):
            CalculationRecord.create(
                calculation_id="c_unavail_num",
                run_id="run-1",
                calculation_name="unavail",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.UNAVAILABLE,
                bound_inputs=[],
                selection_snapshot_hash="snap",
                result_numeric=Decimal("50"),
            )

        with self.assertRaises(ContractValidationError):
            CalculationRecord.create(
                calculation_id="c_unavail_nested",
                run_id="run-1",
                calculation_name="unavail",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.UNAVAILABLE,
                bound_inputs=[],
                selection_snapshot_hash="snap",
                result_payload={"details": {"entry": Decimal("100")}},
            )

        with self.assertRaises(ContractValidationError):
            CalculationRecord.create(
                calculation_id="c_unavail_str_num",
                run_id="run-1",
                calculation_name="unavail",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.UNAVAILABLE,
                bound_inputs=[],
                selection_snapshot_hash="snap",
                result_payload={"진입가": "100"},
            )

        record_ok = CalculationRecord.create(
            calculation_id="c_unavail_text",
            run_id="run-1",
            calculation_name="unavail",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.UNAVAILABLE,
            bound_inputs=[],
            selection_snapshot_hash="snap",
            result_payload={"price_error": "source unavailable"},
        )
        self.assertIsNone(record_ok.result_numeric)
        self.assertTrue(record_ok.verify_lineage())

    def test_validate_calculation_for_use_arithmetic_passes_without_gate(self) -> None:
        record = CalculationRecord.create(
            calculation_id="c_arith",
            run_id="run-1",
            calculation_name="arithmetic_sum",
            formula_id="arithmetic",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[],
            selection_snapshot_hash="snap",
            result_numeric=Decimal("5"),
            result_unit="count",
            typed_outputs=[
                TypedOutput(kind=OutputKind.ARITHMETIC_RESULT, value=Decimal("5"), unit="count")
            ],
        )
        validated = validate_calculation_for_use(record)
        self.assertTrue(validated.is_consumable)
        self.assertEqual(validated.requirement, FormulaRequirement.ARITHMETIC)
        self.assertEqual(len(validated.outputs), 1)

    def test_validate_calculation_for_use_scenario_conditional(self) -> None:
        assumption = CalculationAssumption(
            assumption_id="a1",
            name="growth_rate",
            value="0.05",
            unit="ratio",
            kind=AssumptionKind.ANALYST_SCENARIO,
            is_approved=False,
        )
        record = CalculationRecord.create(
            calculation_id="c_scen",
            run_id="run-1",
            calculation_name="scenario_eval",
            formula_id="scenario_growth",
            formula_version="1.0",
            status=CalculationStatus.CONDITIONAL,
            bound_inputs=[],
            selection_snapshot_hash="snap",
            assumptions=[assumption],
            result_numeric=Decimal("105"),
            typed_outputs=[
                TypedOutput(kind=OutputKind.SCENARIO_VALUE, value=Decimal("105"), unit="USD")
            ],
        )
        validated = validate_calculation_for_use(record)
        self.assertTrue(validated.is_consumable)
        self.assertEqual(validated.requirement, FormulaRequirement.ANALYST_SCENARIO)

    def test_validate_calculation_for_use_policy_verification_rejection(self) -> None:
        gate_disabled = GateDecision(
            gate_id="g_13f_dis",
            purpose="13F_AGGREGATE",
            policy_id="pol-13f",
            policy_version="1.0",
            policy_hash="h1",
            state=GateState.DISABLED,
        )
        record = CalculationRecord.create(
            calculation_id="c_13f",
            run_id="run-1",
            calculation_name="13f_eval",
            formula_id="13f_comparison",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[],
            selection_snapshot_hash="snap",
            gate_refs=["g_13f_dis"],
            result_numeric=Decimal("42"),
        )
        with self.assertRaises(UnapprovedPolicyError):
            validate_calculation_for_use(record, registered_gates=[gate_disabled])

    def test_provider_observation_lossless_roundtrip(self) -> None:
        obs = ProviderObservation(
            evidence_type="NEWS",
            source_name="Bloomberg",
            source_url="https://bloomberg.com/news/1",
            source_tier=1,
            provider_id="bloomberg_feed",
            value="AAPL Q4 beat",
            instrument_id="AAPL",
            official_confirmation_status="CONFIRMED",
            event_cluster_id="cluster-99",
            relevance_reason="High earnings impact",
        )
        env = obs.to_contract_envelope()
        decoded = decode_contract(env, expected_kind="ProviderObservation")
        self.assertEqual(decoded.official_confirmation_status, "CONFIRMED")
        self.assertEqual(decoded.event_cluster_id, "cluster-99")
        self.assertEqual(decoded.relevance_reason, "High earnings impact")
        self.assertEqual(decoded, obs)

    def test_provider_adapter_unit_normalization(self) -> None:
        fact_shares = FinancialFact(
            fact_id="f-sh",
            evidence_id="e-sh",
            instrument_id="AAPL",
            taxonomy="us-gaap",
            original_tag="CommonStockSharesOutstanding",
            canonical_metric="shares_outstanding",
            raw_value=Decimal("2"),
            raw_unit="thousand shares",
            explicit_scale=ScaleStatus.VALID,
            scale_multiplier=Decimal("1000"),
            normalized_value=Decimal("2000"),
            dimension=DimensionKind.SHARES,
            currency=None,
            period_type=PeriodType.INSTANT,
            period_start="2025-12-31",
            period_end="2025-12-31",
            duration_days=0,
            fiscal_year=2025,
            fiscal_period="FY",
            reporting_frequency=ReportingFrequency.ANNUAL,
            consolidation=ConsolidationKind.CONSOLIDATED,
            accounting_standard=AccountingStandard.US_GAAP,
            adjustment_basis=AdjustmentBasis.REPORTED,
            public_availability=self.pub,
        )
        obs_shares = fact_to_observation(fact_shares)
        self.assertEqual(obs_shares.value, "2000")
        self.assertEqual(obs_shares.unit, "shares")

        fact_eps = FinancialFact(
            fact_id="f-eps",
            evidence_id="e-eps",
            instrument_id="AAPL",
            taxonomy="us-gaap",
            original_tag="EarningsPerShareBasic",
            canonical_metric="eps",
            raw_value=Decimal("2"),
            raw_unit="USD thousand/share",
            explicit_scale=ScaleStatus.VALID,
            scale_multiplier=Decimal("1000"),
            normalized_value=Decimal("2000"),
            dimension=DimensionKind.MONEY_PER_SHARE,
            currency="USD",
            period_type=PeriodType.DURATION,
            period_start="2025-01-01",
            period_end="2025-12-31",
            duration_days=365,
            fiscal_year=2025,
            fiscal_period="FY",
            reporting_frequency=ReportingFrequency.ANNUAL,
            consolidation=ConsolidationKind.CONSOLIDATED,
            accounting_standard=AccountingStandard.US_GAAP,
            adjustment_basis=AdjustmentBasis.REPORTED,
            public_availability=self.pub,
        )
        obs_eps = fact_to_observation(fact_eps)
        self.assertEqual(obs_eps.value, "2000")
        self.assertEqual(obs_eps.unit, "USD/share")


if __name__ == "__main__":
    unittest.main()
