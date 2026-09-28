"""Read-only binding of typed host portfolio snapshots to immutable run pins.

The personal ledger stores book projections, not a complete marked portfolio.
This adapter therefore reports missing valuation/FX/reserve/order/cost evidence
explicitly and never treats a caller supplied readiness flag as proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from investment_stack.evidence.manager import RunDatabaseManager


@dataclass(frozen=True, slots=True)
class SnapshotAmount:
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class HoldingMark:
    instrument_id: str
    quantity: Decimal
    market_value: SnapshotAmount | None
    evaluation_value: SnapshotAmount | None
    valuation_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PersonalPortfolioSnapshot:
    """Typed payload supplied by a trusted host for a pinned ledger snapshot."""

    personal_db_instance_id: str
    state_version: int
    snapshot_id: str
    data_as_of: str
    evaluation_currency: str
    holdings: tuple[HoldingMark, ...]
    cash: tuple[SnapshotAmount, ...]
    emergency_reserve: SnapshotAmount | None = None
    planned_spending_reserve: SnapshotAmount | None = None
    pending_order_reservations: tuple[SnapshotAmount, ...] | None = None
    liabilities: tuple[SnapshotAmount, ...] | None = None
    unpriced_asset_count: int | None = None
    fee_schedule_reference: str | None = None
    lot_rule_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PersonalPolicyBinding:
    run_id: str
    state_version: int | None
    snapshot_id: str | None
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
    snapshot: PersonalPortfolioSnapshot | None,
    *,
    instrument_id: str,
) -> PersonalPolicyBinding:
    """Bind snapshot identity to run.db and derive only fully supported values.

    The existing ledger cannot prove current marks, FX conversions, reserved
    orders, liability completeness, fee schedules, or lot rules. Caller strings
    cannot establish those facts; until the host provides dedicated evidence,
    the adapter returns unavailable policy values and explicit reasons.
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
    if snapshot is None:
        reasons.append("typed personal portfolio snapshot is missing")
    elif not isinstance(snapshot, PersonalPortfolioSnapshot):
        reasons.append("personal snapshot has an unsupported type")
    if not isinstance(pin, dict):
        reasons.append("run.db has no pinned personal state")
    elif isinstance(snapshot, PersonalPortfolioSnapshot):
        bound = (
            pin.get("state_version") == snapshot.state_version
            and pin.get("personal_db_instance_id") == snapshot.personal_db_instance_id
            and pin.get("portfolio_snapshot_id") == snapshot.snapshot_id
            and pin.get("portfolio_data_as_of") == snapshot.data_as_of
            and isinstance(snapshot.state_version, int)
            and not isinstance(snapshot.state_version, bool)
            and snapshot.state_version >= 0
            and bool(snapshot.personal_db_instance_id)
            and bool(snapshot.snapshot_id)
        )
        if not bound:
            reasons.append("typed snapshot identity does not match the immutable same-run pin")

    holding_value = denominator = investable_cash = None
    if bound and isinstance(snapshot, PersonalPortfolioSnapshot):
        if not any(h.instrument_id == instrument_id for h in snapshot.holdings):
            reasons.append("requested instrument is absent from pinned snapshot")
        reasons.extend((
            "portfolio snapshot has no trusted current valuation and FX evidence",
            "portfolio denominator may omit unpriced assets or liabilities",
            "emergency and planned-spending reserve balances lack verified source evidence",
            "pending-order reservations are not verified by the personal ledger contract",
            "fee schedule and instrument lot rules have no verified contract",
        ))
        if snapshot.unpriced_asset_count is None:
            reasons.append("unpriced asset coverage is unknown")

    # Keep the received IDs visible for audit while never converting unsupported
    # host assertions into verified policy inputs.
    return PersonalPolicyBinding(
        run_id=run_id,
        state_version=snapshot.state_version if isinstance(snapshot, PersonalPortfolioSnapshot) else None,
        snapshot_id=snapshot.snapshot_id if isinstance(snapshot, PersonalPortfolioSnapshot) else None,
        instrument_holding_value=holding_value,
        portfolio_denominator=denominator,
        investable_cash=investable_cash,
        portfolio_state_bound=bound,
        fee_and_lot_ready=False,
        eligible_for_policy_sizing=False,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "HoldingMark", "PersonalPortfolioSnapshot", "PersonalPolicyBinding",
    "SnapshotAmount", "bind_personal_snapshot",
]
