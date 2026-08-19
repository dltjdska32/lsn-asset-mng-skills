from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import (
    AlternativeAsset, AlternativeAssetInput, AssetRiskInput, BusinessType,
    EquityFundamentalInput, EquityValuationInput, FundAnalysisInput, FundHolding,
    PositionExposure,
)
from investment_stack.evidence import RunDatabaseManager
from investment_stack.materiality import LightweightAsset, MaterialityConfig, MaterialityEngine

D = Decimal


class Phase5AssetRuntimeIntegrationTests(unittest.TestCase):
    def make_runtime(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = RunDatabaseManager(Path(tmp.name) / "workspace", "phase5")
        manager.create()
        manager.initialize_run_context(request_mode="PERSONAL_PORTFOLIO_ANALYSIS", analysis_as_of="2026-08-14T10:00:00+00:00", analysis_timezone="UTC", state_version=3, personal_db_instance_id="p3")
        runtime = Phase5AssetAnalysisRuntime(manager, materiality=MaterialityEngine(MaterialityConfig("cfg-1", D("0.05"), D("0.20"), D("0.80"))))
        return manager, runtime

    def test_equity_results_persist_as_calculation_lineage(self):
        manager, runtime = self.make_runtime()
        runtime.analyze_equity(
            EquityFundamentalInput("EQ", "USD", revenue=D("100"), prior_revenue=D("90"), operating_income=D("20"), net_income=D("10")),
            EquityValuationInput("EQ", BusinessType.STABLE_CASH_FLOW, current_price=D("50"), eps=D("5")),
        )
        con = sqlite3.connect(manager.database_path)
        try:
            names = [row[0] for row in con.execute("SELECT calculation_name FROM calculations ORDER BY rowid")]
        finally:
            con.close()
        self.assertEqual(names, ["EQUITY_FUNDAMENTAL", "EQUITY_VALUATION"])

    def test_portfolio_materiality_happens_before_deep_callbacks(self):
        manager, runtime = self.make_runtime()
        calls = []
        lightweight = (
            LightweightAsset("BIG", D("1"), D("0.8"), D("1"), D("0.3"), D("0.1")),
            LightweightAsset("SMALL", D("1"), D("0.01"), D("1"), D("0.01"), D("0.1")),
        )
        def deep_big():
            con = sqlite3.connect(manager.database_path)
            try:
                count = con.execute("SELECT COUNT(*) FROM materiality_decisions").fetchone()[0]
            finally:
                con.close()
            calls.append(count)
            return "deep"
        result = runtime.analyze_portfolio(
            lightweight_assets=lightweight,
            exposures=(PositionExposure("BIG", D("800"), asset_class="EQUITY"), PositionExposure("SMALL", D("10"), asset_class="EQUITY")),
            risk_assets=(AssetRiskInput("BIG", D("1"), (D("100"), D("101"), D("99"))),),
            deep_analyzers={"BIG": deep_big, "SMALL": lambda: self.fail("non-material asset deep researched")},
        )
        self.assertEqual(calls, [2])
        self.assertEqual(set(result.deep_results), {"BIG"})

    def test_alternative_and_fund_persist_without_personal_mutation(self):
        manager, runtime = self.make_runtime()
        runtime.analyze_fund(FundAnalysisInput("ETF", D("100"), D("100"), D("0.001"), D("1000"), D("100"), (FundHolding("A", D("1")),), "2026-08-13"))
        runtime.analyze_alternative(AlternativeAssetInput("BTC", AlternativeAsset.BITCOIN, "NATIVE_CRYPTO", "exchange", (D("100"), D("110"), D("105")), "USD", venue="KRAKEN"))
        con = sqlite3.connect(manager.database_path)
        try:
            count = con.execute("SELECT COUNT(*) FROM calculations").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
