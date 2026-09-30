"""Read-only binding of typed host portfolio snapshots to immutable run pins.

The personal ledger stores book projections, not a complete marked portfolio.
This adapter therefore reports missing valuation/FX/reserve/order/cost evidence
explicitly and never treats a caller supplied readiness flag as proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import sqlite3
from typing import TYPE_CHECKING

from investment_stack.decisions.policy_b import Money
from investment_stack.decisions.policy_b_market import load_policy_b_market_evidence
from investment_stack.decisions.policy_b_sizing import TradingRules
from investment_stack.evidence.source_receipt import (
    load_source_payload,
    source_table_available,
    verify_fx_body,
    verify_trading_rule_body,
)
from investment_stack.personal.errors import ProjectionError
from investment_stack.storage.sqlite import sqlite_readonly_connection

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
    trading_rules: TradingRules | None = None
    orders_posted: bool = False


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _convert(amount: Decimal, currency: str, evaluation: str, rates: dict[tuple[str, str], Decimal]) -> Decimal | None:
    code = currency.upper()
    if code == evaluation:
        return amount
    rate = rates.get((code, evaluation))
    if rate is None:
        return None
    return amount * rate


def _load_fx_rates(
    connection: sqlite3.Connection, *, run_id: str, evaluation: str, cutoff: datetime,
) -> dict[tuple[str, str], Decimal]:
    if not source_table_available(connection):
        return {}
    rows = connection.execute(
        "SELECT evidence_id, instrument_id, observed_at, retrieved_at FROM evidence "
        "WHERE run_id = ? AND evidence_type = 'fx' AND metric = 'fx_rate' AND selection_state = 'SELECTED'",
        (run_id,),
    ).fetchall()
    rates: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        instrument = str(row["instrument_id"] or "")
        if not instrument.startswith("FX:") or "/" not in instrument:
            continue
        pair = instrument.removeprefix("FX:")
        base, quote = pair.split("/", 1)
        loaded = load_source_payload(connection, run_id=run_id, evidence_id=str(row["evidence_id"]))
        observed, retrieved = _aware(row["observed_at"]), _aware(row["retrieved_at"])
        if loaded is None or observed is None or retrieved is None or observed > cutoff or retrieved > cutoff:
            continue
        payload, parser_id = loaded
        if parser_id != "yahoo_fx_v1":
            continue
        per_usd, _reason = verify_fx_body(
            payload, base=base, quote=quote, observed_at=observed, retrieved_at=retrieved,
        )
        if per_usd is None or base != "USD":
            continue
        if quote.upper() == evaluation:
            rates[(base, evaluation)] = per_usd
        if base == evaluation:
            rates[(quote.upper(), evaluation)] = Decimal(1) / per_usd
    return rates


def _load_trading_rules(
    connection: sqlite3.Connection, *, run_id: str, instrument_id: str, currency: str, cutoff: datetime,
) -> TradingRules | None:
    if not source_table_available(connection):
        return None
    rows = connection.execute(
        "SELECT evidence_id, value_text FROM evidence WHERE run_id = ? AND instrument_id = ? "
        "AND evidence_type = 'trading_rule' AND metric = 'trading_rule' AND selection_state = 'SELECTED'",
        (run_id, instrument_id),
    ).fetchall()
    if len(rows) != 1:
        return None
    loaded = load_source_payload(connection, run_id=run_id, evidence_id=str(rows[0]["evidence_id"]))
    if loaded is None:
        return None
    payload, parser_id = loaded
    if parser_id != "exchange_trading_rule_v1":
        return None
    numbers, reason = verify_trading_rule_body(
        payload, instrument_id=instrument_id, currency=currency, cutoff=cutoff,
    )
    if numbers is None or reason is not None:
        return None
    return TradingRules(
        currency, numbers["lot_size"], numbers["price_tick"], numbers["fee_per_unit"],
        f"source-document:{rows[0]['evidence_id']}", True,
    )


def bind_personal_snapshot(
    run_db: "RunDatabaseManager",
    personal_ledger: "PersonalLedgerService | None",
    *,
    instrument_id: str,
    evaluation_currency: str | None = None,
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
    rules = None
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
        currency = evaluation_currency.strip().upper() if isinstance(evaluation_currency, str) else ""
        database_path = getattr(run_db, "database_path", None)
        metadata = context.get("run_metadata") if isinstance(context, dict) else None
        as_of = metadata.get("analysis_as_of") if isinstance(metadata, dict) else None
        cutoff = _aware(as_of)
        rules = None
        if not currency or database_path is None or cutoff is None:
            reasons.extend((
                "verified ledger quantity has no trusted current market value or FX evidence",
                "portfolio denominator may omit market values and liabilities",
                "emergency and planned-spending reserve balances have no verified source contract",
                "pending-order reservations are not verified by the personal ledger contract",
                "fee schedule and instrument lot rules have no verified contract",
            ))
        else:
            covered, reservations = personal_ledger.list_cash_reservations(verified.state_version)
            rates: dict[tuple[str, str], Decimal] = {}
            try:
                with sqlite_readonly_connection(database_path) as connection:
                    connection.row_factory = sqlite3.Row
                    rates = _load_fx_rates(connection, run_id=run_id, evaluation=currency, cutoff=cutoff)
                    rules = _load_trading_rules(
                        connection, run_id=run_id, instrument_id=instrument_id, currency=currency, cutoff=cutoff,
                    )
            except (OSError, sqlite3.Error, ValueError) as exc:
                reasons.append(f"valuation evidence could not be read safely: {type(exc).__name__}")
            quotes = {}
            marked_positions: list[Decimal] = []
            marks_complete = True
            for position in verified.projection.positions:
                if position.quantity == 0:
                    continue
                market = load_policy_b_market_evidence(
                    database_path, run_id=run_id, instrument_id=position.instrument_id,
                    as_of=cutoff.isoformat(),
                )
                quote = market.quote_per_share
                quotes[position.instrument_id] = quote
                if quote is None or not quote.verified:
                    marks_complete = False
                    continue
                marked = _convert(position.quantity * quote.amount, quote.currency, currency, rates)
                if marked is None:
                    marks_complete = False
                    continue
                marked_positions.append(marked)
            selected_quote = quotes.get(instrument_id)
            if (
                holding_units is not None and selected_quote is not None and selected_quote.verified
            ):
                holding_value_amount = _convert(holding_units * selected_quote.amount, selected_quote.currency, currency, rates)
                if holding_value_amount is not None:
                    holding_value = Money(holding_value_amount, currency, True)
            cash_amount = Decimal(0)
            cash_complete = True
            for component in cash_components:
                converted = _convert(component.amount, component.currency, currency, rates)
                if converted is None:
                    cash_complete = False
                    break
                cash_amount += converted
            liability_amount = Decimal(0)
            liability_complete = True
            for component in liability_components:
                converted = _convert(component.principal, component.currency, currency, rates)
                if converted is None:
                    liability_complete = False
                    break
                liability_amount += converted
            reserve_amount = Decimal(0)
            reserve_complete = covered
            if covered:
                for reservation in reservations:
                    converted = _convert(reservation.amount, reservation.currency, currency, rates)
                    if converted is None:
                        reserve_complete = False
                        break
                    reserve_amount += converted
            if marks_complete and cash_complete and liability_complete:
                denominator_amount = sum(marked_positions, Decimal(0)) + cash_amount - liability_amount
                if denominator_amount > 0:
                    denominator = Money(denominator_amount, currency, True)
            if cash_complete and reserve_complete:
                investable_amount = cash_amount - reserve_amount
                if investable_amount >= 0:
                    investable_cash = Money(investable_amount, currency, True)
            if holding_value is None:
                reasons.append("verified ledger quantity has no trusted current market value or FX evidence")
            if denominator is None:
                reasons.append("portfolio denominator may omit market values and liabilities")
            if not covered:
                reasons.append("emergency and planned-spending reserve balances have no verified source contract")
                reasons.append("pending-order reservations are not verified by the personal ledger contract")
            elif investable_cash is None:
                reasons.append("reserved cash exceeds posted cash after FX conversion")
            if rules is None:
                reasons.append("fee schedule and instrument lot rules have no verified contract")

    eligible = (
        holding_value is not None and denominator is not None and investable_cash is not None
        and rules is not None and holding_units is not None and bound
    )
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
        fee_and_lot_ready=rules is not None,
        eligible_for_policy_sizing=eligible,
        trading_rules=rules,
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "PersonalPolicyBinding", "VerifiedCashComponent", "VerifiedLiabilityComponent",
    "bind_personal_snapshot",
]
