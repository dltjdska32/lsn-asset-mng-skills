"""Point-in-time institutional feature extraction and strict UNVALIDATED trade gate enforcement."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from investment_stack.contracts.calculation import GateDecision, GateState
from investment_stack.contracts.codec import parse_finite_decimal
from investment_stack.contracts.errors import (
    ContractValidationError,
    PointInTimeError,
    TimezoneValidationError,
    UnapprovedPolicyError,
)
from investment_stack.contracts.institutional import NoticeStatus
from investment_stack.institutional.models import (
    HoldingChangeStatus,
    InstitutionalFeatureSet,
    InstitutionalPortfolioComparison,
    ValidationReport,
)


def compute_institutional_features(
    target_cusip: str,
    manager_cik: str,
    comparisons: Sequence[InstitutionalPortfolioComparison],
    as_of: datetime,
) -> InstitutionalFeatureSet:
    """Compute point-in-time institutional signal features from historical comparison records.

    Strict Rule (REQ R13):
    - Features are generated with score_status="UNVALIDATED".
    - They must not be fed into automated trading or position sizing models.
    """
    if as_of.tzinfo is None:
        raise TimezoneValidationError("as_of must be timezone-aware")

    target_cusip = target_cusip.upper().strip()
    mgr_comparisons = [c for c in comparisons if c.manager_cik == manager_cik and c.is_comparable]
    mgr_comparisons.sort(key=lambda c: c.current_period)

    if not mgr_comparisons:
        return InstitutionalFeatureSet(
            manager_cik=manager_cik,
            target_cusip=target_cusip,
            as_of=as_of,
            holding_period="",
            quarterly_share_change_pct=None,
            portfolio_weight_current=None,
            portfolio_weight_change=None,
            institutional_consensus_direction=None,
            consecutive_quarters_held=0,
            information_lag_days=None,
            coverage_quality_score=None,
            is_point_in_time=True,
            score_status="UNVALIDATED",
        )

    latest_comp = mgr_comparisons[-1]
    holding_period = latest_comp.current_period

    # Find target position in latest comparison
    target_change = next((c for c in latest_comp.changes if c.cusip == target_cusip), None)

    quarterly_pct: Decimal | None = None
    curr_weight: Decimal | None = None
    wt_change: Decimal | None = None
    direction: int | None = None

    if target_change is not None:
        quarterly_pct = target_change.share_change_pct
        curr_weight = target_change.current_weight
        wt_change = target_change.weight_change
        if target_change.status in (HoldingChangeStatus.INCREASED, HoldingChangeStatus.NEW_POSITION):
            direction = 1
        elif target_change.status in (HoldingChangeStatus.DECREASED, HoldingChangeStatus.CLOSED_POSITION):
            direction = -1
        elif target_change.status == HoldingChangeStatus.UNCHANGED:
            direction = 0

    # Calculate consecutive quarters held
    consecutive_quarters = 0
    for comp in reversed(mgr_comparisons):
        ch = next((c for c in comp.changes if c.cusip == target_cusip), None)
        if ch is not None and ch.current_shares is not None and ch.current_shares > Decimal("0"):
            consecutive_quarters += 1
        else:
            break

    # Calculate coverage quality score
    observed_count = sum(
        1 for comp in mgr_comparisons
        if any(ch.cusip == target_cusip for ch in comp.changes)
    )
    complete_count = sum(
        1 for comp in mgr_comparisons
        for ch in comp.changes
        if ch.cusip == target_cusip and ch.notice_status == NoticeStatus.COMPLETE
    )
    coverage_score = (
        Decimal(str(round(complete_count / observed_count, 4)))
        if observed_count else None
    )

    # Comparison records currently do not carry the filing's verified public timestamp.
    # Quarter-end is not publication time, so information age stays unavailable.
    lag_days = None

    return InstitutionalFeatureSet(
        manager_cik=manager_cik,
        target_cusip=target_cusip,
        as_of=as_of,
        holding_period=holding_period,
        quarterly_share_change_pct=quarterly_pct,
        portfolio_weight_current=curr_weight,
        portfolio_weight_change=wt_change,
        institutional_consensus_direction=direction,
        consecutive_quarters_held=consecutive_quarters,
        information_lag_days=lag_days,
        coverage_quality_score=coverage_score,
        is_point_in_time=True,
        score_status="UNVALIDATED",
    )


def calculate_consensus_direction(
    target_cusip: str,
    manager_comparisons: Sequence[InstitutionalPortfolioComparison],
) -> int | None:
    """Return descriptive direction, or None when there are no comparable observations.

    This is an unvalidated research feature only; it is not an investment score.
    """
    target_cusip = target_cusip.upper().strip()
    net_score = 0
    observed = False
    for comp in manager_comparisons:
        if not comp.is_comparable:
            continue
        ch = next((c for c in comp.changes if c.cusip == target_cusip), None)
        if ch is None:
            continue
        if ch.status in (HoldingChangeStatus.INCREASED, HoldingChangeStatus.NEW_POSITION):
            net_score += 1
            observed = True
        elif ch.status in (HoldingChangeStatus.DECREASED, HoldingChangeStatus.CLOSED_POSITION):
            net_score -= 1
            observed = True
        elif ch.status == HoldingChangeStatus.UNCHANGED:
            observed = True

    if not observed:
        return None

    if net_score > 0:
        return 1
    if net_score < 0:
        return -1
    return 0


def check_13f_trade_gate(
    features: InstitutionalFeatureSet,
    *,
    validation_report: ValidationReport | None = None,
    approval_ref: str | None = None,
) -> GateDecision:
    """Strict governance gate preventing unvalidated 13F scores from driving trade decisions.

    Strict Invariants (REQ R13):
    - 13F signal weights must NOT drive trade decisions in this runtime.
    - Even if a caller passes a synthetic ValidationReport with score_status='VALIDATED'
      or an approval_ref string, trade ENABLEMENT must not be invented because no empirical
      out-of-sample backtest, holdout dataset, transaction cost model, or formal governance
      criteria has been executed or validated in current runtime.
    - The status remains UNVALIDATED, and gate state remains strictly DISABLED.
    - Connection to Session A's typed trusted gate context protocol is preserved as an external
      integration requirement in handoffs.
    """
    assessed_at = datetime.now(timezone.utc).isoformat()
    return GateDecision(
        gate_id="gate:13f_trade_consumption",
        purpose="13F_WEIGHT",
        policy_id="policy:13f_unapproved_model",
        policy_version="0.2",
        policy_hash="unapproved_13f_policy_gate",
        state=GateState.DISABLED,
        approval_ref=None,
        validation_ref=None,
        prerequisites=(
            "executed_leak_free_point_in_time_backtest",
            "pre_registered_baseline_comparison",
            "holdout_cost_criteria_validation",
            "trusted_gate_context_integration",
        ),
        reasons=(
            "13F score status is UNVALIDATED; 13F signal weights must not drive trade decisions per REQ R13. "
            "No empirical backtest/holdout/cost criteria dataset exists in current runtime; "
            "trade enablement cannot be invented by passing synthetic validation reports or approval strings.",
        ),
        assessed_at=assessed_at,
    )


__all__ = [
    "calculate_consensus_direction",
    "check_13f_trade_gate",
    "compute_institutional_features",
]
