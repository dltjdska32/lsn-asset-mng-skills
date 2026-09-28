"""Read-only binding of typed host portfolio snapshots to immutable run pins.

The personal ledger stores book projections, not a complete marked portfolio.
This adapter therefore reports missing valuation/FX/reserve/order/cost evidence
explicitly and never treats a caller supplied readiness flag as proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from investment_stack.decisions.policy_b import Money
from investment_stack.personal.errors import ProjectionError

if TYPE_CHECKING:
    from investment_stack.evidence.manager import RunDatabaseManager
    from investment_stack.personal.ledger import PersonalLedgerService


@dataclass(frozen=True, slots=True)
class VerifiedCashComponent:
    account_id: str
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class VerifiedLiabilityComponent:
    liability_id: str
    account_id: str | None
    currency: str
    principal: Decimal


@dataclass(frozen=True, slots=True)
class PersonalPolicyBinding:
    run_id: str
    state_version: int | None
    snapshot_id: str | None
    instrument_holding_units: Decimal | None
    cash_components: tuple[VerifiedCashComponent, ...]
    liability_components: tuple[VerifiedLiabilityComponent, ...]
    instrument_holding_value: Money | None
    portfolio_denominator: Money | None
    investable_cash: Money | None
    portfolio_state_bound: bool
    fee_and_lot_ready: bool
    eligible_for_policy_sizing: bool
    unavailable_reasons: tuple[str, ...]
    orders_posted: bool = False


def bind_personal_snapshot(
    run_db: "RunDatabaseManager",
    personal_ledger: "PersonalLedgerService | None",
    *,
    instrument_id: str,
) -> PersonalPolicyBinding:
    """Bind a real personal snapshot row/projection to run.db's immutable pin.

    Posted-entry quantities and cash are independently verified book facts.
    The ledger cannot prove current marks, FX conversions, reserved orders,
    liability completeness, fee schedules, or lot rules, so those values remain
    unavailable and caller strings cannot establish them.
    """
    reasons: list[str] = []
    try:
        context = run_db.fetch_phase6_context()
    except Exception:
        context = {}
        reasons.append("same-run personal pin could not be read from run.db")
    pin = context.get("pinned_personal_state")
    run_id = getattr(run_db, "run_id", "")
    bound = False
    verified = None
    if not isinstance(pin, dict):
        reasons.append("run.db has no pinned personal state")
    elif personal_ledger is None:
        reasons.append("read-only personal ledger service is missing")
    else:
        try:
            verified = personal_ledger.get_verified_portfolio_snapshot_projection(
                expected_personal_db_instance_id=pin.get("personal_db_instance_id"),
                expected_state_version=pin.get("state_version"),
                expected_snapshot_id=pin.get("portfolio_snapshot_id"),
                expected_data_as_of=pin.get("portfolio_data_as_of"),
            )
            bound = True
        except (ProjectionError, OSError, ValueError) as exc:
            reasons.append(f"personal snapshot/projection binding failed: {exc}")

    holding_units = None
    cash_components: tuple[VerifiedCashComponent, ...] = ()
    liability_components: tuple[VerifiedLiabilityComponent, ...] = ()
    holding_value = denominator = investable_cash = None
    if verified is not None:
        matching = [position for position in verified.projection.positions if position.instrument_id == instrument_id]
        holding_units = sum((position.quantity for position in matching), Decimal(0))
        cash_components = tuple(
            VerifiedCashComponent(balance.account_id, balance.currency, balance.balance)
            for balance in verified.projection.cash_balances
        )
        liability_components = tuple(
            VerifiedLiabilityComponent(
                balance.liability_id, balance.account_id, balance.currency, balance.principal
            )
            for balance in verified.projection.liabilities
        )
        if not matching:
            reasons.append("requested instrument has no posted position in pinned projection")
        reasons.extend((
            "verified ledger quantity has no trusted current market value or FX evidence",
            "portfolio denominator may omit market values and liabilities",
            "emergency and planned-spending reserve balances have no verified source contract",
            "pending-order reservations are not verified by the personal ledger contract",
            "fee schedule and instrument lot rules have no verified contract",
        ))

    return PersonalPolicyBinding(
        run_id=run_id,
        state_version=verified.state_version if verified else pin.get("state_version") if isinstance(pin, dict) else None,
        snapshot_id=verified.snapshot_id if verified else pin.get("portfolio_snapshot_id") if isinstance(pin, dict) else None,
        instrument_holding_units=holding_units,
        cash_components=cash_components,
        liability_components=liability_components,
        instrument_holding_value=holding_value,
        portfolio_denominator=denominator,
        investable_cash=investable_cash,
        portfolio_state_bound=bound,
        fee_and_lot_ready=False,
        eligible_for_policy_sizing=False,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "PersonalPolicyBinding", "VerifiedCashComponent", "VerifiedLiabilityComponent",
    "bind_personal_snapshot",
]
