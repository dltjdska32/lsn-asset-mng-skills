"""Ordered personal database migrations."""

from investment_stack.migrations.personal.v0001_initial import MIGRATION as V0001_INITIAL
from investment_stack.migrations.personal.v0002_storage_indexes import MIGRATION as V0002_STORAGE_INDEXES
from investment_stack.migrations.personal.v0003_ledger_projection import (
    MIGRATION as V0003_LEDGER_PROJECTION,
)

PERSONAL_MIGRATIONS = (V0001_INITIAL, V0002_STORAGE_INDEXES, V0003_LEDGER_PROJECTION)
CURRENT_PERSONAL_SCHEMA_VERSION = PERSONAL_MIGRATIONS[-1].version

__all__ = ["CURRENT_PERSONAL_SCHEMA_VERSION", "PERSONAL_MIGRATIONS"]
