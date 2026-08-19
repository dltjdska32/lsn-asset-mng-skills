from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.invariants import validate_runtime_invariants
from investment_stack.providers import ProviderCapability, ProviderFallbackExecutor, ProviderObservation, ProviderRequest, ProviderResult, ProviderStatus
from investment_stack.providers.adapters import OpenDartAdapter
from investment_stack.providers.credentials import EnvironmentCredentials
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.review.models import ReviewContext
from investment_stack.research import Phase4ResearchRuntime


CUTOFF = "2026-08-14T10:00:00+00:00"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _ExplodingAdapter:
    name = "exploding"
    capabilities = frozenset({ProviderCapability.CURRENT_PRICE})

    def fetch(self, request):
        raise TimeoutError("secret-bearing internal timeout should never escape")


class _GoodAdapter:
    name = "good"
    capabilities = frozenset({ProviderCapability.CURRENT_PRICE})

    def fetch(self, request):
        return ProviderResult(
            self.name,
            request.capability,
            ProviderStatus.AVAILABLE,
            observations=(ProviderObservation(
                evidence_type="market", source_name="Good", source_url="https://good.test/q",
                source_tier=1, provider_id=self.name, value="100", currency="USD",
                instrument_id=request.instrument_id, metric="current_price",
                observed_at="2026-08-14T09:59:00+00:00", retrieved_at=CUTOFF,
            ),),
        )


class Phase8HardeningTests(unittest.TestCase):
    def make_run(self, run_id: str):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        manager = RunDatabaseManager(Path(temp.name) / "workspace", run_id)
        self.assertTrue(manager.create().valid)
        manager.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS", analysis_as_of=CUTOFF,
            analysis_timezone="UTC", state_version=1, personal_db_instance_id="p1",
        )
        return manager

    def test_unexpected_provider_timeout_fails_soft_and_falls_back(self) -> None:
        manager = self.make_run("phase8-provider-failure")
        runtime = Phase4ResearchRuntime(
            providers=ProviderFallbackExecutor((_ExplodingAdapter(), _GoodAdapter())),
            evidence=EvidenceResearchStore(manager),
        )
        outcome = runtime.collect(ProviderRequest(ProviderCapability.CURRENT_PRICE, CUTOFF, "UTC", "EQ"))
        self.assertEqual("100", outcome.selected.observation.value)
        states = manager.fetch_phase6_context()["provider_states"]
        self.assertEqual(["ERROR", "AVAILABLE"], [row["provider_status"] for row in states])
        self.assertNotIn("secret-bearing", manager.database_path.read_bytes().decode("latin1", errors="ignore"))

    def test_opendart_secret_is_not_persisted_on_transport_failure(self) -> None:
        secret = "phase8-super-secret-opendart-key"
        manager = self.make_run("phase8-secret")

        def transport(url, headers, timeout):
            self.assertIn(secret, url)
            raise RuntimeError(f"transport exploded at {url}")

        adapter = OpenDartAdapter(EnvironmentCredentials({"OPENDART_API_KEY": secret}), transport=transport)
        runtime = Phase4ResearchRuntime(
            providers=ProviderFallbackExecutor((adapter,)), evidence=EvidenceResearchStore(manager)
        )
        runtime.collect(ProviderRequest(
            ProviderCapability.FUNDAMENTALS, CUTOFF, "UTC", "KR-EQ", "revenue",
            {"corp_code": "00126380", "business_year": "2025", "report_code": "11011"},
        ))
        raw = manager.database_path.read_bytes()
        self.assertNotIn(secret.encode(), raw)

    def test_optional_reviewer_failure_does_not_block_report(self) -> None:
        manager = self.make_run("phase8-reviewer")

        def reviewer(_packet):
            raise RuntimeError("review service unavailable")

        result = Phase6ReportReviewRuntime(manager).generate(
            title="Hardening",
            sections=(ReportSectionInput("strategy", "Strategy", ("No execution is performed.",), status=Availability.AVAILABLE),),
            review_context=ReviewContext(strong_strategy_change=True),
            independent_reviewer=reviewer,
        )
        self.assertTrue(result.report.markdown)
        self.assertTrue(any(item.code == "OPTIONAL_REVIEWER_FAILED" for item in result.review.findings))

    def test_repository_release_invariants_include_sensitive_artifact_gate(self) -> None:
        results = {item.name: item for item in validate_runtime_invariants(PROJECT_ROOT)}
        self.assertIn("sensitive_runtime_artifacts_absent", results)
        self.assertTrue(results["sensitive_runtime_artifacts_absent"].passed, results["sensitive_runtime_artifacts_absent"].detail)


if __name__ == "__main__":
    unittest.main()
