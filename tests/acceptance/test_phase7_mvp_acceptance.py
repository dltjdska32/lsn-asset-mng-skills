from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from investment_stack.calculations import (
    AlternativeAsset,
    AlternativeAssetAnalyzer,
    AlternativeAssetInput,
)
from investment_stack.evidence import EvidenceResearchStore, RunDatabaseManager
from investment_stack.invariants import validate_runtime_invariants
from investment_stack.personal import (
    ConfirmationState,
    IntentState,
    PersonalDatabaseManager,
    PersonalLedgerService,
    TransactionIntent,
    TransactionType,
    evaluate_intent,
)
from investment_stack.personal.intent import OpeningBalanceKind
from investment_stack.personal.interpretation import parse_transaction_request
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.providers import (
    ProviderCapability,
    ProviderFallbackExecutor,
    ProviderObservation,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from investment_stack.reporting.models import Availability, ReportSectionInput
from investment_stack.reporting.runtime import Phase6ReportReviewRuntime
from investment_stack.routing import RequestMode
from investment_stack.research import Phase4ResearchRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WHEN = datetime(2026, 8, 14, 10, 0)
CUTOFF = "2026-08-14T10:00:00+00:00"


class _Adapter:
    def __init__(self, name: str, result: ProviderResult) -> None:
        self.name = name
        self.capabilities = frozenset({result.capability})
        self.result = result

    def fetch(self, request: ProviderRequest) -> ProviderResult:
        return self.result


class Phase7MvpAcceptanceTests(unittest.TestCase):
    def make_ledger(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        manager = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
        manager.initialize()
        ledger = PersonalLedgerService(manager)
        ledger.register_account("a", name="A", currency="KRW", timezone_name="Asia/Seoul")
        ledger.register_account("b", name="B", currency="KRW", timezone_name="Asia/Seoul")
        ledger.register_instrument("fanuc", canonical_name="FANUC", currency="JPY")
        return manager, ledger

    def make_run(self, run_id: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager = RunDatabaseManager(Path(temporary.name) / "workspace", run_id)
        self.assertTrue(manager.create().valid)
        manager.initialize_run_context(
            request_mode="SINGLE_ASSET_ANALYSIS",
            analysis_as_of=CUTOFF,
            analysis_timezone="UTC",
            state_version=0,
            personal_db_instance_id="phase7-personal",
        )
        return manager

    def test_frozen_architecture_structural_invariants_pass(self) -> None:
        results = validate_runtime_invariants(PROJECT_ROOT)
        failed = [result for result in results if not result.passed]
        self.assertFalse(failed, failed)
        names = {result.name for result in results}
        self.assertIn("exactly_eight_skills", names)
        self.assertIn("exactly_seven_request_modes", names)
        self.assertIn("research_cache_db_absent", names)
        self.assertIn("server_infrastructure_dependencies_absent", names)

    def test_cash_transfer_is_internal_and_total_cash_effect_is_zero(self) -> None:
        _, ledger = self.make_ledger()
        ledger.post(TransactionIntent(
            TransactionType.DEPOSIT,
            account_id="a",
            cash_amount="1000",
            currency="KRW",
            occurred_at=WHEN,
            timezone="Asia/Seoul",
        ))
        before_total = sum((row.balance for row in ledger.get_cash_balances()), Decimal("0"))
        before_version = ledger.get_current_state_version()
        ledger.post(TransactionIntent(
            TransactionType.TRANSFER,
            source_account_id="a",
            destination_account_id="b",
            cash_amount="300",
            currency="KRW",
            occurred_at=WHEN,
            timezone="Asia/Seoul",
        ))
        after_total = sum((row.balance for row in ledger.get_cash_balances()), Decimal("0"))
        transfer_rows = [row for row in ledger.get_cashflow() if row.category == "TRANSFER"]
        self.assertEqual(before_total, after_total)
        self.assertEqual(sum((row.amount for row in transfer_rows), Decimal("0")), Decimal("0"))
        self.assertEqual(ledger.get_current_state_version(), before_version + 1)

    def test_in_kind_transfer_is_not_converted_to_sell_buy_or_adjustment(self) -> None:
        _, ledger = self.make_ledger()
        intent = parse_transaction_request(
            "FANUC를 다른 계좌로 옮겼어",
            account_id="a",
            instrument_id="fanuc",
            currency="JPY",
        )
        decision = evaluate_intent(intent)
        self.assertEqual(decision.state, IntentState.UNSUPPORTED)
        self.assertEqual(ledger.list_transactions(), ())

    def test_missing_event_time_never_auto_posts(self) -> None:
        _, ledger = self.make_ledger()
        intent = parse_transaction_request(
            "FANUC 2주 6400엔에 샀어",
            account_id="a",
            instrument_id="fanuc",
            currency="JPY",
        )
        decision = ledger.validate_intent(intent)
        self.assertEqual(decision.state, IntentState.NEEDS_CONFIRMATION)
        self.assertIn("occurred_at", decision.missing_fields)
        self.assertEqual(ledger.get_current_state_version(), 0)

    def test_bootstrap_and_adjustment_transactions_always_require_confirmation(self) -> None:
        intents = (
            TransactionIntent(
                TransactionType.ASSET_ADJUSTMENT,
                account_id="a",
                instrument_id="fanuc",
                quantity="1",
                unit="SHARE",
                occurred_at=WHEN,
                timezone="Asia/Seoul",
            ),
            TransactionIntent(
                TransactionType.OPENING_BALANCE,
                account_id="a",
                cash_amount="1000",
                currency="KRW",
                opening_balance_kind=OpeningBalanceKind.CASH,
                occurred_at=WHEN,
                timezone="Asia/Seoul",
            ),
            TransactionIntent(
                TransactionType.INITIAL_POSITION,
                account_id="a",
                instrument_id="fanuc",
                quantity="1",
                unit="SHARE",
                cost_basis_status="UNAVAILABLE",
                occurred_at=WHEN,
                timezone="Asia/Seoul",
            ),
        )
        for intent in intents:
            with self.subTest(transaction_type=intent.transaction_type.value):
                self.assertEqual(evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION)

    def test_correction_is_reversal_plus_replacement_with_one_state_version(self) -> None:
        _, ledger = self.make_ledger()
        ledger.post(TransactionIntent(
            TransactionType.DEPOSIT,
            account_id="a",
            cash_amount="100000",
            currency="JPY",
            occurred_at=WHEN,
            timezone="Asia/Tokyo",
        ))
        old = ledger.post(TransactionIntent(
            TransactionType.BUY,
            account_id="a",
            instrument_id="fanuc",
            quantity="2",
            unit_price="6400",
            currency="JPY",
            occurred_at=WHEN,
            timezone="Asia/Tokyo",
        ))
        before = ledger.get_current_state_version()
        corrected = ledger.correct(
            old.transaction_ids[0],
            TransactionIntent(
                TransactionType.BUY,
                account_id="a",
                instrument_id="fanuc",
                quantity="3",
                unit_price="6300",
                currency="JPY",
                occurred_at=WHEN,
                timezone="Asia/Tokyo",
            ),
            reason="phase7 correction",
            occurred_at=WHEN,
            timezone_name="Asia/Tokyo",
        )
        types = [row["transaction_type"] for row in ledger.list_transactions()]
        self.assertEqual(types[-2:], ["REVERSAL", "BUY"])
        self.assertNotIn("CORRECTION", types)
        self.assertEqual(corrected.state_version, before + 1)

    def test_materiality_gate_precedes_portfolio_deep_research(self) -> None:
        steps = FixedPipelinePlanner().plan(RequestMode.PERSONAL_PORTFOLIO_ANALYSIS).steps
        self.assertLess(
            steps.index(PipelineStep.APPLY_MATERIALITY_GATE),
            steps.index(PipelineStep.DEEP_RESEARCH_SELECTED_ASSETS),
        )

    def test_latest_as_of_rejects_future_observation(self) -> None:
        manager = self.make_run("phase7-future")
        result = ProviderResult(
            "future-provider",
            ProviderCapability.CURRENT_PRICE,
            ProviderStatus.AVAILABLE,
            observations=(
                ProviderObservation(
                    evidence_type="market",
                    source_name="Future Market",
                    source_url="https://future.test/quote",
                    source_tier=1,
                    provider_id="future-provider",
                    value="999",
                    currency="USD",
                    instrument_id="TEST",
                    metric="current_price",
                    observed_at="2026-08-14T10:01:00+00:00",
                    retrieved_at=CUTOFF,
                ),
            ),
        )
        runtime = Phase4ResearchRuntime(
            providers=ProviderFallbackExecutor((_Adapter("future-provider", result),)),
            evidence=EvidenceResearchStore(manager),
        )
        outcome = runtime.collect(
            ProviderRequest(
                ProviderCapability.CURRENT_PRICE,
                CUTOFF,
                "UTC",
                "TEST",
                "current_price",
            )
        )
        self.assertIsNone(outcome.selected.observation)
        self.assertTrue(outcome.selected.partial)

    def test_latest_news_uses_existing_evidence_schema_not_separate_news_table(self) -> None:
        manager = self.make_run("phase7-news-boundary")
        with closing(sqlite3.connect(manager.database_path)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("news", tables)
        self.assertNotIn("news_observations", tables)
        skills = {
            path.name
            for path in (PROJECT_ROOT / "skills").iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        self.assertNotIn("news", skills)
        self.assertNotIn("news-analysis", skills)

    def test_bitcoin_corporate_valuation_is_forbidden(self) -> None:
        result = AlternativeAssetAnalyzer().analyze(
            AlternativeAssetInput(
                "BTC",
                AlternativeAsset.BITCOIN,
                "NATIVE_CRYPTO",
                "exchange",
                (Decimal("100"), Decimal("105")),
                "USD",
                venue="KRAKEN",
            )
        )
        self.assertFalse(result.metadata["corporate_valuation_allowed"])

    def test_independent_reviewer_is_optional_for_report_generation(self) -> None:
        manager = self.make_run("phase7-optional-review")
        runtime = Phase6ReportReviewRuntime(manager)
        result = runtime.generate(
            title="Deterministic Report",
            sections=(
                ReportSectionInput(
                    "analysis",
                    "Analysis",
                    ("Deterministic evidence-based section.",),
                    status=Availability.AVAILABLE,
                ),
            ),
        )
        self.assertFalse(result.review.required)
        self.assertIn("Deterministic Report", result.report.markdown)


if __name__ == "__main__":
    unittest.main()
