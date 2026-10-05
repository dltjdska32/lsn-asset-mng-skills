"""Small deterministic migration catalog and executor."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class Migration:
    version: int
    migration_id: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        material = "\n-- statement --\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


MigrationHook = Callable[[Migration, sqlite3.Connection], None]


def validate_migration_catalog(migrations: Iterable[Migration]) -> tuple[Migration, ...]:
    catalog = tuple(migrations)
    if not catalog:
        raise ValueError("migration catalog cannot be empty")
    versions = [migration.version for migration in catalog]
    identifiers = [migration.migration_id for migration in catalog]
    if len(versions) != len(set(versions)):
        raise ValueError("duplicate migration version")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate migration id")
    expected = list(range(1, len(catalog) + 1))
    if versions != expected:
        raise ValueError(f"migration versions must be ordered and contiguous: {expected}")
    if any(not identifier or identifier.strip() != identifier for identifier in identifiers):
        raise ValueError("migration ids must be non-empty normalized strings")
    if any(not migration.statements for migration in catalog):
        raise ValueError("each migration must contain at least one statement")
    return catalog


def ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            migration_id TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        )
        """
    )


def applied_migrations(connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
    return tuple(
        connection.execute(
            "SELECT version, migration_id, applied_at, checksum "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()
    )


def apply_pending_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration],
    *,
    hook: MigrationHook | None = None,
) -> tuple[int, ...]:
    """Apply pending statements inside the caller's active transaction."""

    catalog = validate_migration_catalog(migrations)
    if not connection.in_transaction:
        raise RuntimeError("migration execution requires an active transaction")
    rows = applied_migrations(connection)
    applied_versions = {int(row["version"]) for row in rows}
    applied_now: list[int] = []
    for migration in catalog:
        if migration.version in applied_versions:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        if hook is not None:
            hook(migration, connection)
        connection.execute(
            "INSERT INTO schema_migrations "
            "(version, migration_id, applied_at, checksum) VALUES (?, ?, ?, ?)",
            (
                migration.version,
                migration.migration_id,
                datetime.now(timezone.utc).isoformat(),
                migration.checksum,
            ),
        )
        applied_now.append(migration.version)
    return tuple(applied_now)
