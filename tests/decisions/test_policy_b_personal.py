from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import Mock

from investment_stack.decisions.policy_b_personal import (
    HoldingMark,
    PersonalPortfolioSnapshot,
    SnapshotAmount,
    bind_personal_snapshot,
)


class PersonalPolicyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Mock()
        self.db.run_id = "run-synthetic"
        self.snapshot = PersonalPortfolioSnapshot(
            personal_db_instance_id="personal-synthetic",
            state_version=4,
            snapshot_id="snap-synthetic",
            data_as_of="2026-09-28T10:00:00+09:00",
            evaluation_currency="USD",
            holdings=(HoldingMark("ABC", Decimal("2"), None, None),),
            cash=(SnapshotAmount(Decimal("1000"), "USD"),),
            emergency_reserve=SnapshotAmount(Decimal("100"), "USD"),
            planned_spending_reserve=SnapshotAmount(Decimal("50"), "USD"),
            pending_order_reservations=(),
            liabilities=(),
            unpriced_asset_count=0,
            fee_schedule_reference="synthetic-fees",
            lot_rule_reference="synthetic-lot",
        )

    def test_matching_run_pin_binds_identity_but_fails_closed_on_unproven_metrics(self) -> None:
        self.db.fetch_phase6_context.return_value = {
            "pinned_personal_state": {
                "personal_db_instance_id": "personal-synthetic",
                "state_version": 4,
                "portfolio_snapshot_id": "snap-synthetic",
                "portfolio_data_as_of": "2026-09-28T10:00:00+09:00",
            }
        }
        result = bind_personal_snapshot(self.db, self.snapshot, instrument_id="ABC")
        self.assertTrue(result.portfolio_state_bound)
        self.assertFalse(result.eligible_for_policy_sizing)
        self.assertFalse(result.fee_and_lot_ready)
        self.assertIsNone(result.instrument_holding_value)
        self.assertIsNone(result.portfolio_denominator)
        self.assertIsNone(result.investable_cash)
        self.assertTrue(any("valuation and FX" in reason for reason in result.unavailable_reasons))
        self.assertFalse(result.orders_posted)

    def test_mismatched_instance_or_snapshot_does_not_bind(self) -> None:
        self.db.fetch_phase6_context.return_value = {
            "pinned_personal_state": {
                "personal_db_instance_id": "other-instance",
                "state_version": 4,
                "portfolio_snapshot_id": "snap-synthetic",
                "portfolio_data_as_of": self.snapshot.data_as_of,
            }
        }
        result = bind_personal_snapshot(self.db, self.snapshot, instrument_id="ABC")
        self.assertFalse(result.portfolio_state_bound)
        self.assertIn("typed snapshot identity does not match the immutable same-run pin", result.unavailable_reasons)
        self.assertFalse(result.eligible_for_policy_sizing)

    def test_missing_pin_snapshot_and_order_state_are_explicitly_unavailable(self) -> None:
        self.db.fetch_phase6_context.return_value = {"pinned_personal_state": None}
        result = bind_personal_snapshot(self.db, None, instrument_id="ABC")
        self.assertFalse(result.portfolio_state_bound)
        self.assertIn("typed personal portfolio snapshot is missing", result.unavailable_reasons)
        self.assertIn("run.db has no pinned personal state", result.unavailable_reasons)


if __name__ == "__main__":
    unittest.main()
