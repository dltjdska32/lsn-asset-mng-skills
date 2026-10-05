"""Unit tests for CalculationRecord lineage, immutability, GateDecision, and policy governance."""

from __future__ import annotations

import unittest
from decimal import Decimal

from investment_stack.contracts.calculation import (
    AssumptionKind,
    CalculationAssumption,
    CalculationRecord,
    CalculationStatus,
    GateDecision,
    GateState,
)
from investment_stack.contracts.codec import decode_contract, encode_contract
from investment_stack.contracts.errors import (
    ContractValidationError,
    UnapprovedPolicyError,
)
from investment_stack.contracts.slots import BoundSlotInput


class ContractCalculationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.slot1 = BoundSlotInput("s1", Decimal("100"), "USD", "USD", "ev-1")
        self.slot2 = BoundSlotInput("s2", Decimal("50"), "USD", "USD", "ev-2")

    def test_lineage_hash_covers_result_payload_unit_currency(self) -> None:
        calc1 = CalculationRecord.create(
            calculation_id="c1",
            run_id="run-1",
            calculation_name="pe_ratio",
            formula_id="pe",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1, self.slot2],
            selection_snapshot_hash="snap_hash_1",
            result_numeric=Decimal("2.0"),
            result_unit="RATIO",
            result_currency=None,
            result_payload={"details": "standard"},
        )
        self.assertTrue(calc1.verify_lineage())

        # Altering result_currency changes lineage hash
        calc2 = CalculationRecord.create(
            calculation_id="c1",
            run_id="run-1",
            calculation_name="pe_ratio",
            formula_id="pe",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1, self.slot2],
            selection_snapshot_hash="snap_hash_1",
            result_numeric=Decimal("2.0"),
            result_unit="RATIO",
            result_currency="USD",  # changed currency
            result_payload={"details": "standard"},
        )
        self.assertNotEqual(calc1.lineage_hash, calc2.lineage_hash)

        # Altering result_payload changes lineage hash
        calc3 = CalculationRecord.create(
            calculation_id="c1",
            run_id="run-1",
            calculation_name="pe_ratio",
            formula_id="pe",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1, self.slot2],
            selection_snapshot_hash="snap_hash_1",
            result_numeric=Decimal("2.0"),
            result_unit="RATIO",
            result_currency=None,
            result_payload={"details": "altered_payload"},  # changed payload
        )
        self.assertNotEqual(calc1.lineage_hash, calc3.lineage_hash)

    def test_result_payload_deep_immutability(self) -> None:
        original_dict = {"nested": {"counter": 1}}
        calc = CalculationRecord.create(
            calculation_id="c-immut",
            run_id="run-1",
            calculation_name="calc_immut",
            formula_id="f1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1],
            selection_snapshot_hash="snap_1",
            result_payload=original_dict,
        )
        # Mutating original_dict must NOT mutate calc.result_payload
        original_dict["nested"]["counter"] = 999
        self.assertEqual(calc.result_payload["nested"]["counter"], 1)

    def test_unavailable_or_failed_status_cannot_have_numeric_result(self) -> None:
        with self.assertRaises(ContractValidationError) as ctx:
            CalculationRecord.create(
                calculation_id="c-bad-unavail",
                run_id="run-1",
                calculation_name="calc_unavail",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.UNAVAILABLE,
                bound_inputs=[self.slot1],
                selection_snapshot_hash="snap_1",
                result_numeric=Decimal("150"),  # forbidden for UNAVAILABLE
            )
        self.assertIn("numeric result must be None", str(ctx.exception))

        with self.assertRaises(ContractValidationError) as ctx:
            CalculationRecord.create(
                calculation_id="c-bad-failed",
                run_id="run-1",
                calculation_name="calc_failed",
                formula_id="f1",
                formula_version="1.0",
                status=CalculationStatus.FAILED,
                bound_inputs=[self.slot1],
                selection_snapshot_hash="snap_1",
                result_numeric=Decimal("150"),  # forbidden for FAILED
            )
        self.assertIn("numeric result must be None", str(ctx.exception))

    def test_unapproved_assumption_rejection_for_calculated_status(self) -> None:
        unapproved = CalculationAssumption(
            assumption_id="a1",
            name="growth_rate",
            value="0.15",
            is_approved=False,
        )
        with self.assertRaises(ContractValidationError) as ctx:
            CalculationRecord.create(
                calculation_id="c-unapproved",
                run_id="run-1",
                calculation_name="dcf",
                formula_id="dcf_v1",
                formula_version="1.0",
                status=CalculationStatus.CALCULATED,
                bound_inputs=[self.slot1],
                selection_snapshot_hash="snap_1",
                assumptions=[unapproved],
                result_numeric=Decimal("200"),
            )
        self.assertIn("has unapproved assumptions and cannot have status CALCULATED", str(ctx.exception))

        # But CONDITIONAL status with unapproved assumption is allowed
        calc_cond = CalculationRecord.create(
            calculation_id="c-cond",
            run_id="run-1",
            calculation_name="dcf",
            formula_id="dcf_v1",
            formula_version="1.0",
            status=CalculationStatus.CONDITIONAL,
            bound_inputs=[self.slot1],
            selection_snapshot_hash="snap_1",
            assumptions=[unapproved],
            result_numeric=Decimal("200"),
        )
        self.assertEqual(calc_cond.status, CalculationStatus.CONDITIONAL)

    def test_gate_decision_unapproved_policy_protection(self) -> None:
        # ENABLED without approval_ref must raise UnapprovedPolicyError
        with self.assertRaises(UnapprovedPolicyError) as ctx:
            GateDecision(
                gate_id="g1",
                purpose="MOMENTUM_SIGNAL",
                policy_id="pol-1",
                policy_version="1.0",
                policy_hash="hash123",
                state=GateState.ENABLED,
                approval_ref=None,
            )
        self.assertIn("requires explicit approval_ref", str(ctx.exception))

        # ENABLED with approval_ref succeeds
        gate_ok = GateDecision(
            gate_id="g2",
            purpose="MOMENTUM_SIGNAL",
            policy_id="pol-1",
            policy_version="1.0",
            policy_hash="hash123",
            state=GateState.ENABLED,
            approval_ref="gov-apr-2026-001",
        )
        self.assertEqual(gate_ok.state, GateState.ENABLED)

        # DISABLED succeeds without approval_ref
        gate_disabled = GateDecision(
            gate_id="g3",
            purpose="MOMENTUM_SIGNAL",
            policy_id="pol-1",
            policy_version="1.0",
            policy_hash="hash123",
            state=GateState.DISABLED,
        )
        self.assertEqual(gate_disabled.state, GateState.DISABLED)

    def test_gate_decision_codec_roundtrip(self) -> None:
        gate = GateDecision(
            gate_id="g4",
            purpose="VALUATION_GATE",
            policy_id="pol-val",
            policy_version="2.0",
            policy_hash="hash_abc",
            state=GateState.CONDITIONAL,
            prerequisites=("evidence_fresh", "margin_positive"),
            reasons=("Awaiting Q4 audited filings",),
        )
        encoded = encode_contract(gate)
        decoded = decode_contract(encoded, expected_kind="GateDecision")
        self.assertEqual(decoded, gate)


if __name__ == "__main__":
    unittest.main()
