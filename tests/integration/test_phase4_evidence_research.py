from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.providers import ProviderCapability, ProviderObservation, ProviderResult, ProviderStatus


class Phase4EvidenceIntegrationTests(unittest.TestCase):
    cutoff = "2026-08-14T10:00:00+00:00"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = RunDatabaseManager(Path(self.temporary.name) / "workspace", "phase4-run")
        self.assertTrue(self.manager.create().valid)
        self.manager.initialize_run_context(request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=self.cutoff, analysis_timezone="Asia/Seoul", state_version=3, personal_db_instance_id="db-instance")
        self.store = EvidenceResearchStore(self.manager)

    def observation(self, provider: str, value: str, when: str, tier: int = 3) -> ProviderObservation:
        return ProviderObservation(evidence_type="market", source_name=provider, source_url=f"https://{provider}.test/q", source_tier=tier, provider_id=provider, value=value, currency="USD", instrument_id="TEST", metric="current_price", observed_at=when, retrieved_at=self.cutoff)

    def result(self, provider: str, *observations: ProviderObservation) -> ProviderResult:
        return ProviderResult(provider, ProviderCapability.CURRENT_PRICE, ProviderStatus.AVAILABLE, tuple(observations))

    def test_context_clock_and_personal_state_are_immutable(self) -> None:
        with self.assertRaises(RuntimeError):
            self.manager.initialize_run_context(request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of="2026-08-14T11:00:00+00:00", analysis_timezone="Asia/Seoul", state_version=3, personal_db_instance_id="db-instance")
        raw = sqlite3.connect(self.manager.database_path)
        try:
            row = raw.execute("SELECT analysis_as_of FROM run_metadata").fetchone()
            pin = raw.execute("SELECT state_version FROM pinned_personal_state").fetchone()
        finally:
            raw.close()
        self.assertEqual(row[0], self.cutoff)
        self.assertEqual(pin[0], 3)

    def test_future_observation_persisted_but_not_selected(self) -> None:
        outcome = self.store.persist_and_select((self.result("p", self.observation("p", "99", "2026-08-14T10:01:00+00:00")),), analysis_as_of=self.cutoff)
        self.assertIsNone(outcome.observation)
        rows = self.manager.fetch_evidence_rows()
        self.assertEqual(rows[0]["freshness_status"], "UNAVAILABLE")

    def test_conflicting_sources_are_not_averaged(self) -> None:
        first = self.observation("official", "100", "2026-08-14T09:59:00+00:00", 1)
        second = self.observation("market", "110", "2026-08-14T09:59:00+00:00", 3)
        selected = self.store.persist_and_select((self.result("official", first), self.result("market", second)), analysis_as_of=self.cutoff)
        self.assertEqual(selected.observation.value, "100")
        raw = sqlite3.connect(self.manager.database_path)
        try:
            conflict_count = raw.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0]
        finally:
            raw.close()
        self.assertEqual(conflict_count, 1)

    def test_research_data_stays_in_run_database_only(self) -> None:
        self.store.persist_and_select((self.result("p", self.observation("p", "100", "2026-08-14T09:59:00+00:00")),), analysis_as_of=self.cutoff)
        self.assertTrue(self.manager.database_path.exists())
        self.assertFalse((Path(self.temporary.name) / "personal.db").exists())

    def test_financial_and_calculation_lineage_are_persisted_in_run_db(self) -> None:
        observation = ProviderObservation(
            evidence_type="financial",
            source_name="Official Filing",
            source_url="https://filing.test/1",
            source_tier=1,
            provider_id="filing",
            value="1000",
            unit="KRW",
            currency="KRW",
            instrument_id="TEST",
            metric="Revenue",
            published_at="2026-08-13T00:00:00+00:00",
            retrieved_at=self.cutoff,
            metadata={"period_end": "2026-06-30", "basis": "reported"},
        )
        selected = self.store.persist_and_select(
            (ProviderResult("filing", ProviderCapability.FUNDAMENTALS, ProviderStatus.AVAILABLE, (observation,)),),
            analysis_as_of=self.cutoff,
        )
        self.assertIsNotNone(selected.evidence_id)
        self.manager.add_calculation(
            calculation_id="calc-1",
            calculation_name="identity",
            formula="x",
            inputs={"evidence_id": selected.evidence_id},
            result={"value": "1000"},
        )
        raw = sqlite3.connect(self.manager.database_path)
        try:
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM financial_observations").fetchone()[0], 1)
            inputs = raw.execute("SELECT inputs_json FROM calculations WHERE calculation_id='calc-1'").fetchone()[0]
        finally:
            raw.close()
        self.assertIn(selected.evidence_id, inputs)


if __name__ == "__main__":
    unittest.main()
