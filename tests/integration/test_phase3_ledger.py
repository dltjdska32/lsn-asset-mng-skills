from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from investment_stack.personal import (
    ConfirmationState,
    CostBasisStatus,
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    PersonalLedgerService,
    TransactionIntent,
    TransactionType,
)
from investment_stack.personal.errors import (
    ConfirmationRequired,
    DuplicateTransactionError,
    PostingError,
    ProjectionError,
    ReversalError,
)
from investment_stack.personal.intent import OpeningBalanceKind, transaction_fingerprint
from tests.storage_support import sqlite_connection


WHEN = datetime(2026, 8, 10, 12, 0)


class Phase3LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.manager = PersonalDatabaseManager(
            root / "personal.db", backup_directory=root / "backups"
        )
        self.assertEqual(self.manager.initialize().status, PersonalDatabaseStatus.VALID)
        self.ledger = PersonalLedgerService(self.manager)
        self.ledger.register_account(
            "a", name="Account A", currency="JPY", timezone_name="Asia/Tokyo"
        )
        self.ledger.register_account(
            "b", name="Account B", currency="JPY", timezone_name="Asia/Tokyo"
        )
        self.ledger.register_instrument(
            "fanuc", canonical_name="FANUC", currency="JPY"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def intent(self, tx: TransactionType, **values: object) -> TransactionIntent:
        defaults = dict(occurred_at=WHEN, timezone="Asia/Tokyo")
        defaults.update(values)
        return TransactionIntent(tx, **defaults)

    def opening_cash(self, amount: str = "100000", account: str = "a"):
        return self.ledger.post(
            self.intent(
                TransactionType.OPENING_BALANCE,
                account_id=account,
                cash_amount=amount,
                currency="JPY",
                opening_balance_kind=OpeningBalanceKind.CASH,
                confirmation_state=ConfirmationState.CONFIRMED,
            )
        )

    def buy(self, quantity: str = "10", price: str = "100", **values: object):
        return self.ledger.post(
            self.intent(
                TransactionType.BUY,
                account_id="a",
                instrument_id="fanuc",
                quantity=quantity,
                unit_price=price,
                currency="JPY",
                **values,
            )
        )

    def test_cash_types_transfer_dividend_and_fee(self) -> None:
        self.opening_cash("10000")
        self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1000", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.WITHDRAWAL, account_id="a", cash_amount="500", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.TRANSFER, source_account_id="a", destination_account_id="b", cash_amount="1000", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.DIVIDEND, account_id="a", cash_amount="100", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.FEE, account_id="a", cash_amount="10", currency="JPY"))
        balances = {(item.account_id, item.currency): item.balance for item in self.ledger.get_cash_balances()}
        self.assertEqual(balances[("a", "JPY")], Decimal("9590"))
        self.assertEqual(balances[("b", "JPY")], Decimal("1000"))
        categories = [item.category for item in self.ledger.get_cashflow()]
        self.assertIn("INCOME", categories)
        self.assertIn("EXPENSE", categories)
        self.assertEqual(categories.count("TRANSFER"), 2)
        self.assertEqual(self.ledger.get_current_state_version(), 6)

    def test_weighted_average_sell_and_fee_policy(self) -> None:
        self.opening_cash("10000")
        self.buy("10", "100")
        self.buy("10", "200")
        position = self.ledger.get_positions()[0]
        self.assertEqual(position.quantity, Decimal("20"))
        self.assertEqual(position.average_unit_cost, Decimal("150"))
        self.ledger.post(self.intent(TransactionType.SELL, account_id="a", instrument_id="fanuc", quantity="5", unit_price="250", fee_amount="50", tax_amount="0", currency="JPY"))
        position = self.ledger.get_positions()[0]
        self.assertEqual(position.quantity, Decimal("15"))
        self.assertEqual(position.total_cost, Decimal("2250"))
        self.assertEqual(position.average_unit_cost, Decimal("150"))

    def test_eligible_buy_fee_is_included_in_weighted_basis(self) -> None:
        self.opening_cash("10000")
        self.buy("10", "100", fee_amount="100", tax_amount="50")
        position = self.ledger.get_positions()[0]
        self.assertEqual(position.total_cost, Decimal("1100"))
        self.assertEqual(position.average_unit_cost, Decimal("110"))

    def test_fx_and_loan_projection(self) -> None:
        self.opening_cash("100000")
        self.ledger.post(self.intent(TransactionType.FX_BUY, account_id="a", source_amount="10000", target_amount="100", source_currency="JPY", target_currency="USD", fx_rate="0.01"))
        self.ledger.post(self.intent(TransactionType.LOAN_DRAW, account_id="a", liability_id="loan", principal_amount="1000", currency="JPY"))
        self.ledger.post(self.intent(TransactionType.LOAN_PAYMENT, account_id="a", liability_id="loan", principal_amount="800", interest_amount="50", currency="JPY"))
        liability = self.ledger.get_liabilities()[0]
        self.assertEqual(liability.principal, Decimal("200"))
        expense = [item for item in self.ledger.get_cashflow() if item.category == "EXPENSE"]
        self.assertEqual(expense[-1].amount, Decimal("50"))

    def test_interest_adjustment_opening_liability_and_fx_sell(self) -> None:
        self.opening_cash("10000")
        self.ledger.post(self.intent(TransactionType.INTEREST, account_id="a", cash_amount="10", currency="JPY", ambiguity_metadata={"interest_direction": "INCOME"}))
        self.ledger.post(self.intent(TransactionType.FX_SELL, account_id="a", source_amount="100", target_amount="1", source_currency="JPY", target_currency="USD", fx_rate="0.01"))
        self.ledger.post(self.intent(TransactionType.OPENING_BALANCE, account_id="a", liability_id="opening-loan", cash_amount="500", currency="JPY", opening_balance_kind=OpeningBalanceKind.LIABILITY, confirmation_state=ConfirmationState.CONFIRMED))
        self.ledger.post(self.intent(TransactionType.INITIAL_POSITION, account_id="a", instrument_id="fanuc", quantity="5", unit="SHARE", currency="JPY", cost_basis_status=CostBasisStatus.UNAVAILABLE, confirmation_state=ConfirmationState.CONFIRMED))
        self.ledger.post(self.intent(TransactionType.ASSET_ADJUSTMENT, account_id="a", instrument_id="fanuc", quantity="-1", unit="SHARE", currency="JPY", confirmation_state=ConfirmationState.CONFIRMED))
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("4"))
        self.assertIsNone(self.ledger.get_positions()[0].total_cost)
        self.assertEqual(self.ledger.get_liabilities()[0].principal, Decimal("500"))

    def test_book_snapshot_is_append_only_and_does_not_increment_state(self) -> None:
        self.opening_cash()
        version = self.ledger.get_current_state_version()
        self.ledger.create_portfolio_snapshot(snapshot_id="snapshot-1", snapshot_type="ANALYSIS", as_of=WHEN, data={"status": "book-only"})
        self.assertEqual(self.ledger.get_current_state_version(), version)
        with sqlite_connection(self.manager.database_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM portfolio_snapshots WHERE snapshot_id='snapshot-1'")

    def test_initial_position_split_reverse_split_and_ticker_change(self) -> None:
        self.ledger.post(self.intent(TransactionType.INITIAL_POSITION, account_id="a", instrument_id="fanuc", quantity="10", unit="SHARE", currency="JPY", total_cost="1000", cost_basis_status=CostBasisStatus.USER_PROVIDED, confirmation_state=ConfirmationState.CONFIRMED))
        self.ledger.post(self.intent(TransactionType.SPLIT, account_id="a", instrument_id="fanuc", split_numerator="2", split_denominator="1"))
        position = self.ledger.get_positions()[0]
        self.assertEqual((position.quantity, position.total_cost, position.average_unit_cost), (Decimal("20"), Decimal("1000"), Decimal("50")))
        self.ledger.post(self.intent(TransactionType.REVERSE_SPLIT, account_id="a", instrument_id="fanuc", split_numerator="1", split_denominator="2"))
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("10"))
        self.ledger.post(self.intent(TransactionType.TICKER_CHANGE, instrument_id="fanuc", new_ticker="6954"))
        with sqlite_connection(self.manager.database_path, readonly=True) as connection:
            self.assertEqual(connection.execute("SELECT alias FROM instrument_aliases").fetchone()[0], "6954")

    def test_duplicate_key_and_suspected_fingerprint(self) -> None:
        self.opening_cash()
        intent = self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY", idempotency_key="same")
        self.ledger.post(intent)
        with self.assertRaises(DuplicateTransactionError):
            self.ledger.post(intent)
        suspicious = self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY")
        with self.assertRaises(ConfirmationRequired):
            self.ledger.post(suspicious)

    def test_timezone_fallback_duplicate_posts_once(self) -> None:
        first = TransactionIntent(
            TransactionType.DEPOSIT,
            account_id="a",
            cash_amount="10",
            currency="JPY",
            occurred_at=WHEN,
        )
        posted = self.ledger.post(first)
        with self.assertRaises(ConfirmationRequired):
            self.ledger.post(
                TransactionIntent(
                    TransactionType.DEPOSIT,
                    account_id="a",
                    cash_amount="10",
                    currency="JPY",
                    occurred_at=WHEN,
                )
            )
        rows = self.ledger.list_transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("10"))
        self.assertEqual(self.ledger.get_current_state_version(), 1)
        stored = self.ledger.get_transaction(posted.transaction_ids[0])
        explicit = self.intent(
            TransactionType.DEPOSIT,
            account_id="a",
            cash_amount="10",
            currency="JPY",
            timezone="Asia/Tokyo",
        )
        self.assertEqual(stored["fingerprint"], transaction_fingerprint(explicit))
        with self.assertRaises(ConfirmationRequired):
            self.ledger.post(explicit)

    def test_decimal_canonicalization_and_distinct_occurred_at(self) -> None:
        self.ledger.post(
            self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY")
        )
        for amount in ("10.0", "10.00"):
            with self.subTest(amount=amount), self.assertRaises(ConfirmationRequired):
                self.ledger.post(
                    self.intent(
                        TransactionType.DEPOSIT,
                        account_id="a",
                        cash_amount=amount,
                        currency="JPY",
                    )
                )
        self.assertEqual(len(self.ledger.list_transactions()), 1)
        later = self.ledger.post(
            self.intent(
                TransactionType.DEPOSIT,
                account_id="a",
                cash_amount="10",
                currency="JPY",
                occurred_at=datetime(2026, 8, 11, 12, 0),
            )
        )
        self.assertEqual(len(self.ledger.list_transactions()), 2)
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("20"))
        self.assertEqual(self.ledger.get_current_state_version(), 2)
        self.assertIsNotNone(later)

    def test_cashflow_occurred_at_matches_ledger_and_rebuild_is_stable(self) -> None:
        occurred = datetime(2026, 1, 2, 3, 4, 5)
        self.ledger.post(
            self.intent(
                TransactionType.DEPOSIT,
                account_id="a",
                cash_amount="10",
                currency="JPY",
                occurred_at=occurred,
            )
        )
        item = self.ledger.get_cashflow()[0]
        self.assertEqual(item.occurred_at, occurred.isoformat())
        with sqlite_connection(self.manager.database_path, readonly=True) as connection:
            ledger_time = connection.execute(
                "SELECT occurred_at FROM transactions"
            ).fetchone()[0]
            cashflow_time = connection.execute(
                "SELECT occurred_at FROM cashflow"
            ).fetchone()[0]
        self.assertEqual(cashflow_time, ledger_time)
        first = self.ledger.rebuild_projection()
        second = self.ledger.rebuild_projection()
        self.assertEqual(first, second)
        self.assertEqual(first.cashflow[0].occurred_at, occurred.isoformat())
        self.assertEqual(self.ledger.get_current_state_version(), 1)

    def test_correction_sequence_replays_reversal_before_replacement(self) -> None:
        self.opening_cash("20000")
        old = self.buy("2", "6400")
        before = self.ledger.get_current_state_version()
        replacement = self.intent(
            TransactionType.BUY,
            account_id="a",
            instrument_id="fanuc",
            quantity="3",
            unit_price="6300",
            currency="JPY",
        )

        class _Hex:
            def __init__(self, value: str) -> None:
                self.hex = value

        with patch(
            "investment_stack.personal.ledger._now",
            return_value="2026-08-14T00:00:00+00:00",
        ), patch(
            "investment_stack.personal.ledger.uuid4",
            side_effect=[
                _Hex("c" * 32),
                _Hex("f" * 32),
                _Hex("a" * 32),
            ],
        ):
            result = self.ledger.correct(
                old.transaction_ids[0],
                replacement,
                reason="correct quantity and price",
                occurred_at=WHEN,
                timezone_name="Asia/Tokyo",
            )
        self.assertEqual(result.state_version, before + 1)
        self.assertEqual(self.ledger.get_current_state_version(), before + 1)
        reversal = self.ledger.get_transaction(result.transaction_ids[0])
        replacement_row = self.ledger.get_transaction(result.transaction_ids[1])
        self.assertEqual(reversal["transaction_type"], "REVERSAL")
        self.assertEqual(replacement_row["transaction_type"], "BUY")
        self.assertEqual(reversal["operation_sequence"], 0)
        self.assertEqual(replacement_row["operation_sequence"], 1)
        self.assertEqual(reversal["created_at"], replacement_row["created_at"])
        self.assertLess(replacement_row["transaction_id"], reversal["transaction_id"])
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("3"))
        rebuilt = self.ledger.rebuild_projection()
        historical = self.ledger.get_projection_as_of_state_version(result.state_version)
        self.assertEqual(rebuilt, historical)
        self.assertEqual(rebuilt.positions[0].quantity, Decimal("3"))

    def test_reversal_restores_projection_and_is_single_use(self) -> None:
        self.opening_cash()
        posted = self.buy("2", "100")
        version = self.ledger.get_current_state_version()
        self.ledger.reverse(posted.transaction_ids[0], occurred_at=WHEN, timezone_name="Asia/Tokyo")
        self.assertEqual(self.ledger.get_positions(), ())
        self.assertEqual(self.ledger.get_cash_balances()[0].balance, Decimal("100000"))
        self.assertEqual(self.ledger.get_current_state_version(), version + 1)
        self.assertIsNotNone(self.ledger.get_transaction(posted.transaction_ids[0]))
        with self.assertRaises(ReversalError):
            self.ledger.reverse(posted.transaction_ids[0], occurred_at=WHEN, timezone_name="Asia/Tokyo")

    def test_correction_is_atomic_bundle_with_one_version(self) -> None:
        self.opening_cash()
        old = self.buy("2", "6400")
        before = self.ledger.get_current_state_version()
        replacement = self.intent(TransactionType.BUY, account_id="a", instrument_id="fanuc", quantity="3", unit_price="6300", currency="JPY")
        result = self.ledger.correct(old.transaction_ids[0], replacement, reason="correct quantity and price", occurred_at=WHEN, timezone_name="Asia/Tokyo")
        self.assertEqual(len(result.transaction_ids), 2)
        self.assertEqual(result.state_version, before + 1)
        self.assertEqual(self.ledger.get_positions()[0].quantity, Decimal("3"))
        original = self.ledger.get_transaction(old.transaction_ids[0])
        self.assertEqual(original["status"], "POSTED")

    def test_projection_rebuild_and_historical_versions(self) -> None:
        self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1000", currency="JPY"))
        self.buy("2", "100")
        self.ledger.post(self.intent(TransactionType.DIVIDEND, account_id="a", cash_amount="50", currency="JPY"))
        latest = self.ledger.get_projection_as_of_state_version(3)
        self.assertEqual(self.ledger.get_projection_as_of_state_version(1).cash_balances[0].balance, Decimal("1000"))
        self.assertEqual(self.ledger.get_projection_as_of_state_version(2).cash_balances[0].balance, Decimal("800"))
        self.assertEqual(latest.cash_balances[0].balance, Decimal("850"))
        version = self.ledger.get_current_state_version()
        with sqlite_connection(self.manager.database_path) as connection:
            connection.execute("DELETE FROM positions")
            connection.execute("DELETE FROM cash_balances")
        rebuilt = self.ledger.rebuild_projection()
        self.assertEqual(rebuilt, latest)
        self.assertEqual(self.ledger.get_current_state_version(), version)

    def test_append_only_triggers_block_update_and_delete(self) -> None:
        posted = self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY"))
        txid = posted.transaction_ids[0]
        with sqlite_connection(self.manager.database_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE transactions SET note='changed' WHERE transaction_id=?",
                    (txid,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM transactions WHERE transaction_id=?",
                    (txid,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE transaction_entries SET currency='USD' WHERE transaction_id=?",
                    (txid,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM transaction_entries WHERE transaction_id=?",
                    (txid,),
                )

    def test_atomic_failure_injection_rolls_back_every_layer(self) -> None:
        stages = ("state_version_inserted", "transaction_inserted", "entry_inserted", "entries_inserted", "projection_replaced")
        for stage in stages:
            with self.subTest(stage=stage):
                baseline_version = self.ledger.get_current_state_version()
                baseline_transactions = len(self.ledger.list_transactions())
                def fail(current: str, connection: sqlite3.Connection) -> None:
                    if current == stage:
                        raise RuntimeError(f"injected {stage}")
                with self.assertRaises(PostingError):
                    self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="10", currency="JPY", idempotency_key=stage), hook=fail)
                self.assertEqual(self.ledger.get_current_state_version(), baseline_version)
                self.assertEqual(len(self.ledger.list_transactions()), baseline_transactions)
                self.assertEqual(self.ledger.get_cash_balances(), ())

    def test_pending_and_invalid_storage_have_no_effect(self) -> None:
        pending = self.intent(TransactionType.BUY, account_id="a", instrument_id="fanuc", quantity="2", unit_price=None, currency="JPY", occurred_at=None, quantity_only=True)
        with self.assertRaises(ConfirmationRequired):
            self.ledger.post(pending)
        self.assertEqual(self.ledger.list_transactions(), ())
        self.assertEqual(self.ledger.get_current_state_version(), 0)
        self.manager.status = PersonalDatabaseStatus.INVALID
        with self.assertRaises(PostingError):
            self.ledger.post(self.intent(TransactionType.DEPOSIT, account_id="a", cash_amount="1", currency="JPY"))

    def test_configured_high_impact_threshold_requires_confirmation(self) -> None:
        ledger = PersonalLedgerService(self.manager, high_impact_threshold="100")
        intent = self.intent(
            TransactionType.DEPOSIT,
            account_id="a",
            cash_amount="101",
            currency="JPY",
        )
        with self.assertRaises(ConfirmationRequired):
            ledger.post(intent)
        ledger.post(
            TransactionIntent(
                TransactionType.DEPOSIT,
                account_id="a",
                cash_amount="101",
                currency="JPY",
                occurred_at=WHEN,
                timezone="Asia/Tokyo",
                confirmation_state=ConfirmationState.CONFIRMED,
            )
        )


if __name__ == "__main__":
    unittest.main()
