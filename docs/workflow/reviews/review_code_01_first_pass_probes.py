"""Independent regression expectations; baseline 57aca43 fails these five tests.

Run from the repository: python docs/workflow/reviews/review_code_01_first_pass_probes.py -v
Uses synthetic state only; no production source edits, credentials, or real personal DB.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
import json
import unittest

from tests.unit.test_r14_portfolio_modes import PortfolioModesTests
from tests.integration.test_r14_equity_mode_bundles import R14EquityModeBundleIntegrationTests
from investment_stack.reporting.portfolio_modes import FxEvidence, analyze_portfolio
from investment_stack.execution.models import Availability, ModeRequest, StepResult
from investment_stack.execution.dispatcher import RuntimeServices, execute_mode
from investment_stack.routing import RequestMode
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.providers.market_quotes import MarketQuoteProvider, calendar_aware_freshness_evaluator
from investment_stack.freshness import get_pinned_calendar
from investment_stack.contracts.institutional import Holding13F, HoldingSet13F
from investment_stack.institutional.compare import compare_portfolios
from investment_stack.institutional.scoring import compute_institutional_features


class IndependentFirstPass(unittest.TestCase):
    def test_rc01_fx_equivalent_portfolio_has_same_risk(self):
        request = PortfolioModesTests().complete_request()
        baseline = analyze_portfolio(request)
        fx = FxEvidence("JPY", "USD", D(".01"), "synthetic-fx",
                        "2026-09-27T10:00:00+00:00", "2026-09-27T10:00:00+00:00",
                        "ELIGIBLE", "FRESH", True)
        equivalent = replace(request, positions=(
            replace(request.positions[0], market_value=D("80000"), currency="JPY"),
            request.positions[1]), fx_evidence=(fx,))
        actual = analyze_portfolio(equivalent)
        self.assertEqual(baseline.gross_assets, actual.gross_assets)
        self.assertEqual(baseline.risk.volatility, actual.risk.volatility)

    def test_rc02_explicit_yahoo_delay_requires_approved_policy(self):
        cutoff = datetime.fromisoformat("2026-09-28T10:01:00-04:00")
        payload = {"chart": {"result": [{"meta": {
            "currency": "USD", "symbol": "AAPL", "exchangeName": "NMS",
            "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 100,
            "regularMarketTime": int(datetime.fromisoformat("2026-09-28T09:46:00-04:00").timestamp()),
            "exchangeDataDelayedBy": 15,
        }}], "error": None}}
        provider = MarketQuoteProvider(source_bundles={
            "NASDAQ:AAPL": {"source_id": "yahoo_finance", "payload": payload}}, clock=lambda: cutoff)
        result = provider.fetch_current("NASDAQ:AAPL", analysis_as_of=cutoff,
            eligibility_evaluator=calendar_aware_freshness_evaluator(get_pinned_calendar("NASDAQ")))
        self.assertNotEqual("AVAILABLE", result.status.value)

    def test_rc03_posted_receipt_survives_projection_and_log_failure(self):
        class Logger:
            run_id = "review-receipt"
            def record_task_state(self, *, task_name, **kwargs):
                if task_name.endswith(PipelineStep.PROJECT_PERSONAL_STATE.value):
                    raise OSError("synthetic log failure")
        def projection_failure(*_):
            raise ValueError("synthetic projection failure")
        handlers = {step: lambda *_: StepResult(Availability.COMPLETE, output={"ok": True})
                    for step in FixedPipelinePlanner().plan(RequestMode.ASSET_UPDATE).steps}
        handlers[PipelineStep.DECIDE_POSTING] = lambda *_: StepResult(Availability.COMPLETE,
            mutation_receipt={"status": "POSTED", "transaction_ids": ["synthetic-committed"], "state_version": 7})
        handlers[PipelineStep.PROJECT_PERSONAL_STATE] = projection_failure
        try:
            result = execute_mode(ModeRequest("review-receipt", RequestMode.ASSET_UPDATE),
                                  RuntimeServices(handlers, run_db=Logger()))
        except Exception as exc:
            self.fail(f"Already-posted receipt lost when {type(exc).__name__} escapes")
        self.assertEqual(Availability.FAILED, result.availability)
        self.assertEqual("POSTED", result.mutation_receipt["status"])

    def test_rc04_annual_usgaap_and_quarter_ifrs_are_not_comparable(self):
        class DifferentBasisFixture(R14EquityModeBundleIntegrationTests):
            def bundle(self, specs, **kwargs):
                data = super().bundle(specs, **kwargs)
                for index, response in enumerate(data["responses"]):
                    if index % 2 == 1:
                        for hit in response["hits"]:
                            hit["metadata"].update({
                                "start": "2025-07-01" if index == 1 else "2026-04-01",
                                "reporting_frequency": "ANNUAL" if index == 1 else "QUARTER",
                                "accounting_standard": "US-GAAP" if index == 1 else "IFRS",
                                "consolidation": "CONSOLIDATED", "adjustment_basis": "REPORTED"})
                return data
        fixture = DifferentBasisFixture()
        try:
            specs = fixture.specs()
            run, services = fixture.make_services("review-basis", specs, mode=RequestMode.ASSET_COMPARISON)
            execute_mode(ModeRequest("review-basis", RequestMode.ASSET_COMPARISON,
                                    {"research_specs": specs}), services)
            row = next(row for row in run.fetch_phase6_context()["calculations"]
                       if row["calculation_name"] == "asset_comparison")
            matrix = json.loads(row["inputs_json"])["compatibility_matrix"]
            self.assertFalse(matrix["complete"], json.loads(row["result_json"]))
        finally:
            fixture.doCleanups()

    def test_rc05_future_13f_period_cannot_be_point_in_time(self):
        def holdings(fid, period, quantity):
            holding = Holding13F("h-" + fid, fid, "037833100", "SYNTHETIC",
                D(quantity), D("1000"), D("1000"), D(quantity), security_class="COM", value_scale=D(1))
            return HoldingSet13F.create(fid, "0000000001", period, (holding,))
        prior = holdings("prior", "2026-06-30", "100")
        future = holdings("future", "2026-09-30", "200")
        comparison = compare_portfolios(prior, future)
        feature = compute_institutional_features("037833100", "0000000001", (comparison,),
            datetime.fromisoformat("2026-09-27T12:00:00+00:00"))
        self.assertTrue(not feature.is_point_in_time or feature.quarterly_share_change_pct is None,
                        f"Future period {feature.holding_period} marked PIT: {feature}")


if __name__ == "__main__":
    unittest.main(defaultTest="IndependentFirstPass")
