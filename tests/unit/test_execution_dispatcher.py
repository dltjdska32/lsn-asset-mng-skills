from __future__ import annotations

import unittest
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_stack.execution import Availability, ModeRequest, RuntimeServices, StepResult, asset_update_services, execute_mode, execute_text_request, execute_update_then_analysis
from investment_stack.pipelines import FixedPipelinePlanner, PipelineStep
from investment_stack.routing import RequestMode
from investment_stack.personal import ConfirmationState, PersonalDatabaseManager, PersonalLedgerService, TransactionIntent, TransactionType


class FixedModeDispatcherTests(unittest.TestCase):
    def services_for(self, mode: RequestMode, *, partial_step: PipelineStep | None = None) -> RuntimeServices:
        plan = FixedPipelinePlanner().plan(mode)
        handlers = {}
        for step in plan.steps:
            def handler(_request, _context, current=step):
                if current is PipelineStep.RENDER_PARTIAL_AWARE_REPORT:
                    return StepResult(Availability.PARTIAL if partial_step else Availability.COMPLETE,
                                      report_refs=("report:" + sha256(mode.value.encode()).hexdigest(),),
                                      missing_inputs=("synthetic_input",) if partial_step else ())
                if current is PipelineStep.DECIDE_POSTING:
                    return StepResult(Availability.COMPLETE, output={"posted": True}, mutation_receipt={
                        "status": "POSTED", "transaction_ids": ["tx-synthetic"], "state_version": 1,
                    })
                if current is partial_step:
                    return StepResult(Availability.PARTIAL, output={"partial": True}, missing_inputs=("synthetic_input",))
                return StepResult(Availability.COMPLETE, output={"step": current.value})
            handlers[step] = handler
        return RuntimeServices(handlers=handlers)

    def test_every_fixed_mode_executes_its_registered_steps_and_emits_report_where_required(self) -> None:
        for mode in RequestMode:
            with self.subTest(mode=mode):
                payload = {"previous_report_id": "old-report", "previous_run_id": "old-run", "original_mode": "SINGLE_ASSET_ANALYSIS"} if mode is RequestMode.REPORT_REFRESH else {}
                result = execute_mode(ModeRequest("synthetic", mode, payload), self.services_for(mode))
                self.assertEqual(Availability.COMPLETE, result.availability)
                self.assertEqual([step.value for step in FixedPipelinePlanner().plan(mode).steps],
                                 [state.step for state in result.step_states])
                if mode is RequestMode.ASSET_UPDATE:
                    self.assertEqual("POSTED", result.mutation_receipt["status"])
                else:
                    self.assertTrue(result.report_refs)

    def test_missing_handler_is_unsupported_and_partial_inputs_still_render_report(self) -> None:
        mode = RequestMode.SINGLE_ASSET_ANALYSIS
        plan = FixedPipelinePlanner().plan(mode)
        unsupported = execute_mode(ModeRequest("missing", mode), RuntimeServices())
        self.assertEqual(Availability.UNSUPPORTED, unsupported.availability)
        partial = execute_mode(ModeRequest("partial", mode), self.services_for(mode, partial_step=plan.steps[0]))
        self.assertEqual(Availability.PARTIAL, partial.availability)
        self.assertEqual(("synthetic_input",), partial.missing_inputs)
        self.assertTrue(partial.report_refs)

    def test_task_state_logger_records_steps_without_request_payload(self) -> None:
        class MemoryTaskLogger:
            run_id = "safe-run"
            rows = []
            def record_task_state(self, **values):
                self.rows.append(values)

        logger = MemoryTaskLogger()
        base = self.services_for(RequestMode.SINGLE_ASSET_ANALYSIS)
        result = execute_mode(ModeRequest("safe-run", RequestMode.SINGLE_ASSET_ANALYSIS,
            {"raw_request": "PRIVATE SYNTHETIC TEXT"}), RuntimeServices(base.handlers, run_db=logger))
        self.assertEqual(Availability.COMPLETE, result.availability)
        self.assertEqual(len(FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps), len(logger.rows))
        self.assertTrue(all("PRIVATE SYNTHETIC TEXT" not in str(row) for row in logger.rows))

    def test_router_questions_negations_and_order_commands_do_not_post(self) -> None:
        calls: list[str] = []
        services = self.services_for(RequestMode.SINGLE_ASSET_ANALYSIS)
        for text in ("매수해도 될지 분석해", "매수하지 말고 분석해"):
            result = execute_text_request(text, run_id="r", services=services, mode_hint=RequestMode.ASSET_UPDATE)
            self.assertEqual(Availability.UNSUPPORTED, result.availability)
            self.assertFalse(result.mutation_receipt)
        command = execute_text_request("FANUC 매수해", run_id="r", services=services)
        self.assertEqual(Availability.UNSUPPORTED, command.availability)
        self.assertFalse(calls)

    def test_scenario_and_refresh_replay_cannot_accept_mutation_receipts(self) -> None:
        for mode in (RequestMode.PORTFOLIO_SCENARIO, RequestMode.REPORT_REFRESH):
            with self.subTest(mode=mode):
                plan = FixedPipelinePlanner().plan(mode)
                handlers = {}
                for step in plan.steps:
                    if step is PipelineStep.RENDER_PARTIAL_AWARE_REPORT:
                        handlers[step] = lambda *_: StepResult(Availability.COMPLETE, report_refs=("report:safe",))
                    else:
                        handlers[step] = lambda *_: StepResult(Availability.COMPLETE, output={"safe": True},
                            mutation_receipt={"status": "POSTED", "transaction_ids": ["bad"], "state_version": 1})
                payload = {"previous_report_id": "old-report", "previous_run_id": "old-run", "original_mode": "SINGLE_ASSET_ANALYSIS"} if mode is RequestMode.REPORT_REFRESH else {}
                result = execute_mode(ModeRequest("safe", mode, payload), RuntimeServices(handlers))
                self.assertEqual(Availability.FAILED, result.availability)
                self.assertFalse(result.mutation_receipt)
        replay = execute_mode(ModeRequest("replay", RequestMode.REPORT_REFRESH,
            {"previous_report_id": "r", "previous_run_id": "p", "original_mode": "SINGLE_ASSET_ANALYSIS"}, refresh_replay=True),
            self.services_for(RequestMode.REPORT_REFRESH))
        self.assertEqual(Availability.UNSUPPORTED, replay.availability)

    def test_post_commit_projection_failure_keeps_receipt_and_blocks_composite_analysis(self) -> None:
        update_steps = FixedPipelinePlanner().plan(RequestMode.ASSET_UPDATE).steps
        analysis_steps = FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps
        called_analysis: list[bool] = []
        handlers = {}
        for step in update_steps:
            if step is PipelineStep.DECIDE_POSTING:
                handlers[step] = lambda *_: StepResult(Availability.COMPLETE, output={"posted": True},
                    mutation_receipt={"status": "POSTED", "transaction_ids": ["already-committed"], "state_version": 7})
            elif step is PipelineStep.PROJECT_PERSONAL_STATE:
                handlers[step] = lambda *_: StepResult(Availability.FAILED, output={"error_type": "synthetic"})
            else:
                handlers[step] = lambda *_: StepResult(Availability.COMPLETE, output={"ok": True})
        for step in analysis_steps:
            def analysis_handler(*_, current=step):
                called_analysis.append(True)
                if current is PipelineStep.RENDER_PARTIAL_AWARE_REPORT:
                    return StepResult(Availability.COMPLETE, report_refs=("report:synthetic",))
                return StepResult(Availability.COMPLETE, output={"ok": True})
            handlers[step] = analysis_handler
        services = RuntimeServices(handlers)
        update_result = execute_mode(ModeRequest("update", RequestMode.ASSET_UPDATE), services)
        self.assertEqual(Availability.FAILED, update_result.availability)
        self.assertEqual("POSTED", update_result.mutation_receipt["status"])
        combined = execute_update_then_analysis(
            ModeRequest("update-composite", RequestMode.ASSET_UPDATE),
            ModeRequest("analysis-composite", RequestMode.SINGLE_ASSET_ANALYSIS),
            services,
            requires_posted_update=True,
        )
        self.assertEqual(Availability.FAILED, combined.availability)
        self.assertEqual("POSTED", combined.update.mutation_receipt["status"])
        self.assertIsNone(combined.analysis)
        self.assertFalse(called_analysis)

        class FailingTaskLogger:
            run_id = "log-failure"
            def record_task_state(self, *, task_name, **_):
                if task_name.endswith(PipelineStep.DECIDE_POSTING.value):
                    raise OSError("synthetic run log failure")

        log_failure = execute_mode(ModeRequest("log-failure", RequestMode.ASSET_UPDATE),
            RuntimeServices({step: handlers[step] for step in update_steps}, run_db=FailingTaskLogger()))
        self.assertEqual(Availability.FAILED, log_failure.availability)
        self.assertEqual("POSTED", log_failure.mutation_receipt["status"])

    def test_unconfirmed_composite_update_waits_or_is_excluded_from_analysis(self) -> None:
        update_steps = FixedPipelinePlanner().plan(RequestMode.ASSET_UPDATE).steps
        analysis_steps = FixedPipelinePlanner().plan(RequestMode.SINGLE_ASSET_ANALYSIS).steps
        observed_payloads = []
        handlers = {}
        for step in update_steps:
            if step is PipelineStep.ASSESS_AMBIGUITY_AND_IMPACT:
                handlers[step] = lambda *_: StepResult(Availability.WAITING_CONFIRMATION, missing_inputs=("explicit_confirmation",))
            else:
                handlers[step] = lambda *_: StepResult(Availability.COMPLETE, output={"ok": True})
        for step in analysis_steps:
            def analysis_handler(request, _context, current=step):
                observed_payloads.append(dict(request.payload))
                if current is PipelineStep.RENDER_PARTIAL_AWARE_REPORT:
                    return StepResult(Availability.COMPLETE, report_refs=("report:composite",))
                return StepResult(Availability.COMPLETE, output={"ok": True})
            handlers[step] = analysis_handler
        services = RuntimeServices(handlers)
        update = ModeRequest("pending-update", RequestMode.ASSET_UPDATE)
        analysis = ModeRequest("new-analysis", RequestMode.SINGLE_ASSET_ANALYSIS)
        required = execute_update_then_analysis(update, analysis, services, requires_posted_update=True)
        self.assertEqual(Availability.WAITING_CONFIRMATION, required.availability)
        self.assertIsNone(required.analysis)
        self.assertFalse(observed_payloads)
        optional = execute_update_then_analysis(update, analysis, services, requires_posted_update=False)
        self.assertEqual(Availability.COMPLETE, optional.availability)
        self.assertTrue(optional.excluded_unconfirmed_update)
        self.assertTrue(observed_payloads[-1]["pending_update_excluded"])

    def test_asset_update_posts_atomically_retries_idempotently_and_waits_for_confirmation(self) -> None:
        with TemporaryDirectory() as temporary:
            manager = PersonalDatabaseManager(Path(temporary) / "personal.db", backup_directory=Path(temporary) / "backups")
            self.assertEqual("VALID", manager.initialize().status.value)
            ledger = PersonalLedgerService(manager)
            ledger.register_account("cash", name="Cash", currency="JPY", timezone_name="Asia/Tokyo")
            ledger.register_instrument("fanuc", canonical_name="FANUC", currency="JPY")
            ledger.post(TransactionIntent(TransactionType.DEPOSIT, account_id="cash", cash_amount="50000",
                currency="JPY", occurred_at=datetime(2026, 9, 27, 9), timezone="Asia/Tokyo",
                confirmation_state=ConfirmationState.CONFIRMED, idempotency_key="opening-cash"))
            confirmed = TransactionIntent(TransactionType.BUY, account_id="cash", instrument_id="fanuc",
                quantity="2", unit_price="6400", currency="JPY", occurred_at=datetime(2026, 9, 27, 10),
                timezone="Asia/Tokyo", confirmation_state=ConfirmationState.CONFIRMED, idempotency_key="buy-once")
            services = asset_update_services(ledger)
            request = ModeRequest("update-1", RequestMode.ASSET_UPDATE, {"transaction_intent": confirmed})
            before = ledger.get_current_state_version()
            first = execute_mode(request, services)
            after_post = ledger.get_current_state_version()
            self.assertEqual(Availability.COMPLETE, first.availability, first.as_dict())
            self.assertEqual("POSTED", first.mutation_receipt["status"])
            self.assertGreater(after_post, before)
            retry = execute_mode(ModeRequest("update-2", RequestMode.ASSET_UPDATE, {"transaction_intent": confirmed}), services)
            self.assertEqual(Availability.COMPLETE, retry.availability)
            self.assertEqual("ALREADY_POSTED", retry.mutation_receipt["status"])
            self.assertEqual(after_post, ledger.get_current_state_version())
            self.assertEqual(1, len([row for row in ledger.list_transactions(limit=100) if row.get("idempotency_key") == "buy-once"]))

            unconfirmed = TransactionIntent(TransactionType.BUY, account_id="cash", instrument_id="fanuc",
                quantity="1", unit_price="6000", currency="JPY", occurred_at=datetime(2026, 9, 27, 11),
                timezone="Asia/Tokyo", confirmation_state=ConfirmationState.UNCONFIRMED, idempotency_key="buy-awaiting")
            waiting = execute_mode(ModeRequest("update-3", RequestMode.ASSET_UPDATE, {"transaction_intent": unconfirmed}), services)
            self.assertEqual(Availability.WAITING_CONFIRMATION, waiting.availability)
            self.assertFalse(waiting.mutation_receipt)
            self.assertEqual(after_post, ledger.get_current_state_version())


if __name__ == "__main__":
    unittest.main()
