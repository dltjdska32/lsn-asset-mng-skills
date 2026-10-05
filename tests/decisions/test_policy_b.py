from decimal import Decimal as D
import unittest

from investment_stack.decisions.policy_b import (
    EntryPricePrerequisites,
    Money,
    PolicyBInput,
    evaluate_policy_b,
)


def m(value, currency="USD", verified=True):
    return Money(D(str(value)), currency, verified)


def full(**changes):
    values = dict(
        evaluation_currency="USD",
        fair_value_per_share=m("100"),
        optimistic_fair_value_per_share=m("120"),
        quote_per_share=m("90"),
        portfolio_value=m("100000"),
        cash=m("20000"),
        holding_value=m("4000"),
        holding_units=D("40"),
        holding_units_verified=True,
        thesis_impaired=False,
        approved_risk_budget=m("4000"),
        entry_price_prerequisites=EntryPricePrerequisites(
            valuation_provenance_verified=True,
            pinned_personal_state_verified=True,
            reserves_excluded=True,
            transaction_costs_verified=True,
            trade_units_verified=True,
        ),
    )
    values.update(changes)
    return PolicyBInput(**values)


class PolicyBTests(unittest.TestCase):
    def test_entry_reference_levels_and_equal_budget(self):
        result = evaluate_policy_b(full())
        self.assertEqual([x.price for x in result.entry_tiers], [D("80"), D("75"), D("70")])
        self.assertEqual(result.max_total_add_budget, D("4000"))
        self.assertEqual(sum((x.tranche_budget for x in result.entry_tiers), D(0)), result.max_total_add_budget)
        self.assertLess(abs(result.entry_tiers[0].tranche_budget - result.entry_tiers[2].tranche_budget), D("1e-20"))
        self.assertEqual(result.status, "CONDITIONAL")
        self.assertFalse(result.orders_posted)

    def test_cash_floor_is_ten_percent_of_portfolio_and_excess_cash_only(self):
        low_cash = evaluate_policy_b(full(cash=m("9000")))
        self.assertEqual(low_cash.cash_floor, D("10000"))
        self.assertEqual(low_cash.max_total_add_budget, D("0"))
        self.assertTrue(low_cash.additions_stopped)
        self.assertTrue(any("at or below" in reason for reason in low_cash.stop_reasons))
        at_floor = evaluate_policy_b(full(cash=m("10000")))
        self.assertEqual(at_floor.max_total_add_budget, D("0"))
        self.assertTrue(at_floor.additions_stopped)
        cash_limited = evaluate_policy_b(full(cash=m("11000")))
        self.assertEqual(cash_limited.max_total_add_budget, D("1000"))

    def test_verified_host_risk_budget_can_tighten_policy_cap(self):
        result = evaluate_policy_b(full(approved_risk_budget=m("1000")))
        self.assertEqual(result.max_total_add_budget, D("1000"))

    def test_zero_verified_host_risk_budget_explicitly_stops_additions(self):
        result = evaluate_policy_b(full(approved_risk_budget=m("0")))
        self.assertEqual(result.max_total_add_budget, D("0"))
        self.assertTrue(result.additions_stopped)
        self.assertTrue(any("risk budget is zero" in reason for reason in result.stop_reasons))

    def test_concentration_does_not_cap_an_approved_allocation(self):
        for holding in ('7500', '8000', '10001', '31000'):
            result = evaluate_policy_b(full(holding_value=m(holding)))
            self.assertIsNone(result.concentration_headroom)
            self.assertEqual(result.max_total_add_budget, D('4000'))
            self.assertFalse(result.additions_stopped)
            self.assertFalse(any('concentration' in x for x in result.reduction_triggers))
            self.assertEqual(sum((t.tranche_budget for t in result.entry_tiers), D(0)), D('4000'))

    def test_no_allocation_budget_is_invented_after_removing_position_cap(self):
        result = evaluate_policy_b(full(approved_risk_budget=None))
        self.assertIsNone(result.max_total_add_budget)
        self.assertEqual(result.status, 'WAIT')
        self.assertTrue(result.additions_stopped)

    def test_overvaluation_threshold_is_inclusive_and_candidate_is_one_third(self):
        at_threshold = evaluate_policy_b(full(quote_per_share=m("144")))
        self.assertEqual(at_threshold.candidate_reduction_fraction, D(1) / D(3))
        self.assertIsNone(at_threshold.candidate_reduction_units)
        self.assertIsNone(at_threshold.candidate_reduction_value)
        below = evaluate_policy_b(full(quote_per_share=m("143.99")))
        self.assertIsNone(below.candidate_reduction_fraction)

    def test_unverified_quote_or_optimistic_value_suppresses_trigger_and_candidate(self):
        for changed in (
            {"quote_per_share": m("150", verified=False)},
            {"optimistic_fair_value_per_share": m("100", verified=False)},
        ):
            with self.subTest(changed=changed):
                result = evaluate_policy_b(full(**changed))
                self.assertIsNone(result.candidate_reduction_fraction)
                self.assertFalse(any("1.2x" in x for x in result.reduction_triggers))

    def test_unverified_portfolio_or_holding_suppresses_concentration_trigger(self):
        for changed in (
            {"portfolio_value": m("100000", verified=False)},
            {"holding_value": m("12000", verified=False)},
        ):
            with self.subTest(changed=changed):
                result = evaluate_policy_b(full(**changed))
                self.assertFalse(any("strictly above 10%" in x for x in result.reduction_triggers))

    def test_holding_above_portfolio_is_inconsistent_and_suppresses_reduction_output(self):
        result = evaluate_policy_b(full(holding_value=m("110000"), quote_per_share=m("200")))
        self.assertEqual(result.status, "WAIT")
        self.assertFalse(result.reduction_triggers)
        self.assertIsNone(result.candidate_reduction_fraction)

    def test_cash_above_portfolio_is_inconsistent_and_suppresses_reduction_output(self):
        result = evaluate_policy_b(full(cash=m("110000"), quote_per_share=m("200"), holding_value=m("12000")))
        self.assertEqual(result.status, "WAIT")
        self.assertFalse(result.reduction_triggers)
        self.assertIsNone(result.candidate_reduction_fraction)

    def test_cash_plus_holding_above_portfolio_is_inconsistent(self):
        result = evaluate_policy_b(full(cash=m("25000"), holding_value=m("80000"), quote_per_share=m("200")))
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.max_total_add_budget)
        self.assertFalse(result.reduction_triggers)
        self.assertIsNone(result.candidate_reduction_fraction)

    def test_overvaluation_requires_verified_positive_holding(self):
        for changed in (
            {"holding_value": m("0"), "holding_units": D("0")},
            {"holding_value": None},
            {"holding_units": None},
            {"holding_units_verified": False},
        ):
            with self.subTest(changed=changed):
                result = evaluate_policy_b(full(quote_per_share=m("144"), **changed))
                self.assertIsNone(result.candidate_reduction_fraction)
                self.assertFalse(any("1.2x" in x for x in result.reduction_triggers))

    def test_monetary_inputs_must_be_decimal_without_coercion(self):
        for value in (100.0, "100"):
            with self.subTest(value=value):
                bad_money = Money(value, "USD")
                result = evaluate_policy_b(PolicyBInput(evaluation_currency="USD", fair_value_per_share=bad_money))
                self.assertEqual(result.status, "WAIT")
                self.assertEqual(result.entry_tiers, ())

    def test_money_defaults_to_unverified(self):
        result = evaluate_policy_b(full(fair_value_per_share=Money(D("100"), "USD")))
        self.assertFalse(Money(D("100"), "USD").verified)
        self.assertEqual(result.entry_tiers, ())
        self.assertEqual(result.status, "WAIT")

    def test_thesis_impairment_stops_additions_and_prompts_review(self):
        result = evaluate_policy_b(full(thesis_impaired=True))
        self.assertTrue(result.additions_stopped)
        self.assertIsNone(result.max_total_add_budget)
        self.assertEqual(result.status, "WAIT")
        self.assertTrue(any("thesis impaired" in x for x in result.reduction_triggers))

    def test_missing_thesis_state_blocks_budget(self):
        result = evaluate_policy_b(full(thesis_impaired=None))
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.max_total_add_budget)

    def test_partial_state_keeps_reference_levels_but_no_budget(self):
        result = evaluate_policy_b(PolicyBInput(evaluation_currency="USD", fair_value_per_share=m("100")))
        self.assertEqual(result.entry_tiers, ())
        self.assertEqual(result.status, "WAIT")
        self.assertIsNone(result.max_total_add_budget)

    def test_each_entry_readiness_gate_suppresses_numeric_prices(self):
        gates = (
            "valuation_provenance_verified",
            "pinned_personal_state_verified",
            "reserves_excluded",
            "transaction_costs_verified",
            "trade_units_verified",
        )
        for missing_gate in gates:
            flags = {name: True for name in gates}
            flags[missing_gate] = False
            with self.subTest(missing_gate=missing_gate):
                result = evaluate_policy_b(full(entry_price_prerequisites=EntryPricePrerequisites(**flags)))
                self.assertEqual(result.entry_tiers, ())
                self.assertEqual(result.status, "WAIT")

    def test_raw_truthy_string_is_not_an_entry_prerequisite_bundle(self):
        result = evaluate_policy_b(full(entry_price_prerequisites="all-verified"))
        self.assertEqual(result.entry_tiers, ())
        self.assertEqual(result.status, "WAIT")

    def test_invalid_base_values_never_default_to_zero(self):
        for bad in (None, D("NaN"), D("Infinity"), D("-1")):
            with self.subTest(bad=bad):
                value = None if bad is None else Money(bad, "USD")
                result = evaluate_policy_b(PolicyBInput(evaluation_currency="USD", fair_value_per_share=value))
                self.assertEqual(result.status, "WAIT")
                self.assertEqual(result.entry_tiers, ())

    def test_currency_mismatch_and_unverified_input_block_budget(self):
        self.assertIsNone(evaluate_policy_b(full(cash=m("20000", "EUR"))).max_total_add_budget)
        self.assertIsNone(evaluate_policy_b(full(portfolio_value=m("100000", verified=False))).max_total_add_budget)

    def test_approval_ref_is_not_an_authorization_or_posting_path(self):
        result = evaluate_policy_b(full())
        self.assertFalse(result.orders_posted)


if __name__ == "__main__":
    unittest.main()
