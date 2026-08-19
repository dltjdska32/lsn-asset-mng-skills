"""Ordered run evidence database migrations."""

from investment_stack.migrations.run.v0001_initial import MIGRATION as V0001_INITIAL
from investment_stack.migrations.run.v0002_phase4_evidence import MIGRATION as V0002_PHASE4_EVIDENCE

RUN_MIGRATIONS = (V0001_INITIAL, V0002_PHASE4_EVIDENCE)
CURRENT_RUN_SCHEMA_VERSION = RUN_MIGRATIONS[-1].version

__all__ = ["CURRENT_RUN_SCHEMA_VERSION", "RUN_MIGRATIONS"]
