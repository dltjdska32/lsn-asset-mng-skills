from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType, EquityFundamentalInput, EquityValuationInput
from investment_stack.evidence import RunDatabaseManager
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.reporting.runtime import section_from_analysis_result


D = Decimal


class Phase8DeterminismTests(unittest.TestCase):
    def make_runtime(self, run_id: str):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        manager = RunDatabaseManager(Path(temp.name) / "workspace", run_id)
        self.assertTrue(manager.create().valid)
        manager.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of="2026-08-14T10:00:00+00:00",
            analysis_timezone="UTC",
            state_version=7,
            personal_db_instance_id="personal-7",
        )
        runtime = Phase5AssetAnalysisRuntime(
            manager,
            materiality=MaterialityEngine(MaterialityConfig("phase8", D("0.05"), D("0.20"), D("0.80"))),
        )
        return manager, runtime

    def test_same_inputs_produce_same_semantic_calculation_results(self) -> None:
        inputs = EquityFundamentalInput(
            "EQ", "USD", revenue=D("100"), prior_revenue=D("80"), operating_income=D("20"),
            net_income=D("10"), evidence_ids=("e1",),
        )
        valuation = EquityValuationInput(
            "EQ", BusinessType.STABLE_CASH_FLOW, current_price=D("50"), eps=D("5"),
            currency="USD", evidence_ids=("e1",),
        )
        _, first_runtime = self.make_runtime("phase8-det-a")
        _, second_runtime = self.make_runtime("phase8-det-b")
        first = first_runtime.analyze_equity(inputs, valuation)
        second = second_runtime.analyze_equity(inputs, valuation)

        def without_id(result):
            return (
                result.subject, result.analysis_type, result.status, result.metrics,
                result.findings, result.risks, result.unknowns,
                {k: v for k, v in result.metadata.items() if k != "calculation_id"},
            )

        self.assertEqual(without_id(first.fundamental), without_id(second.fundamental))
        self.assertEqual(without_id(first.valuation), without_id(second.valuation))

    def test_persisted_calculation_id_flows_into_report_section_lineage(self) -> None:
        _, runtime = self.make_runtime("phase8-lineage")
        result = runtime.analyze_equity(
            EquityFundamentalInput("EQ", "USD", revenue=D("100"), prior_revenue=D("90")),
            EquityValuationInput("EQ", BusinessType.STABLE_CASH_FLOW, current_price=D("50"), eps=D("5")),
        )
        section = section_from_analysis_result(result.valuation)
        self.assertEqual((result.valuation.metadata["calculation_id"],), section.calculation_ids)


if __name__ == "__main__":
    unittest.main()
