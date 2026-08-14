from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from investment_stack.personal import (
    ConfirmationState,
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    PersonalLedgerService,
    TransactionIntent,
    TransactionType,
)
from investment_stack.personal.errors import (
    ConfirmationRequired,
    IntentValidationError,
    PostingError,
    ProjectionError,
    ReversalError,
)
from investment_stack.personal.intent import OpeningBalanceKind
from investment_stack.personal.validation import validate_personal_database
from tests.storage_support import sqlite_connection


WHEN = datetime(2026, 8, 10, 12, 0)


class Phase3FailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.manager = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
        self.manager.initialize()
        self.ledger = PersonalLedgerService(self.manager)
        self.ledger.register_account("a", name="A", currency="JPY", timezone_name="Asia/Tokyo")
        self.ledger.register_instrument("fanuc", canonical_name="FANUC", currency="JPY")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def intent(self, tx: TransactionType, **values: object) -> TransactionIntent:
        base = dict(occurred_at=WHEN, timezone="Asia/Tokyo")
        base.update(values)
        return TransactionIntent(tx, **base)

    def opening(self) -> None:
        self.ledger.post(self.intent(TransactionType.OPENING_BALANCE, account_id="a", cash_amount="1000", currency="JPY", opening_balance_kind=OpeningBalanceKind.CASH, confirmation_state=ConfirmationState.CONFIRMED))

    def test_nonfinite_zero_negative_and_float_inputs_fail_closed(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity", 0.1):
            with self.subTest(value=value), self.assertRaises(IntentValidationError):
                self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount=value, currency="JPY")
        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaises(ConfirmationRequired):
                self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount=value, currency="JPY"))
        self.assertEqual(self.ledger.get_current_state_version(), 0)

    def test_nonexistent_entities_cannot_be_confirmed_around(self) -> None:
        with self.assertRaises(IntentValidationError):
            self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="missing", cash_amount="1", currency="JPY", confirmation_state=ConfirmationState.CONFIRMED))
        with self.assertRaises(IntentValidationError):
            self.ledger.post(self.intent(TransactionType.BUY, account_id="a", instrument_id="missing", quantity="1", unit_price="1", currency="JPY", confirmation_state=ConfirmationState.CONFIRMED))

    def test_overdraft_oversell_and_overpayment_roll_back(self) -> None:
        self.opening()
        with self.assertRaises(ProjectionError):
            self.ledger.post(self.intent(TransactionType.WITHDRAWAL, account_id="a", cash_amount="1001", currency="JPY"))
        with self.assertRaises(ProjectionError):
            self.ledger.post(self.intent(TransactionType.SELL, account_id="a", instrument_id="fanuc", quantity="1", unit_price="1", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.LOAN_DRAW, account_id="a", liability_id="loan", principal_amount="100", currency="JPY"))
        with self.assertRaises(ProjectionError):
            self.ledger.post(self.intent(TransactionType.LOAN_PAYMENT, account_id="a", liability_id="loan", principal_amount="101", interest_amount="0", currency="JPY"))

    def test_reversal_nonexistent_reversal_of_reversal_and_double(self) -> None:
        with self.assertRaises(IntentValidationError):
            self.ledger.reverse(
                "missing", occurred_at=WHEN, timezone_name="Mars/Olympus"
            )
        with self.assertRaises(ReversalError):
            self.ledger.reverse("missing", occurred_at=WHEN, timezone_name="Asia/Tokyo")
        posted = self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY"))
        reversal = self.ledger.reverse(posted.transaction_ids[0], occurred_at=WHEN, timezone_name="Asia/Tokyo")
        with self.assertRaises(ReversalError):
            self.ledger.reverse(posted.transaction_ids[0], occurred_at=WHEN, timezone_name="Asia/Tokyo")
        with self.assertRaises(ReversalError):
            self.ledger.reverse(reversal.transaction_ids[0], occurred_at=WHEN, timezone_name="Asia/Tokyo")

    def test_correction_failure_preserves_original_and_state(self) -> None:
        self.opening()
        old = self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY"))
        version = self.ledger.get_current_state_version()
        replacement = self.intent(TransactionType.WITHDRAWAL, account_id="a", cash_amount="999999", currency="JPY")
        with self.assertRaises(ProjectionError):
            self.ledger.correct(old.transaction_ids[0], replacement, reason="bad replacement", occurred_at=WHEN, timezone_name="Asia/Tokyo")
        self.assertEqual(self.ledger.get_current_state_version(), version)
        self.assertEqual(len(self.ledger.list_transactions()), 2)

    def test_state_version_conflict_and_storage_status_block(self) -> None:
        with self.assertRaises(PostingError):
            self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY"), expected_state_version=9)
        self.manager.status = PersonalDatabaseStatus.STARTUP_BLOCKED
        with self.assertRaises(PostingError):
            self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY"))

    def test_external_reference_collision_requires_confirmation(self) -> None:
        self.ledger.post(
            self.intent(
                TransactionType.DEPOSIT,
                account_id="a",
                cash_amount="1",
                currency="JPY",
                external_reference="bank-line-1",
            )
        )
        with self.assertRaises(ConfirmationRequired):
            self.ledger.post(
                self.intent(
                    TransactionType.DEPOSIT,
                    account_id="a",
                    cash_amount="2",
                    currency="JPY",
                    external_reference="bank-line-1",
                )
            )

    def test_append_only_trigger_removal_invalidates_schema(self) -> None:
        with sqlite_connection(self.manager.database_path) as connection:
            connection.execute("DROP TRIGGER transactions_append_only_update")
        report = validate_personal_database(self.manager.database_path)
        self.assertFalse(report.valid)
        with self.assertRaises(PostingError):
            self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY"))

    def test_append_only_trigger_tampering_is_invalid(self) -> None:
        cases = {
            "noop-when": """
                CREATE TRIGGER transactions_append_only_update
                BEFORE UPDATE ON transactions WHEN 0 BEGIN
                    SELECT RAISE(ABORT, 'posted transactions are append-only');
                END
            """,
            "wrong-target": """
                CREATE TRIGGER transactions_append_only_update
                BEFORE UPDATE ON accounts BEGIN
                    SELECT RAISE(ABORT, 'posted transactions are append-only');
                END
            """,
            "update-only": """
                CREATE TRIGGER transactions_append_only_delete
                BEFORE UPDATE ON transactions BEGIN
                    SELECT RAISE(ABORT, 'posted transactions are append-only');
                END
            """,
            "delete-only": """
                CREATE TRIGGER transactions_append_only_update
                BEFORE DELETE ON transactions BEGIN
                    SELECT RAISE(ABORT, 'posted transactions are append-only');
                END
            """,
            "raise-removed": """
                CREATE TRIGGER transactions_append_only_update
                BEFORE UPDATE ON transactions BEGIN
                    SELECT 1;
                END
            """,
        }
        drop_for_case = {
            "noop-when": "transactions_append_only_update",
            "wrong-target": "transactions_append_only_update",
            "update-only": "transactions_append_only_delete",
            "delete-only": "transactions_append_only_update",
            "raise-removed": "transactions_append_only_update",
        }
        for case, sql in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manager = PersonalDatabaseManager(
                    root / "personal.db", backup_directory=root / "backups"
                )
                manager.initialize()
                ledger = PersonalLedgerService(manager)
                ledger.register_account("a", name="A", currency="JPY", timezone_name="Asia/Tokyo")
                posted = ledger.post(
                    self.intent(
                        TransactionType.DEPOSIT,
                        account_id="a",
                        cash_amount="1",
                        currency="JPY",
                    )
                )
                with sqlite_connection(manager.database_path) as connection:
                    connection.execute(f"DROP TRIGGER {drop_for_case[case]}")
                    connection.execute(sql)
                report = validate_personal_database(manager.database_path)
                self.assertFalse(report.valid, report.errors)
                self.assertTrue(
                    any("trigger" in error.lower() for error in report.errors),
                    report.errors,
                )
                with self.assertRaises(PostingError):
                    ledger.post(
                        self.intent(
                            TransactionType.DEPOSIT,
                            account_id="a",
                            cash_amount="2",
                            currency="JPY",
                            occurred_at=datetime(2026, 8, 11, 12, 0),
                        )
                    )
                self.assertIsNotNone(posted)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            with sqlite_connection(manager.database_path) as connection:
                connection.execute("DROP TRIGGER transactions_append_only_update")
            report = validate_personal_database(manager.database_path)
            self.assertFalse(report.valid)
            self.assertTrue(any("trigger" in error.lower() for error in report.errors))

    def test_noop_when_trigger_would_allow_update_but_validator_rejects(self) -> None:
        posted = self.ledger.post(
            self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY")
        )
        with sqlite_connection(self.manager.database_path) as connection:
            connection.execute("DROP TRIGGER transactions_append_only_update")
            connection.execute(
                """
                CREATE TRIGGER transactions_append_only_update
                BEFORE UPDATE ON transactions WHEN 0 BEGIN
                    SELECT RAISE(ABORT, 'posted transactions are append-only');
                END
                """
            )
            connection.execute(
                "UPDATE transactions SET note='changed' WHERE transaction_id=?",
                (posted.transaction_ids[0],),
            )
        report = validate_personal_database(self.manager.database_path)
        self.assertFalse(report.valid)
        with self.assertRaises(PostingError):
            self.ledger.post(
                self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="3", currency="JPY")
            )

    def test_phase3_has_no_raw_writer_or_market_lookup(self) -> None:
        root = Path(__file__).resolve().parents[2]
        files = [
            root / "runtime/investment_stack/personal/ledger.py",
            root / "runtime/investment_stack/personal/projection.py",
            root / "runtime/investment_stack/personal/intent.py",
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertNotIn("_sqlite_write_connection", source)
        self.assertNotIn("sqlite3.connect", source)
        for token in ("httpx", "requests.get", "urllib.request", "current_price"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
