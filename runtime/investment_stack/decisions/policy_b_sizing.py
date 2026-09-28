"""Pure, non-posting lot and fee arithmetic for D12 B simulations.

This helper cannot verify a policy's market/personal provenance or a trading
rule receipt. Its output is arithmetic only, never a released action proposal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from investment_stack.decisions.action import calculate_budget_arithmetic
from investment_stack.decisions.policy_b import PolicyBResult


@dataclass(frozen=True, slots=True)
class TradingRules:
    currency: str
    lot_size: Decimal
    price_tick: Decimal
    fee_per_unit: Decimal
    source_ref: str
    source_verified: bool = False


@dataclass(frozen=True, slots=True)
class SizedTier:
    limit_price: Decimal
    quantity: Decimal
    maximum_cost: Decimal
    maximum_fees: Decimal


@dataclass(frozen=True, slots=True)
class PolicyBSizingResult:
    status: str
    tiers: tuple[SizedTier, ...]
    total_maximum_cost: Decimal | None
    unavailable_reasons: tuple[str, ...]
    orders_posted: bool = False


def size_policy_b_tranches(policy: PolicyBResult, rules: TradingRules | None) -> PolicyBSizingResult:
    """Lot-round three entry budgets without authorizing or placing an order."""
    reasons: list[str] = []
    if not isinstance(policy, PolicyBResult) or policy.status != "CONDITIONAL":
        reasons.append("complete conditional D12 B result is missing")
    elif (policy.additions_stopped or policy.max_total_add_budget is None
          or not isinstance(policy.max_total_add_budget, Decimal)
          or not policy.max_total_add_budget.is_finite()
          or policy.max_total_add_budget <= 0 or len(policy.entry_tiers) != 3):
        reasons.append("D12 B has no positive three-tranche add budget")
    if (not isinstance(rules, TradingRules) or rules.source_verified is not True
            or not isinstance(rules.source_ref, str) or not rules.source_ref.strip()
            or not isinstance(rules.currency, str) or not rules.currency.strip()):
        reasons.append("verified trading rule receipt is missing")
    elif isinstance(policy, PolicyBResult) and rules.currency != policy.evaluation_currency:
        reasons.append("trading currency and evaluated policy currency differ; verified FX conversion is required")
    if reasons:
        return PolicyBSizingResult("WAIT", (), None, tuple(reasons))
    assert isinstance(rules, TradingRules) and isinstance(policy, PolicyBResult)
    numeric = (rules.lot_size, rules.price_tick, rules.fee_per_unit)
    if (any(not isinstance(item, Decimal) or not item.is_finite() for item in numeric)
            or rules.lot_size <= 0 or rules.price_tick <= 0 or rules.fee_per_unit < 0):
        return PolicyBSizingResult("WAIT", (), None, ("trading lot, tick, or fee is invalid",))

    sized: list[SizedTier] = []
    for tier in policy.entry_tiers:
        if (not isinstance(tier.price, Decimal) or not tier.price.is_finite()
                or tier.price <= 0 or not isinstance(tier.tranche_budget, Decimal)
                or not tier.tranche_budget.is_finite() or tier.tranche_budget <= 0):
            return PolicyBSizingResult("WAIT", (), None, ("D12 B entry price or tranche budget is invalid",))
        limit_price = (tier.price / rules.price_tick).to_integral_value(rounding=ROUND_DOWN) * rules.price_tick
        if limit_price <= 0:
            return PolicyBSizingResult("WAIT", (), None, ("entry price falls below one verified tick",))
        arithmetic = calculate_budget_arithmetic(
            tier.tranche_budget, limit_price, rules.lot_size, rules.fee_per_unit,
            rules.currency, policy.evaluation_currency,
        )
        if not arithmetic.is_valid:
            return PolicyBSizingResult("WAIT", (), None, arithmetic.reasons)
        sized.append(SizedTier(limit_price, arithmetic.quantity,
                               arithmetic.total_cost, arithmetic.total_fees))
    total = sum((tier.maximum_cost for tier in sized), Decimal(0))
    if total > policy.max_total_add_budget:
        return PolicyBSizingResult("WAIT", (), None, ("rounded tranches exceed policy add budget",))
    return PolicyBSizingResult("ARITHMETIC_ONLY", tuple(sized), total,
                               ("pinned market/personal/trading rule release receipt is unavailable",))
