from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import GateState
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.institutional import NoticeStatus, PutCall, QuantityType
from investment_stack.institutional.models import (
    HoldingChange13F,
    HoldingChangeStatus,
    InstitutionalPortfolioComparison,
)
from investment_stack.institutional.scoring import check_13f_trade_gate, compute_institutional_features


class TestInstitutionalScoringPointInTime(unittest.TestCase):
    cutoff = datetime(2026, 9, 27, tzinfo=timezone.utc)

    def comparison(self, period: str, availability: PublicAvailability | None) -> InstitutionalPortfolioComparison:
        prior_period = {
            "2026-06-30": "2026-03-31",
            "2026-09-30": "2026-06-30",
        }.get(period, "2026-03-31")
        change = HoldingChange13F(
            manager_cik="0000000001", cusip="037833100", issuer_name="APPLE",
            security_class="COM", quantity_type=QuantityType.SH, put_call=PutCall.NONE,
            prior_shares=Decimal("100"), current_shares=Decimal("200"),
            share_change=Decimal("100"), share_change_pct=Decimal("1"),
            prior_value=None, current_value=None, prior_weight=None, current_weight=None,
            weight_change=None, status=HoldingChangeStatus.INCREASED,
            notice_status=NoticeStatus.COMPLETE,
        )
        return InstitutionalPortfolioComparison(
            manager_cik="0000000001", prior_period=prior_period, current_period=period,
            prior_filing_id="prior", current_filing_id="current", changes=(change,),
            total_eligible_value_prior=Decimal("1"), total_eligible_value_current=Decimal("1"),
            is_comparable=True, prior_public_availability=availability,
            current_public_availability=availability,
        )

    def score(self, comparison: InstitutionalPortfolioComparison):
        return compute_institutional_features(
            "037833100", "0000000001", [comparison], self.cutoff
        )

    def test_future_period_and_future_publication_are_unavailable(self) -> None:
        available = PublicAvailability.exact(datetime(2026, 9, 20, tzinfo=timezone.utc), locator="fixture")
        future_period = self.score(self.comparison("2026-09-30", available))
        self.assertEqual("UNAVAILABLE", future_period.score_status)
        self.assertFalse(future_period.is_point_in_time)
        self.assertIsNone(future_period.quarterly_share_change_pct)
        self.assertIsNone(future_period.institutional_consensus_direction)

        future_publication = PublicAvailability.exact(
            datetime(2026, 9, 28, tzinfo=timezone.utc), locator="fixture"
        )
        unavailable = self.score(self.comparison("2026-06-30", future_publication))
        self.assertEqual("UNAVAILABLE", unavailable.score_status)
        self.assertFalse(unavailable.is_point_in_time)
        self.assertIsNone(unavailable.quarterly_share_change_pct)

    def test_unknown_availability_is_unavailable_and_known_past_availability_is_usable(self) -> None:
        unknown = self.score(self.comparison("2026-06-30", None))
        self.assertEqual("UNAVAILABLE", unknown.score_status)
        self.assertFalse(unknown.is_point_in_time)

        past = PublicAvailability.exact(
            datetime(2026, 8, 14, 20, tzinfo=timezone.utc), locator="fixture"
        )
        usable = self.score(self.comparison("2026-06-30", past))
        self.assertEqual("UNVALIDATED", usable.score_status)
        self.assertTrue(usable.is_point_in_time)
        self.assertEqual(Decimal("1"), usable.quarterly_share_change_pct)
        self.assertEqual(1, usable.institutional_consensus_direction)
        self.assertEqual(GateState.DISABLED, check_13f_trade_gate(usable).state)


if __name__ == "__main__":
    unittest.main()
