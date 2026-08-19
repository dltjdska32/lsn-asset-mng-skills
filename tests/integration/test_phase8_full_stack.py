from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from investment_stack.asset_analysis import Phase5AssetAnalysisRuntime
from investment_stack.calculations import BusinessType, EquityFundamentalInput, EquityValuationInput
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.materiality import MaterialityConfig, MaterialityEngine
from investment_stack.personal import PersonalDatabaseManager, PersonalLedgerService, TransactionIntent, TransactionType
from investment_stack.providers import ProviderCapability, ProviderFallbackExecutor, ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime, section_from_analysis_result
from investment_stack.research import Phase4ResearchRuntime
from tests.storage_support import file_digest


D = Decimal
CUTOFF = "2026-08-14T10:00:00+00:00"


class _PriceAdapter:
    name = "official-market"
    capabilities = frozenset({ProviderCapability.CURRENT_PRICE})

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            self.name,
            request.capability,
            ProviderStatus.AVAILABLE,
            observations=(
                ProviderObservation(
                    evidence_type="market",
                    source_name="Official Market",
                    source_url="https://market.test/quote",
                    source_tier=1,
                    provider_id=self.name,
                    value="50",
                    currency="USD",
                    instrument_id=request.instrument_id,
                    metric="current_price",
                    observed_at="2026-08-14T09:59:00+00:00",
                    retrieved_at=CUTOFF,
                    official_confirmation_status="OFFICIAL",
                ),
            ),
        )


class Phase8FullStackIntegrationTests(unittest.TestCase):
    def test_provider_to_evidence_to_analysis_to_report_preserves_personal_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            personal = PersonalDatabaseManager(root / "personal/personal.db", backup_directory=root / "backups")
            self.assertEqual("VALID", personal.initialize().status.value)
            ledger = PersonalLedgerService(personal)
            ledger.register_account("cash", name="Cash", currency="USD", timezone_name="UTC")
            ledger.post(
                TransactionIntent(
                    TransactionType.DEPOSIT,
                    account_id="cash",
                    cash_amount="1000",
                    currency="USD",
                    occurred_at=datetime(2026, 8, 14, 9, 0),
                    timezone="UTC",
                )
            )
            before = file_digest(personal.database_path)
            state_version = ledger.get_current_state_version()

            run = RunDatabaseManager(root / "workspace", "phase8-full-stack")
            self.assertTrue(run.create().valid)
            run.initialize_run_context(
                request_mode="SINGLE_ASSET_ANALYSIS",
                analysis_as_of=CUTOFF,
                analysis_timezone="UTC",
                state_version=state_version,
                personal_db_instance_id=personal.instance_id,
                portfolio_data_as_of="2026-08-14T09:00:00+00:00",
            )

            research = Phase4ResearchRuntime(
                providers=ProviderFallbackExecutor((_PriceAdapter(),)),
                evidence=EvidenceResearchStore(run),
            )
            outcome = research.collect(
                ProviderRequest(ProviderCapability.CURRENT_PRICE, CUTOFF, "UTC", "EQ", "current_price")
            )
            self.assertIsNotNone(outcome.selected.observation)
            evidence_id = outcome.selected.evidence_id
            assert evidence_id is not None

            analysis = Phase5AssetAnalysisRuntime(
                run,
                materiality=MaterialityEngine(MaterialityConfig("phase8", D("0.05"), D("0.20"), D("0.80"))),
            ).analyze_equity(
                EquityFundamentalInput(
                    "EQ", "USD", revenue=D("100"), prior_revenue=D("90"), operating_income=D("20"),
                    net_income=D("10"), evidence_ids=(evidence_id,),
                ),
                EquityValuationInput(
                    "EQ", BusinessType.STABLE_CASH_FLOW, current_price=D("50"), eps=D("5"),
                    currency="USD", evidence_ids=(evidence_id,),
                ),
            )
            valuation_section = section_from_analysis_result(
                analysis.valuation,
                name="valuation",
                title="Valuation",
                current_value_claim=True,
            )
            result = Phase6ReportReviewRuntime(run).generate(
                title="EQ Final Integration",
                sections=(valuation_section,),
            )

            self.assertIn("Market Data As Of: 2026-08-14T09:59:00+00:00", result.report.markdown)
            self.assertIn("Calculation lineage:", result.report.markdown)
            self.assertIn(str(analysis.valuation.metadata["calculation_id"]), result.report.markdown)
            self.assertEqual(before, file_digest(personal.database_path))
            self.assertEqual(state_version, run.fetch_phase6_context()["pinned_personal_state"]["state_version"])

            with closing(sqlite3.connect(run.database_path)) as connection:
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM calculations").fetchone()[0])
                self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM report_sections").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
