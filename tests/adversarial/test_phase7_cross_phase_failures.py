from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.personal import PersonalDatabaseManager, PersonalLedgerService, TransactionIntent, TransactionType
from investment_stack.personal.manager import PersonalDatabaseStatus, StorageNotWritableError
from investment_stack.providers import ProviderCapability, ProviderFallbackExecutor, ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.research import Phase4ResearchRuntime
from tests.storage_support import file_digest


CUTOFF = "2026-08-14T10:00:00+00:00"
WHEN = datetime(2026, 8, 14, 10, 0)


class _Adapter:
    def __init__(self, result: ProviderResult) -> None:
        self.name = result.provider
        self.capabilities = frozenset({result.capability})
        self.result = result

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        return self.result


class Phase7CrossPhaseFailureTests(unittest.TestCase):
    def test_research_and_report_runtime_do_not_mutate_personal_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            personal = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
            personal.initialize()
            ledger = PersonalLedgerService(personal)
            ledger.register_account("cash", name="Cash", currency="USD", timezone_name="UTC")
            ledger.post(TransactionIntent(TransactionType.DEPOSIT, account_id="cash", cash_amount="1000", currency="USD", occurred_at=WHEN, timezone="UTC"))
            before = file_digest(personal.database_path)

            run = RunDatabaseManager(root / "workspace", "phase7-isolation")
            self.assertTrue(run.create().valid)
            run.initialize_run_context(request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=CUTOFF, analysis_timezone="UTC", state_version=ledger.get_current_state_version(), personal_db_instance_id=personal.instance_id)
            provider = ProviderResult(
                "official-market",
                ProviderCapability.CURRENT_PRICE,
                ProviderStatus.AVAILABLE,
                observations=(ProviderObservation(evidence_type="market", source_name="Official Market", source_url="https://market.test/quote", source_tier=1, provider_id="official-market", value="100", currency="USD", instrument_id="TEST", metric="current_price", observed_at="2026-08-14T09:59:00+00:00", retrieved_at=CUTOFF),),
            )
            research = Phase4ResearchRuntime(providers=ProviderFallbackExecutor((_Adapter(provider),)), evidence=EvidenceResearchStore(run))
            outcome = research.collect(ProviderRequest(ProviderCapability.CURRENT_PRICE, CUTOFF, "UTC", "TEST", "current_price"))
            self.assertIsNotNone(outcome.selected.observation)
            Phase6ReportReviewRuntime(run).generate(title="Isolation", sections=(ReportSectionInput("summary", "Summary", ("Research completed.",), status=Availability.AVAILABLE, evidence_ids=(outcome.selected.evidence_id,), current_value_claim=True),))

            self.assertEqual(file_digest(personal.database_path), before)
            self.assertEqual(personal.status, PersonalDatabaseStatus.VALID)
            personal.assert_writable()

    def test_invalid_personal_database_cannot_become_writable_through_ledger_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "personal.db"
            path.write_bytes(b"corrupt-personal-db")
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")
            startup = manager.startup()
            self.assertNotEqual(startup.status, PersonalDatabaseStatus.VALID)
            with self.assertRaises(StorageNotWritableError):
                manager.assert_writable()

    def test_future_market_data_cannot_be_selected_then_labeled_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = RunDatabaseManager(root / "workspace", "phase7-future-current")
            self.assertTrue(run.create().valid)
            run.initialize_run_context(request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=CUTOFF, analysis_timezone="UTC", state_version=0, personal_db_instance_id="p")
            provider = ProviderResult(
                "future-market",
                ProviderCapability.CURRENT_PRICE,
                ProviderStatus.AVAILABLE,
                observations=(ProviderObservation(evidence_type="market", source_name="Future Market", source_url="https://market.test/future", source_tier=1, provider_id="future-market", value="500", currency="USD", instrument_id="TEST", metric="current_price", observed_at="2026-08-14T10:01:00+00:00", retrieved_at=CUTOFF),),
            )
            research = Phase4ResearchRuntime(providers=ProviderFallbackExecutor((_Adapter(provider),)), evidence=EvidenceResearchStore(run))
            outcome = research.collect(ProviderRequest(ProviderCapability.CURRENT_PRICE, CUTOFF, "UTC", "TEST", "current_price"))
            self.assertIsNone(outcome.selected.observation)
            with self.assertRaises(ValueError):
                Phase6ReportReviewRuntime(run).generate(title="Current", sections=(ReportSectionInput("price", "Current Price", ("Current price: 500",), status=Availability.AVAILABLE, current_value_claim=True),))


if __name__ == "__main__":
    unittest.main()
