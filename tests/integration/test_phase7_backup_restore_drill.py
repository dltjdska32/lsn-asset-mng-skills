from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from investment_stack.personal import (
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    PersonalLedgerService,
    TransactionIntent,
    TransactionType,
)
from investment_stack.personal.manager import RestoreStatus


WHEN = datetime(2026, 8, 14, 10, 0)


class Phase7BackupRestoreDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.manager = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
        self.manager.initialize()
        self.ledger = PersonalLedgerService(self.manager)
        self.ledger.register_account("cash", name="Cash", currency="KRW", timezone_name="Asia/Seoul")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def post_deposit(self, amount: str) -> None:
        self.ledger.post(TransactionIntent(
            TransactionType.DEPOSIT,
            account_id="cash",
            cash_amount=amount,
            currency="KRW",
            occurred_at=WHEN,
            timezone="Asia/Seoul",
        ))

    def test_validated_backup_restore_drill_recovers_ledger_and_projection(self) -> None:
        self.post_deposit("1000")
        backup = self.manager.create_backup(reason="manual")
        self.assertTrue(backup.validation and backup.validation.valid)
        self.assertIsNotNone(backup.path)

        self.post_deposit("500")
        self.assertEqual(self.ledger.get_current_state_version(), 2)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("1500"))

        restored = self.manager.restore(backup.path)
        self.assertEqual(restored.status, RestoreStatus.RESTORED)
        self.assertEqual(self.manager.status, PersonalDatabaseStatus.VALID)
        self.manager.assert_writable()
        self.assertEqual(self.ledger.get_current_state_version(), 1)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("1000"))
        self.assertEqual(len(self.ledger.list_transactions()), 1)

    def test_corrupt_restore_candidate_is_rejected_without_losing_active_state(self) -> None:
        self.post_deposit("1000")
        before_version = self.ledger.get_current_state_version()
        before_balance = self.ledger.get_cash_balances()[0].balance
        corrupt = Path(self.temp.name) / "corrupt.db"
        corrupt.write_bytes(b"not-a-sqlite-database")

        result = self.manager.restore(corrupt)
        self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)
        self.assertEqual(self.manager.status, PersonalDatabaseStatus.VALID)
        self.assertEqual(self.ledger.get_current_state_version(), before_version)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, before_balance)
        self.manager.assert_writable()


if __name__ == "__main__":
    unittest.main()
