"""Tests for non-posting judgements and 5-section briefing generation."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import CalculationRecord, CalculationStatus, DataAvailabilityStatus, InvestmentDecision
from investment_stack.contracts.slots import BoundSlotInput, SelectedInputSet
from investment_stack.decisions.briefing import NonPostingBriefing, generate_briefing


class TestBriefingLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.slot1 = BoundSlotInput(
            slot_id="slot_a",
            canonical_value=Decimal("100.00"),
            canonical_unit="SHARE",
            canonical_currency="USD",
            evidence_id="ev_1",
            input_fingerprint="fp1",
        )
        self.inputs = SelectedInputSet.create(
            run_id="run_1",
            purpose="TEST",
            selection_version=1,
            slots=[self.slot1],
        )

        self.calc1 = CalculationRecord.create(
            calculation_id="calc_1",
            run_id="run_1",
            calculation_name="Test Calc",
            formula_id="f_1",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1],
            selection_snapshot_hash=self.inputs.snapshot_hash,
            result_numeric=Decimal("50.0"),
            result_unit="SHARE",
            result_currency="USD",
        )
        self.calculations = {"calc_1": self.calc1}

    def test_briefing_available_wait(self) -> None:
        briefing = generate_briefing(
            inputs=self.inputs,
            calculations=self.calculations,
            has_price=True,
            has_policy=True,
            has_personal_snapshot=True,
        )
        self.assertEqual(briefing.status, DataAvailabilityStatus.PARTIAL)
        self.assertEqual(briefing.decision, InvestmentDecision.WAIT)
        self.assertIn("대기", briefing.section_judgement)
        self.assertIn("적격 가격 결과 미연결", briefing.section_table["현재가"])
        self.assertIn("승인 정책 provenance", briefing.section_table["금액·수량"])
        self.assertFalse(any("50.0" in line for line in briefing.section_details))
        self.assertFalse(any("50.0" in value for value in briefing.section_table.values()))
        self.assertTrue(any("UNVALIDATED" in line for line in briefing.section_core))

    def test_briefing_missing_price_inconclusive(self) -> None:
        briefing = generate_briefing(
            inputs=self.inputs,
            calculations=self.calculations,
            has_price=False,
            has_policy=True,
            has_personal_snapshot=True,
        )
        self.assertEqual(briefing.status, DataAvailabilityStatus.UNAVAILABLE)
        self.assertEqual(briefing.decision, InvestmentDecision.INCONCLUSIVE)
        self.assertIn("판단 보류", briefing.section_judgement)
        self.assertIn("가격 누락", briefing.section_table["현재가"])

    def test_briefing_missing_all_inconclusive(self) -> None:
        briefing = generate_briefing(
            inputs=self.inputs,
            calculations={},
            has_price=False,
            has_policy=False,
            has_personal_snapshot=False,
        )
        self.assertEqual(briefing.status, DataAvailabilityStatus.UNAVAILABLE)
        self.assertEqual(briefing.decision, InvestmentDecision.INCONCLUSIVE)
        self.assertIn("판단 보류", briefing.section_judgement)
        self.assertIn("가격 누락", briefing.section_table["현재가"])
        self.assertIn("정책 누락", briefing.section_table["정책한도"])

    def test_briefing_run_id_mismatch(self) -> None:
        calc2 = CalculationRecord.create(
            calculation_id="calc_2",
            run_id="run_2_wrong",
            calculation_name="Test Calc 2",
            formula_id="f_2",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[self.slot1],
            selection_snapshot_hash=self.inputs.snapshot_hash,
            result_numeric=Decimal("50.0"),
            result_currency="USD",
        )
        calcs = {"calc_1": self.calc1, "calc_2": calc2}

        briefing = generate_briefing(
            inputs=self.inputs,
            calculations=calcs,
            has_price=True,
            has_policy=True,
            has_personal_snapshot=True,
        )
        self.assertEqual(briefing.status, DataAvailabilityStatus.UNAVAILABLE)
        self.assertEqual(briefing.decision, InvestmentDecision.INCONCLUSIVE)
        self.assertTrue(any("run_id mismatch" in r for r in briefing.section_details))

    def test_briefing_slot_mismatch(self) -> None:
        slot_wrong = BoundSlotInput(
            slot_id="slot_a",
            canonical_value=Decimal("999.00"),
            canonical_unit="SHARE",
            canonical_currency="USD",
            evidence_id="ev_1",
            input_fingerprint="fp1",
        )
        calc2 = CalculationRecord.create(
            calculation_id="calc_2",
            run_id="run_1",
            calculation_name="Test Calc 2",
            formula_id="f_2",
            formula_version="1.0",
            status=CalculationStatus.CALCULATED,
            bound_inputs=[slot_wrong],
            selection_snapshot_hash=self.inputs.snapshot_hash,
            result_numeric=Decimal("50.0"),
            result_currency="USD",
        )
        calcs = {"calc_1": self.calc1, "calc_2": calc2}

        briefing = generate_briefing(
            inputs=self.inputs,
            calculations=calcs,
            has_price=True,
            has_policy=True,
            has_personal_snapshot=True,
        )
        self.assertEqual(briefing.status, DataAvailabilityStatus.UNAVAILABLE)
        self.assertEqual(briefing.decision, InvestmentDecision.INCONCLUSIVE)
        self.assertTrue(any("value mismatch" in r for r in briefing.section_details))
