"""Tests for non-posting judgements and 5-section briefing generation."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import (
    CalculationRecord, CalculationStatus, DataAvailabilityStatus, FormulaRequirement,
    InvestmentDecision, OutputKind, TypedOutput,
)
from investment_stack.contracts.slots import BoundSlotInput, EligibilityDecision, SelectedInputSet
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
        self.assertIn("적격 가격 근거 미연결", briefing.section_table["현재가"])
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

    def test_only_eligible_typed_calculation_is_displayed_and_waits(self) -> None:
        as_of = datetime(2026, 9, 27, 23, 59, tzinfo=timezone.utc)
        slot = BoundSlotInput(
            slot_id="price", canonical_value=Decimal("123.45"), canonical_unit="USD/share",
            canonical_currency="USD", evidence_id="ev-price", eligibility_id="elig-price",
            public_available_at="2026-09-27T08:00:00+00:00", input_fingerprint="fp-price",
        )
        inputs = SelectedInputSet.create("run-price", "CURRENT_PRICE", 1, [slot])
        calc = CalculationRecord.create(
            calculation_id="calc-price", run_id=inputs.run_id, calculation_name="Spot quote",
            formula_id="price-identity", formula_version="1", status=CalculationStatus.CALCULATED,
            bound_inputs=[slot], selection_snapshot_hash=inputs.snapshot_hash,
            result_numeric=Decimal("123.45"), result_unit="USD/share", result_currency="USD",
            typed_outputs=[TypedOutput(OutputKind.PRICE, Decimal("123.45"), "USD/share", "USD")],
            purpose="CURRENT_PRICE", requirement=FormulaRequirement.ARITHMETIC,
        )
        eligibility = EligibilityDecision.eligible("elig-price", "CURRENT_PRICE", "1", "fp-price")
        briefing = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, True, True,
            eligibility_decisions={"elig-price": eligibility}, analysis_as_of=as_of,
        )
        self.assertEqual(briefing.decision, InvestmentDecision.WAIT)
        self.assertEqual(briefing.section_table["현재가"], "123.45 USD/주")
        self.assertEqual(briefing.section_table["금액·수량"], "계산 불가: 승인 정책 provenance 미검증")
        self.assertTrue(any("calc-price" in line and "ev-price" in line for line in briefing.section_details))

        missing_policy = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, False, False,
            eligibility_decisions={"elig-price": eligibility}, analysis_as_of=as_of,
        )
        self.assertEqual(missing_policy.status, DataAvailabilityStatus.UNAVAILABLE)
        self.assertEqual(missing_policy.decision, InvestmentDecision.INCONCLUSIVE)
        self.assertEqual(missing_policy.section_table["현재가"], "123.45 USD/주")
        self.assertEqual(missing_policy.section_table["실행규모"], "계산 불가: 판단 보류")
        self.assertTrue(any("calc-price" in line and "ev-price" in line for line in missing_policy.section_details))

        contradictory_price_flag = generate_briefing(
            inputs, {calc.calculation_id: calc}, False, False, False,
            eligibility_decisions={"elig-price": eligibility}, analysis_as_of=as_of,
        )
        self.assertEqual(contradictory_price_flag.numeric_bindings, ())
        self.assertIn("가격 누락", contradictory_price_flag.section_table["현재가"])

        before_publication = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, True, True,
            eligibility_decisions={"elig-price": eligibility},
            analysis_as_of=datetime(2026, 9, 27, 7, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(before_publication.numeric_bindings, ())
        self.assertIn("근거 미연결", before_publication.section_table["현재가"])
        before_publication_without_policy = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, False, False,
            eligibility_decisions={"elig-price": eligibility},
            analysis_as_of=datetime(2026, 9, 27, 7, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(before_publication_without_policy.numeric_bindings, ())
        self.assertIn("근거 미연결", before_publication_without_policy.section_table["현재가"])

    def test_generic_result_and_unbound_eligibility_are_never_displayed(self) -> None:
        briefing = generate_briefing(
            self.inputs, self.calculations, True, True, True,
            eligibility_decisions={}, analysis_as_of=datetime(2026, 9, 27, tzinfo=timezone.utc),
        )
        self.assertNotIn("50", " ".join(briefing.section_table.values()))
        self.assertEqual(briefing.numeric_bindings, ())

    def test_conditional_valuation_typed_output_displays_as_conditional(self) -> None:
        as_of = datetime(2026, 9, 27, tzinfo=timezone.utc)
        slot = BoundSlotInput(
            slot_id="financial", canonical_value=Decimal("10"), canonical_unit="USD/share",
            canonical_currency="USD", evidence_id="ev-fin", eligibility_id="elig-fin",
            public_available_at="2026-09-26T08:00:00+00:00", input_fingerprint="fp-fin",
        )
        inputs = SelectedInputSet.create("run-fin", "VALUATION_MODEL", 1, [slot])
        calc = CalculationRecord.create(
            calculation_id="calc-dcf", run_id=inputs.run_id, calculation_name="DCF", formula_id="dcf",
            formula_version="1", status=CalculationStatus.CONDITIONAL, bound_inputs=[slot],
            selection_snapshot_hash=inputs.snapshot_hash,
            typed_outputs=[TypedOutput(OutputKind.VALUATION, Decimal("150"), "USD/share", "USD")],
            purpose="VALUATION_MODEL", requirement=FormulaRequirement.ANALYST_SCENARIO,
        )
        eligibility = EligibilityDecision.eligible("elig-fin", "FINANCIAL_CALC", "1", "fp-fin")
        briefing = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, True, True,
            eligibility_decisions={"elig-fin": eligibility}, analysis_as_of=as_of,
        )
        self.assertEqual(briefing.decision, InvestmentDecision.WAIT)
        self.assertEqual(briefing.section_table["적정가 산출값"], "150 USD/주 (조건부 산출값)")
        self.assertNotIn("적정가 범위", briefing.section_table)

    def test_calculated_analyst_scenario_is_not_labeled_as_definitive_fair_price(self) -> None:
        as_of = datetime(2026, 9, 27, tzinfo=timezone.utc)
        slot = BoundSlotInput(
            slot_id="financial", canonical_value=Decimal("10"), canonical_unit="USD/share",
            canonical_currency="USD", evidence_id="ev-fin", eligibility_id="elig-fin",
            public_available_at="2026-09-26T08:00:00+00:00", input_fingerprint="fp-fin",
        )
        inputs = SelectedInputSet.create("run-fin", "VALUATION_MODEL", 1, [slot])
        calc = CalculationRecord.create(
            calculation_id="calc-scenario", run_id=inputs.run_id, calculation_name="DCF scenario",
            formula_id="dcf", formula_version="1", status=CalculationStatus.CALCULATED,
            bound_inputs=[slot], selection_snapshot_hash=inputs.snapshot_hash,
            typed_outputs=[TypedOutput(OutputKind.VALUATION, Decimal("150"), "USD/share", "USD")],
            purpose="VALUATION_MODEL", requirement=FormulaRequirement.ANALYST_SCENARIO,
        )
        eligibility = EligibilityDecision.eligible("elig-fin", "FINANCIAL_CALC", "1", "fp-fin")
        briefing = generate_briefing(
            inputs, {calc.calculation_id: calc}, True, True, True,
            eligibility_decisions={"elig-fin": eligibility}, analysis_as_of=as_of,
        )
        self.assertEqual(briefing.decision, InvestmentDecision.WAIT)
        self.assertEqual(briefing.section_table["적정가 산출값"], "150 USD/주 (조건부 산출값)")
        self.assertEqual(briefing.section_table["금액·수량"], "계산 불가: 승인 정책 provenance 미검증")
