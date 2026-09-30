"""Explicit, non-posting cash reservations for one ledger state version."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


RESERVATION_KINDS = frozenset({"EMERGENCY_FUND", "PLANNED_SPENDING", "PENDING_ORDER"})


@dataclass(frozen=True, slots=True)
class CashReservationDraft:
    kind: str
    currency: str
    amount: Decimal
    instrument_id: str | None = None


@dataclass(frozen=True, slots=True)
class CashReservation:
    reservation_id: str
    state_version: int
    kind: str
    currency: str
    amount: Decimal
    instrument_id: str | None
