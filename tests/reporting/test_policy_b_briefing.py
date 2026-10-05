from datetime import datetime
from decimal import Decimal as D
import unittest

from investment_stack.decisions.policy_b import (
    EntryPricePrerequisites, Money, PolicyBInput, evaluate_policy_b,
)
from investment_stack.decisions.policy_b_sizing import TradingRules, size_policy_b_tranches
from investment_stack.reporting.models import Availability
from investment_stack.reporting.policy_b_briefing import build_policy_b_section


CUTOFF = datetime.fromisoformat("2026-09-28T10:00:00+09:00")


def complete_policy(**overrides):
    def money(value):
        return Money(D(value), "USD", verified=True)
    values = dict(
        evaluation_currency="USD", fair_value_per_share=money("100"),
        optimistic_fair_value_per_share=money("120"), quote_per_share=money("90"),
        portfolio_value=money("100000"), cash=money("20000"),
        holding_value=money("4000"), holding_units=D("40"),
        holding_units_verified=True, thesis_impaired=False,
        approved_risk_budget=money("4000"),
        entry_price_prerequisites=EntryPricePrerequisites(True, True, True, True, True),
    )
    values.update(overrides)
    return evaluate_policy_b(PolicyBInput(**values))


class PolicyBBriefingTests(unittest.TestCase):
    def test_partial_inputs_hide_numeric_entry_levels_even_when_formula_can_be_described(self):
        partial = evaluate_policy_b(PolicyBInput(
            evaluation_currency="USD", fair_value_per_share=Money(D("100"), "USD", verified=True),
        ))
        section = build_policy_b_section("ABC", CUTOFF, partial)
        rendered = "\n".join(section.lines)
        self.assertEqual(Availability.PARTIAL, section.status)
        self.assertIn("진입 가격·금액·수량 대기", rendered)
        self.assertNotIn("80 USD", rendered)
        self.assertEqual((), section.calculation_ids)

    def test_caller_reference_strings_cannot_release_action_prices(self):
        section = build_policy_b_section(
            "ABC", CUTOFF, complete_policy(),
            evidence_ids=("ev:quote", "ev:valuation", "ev:state"),
            calculation_ids=("calc:policy",),
        )
        rendered = "\n".join(section.lines)
        self.assertEqual(Availability.PARTIAL, section.status)
        for value in ("80.00 USD/주", "75.00 USD/주", "70.00 USD/주"):
            self.assertNotIn(value, rendered)
        self.assertIn("진입 가격·금액·수량 대기", rendered)
        self.assertNotIn("ev:quote", rendered)

    def test_missing_binding_or_zero_budget_keeps_action_values_waiting(self):
        for policy, evidence, calculations in (
            (complete_policy(), (), ("calc:policy",)),
            (complete_policy(), ("ev:quote",), ()),
            (complete_policy(cash=Money(D("10000"), "USD", verified=True)), ("ev:quote",), ("calc:policy",)),
        ):
            with self.subTest(policy=policy.status, evidence=evidence, calculations=calculations):
                section = build_policy_b_section("ABC", CUTOFF, policy,
                                                 evidence_ids=evidence, calculation_ids=calculations)
                rendered = "\n".join(section.lines)
                self.assertEqual(Availability.PARTIAL, section.status)
                self.assertNotIn("80.00 USD/주", rendered)
                self.assertNotIn("추가 예산 상한", rendered)

    def test_caller_attested_sizing_cannot_release_lot_quantities(self):
        policy = complete_policy()
        sizing = size_policy_b_tranches(
            policy, TradingRules("USD", D("1"), D("0.01"), D("1"), "synthetic", True),
        )
        section = build_policy_b_section(
            "ABC", CUTOFF, policy, sizing=sizing,
            evidence_ids=("ev:quote", "ev:valuation", "ev:state", "ev:trade-rules"),
            calculation_ids=("calc:policy", "calc:sizing"),
        )
        rendered = "\n".join(section.lines)
        self.assertEqual("ARITHMETIC_ONLY", sizing.status)
        self.assertEqual(Availability.PARTIAL, section.status)
        self.assertNotIn("1차 16주", rendered)
        self.assertNotIn("3차 18주", rendered)
        self.assertIn("진입 가격·금액·수량 대기", rendered)


if __name__ == "__main__":
    unittest.main()
