"""Ordered run evidence database migrations."""

from investment_stack.migrations.run.v0001_initial import MIGRATION as V0001_INITIAL

RUN_MIGRATIONS = (V0001_INITIAL,)
CURRENT_RUN_SCHEMA_VERSION = RUN_MIGRATIONS[-1].version

__all__ = ["CURRENT_RUN_SCHEMA_VERSION", "RUN_MIGRATIONS"]
