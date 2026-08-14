from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from investment_stack.personal import (
    ConfirmationState,
    CostBasisStatus,
    IntentState,
    PersonalDatabaseManager,
    PersonalLedgerService,
    TransactionIntent,
    TransactionType,
    evaluate_intent,
)
from investment_stack.personal.errors import ConfirmationRequired
from investment_stack.personal.intent import OpeningBalanceKind
from investment_stack.personal.interpretation import parse_transaction_request
from tests.storage_support import sqlite_connection


WHEN = datetime(2026, 8, 10, 15, 0)


class Phase3AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        manager = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
        manager.initialize()
        self.manager = manager
        self.ledger = PersonalLedgerService(manager)
        self.ledger.register_account("a", name="A", currency="JPY", timezone_name="Asia/Tokyo")
        self.ledger.register_instrument("fanuc", canonical_name="FANUC", currency="JPY")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scenario_a_opening_cash_then_initial_position(self) -> None:
        self.ledger.post(TransactionIntent(TransactionType.OPENING_BALANCE, account_id="a", cash_amount="5000000", currency="KRW", opening_balance_kind=OpeningBalanceKind.CASH, occurred_at=WHEN, timezone="Asia/Seoul", confirmation_state=ConfirmationState.CONFIRMED))
        self.ledger.post(TransactionIntent(TransactionType.INITIAL_POSITION, account_id="a", instrument_id="fanuc", quantity="5", unit="SHARE", currency="JPY", total_cost="30000", cost_basis_status=CostBasisStatus.USER_PROVIDED, occurred_at=WHEN, timezone="Asia/Tokyo", confirmation_state=ConfirmationState.CONFIRMED))
        self.assertEqual(self.ledger.get_current_state_version(), 2)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("5000000"))
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("5"))

    def test_scenario_b_incomplete_buy_then_completed_post(self) -> None:
        parsed = parse_transaction_request("FANUC 2주 샀어", account_id="a", instrument_id="fanuc", currency="JPY")
        self.assertEqual(evaluate_intent(parsed).state, IntentState.NEEDS_CONFIRMATION)
        self.assertEqual(self.ledger.get_current_state_version(), 0)
        self.ledger.post(TransactionIntent(TransactionType.OPENING_BALANCE, account_id="a", cash_amount="100000", currency="JPY", opening_balance_kind=OpeningBalanceKind.CASH, occurred_at=WHEN, timezone="Asia/Tokyo", confirmation_state=ConfirmationState.CONFIRMED))
        completed = TransactionIntent(TransactionType.BUY, account_id="a", instrument_id="fanuc", quantity="2", unit_price="6400", fee_amount="100", currency="JPY", occurred_at=WHEN, timezone="Asia/Tokyo", confirmation_state=ConfirmationState.CONFIRMED)
        self.ledger.post(completed)
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("2"))

    def test_scenario_c_btc_ambiguity_never_auto_posts(self) -> None:
        intent = TransactionIntent(TransactionType.BUY, instrument_id="btc", quantity="0.05", custody_ambiguous=True)
        self.assertEqual(evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION)
        self.assertEqual(self.ledger.list_transactions(), ())

    def test_scenario_d_loan_payment_requires_principal_interest_split(self) -> None:
        intent = TransactionIntent(TransactionType.LOAN_PAYMENT, account_id="a", liability_id="loan", cash_amount="1000000", currency="KRW", occurred_at=WHEN, timezone="Asia/Seoul")
        self.assertEqual(evaluate_intent(intent).state, IntentState.NEEDS_CONFIRMATION)

    def test_scenario_e_clear_deposit_posts_capital(self) -> None:
        self.ledger.post(TransactionIntent(TransactionType.DEPOSIT, account_id="a", cash_amount="2000000", currency="KRW", occurred_at=WHEN, timezone="Asia/Seoul"))
        self.assertEqual(self.ledger.get_current_state_version(), 1)
        self.assertEqual(self.ledger.get_cashflow()[0].category, "CAPITAL")

    def test_scenario_f_correction_uses_reversal_and_replacement(self) -> None:
        self.ledger.post(TransactionIntent(TransactionType.OPENING_BALANCE, account_id="a", cash_amount="100000", currency="JPY", opening_balance_kind=OpeningBalanceKind.CASH, occurred_at=WHEN, timezone="Asia/Tokyo", confirmation_state=ConfirmationState.CONFIRMED))
        old = self.ledger.post(TransactionIntent(TransactionType.BUY, account_id="a", instrument_id="fanuc", quantity="2", unit_price="6400", currency="JPY", occurred_at=WHEN, timezone="Asia/Tokyo"))
        before = self.ledger.get_current_state_version()
        result = self.ledger.correct(old.transaction_ids[0], TransactionIntent(TransactionType.BUY, account_id="a", instrument_id="fanuc", quantity="3", unit_price="6300", currency="JPY", occurred_at=WHEN, timezone="Asia/Tokyo"), reason="corrected", occurred_at=WHEN, timezone_name="Asia/Tokyo")
        self.assertEqual(result.state_version, before + 1)
        self.assertEqual([row["transaction_type"] for row in self.ledger.list_transactions()], ["OPENING_BALANCE", "BUY", "REVERSAL", "BUY"])

    def test_scenario_g_projection_exactly_rebuilds(self) -> None:
        self.ledger.post(TransactionIntent(TransactionType.DEPOSIT, account_id="a", cash_amount="1000", currency="JPY", occurred_at=WHEN, timezone="Asia/Tokyo"))
        expected = self.ledger.get_projection_as_of_state_version(1)
        with sqlite_connection(self.manager.database_path) as connection:
            connection.execute("DELETE FROM cash_balances")
        actual = self.ledger.rebuild_projection()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
