from decimal import Decimal as D
import unittest

from investment_stack.decisions.policy_b import (
    EntryPricePrerequisites, Money, PolicyBInput, evaluate_policy_b,
)
from investment_stack.decisions.policy_b_sizing import TradingRules, size_policy_b_tranches


def complete_policy(**changes):
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
    values.update(changes)
    return evaluate_policy_b(PolicyBInput(**values))


class PolicyBSizingTests(unittest.TestCase):
    def test_three_tranches_are_lot_rounded_and_stay_within_budget(self):
        policy = complete_policy()
        result = size_policy_b_tranches(policy, TradingRules("USD", D("1"), D("0.01"), D("1"), "synthetic", True))
        self.assertEqual("ARITHMETIC_ONLY", result.status)
        self.assertEqual([D("80.00"), D("75.00"), D("70.00")], [tier.limit_price for tier in result.tiers])
        self.assertEqual([D("16"), D("17"), D("18")], [tier.quantity for tier in result.tiers])
        self.assertLessEqual(result.total_maximum_cost, policy.max_total_add_budget)
        self.assertFalse(result.orders_posted)
        self.assertIn("release receipt is unavailable", result.unavailable_reasons[0])

    def test_unverified_rules_cross_currency_or_insufficient_lot_wait(self):
        policy = complete_policy()
        for rules in (
            TradingRules("USD", D("1"), D("0.01"), D("1"), "synthetic"),
            TradingRules("KRW", D("1"), D("0.01"), D("1"), "synthetic", True),
            TradingRules("USD", D("100"), D("0.01"), D("1"), "synthetic", True),
        ):
            with self.subTest(rules=rules):
                result = size_policy_b_tranches(policy, rules)
                self.assertEqual("WAIT", result.status)
                self.assertEqual((), result.tiers)
                self.assertIsNone(result.total_maximum_cost)

    def test_policy_wait_or_zero_budget_never_exposes_quantity(self):
        rules = TradingRules("USD", D("1"), D("0.01"), D("1"), "synthetic", True)
        partial = evaluate_policy_b(PolicyBInput(evaluation_currency="USD"))
        no_cash = complete_policy(cash=Money(D("10000"), "USD", verified=True))
        for policy in (partial, no_cash):
            with self.subTest(status=policy.status):
                result = size_policy_b_tranches(policy, rules)
                self.assertEqual("WAIT", result.status)
                self.assertEqual((), result.tiers)


if __name__ == "__main__":
    unittest.main()
