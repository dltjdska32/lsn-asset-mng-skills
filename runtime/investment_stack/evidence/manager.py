"""Isolated run.db lifecycle and parameterized CRUD primitives."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

    def initialize_run_context(
        self,
        *,
        request_mode: str,
        analysis_as_of: str,
        analysis_timezone: str,
        state_version: int | None = None,
        personal_db_instance_id: str | None = None,
        portfolio_snapshot_id: str | None = None,
        portfolio_data_as_of: str | None = None,
    ) -> None:
        """Pin immutable run clock and optional personal state once."""
        try:
            cutoff = datetime.fromisoformat(analysis_as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("analysis_as_of must be a valid ISO-8601 timestamp") from exc
        if cutoff.tzinfo is None:
            raise ValueError("analysis_as_of must include an explicit timezone")
        try:
            ZoneInfo(analysis_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("analysis_timezone must be a valid IANA timezone") from exc
        with self._mutation_connection() as connection:
            row = connection.execute(
                "SELECT analysis_as_of, analysis_timezone FROM run_metadata WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("run metadata disappeared")
            if row["analysis_as_of"] is not None or row["analysis_timezone"] is not None:
                if row["analysis_as_of"] != analysis_as_of or row["analysis_timezone"] != analysis_timezone:
                    raise RuntimeError("run analysis clock is immutable once pinned")
            else:
                connection.execute(
                    "UPDATE run_metadata SET request_mode = ?, analysis_as_of = ?, analysis_timezone = ? WHERE run_id = ?",
                    (request_mode, analysis_as_of, analysis_timezone, self.run_id),
                )
            if state_version is not None:
                existing = connection.execute(
                    "SELECT state_version, personal_db_instance_id, portfolio_snapshot_id, portfolio_data_as_of "
                    "FROM pinned_personal_state WHERE run_id = ?",
                    (self.run_id,),
                ).fetchone()
                values = (state_version, personal_db_instance_id, portfolio_snapshot_id, portfolio_data_as_of)
                if existing is None:
                    connection.execute(
                        "INSERT INTO pinned_personal_state "
                        "(pinned_state_id, run_id, state_version, pinned_at, personal_db_instance_id, portfolio_snapshot_id, portfolio_data_as_of) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"pin:{self.run_id}", self.run_id, state_version,
                            datetime.now(timezone.utc).isoformat(), personal_db_instance_id,
                            portfolio_snapshot_id, portfolio_data_as_of,
                        ),
                    )
                elif tuple(existing) != values:
                    raise RuntimeError("pinned personal state is immutable within a run")

    def record_provider_state(
        self,
        *,
        provider_name: str,
        provider_status: str,
        capability: str | None = None,
        error_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO provider_states "
                "(provider_state_id, run_id, provider_name, provider_status, metadata_json, updated_at, capability, error_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"provider:{provider_name}:{capability or 'general'}:{uuid.uuid4().hex}",
                    self.run_id, provider_name, provider_status,
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    datetime.now(timezone.utc).isoformat(), capability, error_reason,
                ),
            )

    def record_task_state(
        self,
        *,
        task_name: str,
        task_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist an executed fixed-pipeline step in run.db."""
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO task_states "
                "(task_state_id, run_id, task_name, task_status, metadata_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"task:{task_name}:{uuid.uuid4().hex}",
                    self.run_id,
                    task_name,
                    task_status,
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def add_phase4_evidence(
        self,
        *,
        evidence_id: str,
        evidence_type: str,
        source_uri: str | None,
        retrieved_at: str | None,
        instrument_id: str | None = None,
        metric: str | None = None,
        value: Any = None,
        unit: str | None = None,
        currency: str | None = None,
        source_name: str | None = None,
        source_tier: int | None = None,
        observed_at: str | None = None,
        published_at: str | None = None,
        freshness_status: str | None = None,
        provider_id: str | None = None,
        headline: str | None = None,
        updated_at: str | None = None,
        event_time: str | None = None,
        official_confirmation_status: str | None = None,
        event_cluster_id: str | None = None,
        relevance_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO evidence "
                "(evidence_id, run_id, evidence_type, source_uri, retrieved_at, metadata_json, instrument_id, metric, value_text, unit, currency, source_name, source_tier, observed_at, published_at, freshness_status, provider_id, headline, updated_at, event_time, official_confirmation_status, event_cluster_id, relevance_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id, self.run_id, evidence_type, source_uri, retrieved_at,
                    json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    instrument_id, metric,
                    None if value is None else json.dumps(value, sort_keys=True, default=str),
                    unit, currency, source_name, source_tier, observed_at, published_at,
                    freshness_status, provider_id, headline, updated_at, event_time,
                    official_confirmation_status, event_cluster_id, relevance_reason,
                ),
            )

    def add_market_observation(
        self,
        *,
        observation_id: str,
        evidence_id: str,
        instrument_id: str | None,
        observed_at: str | None,
        value: str | int | float | None,
        unit: str | None,
        currency: str | None,
        claimed_market_time: str | None,
        market_session_date: str | None,
        provider_id: str,
        freshness_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO market_observations "
                "(observation_id, run_id, evidence_id, instrument_id, observed_at, value_numeric, unit, metadata_json, currency, claimed_market_time, market_session_date, provider_id, freshness_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id, self.run_id, evidence_id, instrument_id, observed_at,
                    value, unit, json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    currency, claimed_market_time, market_session_date, provider_id, freshness_status,
                ),
            )

    def add_freshness_assessment(
        self,
        *,
        freshness_id: str,
        evidence_id: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO freshness_assessments "
                "(freshness_id, run_id, evidence_id, status, assessed_at, details_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    freshness_id, self.run_id, evidence_id, status,
                    datetime.now(timezone.utc).isoformat(), json.dumps(details, sort_keys=True),
                ),
            )

    def mark_evidence_selected(self, *, evidence_id: str, reason: str) -> None:
        with self._mutation_connection() as connection:
            cursor = connection.execute(
                "UPDATE evidence SET selection_state = ?, selection_reason = ? WHERE evidence_id = ? AND run_id = ?",
                ("SELECTED", reason, evidence_id, self.run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("evidence selection did not affect exactly one row")

    def add_observation_selection(
        self,
        *,
        selection_id: str,
        observation_id: str,
        selection_reason: str,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO observation_selections "
                "(selection_id, run_id, observation_id, selection_reason, selected_at) VALUES (?, ?, ?, ?, ?)",
                (selection_id, self.run_id, observation_id, selection_reason, datetime.now(timezone.utc).isoformat()),
            )

    def add_conflict(
        self,
        *,
        conflict_id: str,
        conflict_type: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO conflicts "
                "(conflict_id, run_id, conflict_type, status, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (conflict_id, self.run_id, conflict_type, status, json.dumps(details, sort_keys=True), datetime.now(timezone.utc).isoformat()),
            )

    def fetch_evidence_rows(self) -> tuple[dict[str, Any], ...]:
        with self._operation_lock:
            self._assert_valid()
            database_path = self._operational_database_path()
            if self._database_identity is None:
                raise StorageIdentityError("run database identity was not established")
            with _sqlite_verified_read_connection(database_path, expected_identity=self._database_identity) as connection:
                rows = connection.execute("SELECT * FROM evidence WHERE run_id = ? ORDER BY rowid", (self.run_id,)).fetchall()
            return tuple(dict(row) for row in rows)

    def add_financial_observation(
        self,
        *,
        observation_id: str,
        evidence_id: str,
        metric_name: str,
        period_end: str | None,
        value: str | int | float | None,
        unit: str | None,
        currency: str | None,
        provider_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO financial_observations "
                "(observation_id, run_id, evidence_id, metric_name, period_end, value_numeric, unit, metadata_json, currency, provider_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id, self.run_id, evidence_id, metric_name, period_end, value,
                    unit, json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    currency, provider_id,
                ),
            )

    def add_macro_observation(
        self,
        *,
        observation_id: str,
        evidence_id: str,
        series_name: str,
        observed_at: str | None,
        value: str | int | float | None,
        unit: str | None,
        currency: str | None,
        provider_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO macro_observations "
                "(observation_id, run_id, evidence_id, series_name, observed_at, value_numeric, unit, metadata_json, currency, provider_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id, self.run_id, evidence_id, series_name, observed_at, value,
                    unit, json.dumps(metadata, sort_keys=True) if metadata is not None else None,
                    currency, provider_id,
                ),
            )

    def add_materiality_decision(
        self,
        *,
        decision_id: str,
        subject: str,
        decision: str,
        rationale: str,
    ) -> None:
        """Persist a Phase 5 materiality decision in run.db."""
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO materiality_decisions "
                "(decision_id, run_id, subject, decision, rationale, decided_at) VALUES (?, ?, ?, ?, ?, ?)",
                (decision_id, self.run_id, subject, decision, rationale, datetime.now(timezone.utc).isoformat()),
            )

    def add_calculation(
        self,
        *,
        calculation_id: str,
        calculation_name: str,
        formula: str,
        inputs: dict[str, Any],
        result: dict[str, Any] | None,
    ) -> None:
        """Persist deterministic calculation lineage referencing evidence IDs in inputs."""
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO calculations "
                "(calculation_id, run_id, calculation_name, formula, inputs_json, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    calculation_id, self.run_id, calculation_name, formula,
                    json.dumps(inputs, sort_keys=True, default=str),
                    json.dumps(result, sort_keys=True, default=str) if result is not None else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def fetch_phase6_context(self) -> dict[str, object]:
        """Return validated run-local inputs needed by Phase 6 report/review logic."""
        table_names = (
            "task_states",
            "provider_states",
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
        )
        with self._operation_lock:
            self._assert_valid()
            database_path = self._operational_database_path()
            if self._database_identity is None:
                raise StorageIdentityError("run database identity was not established")
            with _sqlite_verified_read_connection(
                database_path, expected_identity=self._database_identity
            ) as connection:
                errors = _validate_run_connection(connection, expected_run_id=self.run_id)
                if errors:
                    raise RuntimeError("run database changed after open: " + "; ".join(errors))
                metadata_row = connection.execute(
                    "SELECT * FROM run_metadata WHERE run_id = ?", (self.run_id,)
                ).fetchone()
                pinned_row = connection.execute(
                    "SELECT * FROM pinned_personal_state WHERE run_id = ?", (self.run_id,)
                ).fetchone()
                tables = {
                    table: tuple(
                        dict(row)
                        for row in connection.execute(
                            f"SELECT * FROM {table} WHERE run_id = ? ORDER BY rowid",  # noqa: S608 - fixed whitelist
                            (self.run_id,),
                        ).fetchall()
                    )
                    for table in table_names
                }
            if metadata_row is None:
                raise RuntimeError("run metadata disappeared")
            return {
                "run_metadata": dict(metadata_row),
                "pinned_personal_state": None if pinned_row is None else dict(pinned_row),
                **tables,
            }

    def add_review_finding(
        self,
        *,
        finding_id: str,
        severity: str,
        status: str,
        finding_text: str,
    ) -> None:
        """Persist a derived Phase 6 review finding in run.db."""
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO review_findings "
                "(finding_id, run_id, severity, status, finding_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    finding_id,
                    self.run_id,
                    severity,
                    status,
                    finding_text,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def upsert_report_section(
        self,
        *,
        section_id: str,
        section_name: str,
        section_status: str,
        content_reference: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist a derived report section; reports are not a personal Source of Truth."""
        with self._mutation_connection() as connection:
            connection.execute(
                "INSERT INTO report_sections "
                "(section_id, run_id, section_name, section_status, content_reference, metadata_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(section_id) DO UPDATE SET "
                "section_name = excluded.section_name, "
                "section_status = excluded.section_status, "
                "content_reference = excluded.content_reference, "
                "metadata_json = excluded.metadata_json, "
                "updated_at = excluded.updated_at "
                "WHERE report_sections.run_id = excluded.run_id",
                (
                    section_id,
                    self.run_id,
                    section_name,
                    section_status,
                    content_reference,
                    json.dumps(metadata, sort_keys=True, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
