"""Unit tests for REQ-2026-09-23-v1 R13: Point-in-time validation harness and UNVALIDATED trade gate."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import GateState
from investment_stack.contracts.context import PublicAvailability
from investment_stack.contracts.institutional import (
    AmendmentType,
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingSet13F,
    NoticeStatus,
    PutCall,
    QuantityType,
)
from investment_stack.institutional.compare import compare_portfolios
from investment_stack.institutional.models import (
    HoldingChange13F,
    HoldingChangeStatus,
    InstitutionalFeatureSet,
    InstitutionalPortfolioComparison,
    ValidationReport,
)
from investment_stack.institutional.scoring import (
    calculate_consensus_direction,
    check_13f_trade_gate,
    compute_institutional_features,
)
from investment_stack.institutional.validation import (
    run_point_in_time_audit,
    validate_absence_not_sold_under_confidential_omission,
    validate_amendment_cutoff_invariance,
    validate_lookahead_leak,
    validate_quantity_type_purity,
)


class TestPointInTimeValidation(unittest.TestCase):
    def test_missing_consensus_observations_remain_missing(self) -> None:
        self.assertIsNone(calculate_consensus_direction("037833100", []))
        features = compute_institutional_features(
            "037833100", "0001067983", [], datetime(2024, 8, 1, tzinfo=timezone.utc)
        )
        self.assertIsNone(features.information_lag_days)
        self.assertIsNone(features.coverage_quality_score)

    def test_lookahead_leak_detected(self) -> None:
        # Filing accepted on 2024-05-15
        filing_future = Filing13F(
            filing_id="f1",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc1",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(
                datetime(2024, 5, 15, 20, 30, tzinfo=timezone.utc), locator="acc1"
            ),
        )
        # Cutoff as of 2024-05-01: filing_future is a future leak
        cutoff_past = datetime(2024, 5, 1, 0, 0, tzinfo=timezone.utc)
        has_leak, details = validate_lookahead_leak([filing_future], cutoff_past)
        self.assertTrue(has_leak)
        self.assertEqual(1, len(details))
        self.assertIn("NOT point-in-time available", details[0])

        # Cutoff as of 2024-05-20: filing_future is available
        cutoff_future = datetime(2024, 5, 20, 0, 0, tzinfo=timezone.utc)
        has_leak_2, details_2 = validate_lookahead_leak([filing_future], cutoff_future)
        self.assertFalse(has_leak_2)
        self.assertEqual(0, len(details_2))

    def test_amendment_cutoff_invariance(self) -> None:
        # Original filing May 15, restatement June 20
        f_orig = Filing13F(
            filing_id="f_orig",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc_orig",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(
                datetime(2024, 5, 15, 20, 30, tzinfo=timezone.utc), locator="acc_orig"
            ),
        )
        h_orig = HoldingSet13F.create(
            "f_orig", "0001067983", "2024-03-31",
            [Holding13F("h1", "f_orig", "037833100", "APPLE", Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"))]
        )

        f_restate = Filing13F(
            filing_id="f_restate",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR_A,
            accession="acc_restate",
            report_period="2024-03-31",
            filed_date="2024-06-20",
            public_availability=PublicAvailability.exact(
                datetime(2024, 6, 20, 17, 0, tzinfo=timezone.utc), locator="acc_restate"
            ),
            amendment_type=AmendmentType.RESTATED,
        )
        h_restate = HoldingSet13F.create(
            "f_restate", "0001067983", "2024-03-31",
            [Holding13F("h2", "f_restate", "037833100", "APPLE", Decimal("200"), Decimal("200"), Decimal("200"), Decimal("200"))]
        )

        pairs = [(f_orig, h_orig), (f_restate, h_restate)]
        # Audit as of 2024-05-20: should not leak June restatement
        has_leak, errors = validate_amendment_cutoff_invariance("0001067983", "2024-03-31", pairs, datetime(2024, 5, 20, tzinfo=timezone.utc))
        self.assertFalse(has_leak)
        self.assertEqual(0, len(errors))

    def test_confidential_omission_absence_audit(self) -> None:
        # Incorrectly coding an omitted holding as CLOSED_POSITION triggers violation
        bad_change = HoldingChange13F(
            manager_cik="0001067983",
            cusip="037833100",
            issuer_name="APPLE INC",
            security_class="COM",
            quantity_type=QuantityType.SH,
            put_call=PutCall.NONE,
            prior_shares=Decimal("100"),
            current_shares=None,
            share_change=Decimal("-100"),
            share_change_pct=Decimal("-1.0"),
            prior_value=Decimal("100"),
            current_value=None,
            prior_weight=Decimal("0.5"),
            current_weight=Decimal("0"),
            weight_change=Decimal("-0.5"),
            status=HoldingChangeStatus.CLOSED_POSITION,  # VIOLATION: under confidential omission it must be NOT_REPORTED!
            notice_status=NoticeStatus.CONFIDENTIAL_OMISSION,
        )
        comp = InstitutionalPortfolioComparison(
            manager_cik="0001067983",
            prior_period="2024-03-31",
            current_period="2024-06-30",
            prior_filing_id="p1",
            current_filing_id="c1",
            changes=(bad_change,),
            total_eligible_value_prior=Decimal("200"),
            total_eligible_value_current=Decimal("100"),
            is_comparable=True,
        )
        has_viol, violations = validate_absence_not_sold_under_confidential_omission(comp)
        self.assertTrue(has_viol)
        self.assertIn("incorrectly marked CLOSED_POSITION", violations[0])


class TestStrictUnvalidatedTradeGate(unittest.TestCase):
    def test_unvalidated_features_blocked_by_default(self) -> None:
        as_of = datetime(2024, 5, 20, 0, 0, tzinfo=timezone.utc)
        features = InstitutionalFeatureSet(
            manager_cik="0001067983",
            target_cusip="037833100",
            as_of=as_of,
            holding_period="2024-03-31",
            quarterly_share_change_pct=Decimal("0.15"),
            portfolio_weight_current=Decimal("0.20"),
            portfolio_weight_change=Decimal("0.02"),
            institutional_consensus_direction=1,
            consecutive_quarters_held=4,
            information_lag_days=45,
            coverage_quality_score=Decimal("1.0"),
            is_point_in_time=True,
            score_status="UNVALIDATED",
        )

        # Evaluating trade gate without approval_ref
        decision = check_13f_trade_gate(features)
        self.assertEqual(GateState.DISABLED, decision.state)
        self.assertIn("UNVALIDATED", decision.reasons[0])
        self.assertIn("13F signal weights must not drive trade decisions per REQ R13", decision.reasons[0])

    def test_trade_gate_blocks_unvalidated_features_even_with_approval_string(self) -> None:
        as_of = datetime(2024, 5, 20, 0, 0, tzinfo=timezone.utc)
        features = InstitutionalFeatureSet(
            manager_cik="0001067983",
            target_cusip="037833100",
            as_of=as_of,
            holding_period="2024-03-31",
            quarterly_share_change_pct=Decimal("0.15"),
            portfolio_weight_current=Decimal("0.20"),
            portfolio_weight_change=Decimal("0.02"),
            institutional_consensus_direction=1,
            consecutive_quarters_held=4,
            information_lag_days=45,
            coverage_quality_score=Decimal("1.0"),
            is_point_in_time=True,
            score_status="UNVALIDATED",
        )
        decision = check_13f_trade_gate(features, approval_ref="APPROVAL-R13-2026")
        self.assertEqual(GateState.DISABLED, decision.state)
        self.assertIsNone(decision.approval_ref)
        self.assertIn("UNVALIDATED", decision.reasons[0])

    def test_synthetic_validated_report_and_approval_do_not_enable_trade_gate(self) -> None:
        as_of = datetime(2024, 5, 20, 0, 0, tzinfo=timezone.utc)
        features = InstitutionalFeatureSet(
            manager_cik="0001067983",
            target_cusip="037833100",
            as_of=as_of,
            holding_period="2024-03-31",
            quarterly_share_change_pct=Decimal("0.15"),
            portfolio_weight_current=Decimal("0.20"),
            portfolio_weight_change=Decimal("0.02"),
            institutional_consensus_direction=1,
            consecutive_quarters_held=4,
            information_lag_days=45,
            coverage_quality_score=Decimal("1.0"),
            is_point_in_time=True,
            score_status="VALIDATED",
        )
        report = ValidationReport(
            validation_id="audit-passed-001",
            as_of=as_of,
            universe_size=500,
            period_start="2024-01-01",
            period_end="2024-03-31",
            lookahead_leak_detected=False,
            score_status="VALIDATED",
            reasons=("Passed leak and baseline audits",),
        )
        decision = check_13f_trade_gate(features, validation_report=report, approval_ref="APPROVAL-R13-2026")
        self.assertEqual(GateState.DISABLED, decision.state)
        self.assertIsNone(decision.approval_ref)
        self.assertIsNone(decision.validation_ref)
        self.assertIn("No empirical backtest/holdout/cost criteria dataset exists", decision.reasons[0])
        self.assertIn("synthetic validation reports or approval strings", decision.reasons[0])


class TestValidationReportGeneration(unittest.TestCase):
    def test_run_audit_without_baseline_is_unvalidated(self) -> None:
        as_of = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
        filing = Filing13F(
            filing_id="f1",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc1",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(
                datetime(2024, 5, 15, tzinfo=timezone.utc), locator="acc1"
            ),
        )
        report = run_point_in_time_audit(
            validation_id="audit-001",
            as_of=as_of,
            universe_size=500,
            filings=[filing],
            comparisons=[],
            pre_registered_baseline=None,
        )
        self.assertEqual("UNVALIDATED", report.score_status)
        self.assertFalse(report.lookahead_leak_detected)
        self.assertIn("Pre-registered benchmark baseline is missing", report.reasons[0])

    def test_run_audit_with_leak_is_rejected(self) -> None:
        # Filing in future relative to as_of
        as_of = datetime(2024, 5, 1, 0, 0, tzinfo=timezone.utc)
        filing = Filing13F(
            filing_id="f1",
            manager_cik="0001067983",
            manager_name="TEST MGR",
            form=Form13FKind.HR,
            accession="acc1",
            report_period="2024-03-31",
            filed_date="2024-05-15",
            public_availability=PublicAvailability.exact(
                datetime(2024, 5, 15, tzinfo=timezone.utc), locator="acc1"
            ),
        )
        report = run_point_in_time_audit(
            validation_id="audit-002",
            as_of=as_of,
            universe_size=500,
            filings=[filing],
            comparisons=[],
            pre_registered_baseline="buy_and_hold_sp500",
        )
        self.assertEqual("REJECTED", report.score_status)
        self.assertTrue(report.lookahead_leak_detected)


if __name__ == "__main__":
    unittest.main()
