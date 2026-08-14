"""Isolated run.db lifecycle and parameterized CRUD primitives."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from investment_stack.evidence.paths import resolve_run_db_path, validate_run_id
from investment_stack.migrations.run import RUN_MIGRATIONS
from investment_stack.storage.migrations import (
    apply_pending_migrations,
    ensure_migration_table,
)
from investment_stack.storage.identity import (
    PathIdentity,
    StorageIdentityError,
    get_path_identity,
    verify_opened_database_identity,
)
from investment_stack.storage.permissions import protect_directory, protect_file
from investment_stack.storage.schema import (
    expected_schema_signature,
    introspect_schema,
    schema_signature_errors,
)
from investment_stack.storage.sqlite import (
    _sqlite_verified_read_connection,
    _sqlite_write_connection,
    sqlite_readonly_connection,
    sqlite_transaction,
)


REQUIRED_RUN_TABLES = frozenset(
    {
        "schema_migrations",
        "run_metadata",
        "pinned_personal_state",
        "instrument_resolutions",
        "provider_states",
        "task_states",
        "evidence",
        "market_observations",
        "observation_selections",
        "financial_observations",
        "macro_observations",
        "calculations",
        "conflicts",
        "freshness_assessments",
        "materiality_decisions",
        "review_findings",
        "report_sections",
    }
)


class RunDatabaseStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RunValidationReport:
    valid: bool
    path: Path
    errors: tuple[str, ...]


def _validate_run_connection(
    connection: sqlite3.Connection, *, expected_run_id: str
) -> tuple[str, ...]:
    errors: list[str] = []
    if [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()] != [
        "ok"
    ]:
        errors.append("integrity_check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        errors.append("foreign_key_check failed")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = REQUIRED_RUN_TABLES - tables
    if missing:
        errors.append("missing required run tables: " + ", ".join(sorted(missing)))
        return tuple(errors)
    rows = connection.execute("SELECT run_id FROM run_metadata").fetchall()
    if len(rows) != 1 or rows[0]["run_id"] != expected_run_id:
        errors.append("run_metadata identity mismatch")
    migration_rows = connection.execute(
        "SELECT version, migration_id, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    if len(migration_rows) != len(RUN_MIGRATIONS):
        errors.append("run schema version mismatch")
    else:
        for row, migration in zip(migration_rows, RUN_MIGRATIONS, strict=True):
            if (
                int(row["version"]) != migration.version
                or row["migration_id"] != migration.migration_id
                or row["checksum"] != migration.checksum
            ):
                errors.append("run migration history mismatch")
                break
    if not any("migration" in error or "version" in error for error in errors):
        signature_errors = schema_signature_errors(
            introspect_schema(connection),
            expected_schema_signature(RUN_MIGRATIONS, RUN_MIGRATIONS[-1].version),
        )
        errors.extend(f"run {error}" for error in signature_errors)
    return tuple(errors)


def validate_run_database(path: Path, *, expected_run_id: str) -> RunValidationReport:
    database = Path(path).expanduser().resolve(strict=False)
    if not database.is_file() or database.stat().st_size == 0:
        return RunValidationReport(False, database, ("run database is missing or empty",))
    try:
        with sqlite_readonly_connection(database) as connection:
            errors = _validate_run_connection(
                connection, expected_run_id=expected_run_id
            )
    except (OSError, sqlite3.Error) as exc:
        errors = (f"run database validation error: {exc}",)
    return RunValidationReport(not errors, database, tuple(errors))


class RunDatabaseManager:
    """A run-local manager whose failure never changes personal DB status."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.run_id = validate_run_id(run_id)
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=False)
        self.database_path = resolve_run_db_path(self.workspace_root, self.run_id)
        self._database_path_anchor = self.database_path
        self.status = RunDatabaseStatus.INVALID
        self._database_identity: PathIdentity | None = None
        self._operation_lock = RLock()

    def _operational_database_path(self) -> Path:
        return resolve_run_db_path(
            self.workspace_root,
            self.run_id,
            expected_resolved=self._database_path_anchor,
        )

    def create(self) -> RunValidationReport:
        with self._operation_lock:
            self.status = RunDatabaseStatus.INVALID
            database_path = self._operational_database_path()
            run_directory = database_path.parent
            if run_directory.exists():
                raise FileExistsError(f"run workspace already exists: {run_directory}")
            protect_directory(run_directory.parent)
            database_path = self._operational_database_path()
            run_directory = database_path.parent
            run_directory.mkdir(exist_ok=False)
            protect_directory(run_directory)
            database_path = self._operational_database_path()
            now = datetime.now(timezone.utc).isoformat()
            try:
                descriptor = os.open(
                    database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                os.close(descriptor)
                database_identity = get_path_identity(database_path)
                with _sqlite_write_connection(
                    database_path, expected_identity=database_identity
                ) as connection:
                    with sqlite_transaction(connection):
                        ensure_migration_table(connection)
                        apply_pending_migrations(connection, RUN_MIGRATIONS)
                        connection.execute(
                            "INSERT INTO run_metadata "
                            "(run_id, started_at, run_status) VALUES (?, ?, ?)",
                            (self.run_id, now, "CREATED"),
                        )
                        verify_opened_database_identity(
                            connection,
                            expected_path=database_path,
                            expected_identity=database_identity,
                        )
                protect_file(database_path)
            except (OSError, sqlite3.Error, RuntimeError, ValueError):
                self.status = RunDatabaseStatus.INVALID
                raise
            return self.open()

    def open(self) -> RunValidationReport:
        with self._operation_lock:
            try:
                database_path = self._operational_database_path()
                report = validate_run_database(
                    database_path, expected_run_id=self.run_id
                )
            except (OSError, ValueError) as exc:
                report = RunValidationReport(
                    False, self.database_path, (f"run path validation error: {exc}",)
                )
            self.status = (
                RunDatabaseStatus.VALID if report.valid else RunDatabaseStatus.INVALID
            )
            if report.valid:
                try:
                    self._database_identity = get_path_identity(database_path)
                except (OSError, StorageIdentityError, ValueError) as exc:
                    report = RunValidationReport(
                        False,
                        database_path,
                        (f"run identity validation error: {exc}",),
                    )
                    self.status = RunDatabaseStatus.INVALID
                    self._database_identity = None
            return report

    def _assert_valid(self) -> None:
        if self.status is not RunDatabaseStatus.VALID:
            raise RuntimeError("run database is not valid")

    @contextmanager
    def _mutation_connection(self) -> Iterator[sqlite3.Connection]:
        with self._operation_lock:
            self._assert_valid()
            try:
                database_path = self._operational_database_path()
                database_identity = self._database_identity
                if database_identity is None:
                    raise StorageIdentityError("run database identity was not established")
                with _sqlite_write_connection(
                    database_path, expected_identity=database_identity
                ) as connection:
                    with sqlite_transaction(connection):
                        errors = _validate_run_connection(
                            connection, expected_run_id=self.run_id
                        )
                        if errors:
                            raise RuntimeError(
                                "run database changed after open: " + "; ".join(errors)
                            )
                        yield connection
                        errors = _validate_run_connection(
                            connection, expected_run_id=self.run_id
                        )
                        if errors:
                            raise RuntimeError(
                                "run database became invalid during mutation: "
                                + "; ".join(errors)
                            )
                        verify_opened_database_identity(
                            connection,
                            expected_path=database_path,
                            expected_identity=database_identity,
                        )
            except (OSError, sqlite3.Error, RuntimeError, ValueError):
                self.status = RunDatabaseStatus.INVALID
                raise

    def update_metadata(
        self,
        *,
        run_status: str,
        request_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            cursor = connection.execute(
                "UPDATE run_metadata SET run_status = ?, request_mode = ?, metadata_json = ? "
                "WHERE run_id = ?",
                (
                    run_status,
                    request_mode,
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    self.run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("run metadata update did not affect exactly one row")

    def fetch_metadata(self) -> dict[str, Any]:
        with self._operation_lock:
            self._assert_valid()
            try:
                database_path = self._operational_database_path()
                database_identity = self._database_identity
                if database_identity is None:
                    raise StorageIdentityError("run database identity was not established")
                with _sqlite_verified_read_connection(
                    database_path, expected_identity=database_identity
                ) as connection:
                    errors = _validate_run_connection(
                        connection, expected_run_id=self.run_id
                    )
                    if errors:
                        raise RuntimeError(
                            "run database changed after open: " + "; ".join(errors)
                        )
                    row = connection.execute(
                        "SELECT * FROM run_metadata WHERE run_id = ?", (self.run_id,)
                    ).fetchone()
                if row is None:
                    raise RuntimeError("run metadata disappeared")
                return dict(row)
            except (OSError, sqlite3.Error, RuntimeError, ValueError):
                self.status = RunDatabaseStatus.INVALID
                raise

    def add_evidence(
        self,
        *,
        evidence_id: str,
        evidence_type: str,
        source_uri: str | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist caller-supplied evidence metadata without fetching external data."""

        with self._mutation_connection() as connection:
            cursor = connection.execute(
                "INSERT INTO evidence "
                "(evidence_id, run_id, evidence_type, source_uri, content_hash, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    self.run_id,
                    evidence_type,
                    source_uri,
                    content_hash,
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("evidence insert did not affect exactly one row")
