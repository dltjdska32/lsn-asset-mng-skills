"""Tests for conditional action proposal logic."""

import unittest
from decimal import Decimal
from investment_stack.contracts.calculation import InvestmentDecision
from investment_stack.decisions.action import calculate_action_proposal


class TestActionProposalLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.state_version = "v1"
        self.policy_buy = {
            "approval_ref": "AUTH-123",
            "policy_version": "1.0",
            "quote_currency": "USD",
            "budget_currency": "USD",
            "13f_gate": "ENABLED",
            "chart_gate": "ENABLED",
        }
        self.personal_state = {
            "state_version": "v1",
            "available_cash_after_buffer": Decimal("6000"),
            "concentration_headroom": Decimal("10000"),
            "disposable_quantity": Decimal("150"),
        }
        self.price = Decimal("100")
        self.value = Decimal("150")

    def test_missing_policy_or_state(self):
        prop = calculate_action_proposal(
            intended_decision=InvestmentDecision.BUY,
            state_version=self.state_version,
            policy=None,
            price=self.price,
            value=self.value,
            personal_state=self.personal_state
        )
        self.assertEqual(prop.decision, InvestmentDecision.WAIT)
        self.assertIn("Missing policy.", prop.unavailable_reasons)
        
        prop = calculate_action_proposal(
            intended_decision=InvestmentDecision.BUY,
            state_version=self.state_version,
            policy=self.policy_buy,
            price=self.price,
            value=self.value,
            personal_state=None
        )
        self.assertEqual(prop.decision, InvestmentDecision.WAIT)
        self.assertIn("Missing personal pinned state.", prop.unavailable_reasons)

    def test_no_data_leakage_in_conditions(self):
        prop = calculate_action_proposal(
            intended_decision=InvestmentDecision.BUY,
            state_version=self.state_version,
            policy=self.policy_buy,
            price=self.price,
            value=self.value,
            personal_state=self.personal_state
        )
        self.assertEqual(prop.decision, InvestmentDecision.WAIT)
        self.assertEqual(len(prop.tranches), 0)
        self.assertFalse(any(char.isdigit() for c in prop.conditions for char in c))
        self.assertFalse(any(char.isdigit() for c in prop.unavailable_reasons for char in c))

    def test_unvalidated_signals(self):
        self.policy_buy["13f_gate"] = "DISABLED"
        prop = calculate_action_proposal(
            intended_decision=InvestmentDecision.BUY,
            state_version=self.state_version,
            policy=self.policy_buy,
            price=self.price,
            value=self.value,
            personal_state=self.personal_state
        )
        self.assertEqual(prop.decision, InvestmentDecision.WAIT)
        self.assertTrue(any("Required gates are not explicitly ENABLED" in r for r in prop.unavailable_reasons))

    def test_pure_arithmetic_valid(self):
        from investment_stack.decisions.action import calculate_budget_arithmetic
        
        res = calculate_budget_arithmetic(
            budget_limit=Decimal("5000"),
            price=Decimal("100"),
            lot_size=Decimal("10"),
            fees_per_unit=Decimal("0.05"),
            quote_currency="USD",
            budget_currency="USD"
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.quantity, Decimal("40"))
        self.assertEqual(res.total_cost, Decimal("4002")) # 40 * 100.05
        
        # Cross currency test
        res = calculate_budget_arithmetic(
            budget_limit=Decimal("5000000"),
            price=Decimal("100"),
            lot_size=Decimal("10"),
            fees_per_unit=Decimal("0"),
            quote_currency="USD",
            budget_currency="KRW",
            fx_rate=Decimal("1000")
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(res.quantity, Decimal("50")) # 5000000 / (100 * 1000) = 50
        self.assertEqual(res.total_cost, Decimal("5000000"))

    def test_pure_arithmetic_invalid_domain(self):
        from investment_stack.decisions.action import calculate_budget_arithmetic
        
        # Negative budget
        res = calculate_budget_arithmetic(Decimal("-100"), Decimal("100"), Decimal("10"), Decimal("0"), "USD", "USD")
        self.assertFalse(res.is_valid)
        
        # Zero lot
        res = calculate_budget_arithmetic(Decimal("5000"), Decimal("100"), Decimal("0"), Decimal("0"), "USD", "USD")
        self.assertFalse(res.is_valid)
        
        # Negative price
        res = calculate_budget_arithmetic(Decimal("5000"), Decimal("-10"), Decimal("10"), Decimal("0"), "USD", "USD")
        self.assertFalse(res.is_valid)
        
        # String instead of decimal
        res = calculate_budget_arithmetic("5000", Decimal("100"), Decimal("10"), Decimal("0"), "USD", "USD")
        self.assertFalse(res.is_valid)
        
        # NaN
        res = calculate_budget_arithmetic(Decimal("5000"), Decimal("NaN"), Decimal("10"), Decimal("0"), "USD", "USD")
        self.assertFalse(res.is_valid)

        # Cross currency without FX
        res = calculate_budget_arithmetic(Decimal("5000"), Decimal("100"), Decimal("10"), Decimal("0"), "USD", "KRW", None)
        self.assertFalse(res.is_valid)
        
        # Cross currency with negative FX
        res = calculate_budget_arithmetic(Decimal("5000"), Decimal("100"), Decimal("10"), Decimal("0"), "USD", "KRW", Decimal("-1"))
        self.assertFalse(res.is_valid)
