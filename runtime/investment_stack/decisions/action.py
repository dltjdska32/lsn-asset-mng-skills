"""Non-posting action proposals and conditional budget calculations."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from typing import Mapping

from investment_stack.contracts.calculation import InvestmentDecision


@dataclass(frozen=True, slots=True)
class Tranche:
    quantity: Decimal
    price: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Non-posting conditionally calculated action proposal."""
    decision: InvestmentDecision
    state_version: str
    currency: str | None = None
    non_posting: bool = True
    tranches: tuple[Tranche, ...] = ()
    conditions: tuple[str, ...] = ()
    rationale_calculation_ids: tuple[str, ...] = ()
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.non_posting:
            raise ValueError("ActionProposal must be non_posting=True")


def _check_decimal(val: object, min_val: Decimal | None = None, max_val: Decimal | None = None, exclusive_min: bool = False, exclusive_max: bool = False) -> Decimal | None:
    if not isinstance(val, Decimal) or val.is_nan() or val.is_infinite():
        return None
    if min_val is not None:
        if exclusive_min and val <= min_val:
            return None
        if not exclusive_min and val < min_val:
            return None
    if max_val is not None:
        if exclusive_max and val >= max_val:
            return None
        if not exclusive_max and val > max_val:
            return None
    return val

@dataclass(frozen=True, slots=True)
class BudgetArithmeticResult:
    """Pure arithmetic output for budget, floor, and lot logic, separate from investment action proposals."""
    quantity: Decimal
    total_cost: Decimal
    total_fees: Decimal
    is_valid: bool
    reasons: tuple[str, ...]

def calculate_budget_arithmetic(
    budget_limit: object,
    price: object,
    lot_size: object,
    fees_per_unit: object,
    quote_currency: object,
    budget_currency: object,
    fx_rate: object | None = None,
) -> BudgetArithmeticResult:
    """
    Pure arithmetic logic for computing max lot-rounded quantity within budget.
    Ensures fees are per-unit in quote currency, and total cost in budget currency.
    Validates domain limits and returns invalid result instead of throwing exceptions.
    """
    if not isinstance(quote_currency, str) or not quote_currency.strip():
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Missing or invalid quote_currency.",))
    if not isinstance(budget_currency, str) or not budget_currency.strip():
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Missing or invalid budget_currency.",))

    v_budget = _check_decimal(budget_limit, min_val=Decimal("0"))
    v_price = _check_decimal(price, min_val=Decimal("0"), exclusive_min=True)
    v_lot = _check_decimal(lot_size, min_val=Decimal("0"), exclusive_min=True)
    v_fees = _check_decimal(fees_per_unit, min_val=Decimal("0"))
    
    if v_budget is None or v_price is None or v_lot is None or v_fees is None:
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Invalid or negative numeric parameters (budget, price, lot, fees).",))

    if quote_currency == budget_currency:
        actual_fx = Decimal("1")
    else:
        actual_fx = _check_decimal(fx_rate, min_val=Decimal("0"), exclusive_min=True)
        if actual_fx is None:
            return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Missing or invalid FX rate for cross-currency.",))
    
    # unit_cost in quote currency
    unit_cost_quote = v_price + v_fees
    # unit_cost in budget currency
    unit_cost_budget = unit_cost_quote * actual_fx
    
    if unit_cost_budget <= Decimal("0"):
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Calculated unit cost is 0 or negative.",))

    raw_qty = v_budget / unit_cost_budget
    qty = (raw_qty / v_lot).to_integral_value(rounding=ROUND_DOWN) * v_lot
    
    if qty <= Decimal("0"):
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Budget insufficient for 1 lot size.",))
        
    total_cost = qty * unit_cost_budget
    if total_cost > v_budget:
        return BudgetArithmeticResult(Decimal("0"), Decimal("0"), Decimal("0"), False, ("Arithmetic error: Tranche cost exceeds budget limit.",))
        
    total_fees = qty * v_fees * actual_fx
    return BudgetArithmeticResult(qty, total_cost, total_fees, True, ())


def calculate_action_proposal(
    intended_decision: InvestmentDecision,
    state_version: str,
    policy: Mapping[str, str | Decimal | bool | None] | None,
    price: Decimal | None,
    value: Decimal | None,
    personal_state: Mapping[str, str | Decimal | bool | None] | None,
    rationale_calculation_ids: tuple[str, ...] = ()
) -> ActionProposal:
    """
    Calculate conditional action proposal. 
    Outputs WAIT and NO tranches since proper provenance/registry verification of string keys is absent.
    Prevents leaking unverified executable quantities or prices in public strings.
    """
    reasons = []

    if not policy:
        reasons.append("Missing policy.")
    else:
        # String approval refs are insufficient provenance at this stage.
        if not policy.get("approval_ref") and not policy.get("policy_version"):
            reasons.append("Policy lacks explicit approval_ref or policy_version.")
            
    if not personal_state:
        reasons.append("Missing personal pinned state.")
    else:
        if personal_state.get("state_version") != state_version:
            reasons.append("Personal state version mismatch.")

    if reasons:
        return ActionProposal(
            decision=InvestmentDecision.WAIT,
            state_version=state_version,
            unavailable_reasons=tuple(reasons),
            rationale_calculation_ids=rationale_calculation_ids,
        )

    uncertainties = []
    if personal_state.get("unpriced_assets") or personal_state.get("unpriced_liabilities"):
        uncertainties.append("Unpriced assets/liabilities present.")
    if personal_state.get("pending_orders"):
        uncertainties.append("Pending orders present.")
    
    quote_currency = policy.get("quote_currency")
    budget_currency = policy.get("budget_currency")
    if not isinstance(quote_currency, str) or not quote_currency.strip():
        uncertainties.append("Missing quote_currency in policy.")
    if not isinstance(budget_currency, str) or not budget_currency.strip():
        uncertainties.append("Missing budget_currency in policy.")

    if uncertainties:
        return ActionProposal(
            decision=InvestmentDecision.WAIT,
            state_version=state_version,
            unavailable_reasons=tuple(uncertainties),
            rationale_calculation_ids=rationale_calculation_ids,
        )

    if intended_decision in (InvestmentDecision.BUY, InvestmentDecision.ADD_BUY):
        if policy.get("13f_gate") != "ENABLED" or policy.get("chart_gate") != "ENABLED":
            return ActionProposal(
                decision=InvestmentDecision.WAIT,
                state_version=state_version,
                currency=str(budget_currency),
                unavailable_reasons=("Required gates are not explicitly ENABLED.",),
                rationale_calculation_ids=rationale_calculation_ids,
            )

    return ActionProposal(
        decision=InvestmentDecision.WAIT,
        state_version=state_version,
        currency=str(budget_currency),
        tranches=(),
        conditions=("Awaiting Domain A integration and secure policy provenance registry.",),
        rationale_calculation_ids=rationale_calculation_ids,
    )
