"""ASSET_UPDATE handlers backed by the existing append-only personal ledger."""

from __future__ import annotations

from types import MappingProxyType

from investment_stack.pipelines import PipelineStep
from investment_stack.personal.errors import DuplicateTransactionError
from investment_stack.personal.intent import (
    ConfirmationState,
    IntentState,
    TransactionIntent,
    transaction_fingerprint,
)
from investment_stack.personal.interpretation import parse_transaction_request
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.evidence import RunDatabaseManager

from .dispatcher import RuntimeServices
from .models import Availability, ModeRequest, StepContext, StepResult


def asset_update_services(
    ledger: PersonalLedgerService, *, run_db: RunDatabaseManager | None = None
) -> RuntimeServices:
    """Register only fixed asset-update steps; no analysis mode receives a writer."""

    def extract(request: ModeRequest, _context: StepContext) -> StepResult:
        intent = request.payload.get("transaction_intent")
        if not isinstance(intent, TransactionIntent):
            raw_request = request.payload.get("raw_request")
            if not isinstance(raw_request, str) or not raw_request.strip():
                return StepResult(Availability.PARTIAL, missing_inputs=("completed_transaction_fact",))
            try:
                intent = parse_transaction_request(
                    raw_request,
                    account_id=request.payload.get("account_id"),
                    instrument_id=request.payload.get("instrument_id"),
                    occurred_at=request.payload.get("occurred_at"),
                    timezone_name=request.payload.get("timezone"),
                    currency=request.payload.get("currency"),
                )
            except (TypeError, ValueError):
                return StepResult(
                    Availability.UNSUPPORTED,
                    unsupported_reasons=("request does not contain a supported completed transaction fact",),
                )
        return StepResult(Availability.COMPLETE, output={"intent": intent})

    def validate_time(_request: ModeRequest, context: StepContext) -> StepResult:
        intent = context[PipelineStep.EXTRACT_TRANSACTION_INTENT.value].output.get("intent")
        if not isinstance(intent, TransactionIntent):
            return StepResult(Availability.WAITING_CONFIRMATION, missing_inputs=("typed_transaction_intent",))
        try:
            decision = ledger.validate_intent(intent)
        except Exception as exc:
            return StepResult(
                Availability.FAILED,
                output={"error_type": type(exc).__name__},
                missing_inputs=("personal_ledger_validation",),
            )
        canonical = decision.intent
        missing_time = tuple(name for name in ("occurred_at", "timezone") if getattr(canonical, name) is None)
        if missing_time:
            return StepResult(
                Availability.WAITING_CONFIRMATION,
                output={"intent": canonical},
                missing_inputs=missing_time,
            )
        return StepResult(Availability.COMPLETE, output={"intent": canonical})

    def assess(_request: ModeRequest, context: StepContext) -> StepResult:
        intent = context[PipelineStep.VALIDATE_EVENT_TIME.value].output.get("intent")
        if not isinstance(intent, TransactionIntent):
            return StepResult(Availability.WAITING_CONFIRMATION, missing_inputs=("typed_transaction_intent",))
        try:
            decision = ledger.validate_intent(intent)
        except Exception as exc:
            return StepResult(
                Availability.FAILED,
                output={"error_type": type(exc).__name__},
                missing_inputs=("personal_ledger_validation",),
            )
        if decision.state is IntentState.UNSUPPORTED:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=decision.reasons or ("transaction type is unsupported",))
        if decision.state is IntentState.REJECTED:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=decision.reasons or ("transaction intent is invalid",))
        missing = tuple(dict.fromkeys((*decision.missing_fields, *decision.reasons)))
        if decision.state is IntentState.NEEDS_CONFIRMATION:
            return StepResult(
                Availability.WAITING_CONFIRMATION,
                output={"intent": decision.intent},
                missing_inputs=missing or ("transaction_confirmation",),
            )
        if decision.intent.confirmation_state is not ConfirmationState.CONFIRMED:
            return StepResult(
                Availability.WAITING_CONFIRMATION,
                output={"intent": decision.intent},
                missing_inputs=("explicit_transaction_confirmation",),
            )
        if not decision.intent.idempotency_key:
            return StepResult(
                Availability.WAITING_CONFIRMATION,
                output={"intent": decision.intent},
                missing_inputs=("idempotency_key",),
            )
        return StepResult(Availability.COMPLETE, output={"intent": decision.intent})

    def decide(request: ModeRequest, context: StepContext) -> StepResult:
        assessment = context[PipelineStep.ASSESS_AMBIGUITY_AND_IMPACT.value]
        intent = assessment.output.get("intent")
        if not isinstance(intent, TransactionIntent) or assessment.availability is not Availability.COMPLETE:
            return StepResult(Availability.WAITING_CONFIRMATION, missing_inputs=("validated_transaction_intent",))
        try:
            result = ledger.post(intent)
            receipt = {
                "status": "POSTED",
                "transaction_ids": list(result.transaction_ids),
                "state_version": result.state_version,
                "idempotency_key": intent.idempotency_key,
            }
        except DuplicateTransactionError:
            existing = next(
                (row for row in ledger.list_transactions(limit=10_000)
                 if row.get("idempotency_key") == intent.idempotency_key),
                None,
            )
            if existing is None or existing.get("fingerprint") != transaction_fingerprint(intent):
                return StepResult(
                    Availability.UNSUPPORTED,
                    unsupported_reasons=("idempotency key conflicts with a different or unavailable transaction",),
                )
            receipt = {
                "status": "ALREADY_POSTED",
                "transaction_ids": [existing["transaction_id"]],
                "state_version": int(existing["state_version"]),
                "idempotency_key": intent.idempotency_key,
            }
        return StepResult(Availability.COMPLETE, output={"posted": True}, mutation_receipt=receipt)

    def project(_request: ModeRequest, context: StepContext) -> StepResult:
        receipt = next(
            (step_result.mutation_receipt for step_result in context.values() if step_result.mutation_receipt),
            None,
        )
        if receipt is None:
            return StepResult(Availability.UNSUPPORTED, unsupported_reasons=("atomic posting receipt is missing",))
        version = int(receipt["state_version"])
        current = ledger.get_current_state_version()
        if version > current:
            return StepResult(Availability.FAILED, output={"receipt_state_version": version}, missing_inputs=("committed_state_version",))
        projection = ledger.get_projection_as_of_state_version(version)
        return StepResult(
            Availability.COMPLETE,
            output={
                "state_version": version,
                "positions_count": len(projection.positions),
                "cash_balances_count": len(projection.cash_balances),
                "trade_context": "13F scores are not order conditions",
            },
        )

    def advance(_request: ModeRequest, context: StepContext) -> StepResult:
        projected = context[PipelineStep.PROJECT_PERSONAL_STATE.value].output
        version = projected.get("state_version")
        if not isinstance(version, int) or version > ledger.get_current_state_version():
            return StepResult(Availability.FAILED, output={"version_checked": version}, missing_inputs=("committed_state_version",))
        return StepResult(Availability.COMPLETE, output={"state_version_verified": version})

    return RuntimeServices(
        handlers=MappingProxyType({
            PipelineStep.EXTRACT_TRANSACTION_INTENT: extract,
            PipelineStep.VALIDATE_EVENT_TIME: validate_time,
            PipelineStep.ASSESS_AMBIGUITY_AND_IMPACT: assess,
            PipelineStep.DECIDE_POSTING: decide,
            PipelineStep.PROJECT_PERSONAL_STATE: project,
            PipelineStep.ADVANCE_STATE_VERSION: advance,
        }),
        run_db=run_db,
    )
