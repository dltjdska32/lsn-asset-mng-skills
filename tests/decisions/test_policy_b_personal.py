from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from investment_stack.decisions.policy_b_personal import bind_personal_snapshot
from investment_stack.personal.errors import ProjectionError
from investment_stack.personal.intent import ConfirmationState, TransactionIntent, TransactionType
from investment_stack.personal.ledger import PersonalLedgerService
from investment_stack.personal.manager import PersonalDatabaseManager


class PersonalPolicyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        manager = PersonalDatabaseManager(root / "personal.db", backup_directory=root / "backups")
        self.assertEqual("VALID", manager.initialize().status.value)
        self.ledger = PersonalLedgerService(manager)
        self.ledger.register_account("cash", name="Synthetic cash", currency="USD", timezone_name="UTC")
        self.ledger.register_instrument("ABC", canonical_name="Synthetic ABC", currency="USD")
        self.ledger.post(TransactionIntent(
            TransactionType.DEPOSIT,
            account_id="cash",
            cash_amount="1000",
            currency="USD",
            occurred_at=datetime(2026, 9, 28, 10, tzinfo=timezone.utc),
            timezone="UTC",
            confirmation_state=ConfirmationState.CONFIRMED,
            idempotency_key="synthetic-deposit",
        ))
        self.ledger.post(TransactionIntent(
            TransactionType.BUY,
            account_id="cash",
            instrument_id="ABC",
            quantity="2",
            unit_price="100",
            currency="USD",
            occurred_at=datetime(2026, 9, 28, 11, tzinfo=timezone.utc),
            timezone="UTC",
            confirmation_state=ConfirmationState.CONFIRMED,
            idempotency_key="synthetic-buy",
        ))
        self.state_version = self.ledger.get_current_state_version()
        self.as_of = "2026-09-28T12:00:00+00:00"
        self.snapshot_id = "synthetic-snapshot"
        self.ledger.create_portfolio_snapshot(
            snapshot_id=self.snapshot_id,
            snapshot_type="BOOK_ONLY",
            as_of=datetime.fromisoformat(self.as_of),
            # Deliberately bogus values demonstrate that JSON is not trusted.
            data={"holdings": {"ABC": 999999}, "total": 999999, "fees_verified": True},
        )
        self.db = Mock()
        self.db.run_id = "run-synthetic"
        self.db.fetch_phase6_context.return_value = {
            "pinned_personal_state": {
                "personal_db_instance_id": manager.instance_id,
                "state_version": self.state_version,
                "portfolio_snapshot_id": self.snapshot_id,
                "portfolio_data_as_of": self.as_of,
            }
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_binds_exact_row_and_projection_but_suppresses_unverified_value_sizing(self) -> None:
        result = bind_personal_snapshot(self.db, self.ledger, instrument_id="ABC")
        self.assertTrue(result.portfolio_state_bound)
        self.assertEqual(Decimal("2"), result.instrument_holding_units)
        self.assertEqual(1, len(result.cash_components))
        self.assertEqual("USD", result.cash_components[0].currency)
        self.assertEqual(Decimal("800"), result.cash_components[0].amount)
        self.assertFalse(result.eligible_for_policy_sizing)
        self.assertFalse(result.fee_and_lot_ready)
        self.assertIsNone(result.instrument_holding_value)
        self.assertIsNone(result.portfolio_denominator)
        self.assertIsNone(result.investable_cash)
        self.assertTrue(any("market value or FX" in reason for reason in result.unavailable_reasons))
        self.assertFalse(result.orders_posted)

    def test_wrong_instance_version_or_as_of_never_binds(self) -> None:
        for field, value in (
            ("personal_db_instance_id", "wrong-instance"),
            ("state_version", self.state_version - 1),
            ("portfolio_data_as_of", "2026-09-27T12:00:00+00:00"),
        ):
            with self.subTest(field=field):
                pin = dict(self.db.fetch_phase6_context.return_value["pinned_personal_state"])
                pin[field] = value
                self.db.fetch_phase6_context.return_value = {"pinned_personal_state": pin}
                result = bind_personal_snapshot(self.db, self.ledger, instrument_id="ABC")
                self.assertFalse(result.portfolio_state_bound)
                self.assertIsNone(result.instrument_holding_units)
                self.assertFalse(result.eligible_for_policy_sizing)

    def test_missing_snapshot_row_fails_closed(self) -> None:
        pin = dict(self.db.fetch_phase6_context.return_value["pinned_personal_state"])
        pin["portfolio_snapshot_id"] = "missing-snapshot"
        self.db.fetch_phase6_context.return_value = {"pinned_personal_state": pin}
        result = bind_personal_snapshot(self.db, self.ledger, instrument_id="ABC")
        self.assertFalse(result.portfolio_state_bound)
        self.assertIsNone(result.instrument_holding_units)
        self.assertTrue(any("snapshot/projection binding failed" in reason for reason in result.unavailable_reasons))

    def test_snapshot_row_version_or_as_of_tamper_is_rejected(self) -> None:
        with self.assertRaises(ProjectionError):
            self.ledger.get_verified_portfolio_snapshot_projection(
                expected_personal_db_instance_id=self.ledger.manager.instance_id,
                expected_state_version=self.state_version - 1,
                expected_snapshot_id=self.snapshot_id,
                expected_data_as_of=self.as_of,
            )


if __name__ == "__main__":
    unittest.main()
