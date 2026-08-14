"""Deterministic rebuildable projections derived only from posted ledger entries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from investment_stack.personal.decimal import ZERO, decode_decimal, encode_decimal
from investment_stack.personal.errors import ProjectionError
from investment_stack.personal.intent import CostBasisStatus


@dataclass(frozen=True, slots=True)
class Position:
    account_id: str
    instrument_id: str
    quantity: Decimal
    cost_basis_status: CostBasisStatus
    total_cost: Decimal | None
    average_unit_cost: Decimal | None
    currency: str | None
    state_version: int


@dataclass(frozen=True, slots=True)
class CashBalance:
    account_id: str
    currency: str
    balance: Decimal
    state_version: int


@dataclass(frozen=True, slots=True)
class LiabilityBalance:
    liability_id: str
    account_id: str | None
    currency: str
    principal: Decimal
    state_version: int


@dataclass(frozen=True, slots=True)
class CashflowItem:
    cashflow_id: str
    account_id: str | None
    transaction_id: str
    category: str
    amount: Decimal
    currency: str
    occurred_at: str | None
    state_version: int


@dataclass(frozen=True, slots=True)
class ProjectionState:
    state_version: int
    positions: tuple[Position, ...]
    cash_balances: tuple[CashBalance, ...]
    liabilities: tuple[LiabilityBalance, ...]
    cashflow: tuple[CashflowItem, ...]


def compute_projection(
    connection: sqlite3.Connection,
    *,
    target_state_version: int | None = None,
) -> ProjectionState:
    current = int(connection.execute("SELECT MAX(state_version) FROM state_versions").fetchone()[0])
    target = current if target_state_version is None else target_state_version
    if target < 0 or target > current:
        raise ProjectionError("target state_version is outside ledger history")
    rows = connection.execute(
        "SELECT e.*, t.transaction_type, t.occurred_at AS ledger_occurred_at "
        "FROM transaction_entries e "
        "JOIN transactions t ON t.transaction_id = e.transaction_id "
        "WHERE t.status = 'POSTED' AND e.state_version <= ? "
        "ORDER BY e.state_version, t.operation_sequence, e.entry_sequence",
        (target,),
    ).fetchall()

    positions: dict[tuple[str, str], dict[str, Any]] = {}
    cash: dict[tuple[str, str], Decimal] = {}
    liabilities: dict[tuple[str, str | None, str], Decimal] = {}
    cashflows: list[CashflowItem] = []

    for row in rows:
        role = str(row["entry_type"])
        quantity_delta = decode_decimal(row["quantity_delta_decimal"]) or ZERO
        amount_delta = decode_decimal(row["amount_delta_decimal"]) or ZERO
        cost_delta = decode_decimal(row["cost_basis_delta_decimal"])
        if role == "ASSET":
            account_id = str(row["account_id"])
            instrument_id = str(row["instrument_id"])
            key = (account_id, instrument_id)
            item = positions.setdefault(
                key,
                {
                    "quantity": ZERO,
                    "status": CostBasisStatus.UNAVAILABLE,
                    "total_cost": None,
                    "currency": row["currency"],
                },
            )
            previous_quantity: Decimal = item["quantity"]
            new_quantity = previous_quantity + quantity_delta
            if new_quantity < ZERO:
                raise ProjectionError("ledger produces a negative position")
            entry_status = row["cost_basis_status"]
            if previous_quantity == ZERO and entry_status:
                item["status"] = CostBasisStatus(str(entry_status))
                item["total_cost"] = ZERO if cost_delta is not None else None
            if item["status"] is not CostBasisStatus.UNAVAILABLE and cost_delta is not None:
                item["total_cost"] = (item["total_cost"] or ZERO) + cost_delta
                if item["total_cost"] < ZERO:
                    raise ProjectionError("ledger produces a negative cost basis")
            elif entry_status == CostBasisStatus.UNAVAILABLE.value and new_quantity > ZERO:
                item["status"] = CostBasisStatus.UNAVAILABLE
                item["total_cost"] = None
            item["quantity"] = new_quantity
            item["currency"] = row["currency"] or item["currency"]
            if new_quantity == ZERO:
                del positions[key]
        elif role == "CASH":
            key = (str(row["account_id"]), str(row["currency"]))
            cash[key] = cash.get(key, ZERO) + amount_delta
            if cash[key] < ZERO:
                raise ProjectionError("ledger produces a negative cash balance")
            if cash[key] == ZERO:
                del cash[key]
        elif role == "LIABILITY":
            metadata = json.loads(row["metadata_json"] or "{}")
            key = (
                str(row["liability_reference"]),
                None if row["account_id"] is None else str(row["account_id"]),
                str(row["currency"]),
            )
            liabilities[key] = liabilities.get(key, ZERO) + amount_delta
            if liabilities[key] < ZERO:
                raise ProjectionError("ledger produces a negative liability")
            if liabilities[key] == ZERO:
                del liabilities[key]
        elif role == "CASHFLOW":
            metadata = json.loads(row["metadata_json"] or "{}")
            cashflows.append(
                CashflowItem(
                    str(row["entry_id"]),
                    None if row["account_id"] is None else str(row["account_id"]),
                    str(row["transaction_id"]),
                    str(metadata.get("category", "CAPITAL")),
                    amount_delta,
                    str(row["currency"]),
                    None
                    if row["ledger_occurred_at"] is None
                    else str(row["ledger_occurred_at"]),
                    int(row["state_version"]),
                )
            )

    position_rows = tuple(
        Position(
            account,
            instrument,
            item["quantity"],
            item["status"],
            item["total_cost"],
            (
                None
                if item["total_cost"] is None
                else item["total_cost"] / item["quantity"]
            ),
            item["currency"],
            target,
        )
        for (account, instrument), item in sorted(positions.items())
    )
    cash_rows = tuple(
        CashBalance(account, currency, balance, target)
        for (account, currency), balance in sorted(cash.items())
    )
    liability_rows = tuple(
        LiabilityBalance(liability, account, currency, principal, target)
        for (liability, account, currency), principal in sorted(liabilities.items())
    )
    return ProjectionState(target, position_rows, cash_rows, liability_rows, tuple(cashflows))


def replace_projection(connection: sqlite3.Connection, state: ProjectionState) -> None:
    """Replace materialized projections inside the caller's guarded transaction."""

    now = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM positions")
    connection.execute("DELETE FROM cash_balances")
    connection.execute("DELETE FROM liabilities")
    connection.execute("DELETE FROM cashflow")
    for item in state.positions:
        connection.execute(
            "INSERT INTO positions "
            "(position_id, account_id, instrument_id, quantity, cost_basis_status, "
            "state_version, updated_at, quantity_decimal, total_cost_decimal, "
            "average_unit_cost_decimal, currency_code, updated_state_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{item.account_id}|{item.instrument_id}",
                item.account_id,
                item.instrument_id,
                encode_decimal(item.quantity),
                item.cost_basis_status.value,
                state.state_version,
                now,
                encode_decimal(item.quantity),
                encode_decimal(item.total_cost),
                encode_decimal(item.average_unit_cost),
                item.currency,
                state.state_version,
            ),
        )
    for item in state.cash_balances:
        connection.execute(
            "INSERT INTO cash_balances "
            "(cash_balance_id, account_id, currency, balance, state_version, updated_at, balance_decimal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"{item.account_id}|{item.currency}",
                item.account_id,
                item.currency,
                encode_decimal(item.balance),
                state.state_version,
                now,
                encode_decimal(item.balance),
            ),
        )
    for item in state.liabilities:
        connection.execute(
            "INSERT INTO liabilities "
            "(liability_id, account_id, name, currency, principal, state_version, created_at, principal_decimal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.liability_id,
                item.account_id,
                item.liability_id,
                item.currency,
                encode_decimal(item.principal),
                state.state_version,
                now,
                encode_decimal(item.principal),
            ),
        )
    for item in state.cashflow:
        connection.execute(
            "INSERT INTO cashflow "
            "(cashflow_id, account_id, transaction_id, category, amount, currency, "
            "occurred_at, state_version, created_at, amount_decimal) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.cashflow_id,
                item.account_id,
                item.transaction_id,
                item.category,
                encode_decimal(item.amount),
                item.currency,
                item.occurred_at,
                item.state_version,
                now,
                encode_decimal(item.amount),
            ),
        )
