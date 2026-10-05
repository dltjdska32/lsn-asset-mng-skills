"""Institutional analysis package: SEC Form 13F parsing, normalization, comparison, scoring, and validation."""

from investment_stack.institutional.compare import compare_portfolios
from investment_stack.institutional.models import (
    AmendmentType,
    EffectiveHoldingSet,
    Filing13F,
    Form13FKind,
    Holding13F,
    HoldingChange13F,
    HoldingChangeStatus,
    HoldingSet13F,
    InstitutionalFeatureSet,
    InstitutionalPortfolioComparison,
    NoticeStatus,
    PutCall,
    QuantityType,
    ValidationReport,
)
from investment_stack.institutional.normalize import (
    apply_split_adjustment,
    synthesize_effective_holdings,
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

__all__ = [
    # Models
    "AmendmentType",
    "EffectiveHoldingSet",
    "Filing13F",
    "Form13FKind",
    "Holding13F",
    "HoldingChange13F",
    "HoldingChangeStatus",
    "HoldingSet13F",
    "InstitutionalFeatureSet",
    "InstitutionalPortfolioComparison",
    "NoticeStatus",
    "PutCall",
    "QuantityType",
    "ValidationReport",
    # Normalization & synthesis
    "apply_split_adjustment",
    "synthesize_effective_holdings",
    # Comparison
    "compare_portfolios",
    # Scoring & Gate
    "calculate_consensus_direction",
    "check_13f_trade_gate",
    "compute_institutional_features",
    # Validation & Harness
    "run_point_in_time_audit",
    "validate_absence_not_sold_under_confidential_omission",
    "validate_amendment_cutoff_invariance",
    "validate_lookahead_leak",
    "validate_quantity_type_purity",
]
