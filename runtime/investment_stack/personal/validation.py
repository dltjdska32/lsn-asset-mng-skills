"""Independent personal database integrity and schema validation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from uuid import UUID

from investment_stack.migrations.personal import (
    CURRENT_PERSONAL_SCHEMA_VERSION,
    PERSONAL_MIGRATIONS,
)
from investment_stack.storage.migrations import (
    Migration,
    validate_migration_catalog,
)
from investment_stack.storage.schema import (
    canonicalize_sqlite_sql,
    expected_schema_signature,
    introspect_schema,
    schema_signature_errors,
)
from investment_stack.storage.sqlite import sqlite_readonly_connection


PERSONAL_DB_INSTANCE_ID_KEY = "personal_db_instance_id"
REQUIRED_LEDGER_TRIGGERS = frozenset(
    {
        "transactions_append_only_update",
        "transactions_append_only_delete",
        "transaction_entries_append_only_update",
        "transaction_entries_append_only_delete",
        "portfolio_snapshots_append_only_update",
        "portfolio_snapshots_append_only_delete",
    }
)

REQUIRED_PERSONAL_TABLES = frozenset(
    {
        "accounts",
        "instruments",
        "instrument_aliases",
        "transactions",
        "transaction_entries",
        "positions",
        "position_history",
        "cash_balances",
        "liabilities",
        "cashflow",
        "goals",
        "portfolio_snapshots",
        "state_versions",
        "import_records",
        "schema_migrations",
        "correction_relations",
        "storage_metadata",
    }
)


@dataclass(frozen=True)
class PersonalValidationReport:
    valid: bool
    path: Path
    schema_version: int | None
    instance_id: str | None
    checks: tuple[str, ...]
    errors: tuple[str, ...]
    counts: dict[str, int]


def _validate_migration_history(
    connection: sqlite3.Connection,
    catalog: Sequence[Migration],
    *,
    require_current: bool,
) -> tuple[int | None, list[str]]:
    errors: list[str] = []
    rows = connection.execute(
        "SELECT version, migration_id, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    expected_catalog = validate_migration_catalog(catalog)
    if not rows:
        return 0, ["schema_migrations is empty"]
    if len(rows) > len(expected_catalog):
        errors.append("database schema version is newer than this runtime")
    for index, row in enumerate(rows):
        expected_version = index + 1
        if int(row["version"]) != expected_version:
            errors.append("schema migration versions are not contiguous")
            continue
        if index >= len(expected_catalog):
            continue
        expected = expected_catalog[index]
        if row["migration_id"] != expected.migration_id:
            errors.append(f"migration id mismatch at version {expected_version}")
        if row["checksum"] != expected.checksum:
            errors.append(f"migration checksum mismatch at version {expected_version}")
    version = int(rows[-1]["version"])
    if require_current and version != expected_catalog[-1].version:
        errors.append(
            f"schema version {version} does not equal current {expected_catalog[-1].version}"
        )
    return version, errors


def _read_instance_id(connection: sqlite3.Connection) -> tuple[str | None, list[str]]:
    rows = connection.execute(
        "SELECT metadata_value FROM storage_metadata WHERE metadata_key = ?",
        (PERSONAL_DB_INSTANCE_ID_KEY,),
    ).fetchall()
    if len(rows) != 1:
        return None, ["personal database instance identity is missing or duplicated"]
    instance_id = str(rows[0]["metadata_value"])
    try:
        UUID(instance_id)
    except (ValueError, AttributeError):
        return None, ["personal database instance identity is invalid"]
    return instance_id, []


def validate_personal_connection(
    connection: sqlite3.Connection,
    *,
    path: Path,
    require_current: bool = True,
    migrations: Sequence[Migration] = PERSONAL_MIGRATIONS,
) -> PersonalValidationReport:
    """Validate using the caller's already-open operation connection."""

    database_path = Path(path).expanduser().resolve(strict=False)
    catalog = validate_migration_catalog(migrations)
    checks: list[str] = []
    errors: list[str] = []
    counts: dict[str, int] = {}
    schema_version: int | None = None
    instance_id: str | None = None

    integrity_messages = [
        str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()
    ]
    if integrity_messages != ["ok"]:
        errors.append("integrity_check failed")
    else:
        checks.append("integrity_check")

    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    tables = {str(row["name"]) for row in table_rows}
    missing = sorted(REQUIRED_PERSONAL_TABLES - tables)
    if missing:
        errors.append("missing required tables: " + ", ".join(missing))
    else:
        checks.append("required_tables")

    if "schema_migrations" in tables:
        schema_version, migration_errors = _validate_migration_history(
            connection, catalog, require_current=require_current
        )
        errors.extend(migration_errors)
        if not migration_errors:
            checks.append("schema_version")
            expected_signature = expected_schema_signature(catalog, schema_version)
            signature_errors = schema_signature_errors(
                introspect_schema(connection), expected_signature
            )
            errors.extend(signature_errors)
            if not signature_errors:
                checks.append("schema_signature")
        if schema_version is not None and schema_version >= 3:
            trigger_rows = connection.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
            actual_triggers = {str(row["name"]): row for row in trigger_rows}
            missing_triggers = sorted(REQUIRED_LEDGER_TRIGGERS - actual_triggers.keys())
            trigger_errors: list[str] = []
            if missing_triggers:
                trigger_errors.append(
                    "missing append-only triggers: " + ", ".join(missing_triggers)
                )
            expected_triggers = (
                {item.name: item for item in expected_signature.triggers}
                if not migration_errors
                else {}
            )
            for name in sorted(REQUIRED_LEDGER_TRIGGERS & actual_triggers.keys()):
                row = actual_triggers[name]
                sql = canonicalize_sqlite_sql(
                    None if row["sql"] is None else str(row["sql"])
                )
                if "raise" not in sql:
                    trigger_errors.append(
                        f"append-only trigger is missing RAISE: {name}"
                    )
                expected_trigger = expected_triggers.get(name)
                if expected_trigger is None:
                    if not migration_errors:
                        trigger_errors.append(
                            f"append-only trigger is not in schema signature: {name}"
                        )
                    continue
                if str(row["tbl_name"]) != expected_trigger.table:
                    trigger_errors.append(
                        f"append-only trigger target mismatch: {name}"
                    )
                if sql != expected_trigger.canonical_sql:
                    trigger_errors.append(
                        f"append-only trigger signature mismatch: {name}"
                    )
            errors.extend(trigger_errors)
            if not trigger_errors:
                checks.append("append_only_triggers")

    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_rows:
        errors.append("foreign_key_check failed")
    else:
        checks.append("foreign_key_check")

    if "storage_metadata" in tables:
        instance_id, identity_errors = _read_instance_id(connection)
        errors.extend(identity_errors)
        if not identity_errors:
            checks.append("instance_identity")

    if not missing:
        counts = {
            "accounts": int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]),
            "transactions": int(
                connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            ),
            "transaction_entries": int(
                connection.execute("SELECT COUNT(*) FROM transaction_entries").fetchone()[0]
            ),
            "positions": int(
                connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            ),
        }
        state_row = connection.execute(
            "SELECT MIN(state_version), MAX(state_version), COUNT(*) FROM state_versions"
        ).fetchone()
        if int(state_row[2]) < 1 or int(state_row[0]) < 0 or int(state_row[1]) < 0:
            errors.append("state_version sanity failed")
        else:
            checks.append("state_version_sanity")

        orphan_entries = int(
            connection.execute(
                "SELECT COUNT(*) FROM transaction_entries e "
                "LEFT JOIN transactions t ON t.transaction_id = e.transaction_id "
                "WHERE t.transaction_id IS NULL"
            ).fetchone()[0]
        )
        invalid_positions = int(
            connection.execute(
                "SELECT COUNT(*) FROM positions p "
                "LEFT JOIN accounts a ON a.account_id = p.account_id "
                "LEFT JOIN instruments i ON i.instrument_id = p.instrument_id "
                "WHERE a.account_id IS NULL OR i.instrument_id IS NULL"
            ).fetchone()[0]
        )
        if orphan_entries or invalid_positions:
            errors.append("transaction/entry/account/position sanity failed")
        else:
            checks.append("basic_relational_sanity")
        if schema_version is not None and schema_version >= 3 and not errors:
            invalid_posted = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transactions "
                    "WHERE status = 'POSTED' AND (occurred_at IS NULL OR occurred_timezone IS NULL)"
                ).fetchone()[0]
            )
            invalid_entry_versions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM transaction_entries WHERE state_version IS NULL"
                ).fetchone()[0]
            )
            if invalid_posted or invalid_entry_versions:
                errors.append("posted ledger time/state_version sanity failed")
            else:
                checks.append("posted_ledger_sanity")

    return PersonalValidationReport(
        not errors,
        database_path,
        schema_version,
        instance_id,
        tuple(checks),
        tuple(errors),
        counts,
    )


def validate_personal_database(
    path: Path,
    *,
    require_current: bool = True,
    migrations: Sequence[Migration] = PERSONAL_MIGRATIONS,
) -> PersonalValidationReport:
    """Validate a personal database from a separate read-only connection."""

    database_path = Path(path).expanduser().resolve(strict=False)
    if not database_path.is_file():
        return PersonalValidationReport(
            False,
            database_path,
            None,
            None,
            (),
            ("database file does not exist",),
            {},
        )
    try:
        if database_path.stat().st_size == 0:
            return PersonalValidationReport(
                False,
                database_path,
                None,
                None,
                (),
                ("database file is zero bytes",),
                {},
            )
    except OSError as exc:
        return PersonalValidationReport(
            False, database_path, None, None, (), (str(exc),), {}
        )

    try:
        with sqlite_readonly_connection(database_path) as connection:
            return validate_personal_connection(
                connection,
                path=database_path,
                require_current=require_current,
                migrations=migrations,
            )
    except (OSError, sqlite3.Error, ValueError) as exc:
        return PersonalValidationReport(
            False,
            database_path,
            None,
            None,
            (),
            (f"database validation error: {exc}",),
            {},
        )


def current_personal_schema_version() -> int:
    return CURRENT_PERSONAL_SCHEMA_VERSION
