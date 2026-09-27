from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from investment_stack.evidence import RunDatabaseManager
from investment_stack.execution import (
    Availability,
    ModeRequest,
    RuntimeServices,
    StepResult,
    compose_seven_mode_services,
    execute_mode,
)
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.personal.intent import ConfirmationState, TransactionIntent, TransactionType
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.manager import PersonalDatabaseManager
from investment_stack.reporting.thesis_refresh import (
    ComparisonOperator,
    ObservableCountercondition,
    ThesisClaim,
    ThesisEvidence,
    ThesisReviewRequest,
)
from investment_stack.routing import RequestMode
from investment_stack.execution.portfolio_thesis_modes import portfolio_thesis_services
from tests.integration.test_r14_equity_mode_bundles import R14EquityModeBundleIntegrationTests


class R14SevenModeCompositionIntegrationTests(unittest.TestCase):
    def test_real_equity_and_thesis_bundles_survive_composition(self) -> None:
        for mode in (RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.THESIS_REVIEW):
            with self.subTest(mode=mode.value), tempfile.TemporaryDirectory() as temporary:
                equity_case = R14EquityModeBundleIntegrationTests()
                equity_case.setUp()
                try:
                    specs = equity_case.specs()[:1]
                    run_db, equity = equity_case.make_services(
                        f"composed-{mode.value.lower()}", specs, mode=mode,
                    )
                    portfolio = portfolio_thesis_services(run_db=run_db, base_services=equity)
                    personal = PersonalDatabaseManager(
                        Path(temporary) / "synthetic-personal.db",
                        backup_directory=Path(temporary) / "backups",
                    )
                    self.assertEqual("VALID", personal.initialize().status.value)
                    services = compose_seven_mode_services(
                        run_db=run_db, ledger=PersonalLedgerService(personal),
                        equity_services=equity, portfolio_thesis_services=portfolio,
                    )
                    if mode is RequestMode.SINGLE_ASSET_ANALYSIS:
                        request = ModeRequest(run_db.run_id, mode, {"research_specs": specs})
                    else:
                        thesis = ThesisReviewRequest("FANUC", (ThesisClaim(
                            "claim:growth", "매출 성장이 유지된다",
                            ObservableCountercondition("revenue_growth", ComparisonOperator.LT,
                                                       Decimal("5"), "PERCENT"),
                            ("evidence:prior-growth",),
                            ObservableCountercondition("revenue_growth", ComparisonOperator.GTE,
                                                       Decimal("5"), "PERCENT"),
                        ),))
                        evidence = (ThesisEvidence(
                            "evidence:current-growth", "FANUC", "revenue_growth", Decimal("8"), "PERCENT",
                            "2026-08-14T09:00:00+09:00", "2026-08-14T09:01:00+09:00",
                            "FRESH", "ELIGIBLE", True,
                        ),)
                        request = ModeRequest(run_db.run_id, mode, {
                            "thesis_request": thesis, "thesis_evidence": evidence,
                        })
                    result = execute_mode(request, services)
                    self.assertIn(result.availability, {Availability.COMPLETE, Availability.PARTIAL}, result.as_dict())
                    self.assertTrue(result.report_refs)
                    self.assertIsNone(result.mutation_receipt)
                finally:
                    equity_case.doCleanups()

    def test_composed_fixed_plans_keep_writer_only_on_asset_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_db = RunDatabaseManager(root / "run", "synthetic-run")
            self.assertTrue(run_db.create().valid)
            run_db.initialize_run_context(
                request_mode=RequestMode.ASSET_UPDATE.value,
                analysis_as_of="2026-09-27T10:00:00+00:00", analysis_timezone="UTC",
                state_version=0, personal_db_instance_id="SYNTHETIC-ONLY",
            )

            personal = PersonalDatabaseManager(root / "synthetic-personal.db",
                                               backup_directory=root / "backups")
            self.assertEqual("VALID", personal.initialize().status.value)
            ledger = PersonalLedgerService(personal)
            ledger.register_account("cash", name="Cash", currency="USD", timezone_name="UTC")

            planner = FixedPipelinePlanner()
            equity_modes = {RequestMode.SINGLE_ASSET_ANALYSIS, RequestMode.ASSET_COMPARISON}
            equity_steps = {step for mode in equity_modes for step in planner.plan(mode).steps}
            all_analysis_steps = {
                step for mode in RequestMode if mode is not RequestMode.ASSET_UPDATE
                for step in planner.plan(mode).steps
            }

            def partial(*_args):
                return StepResult(Availability.PARTIAL, missing_inputs=("synthetic_fixture_input",))

            def render(*_args):
                return StepResult(Availability.PARTIAL, report_refs=("report:synthetic",),
                                  missing_inputs=("synthetic_fixture_input",))

            equity = RuntimeServices({step: partial for step in equity_steps}, run_db=run_db)
            portfolio_handlers = {step: partial for step in all_analysis_steps}
            portfolio_handlers[PipelineStep.RENDER_PARTIAL_AWARE_REPORT] = render
            portfolio = RuntimeServices(portfolio_handlers, run_db=run_db)
            services = compose_seven_mode_services(
                run_db=run_db, ledger=ledger, equity_services=equity,
                portfolio_thesis_services=portfolio,
            )

            self.assertEqual(set(RequestMode), {planner.plan(mode).mode for mode in RequestMode})
            for mode in RequestMode:
                self.assertTrue(set(planner.plan(mode).steps).issubset(services.handlers), mode.value)

            before = ledger.get_current_state_version()
            for mode in RequestMode:
                if mode is RequestMode.ASSET_UPDATE:
                    continue
                result = execute_mode(ModeRequest("synthetic-run", mode), services)
                self.assertEqual(Availability.PARTIAL, result.availability, (mode.value, result.unsupported_reasons))
                self.assertIsNone(result.mutation_receipt, mode.value)
            self.assertEqual(before, ledger.get_current_state_version())

            intent = TransactionIntent(
                TransactionType.DEPOSIT, account_id="cash", cash_amount="1000", currency="USD",
                occurred_at=datetime(2026, 9, 27, 11), timezone="UTC",
                confirmation_state=ConfirmationState.CONFIRMED, idempotency_key="synthetic-deposit",
            )
            posted = execute_mode(ModeRequest(
                "synthetic-run", RequestMode.ASSET_UPDATE, {"transaction_intent": intent},
            ), services)
            self.assertEqual(Availability.COMPLETE, posted.availability, posted.as_dict())
            self.assertEqual("POSTED", posted.mutation_receipt["status"])
            self.assertGreater(ledger.get_current_state_version(), before)

            wrong_run = execute_mode(ModeRequest("other-run", RequestMode.ASSET_UPDATE,
                                                 {"transaction_intent": intent}), services)
            self.assertEqual(Availability.UNSUPPORTED, wrong_run.availability)
            self.assertIsNone(wrong_run.mutation_receipt)
            wrong_analysis_run = execute_mode(
                ModeRequest("other-run", RequestMode.PERSONAL_PORTFOLIO_ANALYSIS), services,
            )
            self.assertEqual(Availability.UNSUPPORTED, wrong_analysis_run.availability)
            self.assertIsNone(wrong_analysis_run.mutation_receipt)

    def test_factory_rejects_mixed_run_database_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a = RunDatabaseManager(root, "a")
            run_b = RunDatabaseManager(root, "b")
            run_a.create()
            run_b.create()
            run_a.initialize_run_context(request_mode="ASSET_UPDATE", analysis_as_of="2026-09-27T10:00:00+00:00",
                                         analysis_timezone="UTC")
            run_b.initialize_run_context(request_mode="ASSET_UPDATE", analysis_as_of="2026-09-27T10:00:00+00:00",
                                         analysis_timezone="UTC")
            steps = set(PipelineStep)
            services_a = RuntimeServices({step: lambda *_: StepResult(Availability.PARTIAL) for step in steps}, run_db=run_a)
            services_b = RuntimeServices({step: lambda *_: StepResult(Availability.PARTIAL) for step in steps}, run_db=run_b)
            ledger = PersonalLedgerService(PersonalDatabaseManager(
                root / "other-personal.db", backup_directory=root / "backups"))
            with self.assertRaisesRegex(ValueError, "same run database"):
                compose_seven_mode_services(run_db=run_a, ledger=ledger,
                                            equity_services=services_a, portfolio_thesis_services=services_b)


if __name__ == "__main__":
    unittest.main()
