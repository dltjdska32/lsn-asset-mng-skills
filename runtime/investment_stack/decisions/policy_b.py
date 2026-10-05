"""Pure arithmetic evaluator for the adopted D12 B policy.

This module never places orders or changes portfolio state. Callers remain
responsible for sourcing and verifying the pinned personal state and evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from investment_stack.calculations.position_policy import CASH_FLOOR


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str
    verified: bool = False


@dataclass(frozen=True)
class EntryPricePrerequisites:
    """Readiness attestations populated only by a trusted, state-aware host.

    These flags are not provenance verification. The evaluator has no access to
    persisted run or personal records; the host must bind and verify those
    records before constructing this complete bundle.
    """

    valuation_provenance_verified: bool
    pinned_personal_state_verified: bool
    reserves_excluded: bool
    transaction_costs_verified: bool
    trade_units_verified: bool


@dataclass(frozen=True)
class PolicyBInput:
    evaluation_currency: str
    fair_value_per_share: Optional[Money] = None
    optimistic_fair_value_per_share: Optional[Money] = None
    quote_per_share: Optional[Money] = None
    portfolio_value: Optional[Money] = None
    cash: Optional[Money] = None
    holding_value: Optional[Money] = None
    holding_units: Optional[Decimal] = None
    holding_units_verified: Optional[bool] = None
    approved_risk_budget: Optional[Money] = None
    thesis_impaired: Optional[bool] = None
    entry_price_prerequisites: Optional[EntryPricePrerequisites] = None


@dataclass(frozen=True)
class EntryTier:
    price: Decimal
    fraction_of_fair_value: Decimal
    tranche_budget: Decimal


@dataclass(frozen=True)
class PolicyBResult:
    status: str
    unavailable_reasons: tuple[str, ...]
    evaluation_currency: str
    entry_tiers: tuple[EntryTier, ...]
    max_total_add_budget: Optional[Decimal]
    cash_floor: Optional[Decimal]
    concentration_headroom: Optional[Decimal]
    additions_stopped: bool
    stop_reasons: tuple[str, ...]
    reduction_triggers: tuple[str, ...]
    candidate_reduction_fraction: Optional[Decimal]
    candidate_reduction_units: Optional[Decimal]
    candidate_reduction_value: Optional[Decimal]
    orders_posted: bool = False


_D = Decimal
_TIER_FRACTIONS = (_D("0.80"), _D("0.75"), _D("0.70"))


def _decimal(value: object, label: str, reasons: list[str], *, positive: bool = False) -> Optional[Decimal]:
    if not isinstance(value, Decimal):
        reasons.append(f"{label} must be supplied as Decimal")
        return None
    result = value
    if not result.is_finite() or result < 0 or (positive and result == 0):
        reasons.append(f"{label} must be finite and {'positive' if positive else 'non-negative'}")
        return None
    return result


def evaluate_policy_b(inputs: PolicyBInput) -> PolicyBResult:
    """Evaluate B thresholds and budgets without side effects.

    All currency-denominated inputs must use the caller's verified evaluation
    currency. Missing/invalid prerequisites yield WAIT with explicit reasons.
    """
    reasons: list[str] = []
    currency = inputs.evaluation_currency.strip().upper() if isinstance(inputs.evaluation_currency, str) else ""
    if not currency:
        reasons.append("evaluation currency is missing")

    money_fields = {
        "fair value per share": inputs.fair_value_per_share,
        "optimistic fair value per share": inputs.optimistic_fair_value_per_share,
        "quote per share": inputs.quote_per_share,
        "portfolio value": inputs.portfolio_value,
        "cash": inputs.cash,
        "holding value": inputs.holding_value,
    }
    amounts: dict[str, Optional[Decimal]] = {}
    verified_matches: dict[str, bool] = {}
    for label, money in money_fields.items():
        if money is None:
            reasons.append(f"{label} is missing")
            amounts[label] = None
            verified_matches[label] = False
            continue
        if not isinstance(money, Money):
            reasons.append(f"{label} is invalid")
            amounts[label] = None
            verified_matches[label] = False
            continue
        verified = money.verified is True
        if not verified:
            reasons.append(f"{label} is not verified")
        mc = money.currency.strip().upper() if isinstance(money.currency, str) else ""
        if not mc or (currency and mc != currency):
            reasons.append(f"{label} currency does not match evaluation currency")
        amounts[label] = _decimal(money.amount, label, reasons, positive=label.endswith("per share") or label == "portfolio value")
        verified_matches[label] = verified and bool(currency) and mc == currency and amounts[label] is not None

    approved: Optional[Decimal] = None
    if inputs.approved_risk_budget is not None:
        risk_budget = inputs.approved_risk_budget
        if not isinstance(risk_budget, Money):
            reasons.append("approved risk budget is invalid")
        else:
            if risk_budget.verified is not True:
                reasons.append("approved risk budget is not verified")
            risk_currency = risk_budget.currency.strip().upper() if isinstance(risk_budget.currency, str) else ""
            if not risk_currency or (currency and risk_currency != currency):
                reasons.append("approved risk budget currency does not match evaluation currency")
            approved = _decimal(risk_budget.amount, "approved risk budget", reasons)
            if approved is not None and (risk_budget.verified is not True or not currency or risk_currency != currency):
                approved = None

    units = _decimal(inputs.holding_units, "holding units", reasons) if inputs.holding_units is not None else None
    if inputs.holding_units is None:
        reasons.append("holding units is missing")
    if inputs.holding_units_verified is not True:
        reasons.append("holding units are not verified")
    if inputs.thesis_impaired is None:
        reasons.append("thesis status is missing")
    elif not isinstance(inputs.thesis_impaired, bool):
        reasons.append("thesis status is invalid")
    elif inputs.thesis_impaired:
        reasons.append("impaired thesis blocks entry price levels and add budget")
    prerequisites = inputs.entry_price_prerequisites
    prerequisite_fields = (
        "valuation_provenance_verified",
        "pinned_personal_state_verified",
        "reserves_excluded",
        "transaction_costs_verified",
        "trade_units_verified",
    )
    if not isinstance(prerequisites, EntryPricePrerequisites):
        reasons.append("complete entry price prerequisites are missing")
    else:
        for field in prerequisite_fields:
            if getattr(prerequisites, field) is not True:
                reasons.append(f"entry price prerequisite {field} is not verified")
    fv = amounts["fair value per share"]
    optimistic = amounts["optimistic fair value per share"]
    quote = amounts["quote per share"]
    portfolio = amounts["portfolio value"]
    cash = amounts["cash"]
    holding = amounts["holding value"]
    inconsistent_portfolio_state = (
        (holding is not None and portfolio is not None and holding > portfolio)
        or (cash is not None and portfolio is not None and cash > portfolio)
        or (cash is not None and holding is not None and portfolio is not None and cash + holding > portfolio)
    )
    if holding is not None and portfolio is not None and holding > portfolio:
        reasons.append("holding value exceeds portfolio value")
    if cash is not None and portfolio is not None and cash > portfolio:
        reasons.append("cash exceeds portfolio value")
    if cash is not None and holding is not None and portfolio is not None and cash <= portfolio and holding <= portfolio and cash + holding > portfolio:
        reasons.append("cash plus holding value exceeds portfolio value")
    if units is not None and units == 0 and holding is not None and holding > 0:
        reasons.append("positive holding value requires positive holding units")

    entry_tiers: tuple[EntryTier, ...] = ()
    base_currency = inputs.fair_value_per_share.currency.strip().upper() if isinstance(inputs.fair_value_per_share, Money) and isinstance(inputs.fair_value_per_share.currency, str) else ""
    base_verified = verified_matches.get("fair value per share", False)
    if fv is not None and base_verified and currency and base_currency == currency and not reasons:
        entry_tiers = tuple(EntryTier(fv * factor, factor, _D(0)) for factor in _TIER_FRACTIONS)

    floor = portfolio * CASH_FLOOR if verified_matches.get("portfolio value") and portfolio is not None else None
    cash_available = max(cash - floor, _D(0)) if cash is not None and floor is not None else None
    # v7 concentration is reviewed in capital competition; no fixed position cap.
    headroom = None
    budget: Optional[Decimal] = None
    if not reasons and cash_available is not None and approved is not None:
        budget = min(max(cash_available, _D(0)), approved)
        tranche = budget / _D(3)
        tranche_budgets = (tranche, tranche, budget - tranche * _D(2))
        entry_tiers = tuple(EntryTier(t.price, t.fraction_of_fair_value, tranche_budgets[i]) for i, t in enumerate(entry_tiers))

    if approved is None:
        reasons.append("verified allocation risk budget unavailable; v7 concentration review required")

    stop_reasons: list[str] = []
    if reasons:
        stop_reasons.append("required inputs unavailable")
    if inputs.thesis_impaired:
        stop_reasons.append("investment thesis impaired")
    if cash_available == 0:
        stop_reasons.append("cash is at or below the 10% investable portfolio floor")
    if approved == 0:
        stop_reasons.append("verified host risk budget is zero")
    additions_stopped = bool(stop_reasons)
    if additions_stopped:
        if budget is not None:
            budget = _D(0)
        entry_tiers = tuple(EntryTier(t.price, t.fraction_of_fair_value, _D(0)) for t in entry_tiers)

    reduction: list[str] = []
    candidate_fraction: Optional[Decimal] = None
    candidate_units: Optional[Decimal] = None
    candidate_value: Optional[Decimal] = None
    if inputs.thesis_impaired is True:
        reduction.append("investment thesis impaired; review reduction")
    if (
        not inconsistent_portfolio_state
        and verified_matches.get("quote per share")
        and verified_matches.get("optimistic fair value per share")
        and verified_matches.get("holding value")
        and inputs.holding_units_verified is True
        and holding is not None
        and holding > 0
        and units is not None
        and units > 0
        and quote is not None
        and optimistic is not None
        and quote >= optimistic * _D("1.2")
    ):
        reduction.append("quote at or above 1.2x verified optimistic fair value; review 1/3 reduction")
        candidate_fraction = _D(1) / _D(3)

    return PolicyBResult(
        status="WAIT" if reasons else "CONDITIONAL",
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
        evaluation_currency=currency,
        entry_tiers=entry_tiers,
        max_total_add_budget=budget,
        cash_floor=floor,
        concentration_headroom=headroom,
        additions_stopped=additions_stopped,
        stop_reasons=tuple(stop_reasons),
        reduction_triggers=tuple(reduction),
        candidate_reduction_fraction=candidate_fraction,
        candidate_reduction_units=candidate_units,
        candidate_reduction_value=candidate_value,
    )
