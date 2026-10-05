import unittest
from decimal import Decimal as D
from investment_stack.calculations.investment_decision import FiveYearScenario, expected_five_year_cagr, equity_buy_grade


class InvestmentDecisionTests(unittest.TestCase):
    def test_explicit_three_scenarios_and_identity_growth_return(self):
        fields = ('current_earnings_per_share', 'normalized_earnings_growth', 'terminal_multiple', 'total_dividends_per_share')
        scenarios = tuple(FiveYearScenario(n, D('10'), D('.1'), D('10'), D('0'), {f: n + ':' + f for f in fields}) for n in ('bear', 'base', 'bull'))
        result = expected_five_year_cagr(D('100'), scenarios, price_verified=True, price_evidence_id='quote')
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertAlmostEqual(D(result['scenarios']['base']['cagr']), D('.1'), places=28)
        self.assertEqual(expected_five_year_cagr(D('100'), scenarios, price_verified=False, price_evidence_id='quote')['status'], 'UNAVAILABLE')

    def test_missing_assumption_evidence_does_not_generate_return(self):
        scenarios = tuple(FiveYearScenario(n, D('10'), D('.1'), D('10'), D('0'), {}) for n in ('bear', 'base', 'bull'))
        self.assertEqual(expected_five_year_cagr(D('100'), scenarios, price_verified=True, price_evidence_id='quote')['status'], 'UNAVAILABLE')

    def test_grade_requires_all_gates_and_has_explicit_boundaries(self):
        gates = dict(price_verified=True, fundamental_quality_passed=True, valuation_passed=True, evidence_ids=('quote', 'quality', 'valuation'))
        for fair, grade in [('125', '강력매수'), ('110', '분할매수'), ('90', '적정가'), ('89', '비쌈')]:
            self.assertEqual(equity_buy_grade(D('100'), D(fair), **gates)['grade'], grade)
        gates['fundamental_quality_passed'] = False
        self.assertIsNone(equity_buy_grade(D('100'), D('150'), **gates)['grade'])
