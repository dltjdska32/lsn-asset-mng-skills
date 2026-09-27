from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from investment_stack.reporting.portfolio_modes import (
    FxEvidence,
    HistoricalPriceSeries,
    LimitStatus,
    MoneyBalance,
    PinnedPortfolioState,
    PortfolioAnalysisRequest,
    PortfolioPosition,
    PortfolioRiskPolicy,
    PortfolioScenario,
    RiskObservation,
    RiskPeriodPolicy,
    ScenarioAdjustment,
    ScenarioApproval,
    ScenarioFxAssumption,
    ScenarioRiskShock,
    ScenarioStatus,
    ScenarioTargetKind,
    analyze_portfolio,
    simulate_portfolio_scenario,
)

D = Decimal


class PortfolioModesTests(unittest.TestCase):
    as_of = "2026-09-27T12:00:00+00:00"
    state = PinnedPortfolioState(7, "snapshot:synthetic-7", as_of, "2026-09-27T08:00:00+00:00")

    def risk_series(self, instrument_id, prices):
        days = ("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24")
        return HistoricalPriceSeries(
            instrument_id, "DAILY", tuple(
                RiskObservation(day, D(str(price)), "USD", f"{instrument_id}-{day}",
                                "2026-09-24T22:00:00+00:00", "ELIGIBLE", "FRESH", True)
                for day, price in zip(days, prices)
            ),
        )

    def complete_request(self):
        return PortfolioAnalysisRequest(
            pinned_state=self.state,
            evaluation_currency="USD",
            positions=(
                PortfolioPosition("EQ-A", D("800"), "USD", "EQUITY", account="A", leverage=D("1")),
                PortfolioPosition("EQ-B", D("200"), "USD", "EQUITY", account="A"),
            ),
            cash=(MoneyBalance("cash-main", D("100"), "USD"),),
            liabilities=(MoneyBalance("loan", D("50"), "USD"),),
            price_series=(self.risk_series("EQ-A", (100, 110, 105, 120, 118)),
                          self.risk_series("EQ-B", (100, 102, 101, 104, 106))),
            period_policy=RiskPeriodPolicy("period-policy-1", "DAILY", "2026-09-20", "2026-09-24", 5),
            risk_policy=PortfolioRiskPolicy("risk-policy-1", True, "approval-risk-1", D("0.5"), D("0.4"), "validation-risk-1"),
        )

    def test_complete_portfolio_analysis_respects_pin_and_reports_cash_debt(self):
        request = self.complete_request()
        result = analyze_portfolio(request)
        self.assertEqual(result.availability.value, "AVAILABLE")
        self.assertEqual(result.state_version, 7)
        self.assertEqual(result.snapshot_ref, "snapshot:synthetic-7")
        self.assertEqual(result.gross_assets, D("1100"))
        self.assertEqual(result.total_liabilities, D("50"))
        self.assertEqual(result.net_worth, D("1050"))
        self.assertEqual(result.allocation.by_asset_class["EQUITY"], D("1000") / D("1100"))
        self.assertEqual(result.risk_limits[0].status, LimitStatus.WITHIN)
        self.assertIn("현금: 100", result.section.lines[3])
        self.assertIn("부채: 50", result.section.lines[4])

    def test_unvalued_positions_and_missing_fx_remain_unknown(self):
        request = self.complete_request()
        request = replace(request, positions=request.positions + (
            PortfolioPosition("GOLD", None, "JPY", "GOLD", unvalued_reason="no current quote"),
        ))
        result = analyze_portfolio(request)
        self.assertEqual(result.availability.value, "PARTIAL")
        self.assertIsNone(result.gross_assets)
        self.assertIsNone(result.net_worth)
        self.assertIn("GOLD", result.unvalued_items)
        self.assertIn("GOLD", result.allocation.unvalued_positions)
        self.assertIsNone(result.risk)

    def test_fx_requires_selected_eligible_fresh_point_in_time_evidence(self):
        request = PortfolioAnalysisRequest(
            self.state, "USD", (PortfolioPosition("JP", D("10000"), "JPY", "EQUITY"),), (), (),
            fx_evidence=(
                FxEvidence("JPY", "USD", D("0.01"), "fx-unselected", "2026-09-26T10:00:00+00:00", self.as_of, "ELIGIBLE", "FRESH", False),
                FxEvidence("JPY", "USD", D("0.02"), "fx-ineligible", "2026-09-26T10:00:00+00:00", self.as_of, "INELIGIBLE", "FRESH", True),
                FxEvidence("JPY", "USD", D("0.03"), "fx-future", "2026-09-28T10:00:00+00:00", "2026-09-28T11:00:00+00:00", "ELIGIBLE", "FRESH", True),
            ),
        )
        result = analyze_portfolio(request)
        self.assertIsNone(result.gross_assets)
        self.assertEqual(result.unvalued_items, ("JP",))

    def test_scenario_missing_gate_or_incomplete_baseline_never_reports_delta(self):
        request = self.complete_request()
        no_gate = PortfolioScenario("s-1", "stress", None, (
            ScenarioAdjustment(ScenarioTargetKind.POSITION, "EQ-A", D("100"), "USD", "assumption:a"),
        ))
        blocked = simulate_portfolio_scenario(request, no_gate)
        self.assertEqual(blocked.status, ScenarioStatus.WAIT)
        self.assertIsNone(blocked.before)
        self.assertIsNone(blocked.net_worth_delta)
        approval_shaped = replace(no_gate, approval=ScenarioApproval("scenario-gate", "policy:s", "approval:s", "validation:s", True))
        without_registry = simulate_portfolio_scenario(request, approval_shaped)
        self.assertEqual(without_registry.status, ScenarioStatus.WAIT)
        self.assertIsNone(without_registry.before)

        incomplete = replace(request, positions=request.positions + (
            PortfolioPosition("UNVALUED", None, "USD", "OTHER"),
        ))
        approved = ScenarioApproval("scenario-gate", "policy:s", "approval:s", "validation:s", True)
        scenario = PortfolioScenario("s-2", "stress", approved, (
            ScenarioAdjustment(ScenarioTargetKind.POSITION, "EQ-A", D("10"), "USD", "assumption:b"),
        ))
        waiting = simulate_portfolio_scenario(incomplete, scenario, gate_verifier=lambda gate: gate.enabled)
        self.assertEqual(waiting.status, ScenarioStatus.WAIT)
        self.assertIsNotNone(waiting.before)
        self.assertIsNone(waiting.after)
        self.assertIsNone(waiting.net_worth_delta)

    def test_in_memory_scenario_reports_explicit_before_after_without_mutation(self):
        request = self.complete_request()
        original_positions = request.positions
        original_prices = request.price_series
        approval = ScenarioApproval("scenario-gate", "policy:s", "approval:s", "validation:s", True)
        scenario = PortfolioScenario(
            "stress-1", "equity selloff and cash withdrawal", approval,
            (
                ScenarioAdjustment(ScenarioTargetKind.POSITION, "EQ-A", D("200"), "USD", "assume:value-change"),
                ScenarioAdjustment(ScenarioTargetKind.CASH, "cash-main", D("-100"), "USD", "assume:cash-out"),
                ScenarioAdjustment(ScenarioTargetKind.LIABILITY, "loan", D("20"), "USD", "assume:debt"),
            ),
            risk_shocks=(ScenarioRiskShock("EQ-A", D("-0.20"), "assume:shock"),),
        )
        result = simulate_portfolio_scenario(request, scenario, gate_verifier=lambda gate: gate.enabled and gate.validation_ref == "validation:s")
        self.assertEqual(result.status, ScenarioStatus.COMPLETED)
        self.assertEqual(result.before.net_worth, D("1050"))
        self.assertEqual(result.after.gross_assets, D("1200"))
        self.assertEqual(result.after.total_liabilities, D("70"))
        self.assertEqual(result.net_worth_delta, D("80"))
        self.assertIsNotNone(result.risk_volatility_delta)
        self.assertNotEqual(result.risk_volatility_delta, D("0"))
        self.assertIn("assume:shock", result.section.lines[-1])
        self.assertFalse(result.section.metadata["posting_enabled"])
        self.assertIn("예측이나 최신 시세가 아닙니다", " ".join(result.section.lines))
        self.assertEqual(request.positions, original_positions)
        self.assertEqual(request.price_series, original_prices)

    def test_scenario_fx_assumption_cannot_fill_missing_baseline(self):
        request = PortfolioAnalysisRequest(
            self.state, "USD", (PortfolioPosition("JP", D("10000"), "JPY", "EQUITY"),),
            (MoneyBalance("cash", D("100"), "USD"),), (),
        )
        self.assertIsNone(analyze_portfolio(request).gross_assets)
        scenario = PortfolioScenario(
            "fx-case", "explicit exchange assumption",
            ScenarioApproval("gate", "policy", "approval", "validation", True),
            (ScenarioAdjustment(ScenarioTargetKind.POSITION, "JP", D("5000"), "JPY", "assumption:value"),),
            fx_assumptions=(ScenarioFxAssumption("JPY", "USD", D("0.01"), "assumption:fx"),),
        )
        result = simulate_portfolio_scenario(request, scenario, gate_verifier=lambda gate: gate.enabled)
        self.assertEqual(result.status, ScenarioStatus.WAIT)
        self.assertIsNone(result.before.gross_assets)
        self.assertIsNone(result.after)
        self.assertIsNone(result.gross_assets_delta)
        self.assertIsNone(analyze_portfolio(request).gross_assets)

    def test_scenario_fx_delta_compares_real_baseline_with_hypothetical_fx(self):
        baseline_fx = FxEvidence(
            "JPY", "USD", D("0.02"), "fx-baseline", "2026-09-26T10:00:00+00:00",
            "2026-09-26T10:01:00+00:00", "ELIGIBLE", "FRESH", True,
        )
        request = PortfolioAnalysisRequest(
            self.state, "USD", (PortfolioPosition("JP", D("10000"), "JPY", "EQUITY"),),
            (MoneyBalance("cash", D("100"), "USD"),), (), fx_evidence=(baseline_fx,),
        )
        scenario = PortfolioScenario(
            "fx-shock", "hypothetical weaker JPY", ScenarioApproval("gate", "policy", "approval", "validation", True),
            (), fx_assumptions=(ScenarioFxAssumption("JPY", "USD", D("0.01"), "assumption:fx-shock"),),
        )
        result = simulate_portfolio_scenario(request, scenario, gate_verifier=lambda gate: gate.enabled)
        self.assertEqual(result.status, ScenarioStatus.PARTIAL)
        self.assertEqual(result.before.gross_assets, D("300"))
        self.assertEqual(result.after.gross_assets, D("200"))
        self.assertEqual(result.gross_assets_delta, D("-100"))

    def test_unapproved_or_missing_risk_policy_does_not_create_risk_limits(self):
        request = replace(self.complete_request(), risk_policy=PortfolioRiskPolicy("risk", False, None, D("0.1"), D("0.2")))
        result = analyze_portfolio(request)
        self.assertIsNone(result.risk)
        self.assertTrue(all(limit.status is LimitStatus.UNKNOWN for limit in result.risk_limits))


if __name__ == "__main__":
    unittest.main()
