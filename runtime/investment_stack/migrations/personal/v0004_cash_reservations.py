"""Explicit cash reservations attached to an existing ledger state version.

Reservations do not post orders or change positions. A coverage row is required
before a state version's emergency fund, planned spending, and pending-order
reservations are treated as a complete set.
"""

from investment_stack.storage.migrations import Migration


MIGRATION = Migration(
    version=4,
    migration_id="personal-0004-cash-reservations",
    statements=(
        """
        CREATE TABLE reservation_coverage (
            state_version INTEGER PRIMARY KEY REFERENCES state_versions(state_version),
            statement TEXT NOT NULL CHECK (statement = 'COMPLETE'),
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE cash_reservations (
            reservation_id TEXT PRIMARY KEY,
            state_version INTEGER NOT NULL REFERENCES state_versions(state_version),
            kind TEXT NOT NULL CHECK (kind IN ('EMERGENCY_FUND', 'PLANNED_SPENDING', 'PENDING_ORDER')),
            currency TEXT NOT NULL,
            amount_decimal TEXT NOT NULL,
            instrument_id TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TRIGGER reservation_coverage_append_only_update
        BEFORE UPDATE ON reservation_coverage BEGIN
            SELECT RAISE(ABORT, 'reservation coverage is append-only');
        END
        """,
        """
        CREATE TRIGGER reservation_coverage_append_only_delete
        BEFORE DELETE ON reservation_coverage BEGIN
            SELECT RAISE(ABORT, 'reservation coverage is append-only');
        END
        """,
        """
        CREATE TRIGGER cash_reservations_append_only_update
        BEFORE UPDATE ON cash_reservations BEGIN
            SELECT RAISE(ABORT, 'cash reservations are append-only');
        END
        """,
        """
        CREATE TRIGGER cash_reservations_append_only_delete
        BEFORE DELETE ON cash_reservations BEGIN
            SELECT RAISE(ABORT, 'cash reservations are append-only');
        END
        """,
    ),
)
