"""Append-only personal ledger, guarded posting, and deterministic queries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from investment_stack.personal.decimal import (
    ZERO,
    DecimalInput,
    decode_decimal,
    encode_decimal,
    exact_decimal,
)
from investment_stack.personal.errors import (
    ConfirmationRequired,
    DuplicateTransactionError,
    IntentValidationError,
    LedgerError,
    PostingError,
    ProjectionError,
    ReversalError,
    UnsupportedTransactionError,
)
from investment_stack.personal.intent import (
    ConfirmationState,
    CostBasisStatus,
    IntentState,
    IntentValidationContext,
    OpeningBalanceKind,
    TransactionIntent,
    TransactionType,
    evaluate_intent,
    resolve_timezone,
    transaction_fingerprint,
)
from investment_stack.personal.manager import PersonalDatabaseManager, StorageNotWritableError
from investment_stack.personal.projection import (
    ProjectionState,
    VerifiedPortfolioSnapshotProjection,
    compute_projection,
    replace_projection,
)
from investment_stack.personal.reserves import (
    RESERVATION_KINDS,
    CashReservation,
    CashReservationDraft,
)
from investment_stack.personal.validation import (
    validate_personal_connection,
    validate_personal_database,
)
from investment_stack.storage.sqlite import sqlite_readonly_connection


PostingHook = Callable[[str, sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_type: str
    account_id: str | None = None
    instrument_id: str | None = None
    liability_id: str | None = None
    quantity_delta: Decimal | None = None
    amount_delta: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    cost_basis_delta: Decimal | None = None
    cost_basis_status: CostBasisStatus | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PostingResult:
    transaction_ids: tuple[str, ...]
    state_version: int
    projection: ProjectionState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_decimal(row: sqlite3.Row | None, name: str) -> Decimal | None:
    return None if row is None else decode_decimal(row[name])


class PersonalLedgerService:
    """The only supported Phase 3 personal ledger mutation service."""

    def __init__(
        self,
        manager: PersonalDatabaseManager,
        *,
        user_default_timezone: str | None = None,
        high_impact_threshold: DecimalInput | None = None,
    ) -> None:
        self.manager = manager
        self.user_default_timezone = user_default_timezone
        self.high_impact_threshold = exact_decimal(
            high_impact_threshold, field="high_impact_threshold"
        )
        if self.high_impact_threshold is not None and self.high_impact_threshold <= ZERO:
            raise ValueError("high_impact_threshold must be greater than zero")

    def register_account(
        self,
        account_id: str,
        *,
        name: str,
        account_type: str = "BROKERAGE",
        currency: str | None = None,
        timezone_name: str | None = None,
    ) -> None:
        try:
            with self.manager.guarded_write_transaction() as connection:
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, name, account_type, currency, status, created_at, timezone) "
                    "VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)",
                    (account_id, name, account_type, currency, _now(), timezone_name),
                )
        except (sqlite3.Error, StorageNotWritableError) as exc:
            raise PostingError(f"account registration failed: {exc}") from exc

    def register_instrument(
        self,
        instrument_id: str,
        *,
        canonical_name: str,
        asset_class: str = "EQUITY",
        currency: str | None = None,
        identifiers: dict | None = None,
    ) -> None:
        if identifiers is not None:
            from investment_stack.providers.instruments import InstrumentResolver
            row = {"instrument_id": instrument_id, "canonical_name": canonical_name,
                   "asset_class": asset_class, "currency": currency,
                   "identifiers_json": json.dumps(identifiers)}
            InstrumentResolver((row,)).resolve(instrument_id)
        try:
            with self.manager.guarded_write_transaction() as connection:
                connection.execute(
                    "INSERT INTO instruments "
                    "(instrument_id, canonical_name, asset_class, currency, identifiers_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (instrument_id, canonical_name, asset_class, currency, json.dumps(identifiers) if identifiers is not None else None, _now()),
                )
        except (sqlite3.Error, StorageNotWritableError) as exc:
            raise PostingError(f"instrument registration failed: {exc}") from exc

    @staticmethod
    def _current_state_version(connection: sqlite3.Connection) -> int:
        return int(
            connection.execute("SELECT MAX(state_version) FROM state_versions").fetchone()[0]
        )

    def _canonical_posting_state(
        self, connection: sqlite3.Connection, intent: TransactionIntent
    ) -> tuple[TransactionIntent, IntentValidationContext, str]:
        account_ids = [
            value
            for value in (
                intent.account_id,
                intent.source_account_id,
                intent.destination_account_id,
            )
            if value is not None
        ]
        account_exists = True
        account_timezone: str | None = None
        if account_ids:
            placeholders = ",".join("?" for _ in account_ids)
            rows = connection.execute(
                f"SELECT account_id, timezone FROM accounts WHERE account_id IN ({placeholders})",
                tuple(account_ids),
            ).fetchall()
            account_exists = len({str(row["account_id"]) for row in rows}) == len(
                set(account_ids)
            )
            zones = {str(row["timezone"]) for row in rows if row["timezone"]}
            if len(zones) == 1:
                account_timezone = zones.pop()
        instrument_exists = True
        if intent.instrument_id is not None:
            instrument_exists = (
                connection.execute(
                    "SELECT 1 FROM instruments WHERE instrument_id = ?",
                    (intent.instrument_id,),
                ).fetchone()
                is not None
            )
        amounts = [
            value
            for value in (
                intent.cash_amount,
                intent.gross_amount,
                intent.source_amount,
                intent.target_amount,
                intent.principal_amount,
                intent.total_cost,
            )
            if value is not None
        ]
        if intent.quantity is not None and intent.unit_price is not None:
            amounts.append(intent.quantity * intent.unit_price)
        high_impact = bool(
            self.high_impact_threshold is not None
            and amounts
            and max(abs(value) for value in amounts) > self.high_impact_threshold
        )
        canonical = resolve_timezone(
            intent,
            IntentValidationContext(
                account_timezone=account_timezone,
                user_default_timezone=self.user_default_timezone,
            ),
        )
        fingerprint = transaction_fingerprint(canonical)
        duplicate = (
            connection.execute(
                "SELECT 1 FROM transactions WHERE fingerprint = ? AND status = 'POSTED'",
                (fingerprint,),
            ).fetchone()
            is not None
        )
        context = IntentValidationContext(
            account_timezone=account_timezone,
            user_default_timezone=self.user_default_timezone,
            account_exists=account_exists,
            instrument_exists=instrument_exists,
            duplicate_suspected=duplicate,
            high_impact=high_impact,
        )
        return canonical, context, fingerprint

    def validate_intent(self, intent: TransactionIntent):
        try:
            report = validate_personal_database(self.manager.database_path)
            if not report.valid:
                raise PostingError("personal database is not valid")
            with sqlite_readonly_connection(self.manager.database_path) as connection:
                canonical, context, _fingerprint = self._canonical_posting_state(
                    connection, intent
                )
                return evaluate_intent(canonical, context=context)
        except LedgerError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise PostingError(f"intent validation failed: {exc}") from exc

    @staticmethod
    def _require_ready(
        intent: TransactionIntent, context: IntentValidationContext
    ) -> TransactionIntent:
        decision = evaluate_intent(intent, context=context)
        if decision.state is IntentState.UNSUPPORTED:
            raise UnsupportedTransactionError("; ".join(decision.reasons))
        if decision.state is IntentState.NEEDS_CONFIRMATION:
            details = ", ".join((*decision.missing_fields, *decision.reasons))
            raise ConfirmationRequired(details or "transaction requires confirmation")
        if decision.state is not IntentState.READY_TO_POST:
            details = ", ".join((*decision.missing_fields, *decision.reasons))
            raise IntentValidationError(details or "transaction intent is invalid")
        return decision.intent

    @staticmethod
    def _find_position(state: ProjectionState, account: str, instrument: str):
        return next(
            (
                item
                for item in state.positions
                if item.account_id == account and item.instrument_id == instrument
            ),
            None,
        )

    @staticmethod
    def _derive_entries(
        connection: sqlite3.Connection,
        intent: TransactionIntent,
        state: ProjectionState,
    ) -> tuple[LedgerEntry, ...]:
        tx = intent.transaction_type
        fee = intent.fee_amount or ZERO
        tax = intent.tax_amount or ZERO
        entries: list[LedgerEntry] = []
        if tx in {TransactionType.BUY, TransactionType.SELL}:
            assert intent.account_id and intent.instrument_id and intent.quantity
            assert intent.unit_price is not None and intent.currency
            gross = intent.gross_amount or intent.quantity * intent.unit_price
            position = PersonalLedgerService._find_position(
                state, intent.account_id, intent.instrument_id
            )
            if tx is TransactionType.BUY:
                cash = intent.cash_amount or gross + fee + tax
                if cash != gross + fee + tax:
                    raise IntentValidationError("BUY cash amount does not match price, fee, and tax")
                status = (
                    CostBasisStatus.UNAVAILABLE
                    if position and position.cost_basis_status is CostBasisStatus.UNAVAILABLE
                    else CostBasisStatus.WEIGHTED_AVERAGE
                )
                entries.extend(
                    (
                        LedgerEntry(
                            "ASSET",
                            intent.account_id,
                            intent.instrument_id,
                            quantity_delta=intent.quantity,
                            currency=intent.currency,
                            unit=intent.unit or "SHARE",
                            cost_basis_delta=None if status is CostBasisStatus.UNAVAILABLE else gross + fee,
                            cost_basis_status=status,
                        ),
                        LedgerEntry("CASH", intent.account_id, amount_delta=-cash, currency=intent.currency),
                    )
                )
            else:
                if position is None or position.quantity < intent.quantity:
                    raise ProjectionError("SELL exceeds current holdings")
                gross = intent.gross_amount or intent.quantity * intent.unit_price
                cash = intent.cash_amount or gross - fee - tax
                if cash != gross - fee - tax or cash < ZERO:
                    raise IntentValidationError("SELL cash amount does not match price, fee, and tax")
                cost_delta = (
                    None
                    if position.average_unit_cost is None
                    else -(position.average_unit_cost * intent.quantity)
                )
                entries.extend(
                    (
                        LedgerEntry(
                            "ASSET",
                            intent.account_id,
                            intent.instrument_id,
                            quantity_delta=-intent.quantity,
                            currency=intent.currency,
                            unit=intent.unit or "SHARE",
                            cost_basis_delta=cost_delta,
                            cost_basis_status=position.cost_basis_status,
                        ),
                        LedgerEntry("CASH", intent.account_id, amount_delta=cash, currency=intent.currency),
                    )
                )
            if fee:
                entries.append(
                    LedgerEntry(
                        "CASHFLOW",
                        intent.account_id,
                        amount_delta=fee,
                        currency=intent.currency,
                        metadata={"category": "EXPENSE", "kind": "FEE"},
                    )
                )
            if tax:
                entries.append(
                    LedgerEntry(
                        "CASHFLOW",
                        intent.account_id,
                        amount_delta=tax,
                        currency=intent.currency,
                        metadata={"category": "EXPENSE", "kind": "TAX"},
                    )
                )
        elif tx in {TransactionType.DEPOSIT, TransactionType.WITHDRAWAL}:
            assert intent.account_id and intent.cash_amount and intent.currency
            sign = Decimal(1) if tx is TransactionType.DEPOSIT else Decimal(-1)
            entries.extend(
                (
                    LedgerEntry("CASH", intent.account_id, amount_delta=sign * intent.cash_amount, currency=intent.currency),
                    LedgerEntry(
                        "CASHFLOW",
                        intent.account_id,
                        amount_delta=sign * intent.cash_amount,
                        currency=intent.currency,
                        metadata={"category": "CAPITAL"},
                    ),
                )
            )
        elif tx is TransactionType.TRANSFER:
            assert intent.source_account_id and intent.destination_account_id
            assert intent.cash_amount and intent.currency
            if intent.source_account_id == intent.destination_account_id:
                raise IntentValidationError("TRANSFER accounts must differ")
            entries.extend(
                (
                    LedgerEntry("CASH", intent.source_account_id, amount_delta=-intent.cash_amount, currency=intent.currency),
                    LedgerEntry("CASH", intent.destination_account_id, amount_delta=intent.cash_amount, currency=intent.currency),
                    LedgerEntry("CASHFLOW", intent.source_account_id, amount_delta=-intent.cash_amount, currency=intent.currency, metadata={"category": "TRANSFER"}),
                    LedgerEntry("CASHFLOW", intent.destination_account_id, amount_delta=intent.cash_amount, currency=intent.currency, metadata={"category": "TRANSFER"}),
                )
            )
        elif tx in {TransactionType.DIVIDEND, TransactionType.INTEREST, TransactionType.FEE}:
            assert intent.account_id and intent.cash_amount and intent.currency
            direction = "INCOME"
            if tx is TransactionType.FEE:
                direction = "EXPENSE"
            elif tx is TransactionType.INTEREST:
                direction = str(intent.ambiguity_metadata["interest_direction"])
            sign = Decimal(1) if direction == "INCOME" else Decimal(-1)
            entries.extend(
                (
                    LedgerEntry("CASH", intent.account_id, amount_delta=sign * intent.cash_amount, currency=intent.currency),
                    LedgerEntry("CASHFLOW", intent.account_id, amount_delta=intent.cash_amount, currency=intent.currency, metadata={"category": direction}),
                )
            )
        elif tx in {TransactionType.FX_BUY, TransactionType.FX_SELL}:
            assert intent.account_id and intent.source_amount and intent.target_amount
            assert intent.source_currency and intent.target_currency and intent.fx_rate
            if intent.source_currency == intent.target_currency:
                raise IntentValidationError("FX currencies must differ")
            if intent.target_amount != intent.source_amount * intent.fx_rate:
                raise IntentValidationError("FX amounts do not match the supplied rate")
            entries.extend(
                (
                    LedgerEntry("CASH", intent.account_id, amount_delta=-intent.source_amount, currency=intent.source_currency),
                    LedgerEntry("CASH", intent.account_id, amount_delta=intent.target_amount, currency=intent.target_currency),
                )
            )
        elif tx is TransactionType.LOAN_DRAW:
            assert intent.account_id and intent.liability_id and intent.principal_amount and intent.currency
            entries.extend(
                (
                    LedgerEntry("CASH", intent.account_id, amount_delta=intent.principal_amount, currency=intent.currency),
                    LedgerEntry("LIABILITY", intent.account_id, liability_id=intent.liability_id, amount_delta=intent.principal_amount, currency=intent.currency),
                    LedgerEntry("CASHFLOW", intent.account_id, amount_delta=intent.principal_amount, currency=intent.currency, metadata={"category": "FINANCING"}),
                )
            )
        elif tx is TransactionType.LOAN_PAYMENT:
            assert intent.account_id and intent.liability_id
            assert intent.principal_amount is not None and intent.interest_amount is not None
            assert intent.currency
            total = intent.principal_amount + intent.interest_amount
            entries.extend(
                (
                    LedgerEntry("CASH", intent.account_id, amount_delta=-total, currency=intent.currency),
                    LedgerEntry("LIABILITY", intent.account_id, liability_id=intent.liability_id, amount_delta=-intent.principal_amount, currency=intent.currency),
                    LedgerEntry("CASHFLOW", intent.account_id, amount_delta=-intent.principal_amount, currency=intent.currency, metadata={"category": "FINANCING"}),
                    LedgerEntry("CASHFLOW", intent.account_id, amount_delta=intent.interest_amount, currency=intent.currency, metadata={"category": "EXPENSE", "kind": "INTEREST"}),
                )
            )
        elif tx is TransactionType.OPENING_BALANCE:
            assert intent.account_id and intent.cash_amount and intent.currency
            if intent.opening_balance_kind is OpeningBalanceKind.CASH:
                entries.append(LedgerEntry("CASH", intent.account_id, amount_delta=intent.cash_amount, currency=intent.currency))
            else:
                assert intent.liability_id
                entries.append(LedgerEntry("LIABILITY", intent.account_id, liability_id=intent.liability_id, amount_delta=intent.cash_amount, currency=intent.currency))
        elif tx is TransactionType.INITIAL_POSITION:
            assert intent.account_id and intent.instrument_id and intent.quantity
            assert intent.cost_basis_status is not None
            total_cost = intent.total_cost
            if total_cost is None and intent.average_unit_cost is not None:
                total_cost = intent.average_unit_cost * intent.quantity
            entries.append(
                LedgerEntry(
                    "ASSET",
                    intent.account_id,
                    intent.instrument_id,
                    quantity_delta=intent.quantity,
                    currency=intent.currency,
                    unit=intent.unit,
                    cost_basis_delta=total_cost,
                    cost_basis_status=intent.cost_basis_status,
                )
            )
        elif tx is TransactionType.ASSET_ADJUSTMENT:
            assert intent.account_id and intent.instrument_id and intent.quantity
            entries.append(
                LedgerEntry(
                    "ASSET",
                    intent.account_id,
                    intent.instrument_id,
                    quantity_delta=intent.quantity,
                    currency=intent.currency,
                    unit=intent.unit,
                    cost_basis_status=CostBasisStatus.UNAVAILABLE,
                )
            )
        elif tx in {TransactionType.SPLIT, TransactionType.REVERSE_SPLIT}:
            assert intent.account_id and intent.instrument_id
            assert intent.split_numerator and intent.split_denominator
            position = PersonalLedgerService._find_position(state, intent.account_id, intent.instrument_id)
            if position is None:
                raise ProjectionError("split target position does not exist")
            new_quantity = position.quantity * intent.split_numerator / intent.split_denominator
            entries.append(
                LedgerEntry(
                    "ASSET",
                    intent.account_id,
                    intent.instrument_id,
                    quantity_delta=new_quantity - position.quantity,
                    currency=position.currency,
                    unit=intent.unit or "SHARE",
                    cost_basis_delta=ZERO if position.total_cost is not None else None,
                    cost_basis_status=position.cost_basis_status,
                    metadata={"ratio": f"{intent.split_numerator}:{intent.split_denominator}"},
                )
            )
        elif tx is TransactionType.TICKER_CHANGE:
            assert intent.instrument_id and intent.new_ticker
            entries.append(LedgerEntry("ALIAS", instrument_id=intent.instrument_id, metadata={"ticker": intent.new_ticker}))
        else:
            raise UnsupportedTransactionError(f"direct derivation is unsupported for {tx.value}")
        return tuple(entries)

    @staticmethod
    def _reversal_entries(
        connection: sqlite3.Connection, target_transaction_id: str
    ) -> tuple[LedgerEntry, ...]:
        target = connection.execute(
            "SELECT transaction_type FROM transactions WHERE transaction_id = ? AND status = 'POSTED'",
            (target_transaction_id,),
        ).fetchone()
        if target is None:
            raise ReversalError("reversal target does not exist")
        if target["transaction_type"] == TransactionType.REVERSAL.value:
            raise ReversalError("reversal of a reversal is not supported")
        if connection.execute(
            "SELECT 1 FROM transactions WHERE reversal_of = ? AND status = 'POSTED'",
            (target_transaction_id,),
        ).fetchone():
            raise ReversalError("transaction has already been reversed")
        rows = connection.execute(
            "SELECT * FROM transaction_entries WHERE transaction_id = ? ORDER BY entry_sequence",
            (target_transaction_id,),
        ).fetchall()
        if not rows:
            raise ReversalError("reversal target has no entries")
        result: list[LedgerEntry] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            if str(row["entry_type"]) == "ALIAS":
                metadata["reversed"] = True
            result.append(
                LedgerEntry(
                    str(row["entry_type"]),
                    None if row["account_id"] is None else str(row["account_id"]),
                    None if row["instrument_id"] is None else str(row["instrument_id"]),
                    None
                    if row["liability_reference"] is None
                    else str(row["liability_reference"]),
                    None if row["quantity_delta_decimal"] is None else -decode_decimal(row["quantity_delta_decimal"]),
                    None if row["amount_delta_decimal"] is None else -decode_decimal(row["amount_delta_decimal"]),
                    None if row["currency"] is None else str(row["currency"]),
                    None if row["unit"] is None else str(row["unit"]),
                    None if row["cost_basis_delta_decimal"] is None else -decode_decimal(row["cost_basis_delta_decimal"]),
                    None if row["cost_basis_status"] is None else CostBasisStatus(str(row["cost_basis_status"])),
                    metadata,
                )
            )
        return tuple(result)

    @staticmethod
    def _insert_state_version(
        connection: sqlite3.Connection, version: int, reason: str, metadata: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO state_versions (state_version, created_at, reason, metadata_json) "
            "VALUES (?, ?, ?, ?)",
            (version, _now(), reason, json.dumps(metadata, sort_keys=True)),
        )

    @staticmethod
    def _insert_transaction(
        connection: sqlite3.Connection,
        intent: TransactionIntent,
        *,
        transaction_id: str,
        state_version: int,
        fingerprint: str,
        operation_sequence: int = 0,
    ) -> None:
        connection.execute(
            "INSERT INTO transactions "
            "(transaction_id, status, occurred_at, occurred_timezone, posted_at, "
            "transaction_type, account_id, instrument_id, currency, related_liability_id, "
            "source, note, reversal_of, idempotency_key, state_version, operation_sequence, "
            "created_at, "
            "correction_of, intent_id, source_account_id, destination_account_id, "
            "external_reference, replacement_for_transaction_id, fingerprint, "
            "confirmation_state, metadata_json, quantity_decimal, unit_price_decimal, "
            "gross_amount_decimal, fee_amount_decimal, tax_amount_decimal, "
            "cash_amount_decimal, fx_rate_decimal) "
            "VALUES (?, 'POSTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                transaction_id,
                intent.occurred_at.isoformat() if intent.occurred_at else None,
                intent.timezone,
                _now(),
                intent.transaction_type.value,
                intent.account_id,
                intent.instrument_id,
                intent.currency,
                None,
                "phase3-ledger",
                intent.notes,
                intent.reversal_of_transaction_id,
                intent.idempotency_key,
                state_version,
                operation_sequence,
                _now(),
                intent.replacement_for_transaction_id,
                intent.intent_id,
                intent.source_account_id,
                intent.destination_account_id,
                intent.external_reference,
                intent.replacement_for_transaction_id,
                fingerprint,
                intent.confirmation_state.value,
                json.dumps(
                    {**dict(intent.ambiguity_metadata), "liability_id": intent.liability_id},
                    sort_keys=True,
                ),
                encode_decimal(intent.quantity),
                encode_decimal(intent.unit_price),
                encode_decimal(intent.gross_amount),
                encode_decimal(intent.fee_amount),
                encode_decimal(intent.tax_amount),
                encode_decimal(intent.cash_amount),
                encode_decimal(intent.fx_rate),
            ),
        )

    @staticmethod
    def _insert_entries(
        connection: sqlite3.Connection,
        entries: Iterable[LedgerEntry],
        *,
        transaction_id: str,
        state_version: int,
        hook: PostingHook | None = None,
    ) -> None:
        for sequence, entry in enumerate(entries):
            entry_id = f"{transaction_id}:{sequence:03d}"
            connection.execute(
                "INSERT INTO transaction_entries "
                "(entry_id, transaction_id, account_id, instrument_id, liability_id, liability_reference, "
                "entry_type, quantity_delta, amount_delta, currency, created_at, "
                "entry_sequence, unit, quantity_delta_decimal, amount_delta_decimal, "
                "cost_basis_delta_decimal, cost_basis_status, state_version, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    transaction_id,
                    entry.account_id,
                    entry.instrument_id,
                    None,
                    entry.liability_id,
                    entry.entry_type,
                    encode_decimal(entry.quantity_delta),
                    encode_decimal(entry.amount_delta),
                    entry.currency,
                    _now(),
                    sequence,
                    entry.unit,
                    encode_decimal(entry.quantity_delta),
                    encode_decimal(entry.amount_delta),
                    encode_decimal(entry.cost_basis_delta),
                    entry.cost_basis_status.value if entry.cost_basis_status else None,
                    state_version,
                    json.dumps(entry.metadata or {}, sort_keys=True),
                ),
            )
            if hook is not None and sequence == 0:
                hook("entry_inserted", connection)
            if entry.entry_type == "ALIAS" and not (entry.metadata or {}).get("reversed"):
                ticker = str((entry.metadata or {})["ticker"])
                connection.execute(
                    "INSERT INTO instrument_aliases "
                    "(alias_id, instrument_id, alias, provider, created_at) VALUES (?, ?, ?, 'ledger', ?)",
                    (uuid4().hex, entry.instrument_id, ticker, _now()),
                )

    @staticmethod
    def _check_idempotency(connection: sqlite3.Connection, intent: TransactionIntent) -> None:
        if intent.idempotency_key and connection.execute(
            "SELECT 1 FROM transactions WHERE idempotency_key = ?",
            (intent.idempotency_key,),
        ).fetchone():
            raise DuplicateTransactionError("idempotency key has already been posted")

    def post(
        self,
        intent: TransactionIntent,
        *,
        expected_state_version: int | None = None,
        hook: PostingHook | None = None,
    ) -> PostingResult:
        try:
            with self.manager.guarded_write_transaction() as connection:
                self._check_idempotency(connection, intent)
                canonical, context, fingerprint = self._canonical_posting_state(
                    connection, intent
                )
                normalized = self._require_ready(canonical, context)
                current = self._current_state_version(connection)
                if expected_state_version is not None and current != expected_state_version:
                    raise PostingError("state_version conflict")
                before = compute_projection(connection, target_state_version=current)
                entries = self._derive_entries(connection, normalized, before)
                next_version = current + 1
                self._insert_state_version(
                    connection,
                    next_version,
                    "ledger-post",
                    {"intent_id": normalized.intent_id},
                )
                if hook:
                    hook("state_version_inserted", connection)
                transaction_id = uuid4().hex
                self._insert_transaction(
                    connection,
                    normalized,
                    transaction_id=transaction_id,
                    state_version=next_version,
                    fingerprint=fingerprint,
                    operation_sequence=0,
                )
                if hook:
                    hook("transaction_inserted", connection)
                self._insert_entries(
                    connection,
                    entries,
                    transaction_id=transaction_id,
                    state_version=next_version,
                    hook=hook,
                )
                if hook:
                    hook("entries_inserted", connection)
                projection = compute_projection(
                    connection, target_state_version=next_version
                )
                replace_projection(connection, projection)
                if hook:
                    hook("projection_replaced", connection)
                return PostingResult((transaction_id,), next_version, projection)
        except LedgerError:
            raise
        except (sqlite3.Error, StorageNotWritableError, RuntimeError, ValueError) as exc:
            raise PostingError(f"atomic posting failed: {exc}") from exc

    def reverse(
        self,
        transaction_id: str,
        *,
        occurred_at: datetime,
        timezone_name: str,
        idempotency_key: str | None = None,
        hook: PostingHook | None = None,
    ) -> PostingResult:
        intent = TransactionIntent(
            TransactionType.REVERSAL,
            occurred_at=occurred_at,
            timezone=timezone_name,
            reversal_of_transaction_id=transaction_id,
            idempotency_key=idempotency_key,
            confirmation_state=ConfirmationState.CONFIRMED,
        )
        try:
            with self.manager.guarded_write_transaction() as connection:
                intent = self._require_ready(intent, IntentValidationContext())
                self._check_idempotency(connection, intent)
                current = self._current_state_version(connection)
                entries = self._reversal_entries(connection, transaction_id)
                next_version = current + 1
                self._insert_state_version(connection, next_version, "ledger-reversal", {"target": transaction_id})
                reversal_id = uuid4().hex
                self._insert_transaction(
                    connection,
                    intent,
                    transaction_id=reversal_id,
                    state_version=next_version,
                    fingerprint=transaction_fingerprint(intent),
                )
                self._insert_entries(connection, entries, transaction_id=reversal_id, state_version=next_version, hook=hook)
                projection = compute_projection(connection, target_state_version=next_version)
                replace_projection(connection, projection)
                if hook:
                    hook("projection_replaced", connection)
                return PostingResult((reversal_id,), next_version, projection)
        except LedgerError:
            raise
        except (sqlite3.Error, StorageNotWritableError, RuntimeError, ValueError) as exc:
            raise PostingError(f"atomic reversal failed: {exc}") from exc

    def correct(
        self,
        original_transaction_id: str,
        replacement_intent: TransactionIntent,
        *,
        reason: str,
        occurred_at: datetime,
        timezone_name: str,
        hook: PostingHook | None = None,
    ) -> PostingResult:
        if replacement_intent.transaction_type is TransactionType.REVERSAL:
            raise IntentValidationError("replacement must be a complete economic transaction")
        correction_id = uuid4().hex
        reversal_intent = TransactionIntent(
            TransactionType.REVERSAL,
            occurred_at=occurred_at,
            timezone=timezone_name,
            reversal_of_transaction_id=original_transaction_id,
            notes=reason,
            confirmation_state=ConfirmationState.CONFIRMED,
        )
        replacement_intent = replace(
            replacement_intent,
            replacement_for_transaction_id=original_transaction_id,
            confirmation_state=ConfirmationState.CONFIRMED,
        )
        try:
            with self.manager.guarded_write_transaction() as connection:
                reversal_intent = self._require_ready(
                    reversal_intent, IntentValidationContext()
                )
                canonical, context, fingerprint = self._canonical_posting_state(
                    connection, replacement_intent
                )
                normalized = self._require_ready(canonical, context)
                self._check_idempotency(connection, normalized)
                current = self._current_state_version(connection)
                reversal_entries = self._reversal_entries(connection, original_transaction_id)
                next_version = current + 1
                self._insert_state_version(connection, next_version, "ledger-correction", {"correction_id": correction_id})
                reversal_id = uuid4().hex
                replacement_id = uuid4().hex
                self._insert_transaction(
                    connection,
                    reversal_intent,
                    transaction_id=reversal_id,
                    state_version=next_version,
                    fingerprint=transaction_fingerprint(reversal_intent),
                    operation_sequence=0,
                )
                self._insert_entries(connection, reversal_entries, transaction_id=reversal_id, state_version=next_version, hook=hook)
                after_reversal = compute_projection(
                    connection, target_state_version=next_version
                )
                replacement_entries = self._derive_entries(
                    connection, normalized, after_reversal
                )
                self._insert_transaction(
                    connection,
                    normalized,
                    transaction_id=replacement_id,
                    state_version=next_version,
                    fingerprint=fingerprint,
                    operation_sequence=1,
                )
                self._insert_entries(connection, replacement_entries, transaction_id=replacement_id, state_version=next_version, hook=hook)
                connection.execute(
                    "INSERT INTO correction_relations "
                    "(correction_id, original_transaction_id, reversal_transaction_id, "
                    "replacement_transaction_id, correction_reason, state_version, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (correction_id, original_transaction_id, reversal_id, replacement_id, reason, next_version, _now()),
                )
                projection = compute_projection(connection, target_state_version=next_version)
                replace_projection(connection, projection)
                if hook:
                    hook("projection_replaced", connection)
                return PostingResult((reversal_id, replacement_id), next_version, projection)
        except LedgerError:
            raise
        except (sqlite3.Error, StorageNotWritableError, RuntimeError, ValueError) as exc:
            raise PostingError(f"atomic correction failed: {exc}") from exc

    def rebaseline_position(
        self,
        *,
        account_id: str,
        instrument_id: str,
        quantity: DecimalInput,
        average_unit_cost: DecimalInput | None,
        currency: str | None,
        unit: str = "SHARE",
        source: str = "broker-snapshot-rebaseline",
        note: str | None = None,
        expected_state_version: int | None = None,
    ) -> PostingResult:
        """Append a broker-snapshot position rebaseline without inventing trade fills.

        The ledger records only the delta required to make the deterministic
        projection equal the authoritative broker quantity/cost basis.  This is
        intentionally distinct from BUY/SELL because exact executions may be
        unavailable.
        """
        target_quantity = exact_decimal(quantity, field="quantity")
        target_average = exact_decimal(average_unit_cost, field="average_unit_cost")
        if target_quantity is None or target_quantity < ZERO:
            raise IntentValidationError("rebaseline quantity must be non-negative")
        if target_average is not None and target_average < ZERO:
            raise IntentValidationError("rebaseline average_unit_cost must be non-negative")
        try:
            with self.manager.guarded_write_transaction() as connection:
                current = self._current_state_version(connection)
                if expected_state_version is not None and current != expected_state_version:
                    raise PostingError("state_version conflict")
                before = compute_projection(connection, target_state_version=current)
                position = self._find_position(before, account_id, instrument_id)
                old_quantity = ZERO if position is None else position.quantity
                old_cost = ZERO if position is None or position.total_cost is None else position.total_cost
                target_cost = None if target_average is None else target_quantity * target_average
                quantity_delta = target_quantity - old_quantity
                cost_delta = None if target_cost is None else target_cost - old_cost
                status = CostBasisStatus.UNAVAILABLE if target_cost is None else CostBasisStatus.USER_PROVIDED
                next_version = current + 1
                intent = TransactionIntent(
                    TransactionType.ASSET_ADJUSTMENT,
                    account_id=account_id, instrument_id=instrument_id,
                    quantity=quantity_delta, currency=currency, unit=unit,
                    occurred_at=datetime.now(timezone.utc), timezone="UTC",
                    notes=note or source, confirmation_state=ConfirmationState.CONFIRMED,
                    idempotency_key=f"{source}:{account_id}:{instrument_id}:{next_version}",
                )
                canonical, context, fingerprint = self._canonical_posting_state(connection, intent)
                normalized = self._require_ready(canonical, context)
                self._insert_state_version(connection, next_version, "broker-position-rebaseline", {
                    "account_id": account_id, "instrument_id": instrument_id, "source": source,
                    "target_quantity": encode_decimal(target_quantity),
                    "target_average_unit_cost": encode_decimal(target_average),
                })
                transaction_id = uuid4().hex
                self._insert_transaction(connection, normalized, transaction_id=transaction_id,
                                         state_version=next_version, fingerprint=fingerprint)
                self._insert_entries(connection, (LedgerEntry(
                    "ASSET", account_id, instrument_id, quantity_delta=quantity_delta,
                    currency=currency, unit=unit, cost_basis_delta=cost_delta,
                    cost_basis_status=status, metadata={"rebaseline": True, "source": source},
                ),), transaction_id=transaction_id, state_version=next_version)
                projection = compute_projection(connection, target_state_version=next_version)
                replace_projection(connection, projection)
                return PostingResult((transaction_id,), next_version, projection)
        except LedgerError:
            raise
        except (sqlite3.Error, StorageNotWritableError, RuntimeError, ValueError) as exc:
            raise PostingError(f"position rebaseline failed: {exc}") from exc

    def rebuild_projection(
        self, target_state_version: int | None = None, *, hook: PostingHook | None = None
    ) -> ProjectionState:
        try:
            with self.manager.guarded_write_transaction() as connection:
                state = compute_projection(
                    connection, target_state_version=target_state_version
                )
                replace_projection(connection, state)
                if hook:
                    hook("projection_replaced", connection)
                return state
        except LedgerError:
            raise
        except (sqlite3.Error, StorageNotWritableError, RuntimeError, ValueError) as exc:
            raise ProjectionError(f"projection rebuild failed: {exc}") from exc

    def create_portfolio_snapshot(
        self,
        *,
        snapshot_id: str,
        snapshot_type: str,
        as_of: datetime,
        data: dict[str, Any],
    ) -> None:
        try:
            with self.manager.guarded_write_transaction() as connection:
                version = self._current_state_version(connection)
                connection.execute(
                    "INSERT INTO portfolio_snapshots "
                    "(snapshot_id, state_version, snapshot_type, as_of, data_json, created_at, valuation_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'BOOK_ONLY')",
                    (snapshot_id, version, snapshot_type, as_of.isoformat(), json.dumps(data, sort_keys=True), _now()),
                )
        except (sqlite3.Error, StorageNotWritableError, TypeError, ValueError) as exc:
            raise PostingError(f"snapshot creation failed: {exc}") from exc

    def _read(self, query: str, parameters: tuple[object, ...] = ()) -> list[dict[str, Any]]:
        try:
            report = validate_personal_database(self.manager.database_path)
            if not report.valid:
                raise PostingError("personal database is not valid")
            with sqlite_readonly_connection(self.manager.database_path) as connection:
                return [
                    dict(row)
                    for row in connection.execute(query, parameters).fetchall()
                ]
        except LedgerError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise PostingError(f"ledger query failed: {exc}") from exc

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        rows = self._read("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
        return rows[0] if rows else None

    def list_transactions(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        return tuple(self._read("SELECT * FROM transactions ORDER BY state_version, operation_sequence, created_at LIMIT ?", (limit,)))

    def get_transaction_entries(self, transaction_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(self._read("SELECT * FROM transaction_entries WHERE transaction_id = ? ORDER BY entry_sequence", (transaction_id,)))

    def get_current_state_version(self) -> int:
        return int(self._read("SELECT MAX(state_version) AS version FROM state_versions")[0]["version"])

    def get_projection_as_of_state_version(self, version: int) -> ProjectionState:
        try:
            report = validate_personal_database(self.manager.database_path)
            if not report.valid:
                raise ProjectionError("personal database is not valid")
            with sqlite_readonly_connection(self.manager.database_path) as connection:
                return compute_projection(connection, target_state_version=version)
        except LedgerError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise ProjectionError(f"projection query failed: {exc}") from exc

    def get_verified_portfolio_snapshot_projection(
        self,
        *,
        expected_personal_db_instance_id: str,
        expected_state_version: int,
        expected_snapshot_id: str,
        expected_data_as_of: str,
    ) -> VerifiedPortfolioSnapshotProjection:
        """Read and bind the referenced snapshot row to its ledger projection.

        The snapshot's JSON payload and valuation status are returned only as
        descriptive metadata; neither is used as proof of marked values.
        Projection quantities, cash, and liabilities are recomputed solely from
        posted entries through the pinned state version.
        """
        if (
            not isinstance(expected_state_version, int)
            or isinstance(expected_state_version, bool)
            or expected_state_version < 0
        ):
            raise ProjectionError("pinned state_version must be a non-negative integer")
        if not all((expected_personal_db_instance_id, expected_snapshot_id, expected_data_as_of)):
            raise ProjectionError("personal DB instance, snapshot ID, and data-as-of pin are required")
        try:
            database_path = self.manager._operational_database_path()
            with sqlite_readonly_connection(database_path) as connection:
                connection.execute("BEGIN")
                report = validate_personal_connection(
                    connection, path=database_path, require_current=True,
                    migrations=self.manager.migrations,
                )
                if not report.valid or not report.instance_id:
                    raise ProjectionError("personal database failed read-only validation")
                if report.instance_id != expected_personal_db_instance_id:
                    raise ProjectionError("personal DB instance does not match run pin")
                row = connection.execute(
                    "SELECT snapshot_id, state_version, snapshot_type, as_of, valuation_status "
                    "FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (expected_snapshot_id,),
                ).fetchone()
                if row is None:
                    raise ProjectionError("pinned portfolio snapshot row is missing")
                if (
                    row["state_version"] != expected_state_version
                    or row["as_of"] != expected_data_as_of
                ):
                    raise ProjectionError("portfolio snapshot row does not match pinned version/as-of")
                projection = compute_projection(
                    connection, target_state_version=expected_state_version
                )
                if projection.state_version != expected_state_version:
                    raise ProjectionError("computed personal projection does not match pinned version")
                return VerifiedPortfolioSnapshotProjection(
                    personal_db_instance_id=report.instance_id,
                    snapshot_id=str(row["snapshot_id"]),
                    state_version=int(row["state_version"]),
                    snapshot_type=str(row["snapshot_type"]),
                    data_as_of=str(row["as_of"]),
                    valuation_status=row["valuation_status"],
                    projection=projection,
                )
        except (OSError, sqlite3.Error, ValueError, StorageNotWritableError) as exc:
            if isinstance(exc, ProjectionError):
                raise
            raise ProjectionError(f"pinned snapshot read failed: {exc}") from exc

    def declare_cash_reservations(
        self,
        *,
        expected_state_version: int,
        reservations: tuple[CashReservationDraft, ...] = (),
    ) -> None:
        """Record a complete reservation set without posting an order or transaction.

        An empty set is an explicit statement that this state version has no
        emergency, planned-spending, or pending-order reserve. It does not
        invent amounts for a later state version.
        """
        if isinstance(expected_state_version, bool) or not isinstance(expected_state_version, int):
            raise PostingError("reservation state_version must be an integer")
        if not isinstance(reservations, tuple):
            raise PostingError("reservations must be a tuple")
        normalized: list[tuple[str, str, Decimal, str | None]] = []
        for draft in reservations:
            if not isinstance(draft, CashReservationDraft) or draft.kind not in RESERVATION_KINDS:
                raise PostingError("reservation kind is unsupported")
            if not isinstance(draft.currency, str) or len(draft.currency.strip()) != 3:
                raise PostingError("reservation currency must be a three-letter code")
            amount = exact_decimal(draft.amount, field="reservation amount")
            if amount is None or amount < 0:
                raise PostingError("reservation amount must be zero or positive")
            instrument_id = draft.instrument_id
            if instrument_id is not None and (not isinstance(instrument_id, str) or not instrument_id.strip()):
                raise PostingError("pending-order reservation instrument is invalid")
            normalized.append((draft.kind, draft.currency.strip().upper(), amount, instrument_id))
        try:
            with self.manager.guarded_write_transaction() as connection:
                current = self._current_state_version(connection)
                if current != expected_state_version:
                    raise PostingError("reservation state_version does not match the ledger")
                if connection.execute(
                    "SELECT 1 FROM reservation_coverage WHERE state_version = ?", (current,)
                ).fetchone():
                    raise PostingError("reservation coverage is already declared for this state version")
                created_at = _now()
                connection.execute(
                    "INSERT INTO reservation_coverage (state_version, statement, created_at) VALUES (?, 'COMPLETE', ?)",
                    (current, created_at),
                )
                for kind, currency, amount, instrument_id in normalized:
                    connection.execute(
                        "INSERT INTO cash_reservations "
                        "(reservation_id, state_version, kind, currency, amount_decimal, instrument_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (uuid4().hex, current, kind, currency, encode_decimal(amount), instrument_id, created_at),
                    )
        except PostingError:
            raise
        except (OSError, sqlite3.Error, StorageNotWritableError, ValueError) as exc:
            raise PostingError(f"reservation declaration failed: {exc}") from exc

    def list_cash_reservations(self, state_version: int) -> tuple[bool, tuple[CashReservation, ...]]:
        """Return whether coverage was declared and the rows stored at that version."""
        if isinstance(state_version, bool) or not isinstance(state_version, int) or state_version < 0:
            raise ProjectionError("reservation state_version must be a non-negative integer")
        coverage = self._read(
            "SELECT statement FROM reservation_coverage WHERE state_version = ?", (state_version,)
        )
        if len(coverage) != 1 or coverage[0].get("statement") != "COMPLETE":
            return False, ()
        rows = self._read(
            "SELECT * FROM cash_reservations WHERE state_version = ? ORDER BY reservation_id",
            (state_version,),
        )
        reservations = tuple(
            CashReservation(
                str(row["reservation_id"]), int(row["state_version"]), str(row["kind"]),
                str(row["currency"]), decode_decimal(row["amount_decimal"]) or ZERO,
                row["instrument_id"],
            )
            for row in rows
        )
        return True, reservations

    def get_positions(self):
        return self.get_projection_as_of_state_version(self.get_current_state_version()).positions

    def get_cash_balances(self):
        return self.get_projection_as_of_state_version(self.get_current_state_version()).cash_balances

    def get_liabilities(self):
        return self.get_projection_as_of_state_version(self.get_current_state_version()).liabilities

    def get_cashflow(self):
        return self.get_projection_as_of_state_version(self.get_current_state_version()).cashflow
