"""Ordered personal database migrations."""

from investment_stack.migrations.personal.v0001_initial import MIGRATION as V0001_INITIAL
from investment_stack.migrations.personal.v0002_storage_indexes import MIGRATION as V0002_STORAGE_INDEXES
from investment_stack.migrations.personal.v0003_ledger_projection import (
    MIGRATION as V0003_LEDGER_PROJECTION,
)
from investment_stack.migrations.personal.v0004_cash_reservations import (
    MIGRATION as V0004_CASH_RESERVATIONS,
)

PERSONAL_MIGRATIONS = (
    V0001_INITIAL,
    V0002_STORAGE_INDEXES,
    V0003_LEDGER_PROJECTION,
    V0004_CASH_RESERVATIONS,
)
CURRENT_PERSONAL_SCHEMA_VERSION = PERSONAL_MIGRATIONS[-1].version

__all__ = ["CURRENT_PERSONAL_SCHEMA_VERSION", "PERSONAL_MIGRATIONS"]
