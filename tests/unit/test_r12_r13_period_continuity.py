from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import GateState
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.institutional import Holding13F, HoldingSet13F, NoticeStatus, PutCall, QuantityType
from investment_stack.institutional.compare import compare_portfolios, is_consecutive_quarter_periods
from investment_stack.institutional.models import (
    HoldingChange13F,
    HoldingChangeStatus,
    InstitutionalPortfolioComparison,
)
from investment_stack.institutional.scoring import (
    calculate_consensus_direction,
    check_13f_trade_gate,
    compute_institutional_features,
)


class InstitutionalPeriodContinuityTests(unittest.TestCase):
    manager = "0000000001"
    cusip = "037833100"

    def comparison(self, prior: str, current: str, *, available: str = "2024-11-01T00:00:00+00:00"):
        change = HoldingChange13F(
            manager_cik=self.manager, cusip=self.cusip, issuer_name="APPLE", security_class="COM",
            quantity_type=QuantityType.SH, put_call=PutCall.NONE,
            prior_shares=Decimal("100"), current_shares=Decimal("200"),
            share_change=Decimal("100"), share_change_pct=Decimal("1"),
            prior_value=None, current_value=None, prior_weight=None, current_weight=None,
            weight_change=None, status=HoldingChangeStatus.INCREASED, notice_status=NoticeStatus.COMPLETE,
        )
        prior_availability = PublicAvailability.exact(
            datetime.fromisoformat(available), locator=f"fixture:{prior}:prior"
        )
        current_availability = PublicAvailability.exact(
            datetime.fromisoformat(available), locator=f"fixture:{current}:current"
        )
        return InstitutionalPortfolioComparison(
            manager_cik=self.manager, prior_period=prior, current_period=current,
            prior_filing_id=f"filing:{prior}", current_filing_id=f"filing:{current}", changes=(change,),
            total_eligible_value_prior=Decimal("100"), total_eligible_value_current=Decimal("200"),
            is_comparable=True, prior_public_availability=prior_availability,
            current_public_availability=current_availability,
        )

    def features(self, comparisons, cutoff="2024-11-15T00:00:00+00:00"):
        return compute_institutional_features(
            self.cusip, self.manager, comparisons, datetime.fromisoformat(cutoff)
        )

    @staticmethod
    def holding_set(filing: str, period: str) -> HoldingSet13F:
        holding = Holding13F(
            f"holding:{filing}", filing, "037833100", "APPLE", Decimal("100"), Decimal("100"),
            Decimal("100"), Decimal("100"),
        )
        return HoldingSet13F.create(filing, "0000000001", period, (holding,))

    def test_comparison_rejects_reverse_order_and_nonadjacent_periods(self):
        q1 = self.holding_set("q1", "2026-03-31")
        q2 = self.holding_set("q2", "2026-06-30")
        q3 = self.holding_set("q3", "2026-09-30")

        reverse = compare_portfolios(q2, q1)
        self.assertFalse(reverse.is_comparable)
        self.assertIn("ordered adjacent calendar quarter ends", reverse.incomparable_reasons[0])
        gap = compare_portfolios(q1, q3)
        self.assertFalse(gap.is_comparable)
        self.assertFalse(is_consecutive_quarter_periods("2026-03-31", "2026-09-30"))

    def test_scoring_rejects_reverse_gapped_and_duplicate_comparisons(self):
        reversed_feature = self.features((self.comparison("2026-06-30", "2026-03-31"),),
                                         cutoff="2026-07-15T00:00:00+00:00")
        self.assertFalse(reversed_feature.is_point_in_time)
        self.assertEqual("UNAVAILABLE", reversed_feature.score_status)
        self.assertIsNone(reversed_feature.quarterly_share_change_pct)
        self.assertIsNone(calculate_consensus_direction(
            self.cusip, (self.comparison("2026-06-30", "2026-03-31"),)
        ))

        gapped = (
            self.comparison("2024-03-31", "2025-03-31"),
            self.comparison("2025-03-31", "2026-06-30"),
        )
        duplicated = (
            self.comparison("2024-03-31", "2024-06-30"),
            self.comparison("2024-03-31", "2024-06-30"),
            self.comparison("2024-06-30", "2024-09-30"),
        )
        for rows in (gapped, duplicated):
            with self.subTest(rows=rows):
                result = self.features(rows)
                self.assertFalse(result.is_point_in_time)
                self.assertEqual("UNAVAILABLE", result.score_status)
                self.assertEqual(0, result.consecutive_quarters_held)
                self.assertIsNone(result.institutional_consensus_direction)

    def test_contiguous_unique_public_quarters_score_and_trade_gate_stays_disabled(self):
        comparisons = (
            self.comparison("2024-03-31", "2024-06-30"),
            self.comparison("2024-06-30", "2024-09-30"),
        )
        result = self.features(comparisons)
        self.assertTrue(result.is_point_in_time)
        self.assertEqual("UNVALIDATED", result.score_status)
        self.assertEqual("2024-09-30", result.holding_period)
        self.assertEqual(Decimal("1"), result.quarterly_share_change_pct)
        self.assertEqual(2, result.consecutive_quarters_held)
        self.assertEqual(1, result.institutional_consensus_direction)
        self.assertEqual(GateState.DISABLED, check_13f_trade_gate(result).state)


if __name__ == "__main__":
    unittest.main()
