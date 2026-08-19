from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.providers import ProviderCapability, ProviderFallbackExecutor, ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.research import Phase4ResearchRuntime
from investment_stack.web_research import WebResearchAdapter, WebResearchHit, WebResearchResponse


class FakeAdapter:
    capabilities = frozenset({ProviderCapability.CURRENT_PRICE, ProviderCapability.NEWS})
    def __init__(self, name: str, result: ProviderResult) -> None:
        self.name = name
        self.result = result
    def fetch(self, request):
        return self.result


def unavailable(name: str, capability: ProviderCapability, status: ProviderStatus = ProviderStatus.UNAVAILABLE) -> ProviderResult:
    return ProviderResult(name, capability, status, reason="not available")


class Phase4ResearchAcceptanceTests(unittest.TestCase):
    cutoff = "2026-08-14T10:00:00+00:00"

    def make_runtime(self, adapters, backend=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager = RunDatabaseManager(Path(temporary.name) / "workspace", f"flow-{len(self._cleanups)}")
        manager.create()
        manager.initialize_run_context(request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=self.cutoff, analysis_timezone="UTC", state_version=7, personal_db_instance_id="instance-7")
        runtime = Phase4ResearchRuntime(
            providers=ProviderFallbackExecutor(adapters),
            evidence=EvidenceResearchStore(manager),
            web_research=None if backend is None else WebResearchAdapter(backend),
        )
        return manager, runtime

    def request(self, capability=ProviderCapability.CURRENT_PRICE):
        return ProviderRequest(capability, self.cutoff, "UTC", "TEST", "current_price" if capability is ProviderCapability.CURRENT_PRICE else "latest_relevant_news")

    def market_result(self, name: str, value: str, when: str, tier: int = 3) -> ProviderResult:
        return ProviderResult(name, ProviderCapability.CURRENT_PRICE, ProviderStatus.AVAILABLE, (
            ProviderObservation(evidence_type="market", source_name=name, source_url=f"https://{name}.test/q", source_tier=tier, provider_id=name, value=value, currency="USD", instrument_id="TEST", metric="current_price", observed_at=when, retrieved_at=self.cutoff),
        ))

    def test_a_structured_provider_available_persists_selected_evidence(self) -> None:
        manager, runtime = self.make_runtime([FakeAdapter("structured", self.market_result("structured", "120", "2026-08-14T09:59:00+00:00", 2))])
        outcome = runtime.collect(self.request())
        self.assertFalse(outcome.used_web_fallback)
        self.assertEqual(outcome.selected.observation.value, "120")
        self.assertEqual(manager.fetch_evidence_rows()[0]["provider_id"], "structured")

    def test_b_missing_credential_falls_back_to_timestamped_web_and_persists(self) -> None:
        missing = unavailable("credentialed", ProviderCapability.CURRENT_PRICE, ProviderStatus.MISSING_CREDENTIAL)
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (WebResearchHit("Official Exchange", "https://exchange.test/q", "quote", value="123", currency="USD", claimed_market_time="2026-08-14T09:59:00+00:00", source_tier=1, source_kind="official_exchange"),))
        manager, runtime = self.make_runtime([FakeAdapter("credentialed", missing)], backend)
        outcome = runtime.collect(self.request(), web_query="TEST current price")
        self.assertTrue(outcome.used_web_fallback)
        self.assertEqual(outcome.selected.observation.value, "123")
        self.assertEqual(manager.fetch_evidence_rows()[0]["provider_id"], "web_research")

    def test_c_provider_error_falls_through_to_next_provider(self) -> None:
        error = unavailable("bad", ProviderCapability.CURRENT_PRICE, ProviderStatus.ERROR)
        good = self.market_result("good", "121", "2026-08-14T09:58:00+00:00")
        manager, runtime = self.make_runtime([FakeAdapter("bad", error), FakeAdapter("good", good)])
        outcome = runtime.collect(self.request())
        self.assertEqual(outcome.selected.observation.value, "121")
        raw = sqlite3.connect(manager.database_path)
        try:
            states = raw.execute("SELECT provider_status FROM provider_states ORDER BY rowid").fetchall()
        finally:
            raw.close()
        self.assertEqual([row[0] for row in states], ["ERROR", "AVAILABLE"])

    def test_d_only_stale_data_is_explicitly_partial_and_stale(self) -> None:
        manager, runtime = self.make_runtime([FakeAdapter("old", self.market_result("old", "90", "2026-08-10T09:00:00+00:00"))])
        outcome = runtime.collect(self.request())
        self.assertTrue(outcome.selected.partial)
        self.assertEqual(outcome.selected.freshness.status.value, "STALE")

    def test_e_conflicting_sources_are_recorded_not_averaged(self) -> None:
        manager, _ = self.make_runtime([])
        store = EvidenceResearchStore(manager)
        first = self.market_result("official", "100", "2026-08-14T09:59:00+00:00", 1)
        second = self.market_result("market", "110", "2026-08-14T09:59:00+00:00", 3)
        selected = store.persist_and_select((first, second), analysis_as_of=self.cutoff)
        self.assertEqual(selected.observation.value, "100")
        self.assertNotEqual(selected.observation.value, "105")
        raw = sqlite3.connect(manager.database_path)
        try:
            self.assertEqual(raw.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0], 1)
        finally:
            raw.close()

    def test_f_latest_news_uses_same_evidence_table_not_news_table(self) -> None:
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (WebResearchHit("IR", "https://ir.test/news", "Guidance update", published_at="2026-08-14T09:30:00+00:00", event_time="2026-08-14T09:20:00+00:00", source_kind="official_ir", event_cluster_id="guidance-1", official_confirmation_status="OFFICIAL"),))
        manager, runtime = self.make_runtime([], backend)
        outcome = runtime.collect(self.request(ProviderCapability.NEWS), web_query="TEST latest relevant news")
        self.assertTrue(outcome.used_web_fallback)
        rows = manager.fetch_evidence_rows()
        self.assertEqual(rows[0]["evidence_type"], "news")
        raw = sqlite3.connect(manager.database_path)
        try:
            tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            raw.close()
        self.assertNotIn("news", tables)
        self.assertNotIn("news_observations", tables)

    def test_g_observation_after_cutoff_is_never_selected(self) -> None:
        _, runtime = self.make_runtime([FakeAdapter("future", self.market_result("future", "999", "2026-08-14T10:01:00+00:00"))])
        outcome = runtime.collect(self.request())
        self.assertIsNone(outcome.selected.observation)
        self.assertTrue(outcome.selected.partial)

    def test_fundamental_web_news_number_is_persisted_but_not_selected_for_calculation(self) -> None:
        def backend(intent, query, cutoff):
            return WebResearchResponse(intent, (
                WebResearchHit(
                    "Media", "https://media.test/revenue", "Revenue reported",
                    value="500", published_at="2026-08-14T09:00:00+00:00",
                    source_kind="news_article",
                ),
            ))
        manager, runtime = self.make_runtime([], backend)
        request = ProviderRequest(ProviderCapability.FUNDAMENTALS, self.cutoff, "UTC", "TEST", "Revenue")
        outcome = runtime.collect(request, web_query="TEST latest revenue")
        self.assertTrue(outcome.used_web_fallback)
        self.assertIsNone(outcome.selected.observation)
        rows = manager.fetch_evidence_rows()
        self.assertEqual(rows[0]["official_confirmation_status"], "NEWS_REPORTED")
        self.assertIsNone(rows[0]["selection_state"])


if __name__ == "__main__":
    unittest.main()
