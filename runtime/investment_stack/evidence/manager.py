"""Isolated run.db lifecycle and parameterized CRUD primitives."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from decimal import Decimal
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
from investment_stack.contracts.calculation import CalculationRecord, CalculationStatus
from investment_stack.contracts.codec import (
    MAX_PAYLOAD_BYTES,
    compute_semantic_hash,
    decode_contract,
    decode_envelope,
    encode_envelope,
    format_decimal,
    to_canonical_dict,
)
from investment_stack.contracts.errors import (
    AmbiguousSnapshotError,
    ContractValidationError,
    CorruptedStorageError,
    EvidenceNotFoundError,
    HistoryPreservationError,
    InputIntegrityError,
    RevisionConflictError,
    TamperDetectionError,
)
from investment_stack.contracts.slots import BoundSlotInput, SelectedInputSet
from investment_stack.contracts.storage import (
    CONTRACT_STORAGE_KEY,
    build_canonical_binding_projection,
    deserialize_calculation_envelope,
    deserialize_snapshot_envelope,
    empty_contract_storage,
    extract_contract_storage,
    serialize_calculation_envelope,
    serialize_snapshot_envelope,
    validate_metadata_update_preservation,
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


def _validate_bound_slot_match(
    calc_id: str, bound_slot: BoundSlotInput, snap_slot: BoundSlotInput
) -> None:
    if to_canonical_dict(bound_slot) != to_canonical_dict(snap_slot):
        raise InputIntegrityError(
            f"Calculation '{calc_id}' bound slot '{bound_slot.slot_id}' does not match referenced snapshot slot"
        )


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
                    with _sqlite_verified_read_connection(
                        database_path, expected_identity=self._database_identity
                    ) as connection:
                        row = connection.execute(
                            "SELECT metadata_json FROM run_metadata WHERE run_id = ?",
                            (self.run_id,),
                        ).fetchone()
                        if row is None:
                            raise CorruptedStorageError("run metadata disappeared during open")
                        extract_contract_storage(row["metadata_json"], expected_run_id=self.run_id)
                        evidence_rows = connection.execute(
                            "SELECT evidence_id, metadata_json FROM evidence WHERE run_id = ?",
                            (self.run_id,),
                        ).fetchall()
                        for evidence_row in evidence_rows:
                            if not evidence_row["metadata_json"]:
                                continue
                            try:
                                evidence_meta = json.loads(evidence_row["metadata_json"])
                                typed_envelope = evidence_meta.get("contract_envelope")
                                cached = evidence_meta.get("canonical_payload")
                                if typed_envelope is None and cached is None:
                                    continue
                                if not isinstance(typed_envelope, dict) or not isinstance(cached, dict):
                                    raise ValueError("typed envelope or projection missing")
                                kind, _ = decode_envelope(typed_envelope)
                                dto = decode_contract(typed_envelope, expected_kind=kind)
                                if build_canonical_binding_projection(dto) != cached:
                                    raise ValueError("cached projection differs from typed source")
                                if build_canonical_binding_projection(dto).get("evidence_id") != evidence_row["evidence_id"]:
                                    raise ValueError("typed evidence identity differs from row id")
                            except Exception as exc:
                                raise CorruptedStorageError(
                                    f"Evidence '{evidence_row['evidence_id']}' integrity validation failed: {exc}"
                                ) from exc
                except (OSError, StorageIdentityError, ValueError) as exc:
                    report = RunValidationReport(
                        False,
                        database_path,
                        (f"run identity validation error: {exc}",),
                    )
                    self.status = RunDatabaseStatus.INVALID
                    self._database_identity = None
                except CorruptedStorageError as exc:
                    report = RunValidationReport(False, database_path, (f"contract ledger validation failed: {exc}",))
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
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            existing_metadata_json = row["metadata_json"] if row else None
            merged_metadata = validate_metadata_update_preservation(
                existing_metadata_json, metadata
            )
            cursor = connection.execute(
                "UPDATE run_metadata SET run_status = ?, request_mode = ?, metadata_json = ? "
                "WHERE run_id = ?",
                (
                    run_status,
                    request_mode,
                    json.dumps(merged_metadata, sort_keys=True) if merged_metadata else None,
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

    def add_contract_evidence(
        self,
        *,
        evidence_id: str,
        contract_envelope: dict[str, Any],
        source_uri: str | None = None,
        content_hash: str | None = None,
        evidence_type: str = "contract_envelope",
    ) -> None:
        """Persist evidence containing a validated typed contract envelope."""
        kind, payload = decode_envelope(contract_envelope)
        envelope_json = json.dumps(contract_envelope, sort_keys=True)
        if len(envelope_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise InputIntegrityError(f"Envelope exceeds {MAX_PAYLOAD_BYTES} bytes budget")

        # Strict typed decoding of the contract envelope
        dto = decode_contract(contract_envelope, expected_kind=kind)
        projection = build_canonical_binding_projection(dto)

        c_hash = content_hash or compute_semantic_hash(payload)
        metadata = {
            "contract_envelope": contract_envelope,
            "canonical_payload": projection,
            "contract_kind": kind,
        }
        self.add_evidence(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            source_uri=source_uri,
            content_hash=c_hash,
            metadata=metadata,
        )

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

    def persist_contract_snapshot(
        self,
        snapshot: SelectedInputSet,
        *,
        expected_revision: int | None = None,
        calculations: tuple[CalculationRecord, ...] = (),
        project_compatible: bool = True,
    ) -> int:
        """Persist a typed selection snapshot and optional calculations atomically in run.db.

        Enforces:
        - Atomic sqlite transaction (rollback on any failure)
        - Run ID match between snapshot and manager
        - Snapshot hash integrity and payload budget check (< 256 KB)
        - Expected revision compare-and-swap (CAS) check
        - Snapshot selection_version == cur_rev + 1
        - Referenced evidence existence in this run's evidence table
        - Referenced observation existence in this run's market_observations table
        - Cross-run reference rejection
        - Calculation run_id, lineage hash, status-numeric coherence, and bound input consistency
        - Append-only snapshot hash chain and tamper verification
        - Active selection tracking via active_selections pointer
        - Idempotent retry handling for identical snapshot
        - Backward-compatible projections to evidence.selection_state, observation_selections, calculations
        """
        if snapshot.request_hash is not None and (
            len(snapshot.request_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in snapshot.request_hash.lower())
        ):
            raise InputIntegrityError("Snapshot request_hash is not a resolvable SHA-256 request identity")
        if snapshot.run_id != self.run_id:
            raise InputIntegrityError(
                f"Snapshot run_id '{snapshot.run_id}' does not match manager run_id '{self.run_id}'"
            )
        if not snapshot.verify_hash():
            raise TamperDetectionError("Snapshot hash verification failed against its slots")

        snapshot_envelope = serialize_snapshot_envelope(snapshot)

        with self._mutation_connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("run metadata disappeared")

            storage = extract_contract_storage(row["metadata_json"], expected_run_id=self.run_id)
            meta_dict = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

            # Idempotent retry check: if identical snapshot already committed
            for entry in storage.get("history", []):
                if entry.get("snapshot_hash") == snapshot.snapshot_hash:
                    existing_snap = deserialize_snapshot_envelope(entry["envelope"])
                    if existing_snap == snapshot:
                        return entry["revision"]
                    raise InputIntegrityError(
                        f"Snapshot hash '{snapshot.snapshot_hash}' collides with existing entry but content differs"
                    )

            cur_rev = storage.get("latest_revision", 0)
            if expected_revision is not None and expected_revision != cur_rev:
                raise RevisionConflictError(
                    f"Revision conflict for run {self.run_id}: expected {expected_revision}, current is {cur_rev}"
                )
            if snapshot.selection_version != cur_rev + 1:
                raise RevisionConflictError(
                    f"Snapshot selection_version {snapshot.selection_version} must equal cur_rev + 1 ({cur_rev + 1})"
                )

            # Resolve and verify request descriptor
            resolved_request = None
            if snapshot.request_hash is not None:
                from investment_stack.contracts.storage import deserialize_request_envelope
                for req_entry in storage.get("requests", []):
                    if req_entry.get("request_hash") == snapshot.request_hash:
                        req_envelope = req_entry.get("envelope")
                        if req_envelope:
                            resolved_request = deserialize_request_envelope(req_envelope)
                            if resolved_request.compute_request_hash() != snapshot.request_hash:
                                raise InputIntegrityError(f"Request descriptor hash mismatch in storage for '{snapshot.request_hash}'")
                        break
                if resolved_request is None:
                    raise InputIntegrityError(f"Snapshot references unregistered request_hash '{snapshot.request_hash}'")

                if snapshot.purpose != str(resolved_request.purpose):
                    raise InputIntegrityError(f"Snapshot purpose '{snapshot.purpose}' does not match request '{resolved_request.purpose}'")
                if snapshot.instrument_id != resolved_request.instrument_id:
                    raise InputIntegrityError(f"Snapshot instrument '{snapshot.instrument_id}' does not match request '{resolved_request.instrument_id}'")

            request_slots_by_id = {s.slot_id: s for s in resolved_request.slots} if resolved_request else {}

            # Strict evidence and observation verification in DB for this run
            for slot in snapshot.slots:
                canonical: dict[str, Any] = {}
                proj_inst = None

                if slot.evidence_id:
                    ev_row = connection.execute(
                        "SELECT evidence_id, run_id, metadata_json, evidence_type, content_hash FROM evidence WHERE evidence_id = ?",
                        (slot.evidence_id,),
                    ).fetchone()
                    if ev_row is None:
                        raise EvidenceNotFoundError(
                            f"Evidence '{slot.evidence_id}' referenced in slot '{slot.slot_id}' does not exist in run.db"
                        )
                    if ev_row["run_id"] != self.run_id:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' belongs to run '{ev_row['run_id']}', cross-run references are rejected"
                        )
                    if not ev_row["metadata_json"]:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' has no canonical binding projection; raw untyped evidence cannot authorize bound calculation slots"
                        )
                    try:
                        ev_meta = json.loads(ev_row["metadata_json"])
                    except Exception as exc:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' metadata is invalid JSON: {exc}"
                        ) from exc
                    canonical = ev_meta.get("canonical_payload") if isinstance(ev_meta, dict) else {}
                    typed_envelope = ev_meta.get("contract_envelope") if isinstance(ev_meta, dict) else None
                    if not canonical or not isinstance(canonical, dict) or not typed_envelope:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' lacks canonical binding projection; raw untyped evidence cannot authorize bound calculation slots"
                        )
                    try:
                        kind, _ = decode_envelope(typed_envelope)
                        typed_dto = decode_contract(typed_envelope, expected_kind=kind)
                        verified_projection = build_canonical_binding_projection(typed_dto)
                    except Exception as exc:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' typed source is invalid: {exc}"
                        ) from exc
                    if canonical != verified_projection:
                        raise InputIntegrityError(
                            f"Evidence '{slot.evidence_id}' cached projection does not match its typed source"
                        )
                    if verified_projection.get("evidence_id") != slot.evidence_id:
                        raise InputIntegrityError(
                            f"Evidence row id '{slot.evidence_id}' does not match typed source identity"
                        )
                    if slot.input_fingerprint and slot.input_fingerprint != ev_row["content_hash"]:
                        raise InputIntegrityError(
                            f"Slot '{slot.slot_id}' input fingerprint does not match registered evidence content hash"
                        )
                    if slot.eligibility_id:
                        eligibility = ev_meta.get("eligibility_decisions", {})
                        decision = eligibility.get(slot.eligibility_id) if isinstance(eligibility, dict) else None
                        if not isinstance(decision, dict) or decision.get("status") != "ELIGIBLE":
                            raise InputIntegrityError(
                                f"Slot '{slot.slot_id}' references unresolved or non-eligible decision '{slot.eligibility_id}'"
                            )
                        if resolved_request:
                            if decision.get("policy_version") != resolved_request.policy_version:
                                raise InputIntegrityError(f"Slot '{slot.slot_id}' policy_version '{decision.get('policy_version')}' does not match request '{resolved_request.policy_version}'")

                    # Compare canonical_value
                    if "canonical_value" not in canonical or slot.canonical_value is None:
                        raise InputIntegrityError(f"Slot '{slot.slot_id}' lacks a verifiable canonical value")
                    if "canonical_value" in canonical and slot.canonical_value is not None:
                        proj_val = Decimal(str(canonical["canonical_value"]))
                        if slot.canonical_value != proj_val:
                            raise InputIntegrityError(
                                f"Slot '{slot.slot_id}' canonical_value '{slot.canonical_value}' does not match evidence '{slot.evidence_id}' projection value '{proj_val}'"
                            )

                    # Compare currency
                    proj_curr = canonical.get("canonical_currency") or canonical.get("currency")
                    if proj_curr is None or slot.canonical_currency is None:
                        raise InputIntegrityError(f"Slot '{slot.slot_id}' lacks a verifiable currency")
                    if proj_curr is not None and slot.canonical_currency is not None:
                        if proj_curr != slot.canonical_currency:
                            raise InputIntegrityError(
                                f"Slot '{slot.slot_id}' canonical_currency '{slot.canonical_currency}' does not match evidence '{slot.evidence_id}' currency '{proj_curr}'"
                            )
                    if canonical.get("canonical_unit") != slot.canonical_unit:
                        raise InputIntegrityError(
                            f"Slot '{slot.slot_id}' canonical_unit '{slot.canonical_unit}' does not match evidence unit '{canonical.get('canonical_unit')}'"
                        )
                    if slot.public_available_at is not None and slot.public_available_at != canonical.get("public_available_at"):
                        raise InputIntegrityError(
                            f"Slot '{slot.slot_id}' public availability does not match typed evidence"
                        )

                    # Compare instrument_id if present in snapshot/slot and projection
                    proj_inst = canonical.get("instrument_id")
                    if proj_inst is not None and snapshot.instrument_id is not None:
                        if proj_inst != snapshot.instrument_id:
                            raise InputIntegrityError(
                                f"Snapshot instrument_id '{snapshot.instrument_id}' does not match evidence '{slot.evidence_id}' instrument '{proj_inst}'"
                            )

                # Verify against SelectionRequest constraints if specified (even if evidence_id is missing)
                if request_slots_by_id:
                    req_slot = request_slots_by_id.get(slot.slot_id)
                    if req_slot is None:
                        raise InputIntegrityError(f"Snapshot slot '{slot.slot_id}' is not requested by the selection request")

                    meta_for_match = dict(canonical) if canonical else {}
                    if "canonical_currency" in meta_for_match:
                        meta_for_match["currency"] = meta_for_match["canonical_currency"]
                    if "availability_interval_end" in meta_for_match:
                        meta_for_match["period_end"] = meta_for_match["availability_interval_end"]
                    if "availability_interval_start" in meta_for_match:
                        meta_for_match["period_start"] = meta_for_match["availability_interval_start"]

                    match_ok, match_err = req_slot.matches_candidate(
                        candidate_currency=slot.canonical_currency,
                        candidate_instrument_id=proj_inst,
                        candidate_metadata=meta_for_match,
                    )
                    if not match_ok:
                        raise InputIntegrityError(f"Slot '{slot.slot_id}' does not match request constraints: {match_err}")

                    if req_slot.metric != meta_for_match.get("metric"):
                        raise InputIntegrityError(f"Slot '{slot.slot_id}' metric '{meta_for_match.get('metric')}' does not match request metric '{req_slot.metric}'")

                    if resolved_request.as_of and canonical.get("public_available_at"):
                        try:
                            dt_avail = datetime.fromisoformat(canonical["public_available_at"].replace("Z", "+00:00"))
                            dt_asof = datetime.fromisoformat(resolved_request.as_of.replace("Z", "+00:00"))
                            if dt_avail.tzinfo is None or dt_asof.tzinfo is None:
                                raise ValueError
                            if dt_avail > dt_asof:
                                raise InputIntegrityError(f"Slot '{slot.slot_id}' typed evidence available_at '{canonical['public_available_at']}' is after request as_of '{resolved_request.as_of}'")
                        except ValueError:
                            # If they aren't valid aware ISO8601 strings, fallback to string compare or fail.
                            # Instructions: "timezone-aware 시각으로 하며 ISO 문자열의 사전식 비교에 의존하지 않는다."
                            raise InputIntegrityError("as_of and public_available_at must be valid timezone-aware datetimes")

            if resolved_request:
                provided_slot_ids = {s.slot_id for s in snapshot.slots}
                missing_slots = set(request_slots_by_id.keys()) - provided_slot_ids
                if missing_slots:
                    raise InputIntegrityError(f"Snapshot missing requested slots: {sorted(missing_slots)}")

                if slot.observation_id:
                    obs_row = connection.execute(
                        "SELECT observation_id, run_id, evidence_id FROM market_observations WHERE observation_id = ?",
                        (slot.observation_id,),
                    ).fetchone()
                    if obs_row is None:
                        raise InputIntegrityError(
                            f"Observation '{slot.observation_id}' referenced in slot '{slot.slot_id}' does not exist in run.db"
                        )
                    if obs_row["run_id"] != self.run_id:
                        raise InputIntegrityError(
                            f"Observation '{slot.observation_id}' belongs to run '{obs_row['run_id']}', cross-run references are rejected"
                        )
                    if slot.evidence_id and obs_row["evidence_id"] and obs_row["evidence_id"] != slot.evidence_id:
                        raise InputIntegrityError(
                            f"Observation '{slot.observation_id}' evidence_id '{obs_row['evidence_id']}' does not match slot evidence_id '{slot.evidence_id}'"
                        )

            # Verify calculations
            snapshot_slots_by_id = {s.slot_id: s for s in snapshot.slots}
            calc_entries = list(storage.get("calculations", []))
            for calc in calculations:
                if calc.run_id != self.run_id:
                    raise InputIntegrityError(
                        f"Calculation '{calc.calculation_id}' run_id '{calc.run_id}' does not match manager run_id '{self.run_id}'"
                    )
                if not calc.verify_lineage():
                    raise InputIntegrityError(
                        f"Calculation '{calc.calculation_id}' lineage hash verification failed"
                    )
                if calc.status in (CalculationStatus.UNAVAILABLE, CalculationStatus.FAILED) and calc.result_numeric is not None:
                    raise InputIntegrityError(
                        f"Calculation '{calc.calculation_id}' has status {calc.status} but non-None result_numeric"
                    )
                if calc.selection_snapshot_hash != snapshot.snapshot_hash:
                    known_map = {h["snapshot_hash"]: h for h in storage.get("history", [])}
                    if calc.selection_snapshot_hash not in known_map:
                        raise InputIntegrityError(
                            f"Calculation '{calc.calculation_id}' references unknown snapshot hash '{calc.selection_snapshot_hash}'"
                        )
                    ref_snap = deserialize_snapshot_envelope(known_map[calc.selection_snapshot_hash]["envelope"])
                    ref_slots_by_id = {s.slot_id: s for s in ref_snap.slots}
                else:
                    ref_slots_by_id = snapshot_slots_by_id

                # Verify calculation bound inputs match referenced snapshot slots
                seen_calc_slot_ids: set[str] = set()
                for bound_slot in calc.bound_inputs:
                    if bound_slot.slot_id in seen_calc_slot_ids:
                        raise InputIntegrityError(
                            f"Calculation '{calc.calculation_id}' contains duplicate bound input slot '{bound_slot.slot_id}'"
                        )
                    seen_calc_slot_ids.add(bound_slot.slot_id)
                    if bound_slot.slot_id not in ref_slots_by_id:
                        raise InputIntegrityError(
                            f"Calculation '{calc.calculation_id}' bound input slot '{bound_slot.slot_id}' not found in snapshot"
                        )
                    snap_slot = ref_slots_by_id[bound_slot.slot_id]
                    _validate_bound_slot_match(calc.calculation_id, bound_slot, snap_slot)

                # Check preceding calculations
                existing_calc_ids = {c["calculation_id"] for c in calc_entries}
                for prec_id in calc.preceding_calculation_ids:
                    if prec_id not in existing_calc_ids:
                        raise InputIntegrityError(
                            f"Calculation '{calc.calculation_id}' references non-existent preceding calculation '{prec_id}'"
                        )

                calc_envelope = serialize_calculation_envelope(calc)
                calc_entries.append(
                    {
                        "calculation_id": calc.calculation_id,
                        "committed_at": datetime.now(timezone.utc).isoformat(),
                        "envelope": calc_envelope,
                    }
                )
                if project_compatible:
                    connection.execute(
                        "INSERT INTO calculations "
                        "(calculation_id, run_id, calculation_name, formula, inputs_json, result_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            calc.calculation_id,
                            self.run_id,
                            calc.calculation_name,
                            f"{calc.formula_id}:{calc.formula_version}",
                            json.dumps(
                                [to_canonical_dict(s) for s in calc.bound_inputs], sort_keys=True
                            ),
                            json.dumps(
                                {
                                    "numeric": format_decimal(calc.result_numeric)
                                    if calc.result_numeric is not None
                                    else None,
                                    "unit": calc.result_unit,
                                    "currency": calc.result_currency,
                                    "payload": to_canonical_dict(calc.result_payload),
                                    "status": str(calc.status),
                                    "lineage_hash": calc.lineage_hash,
                                },
                                sort_keys=True,
                            ),
                            calc.calculated_at or datetime.now(timezone.utc).isoformat(),
                        ),
                    )

            # Project compatible selection states
            if project_compatible:
                for slot in snapshot.slots:
                    if slot.evidence_id:
                        connection.execute(
                            "UPDATE evidence SET selection_state = ?, selection_reason = ? "
                            "WHERE evidence_id = ? AND run_id = ?",
                            (
                                "SELECTED",
                                f"bound_to_slot:{slot.slot_id}",
                                slot.evidence_id,
                                self.run_id,
                            ),
                        )
                    if slot.observation_id:
                        obs_row = connection.execute(
                            "SELECT observation_id FROM market_observations WHERE observation_id = ? AND run_id = ?",
                            (slot.observation_id, self.run_id),
                        ).fetchone()
                        if obs_row is not None:
                            connection.execute(
                                "INSERT OR REPLACE INTO observation_selections "
                                "(selection_id, run_id, observation_id, selection_reason, selected_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (
                                    f"sel:{slot.slot_id}:{snapshot.selection_version}",
                                    self.run_id,
                                    slot.observation_id,
                                    f"bound_to_slot:{slot.slot_id}",
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                            )

            # Append to history and update active selections pointer
            new_rev = cur_rev + 1
            prev_hash = storage.get("latest_snapshot_hash", "")
            history_entry = {
                "revision": new_rev,
                "previous_snapshot_hash": prev_hash,
                "snapshot_hash": snapshot.snapshot_hash,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "envelope": snapshot_envelope,
            }
            history = list(storage.get("history", []))
            history.append(history_entry)

            active_selections = storage.setdefault("active_selections", {})
            active_selections[snapshot.active_key] = snapshot.snapshot_hash

            storage["latest_revision"] = new_rev
            storage["latest_snapshot_hash"] = snapshot.snapshot_hash
            storage["history"] = history
            storage["calculations"] = calc_entries
            meta_dict[CONTRACT_STORAGE_KEY] = storage

            connection.execute(
                "UPDATE run_metadata SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta_dict, sort_keys=True), self.run_id),
            )
            return new_rev

    def fetch_contract_snapshots(
        self,
        purpose: str | None = None,
        *,
        instrument_id: str | None = None,
        request_hash: str | None = None,
    ) -> tuple[SelectedInputSet, ...]:
        """Retrieve and strictly verify all SelectedInputSet snapshots, optionally filtered."""
        meta = self.fetch_metadata()
        storage = extract_contract_storage(meta.get("metadata_json"), expected_run_id=self.run_id)
        history = storage.get("history", [])
        snapshots: list[SelectedInputSet] = []
        for entry in history:
            envelope = entry.get("envelope")
            if envelope:
                snap = deserialize_snapshot_envelope(envelope)
                if purpose is not None and snap.purpose != purpose:
                    continue
                if instrument_id is not None and snap.instrument_id != instrument_id:
                    continue
                if request_hash is not None and snap.request_hash != request_hash:
                    continue
                snapshots.append(snap)
        return tuple(snapshots)

    def fetch_active_contract_snapshot(
        self,
        purpose: str,
        *,
        instrument_id: str | None = None,
        request_hash: str | None = None,
    ) -> SelectedInputSet | None:
        """Retrieve the active SelectedInputSet snapshot for a given purpose via active_selections pointer.

        Supports multi-part request scoping (purpose:instrument:request_hash).
        Rejects ambiguous partial matches with AmbiguousSnapshotError.
        """
        meta = self.fetch_metadata()
        storage = extract_contract_storage(meta.get("metadata_json"), expected_run_id=self.run_id)
        active_map = storage.get("active_selections", {})

        matching_keys: list[str] = []
        for key in active_map:
            parts = key.split(":")
            p = parts[0]
            if p != purpose:
                continue
            key_inst = parts[1] if len(parts) > 1 else None
            key_req = parts[2] if len(parts) > 2 else None

            # Match instrument
            if instrument_id is not None:
                if key_inst is not None and key_inst != "*" and key_inst != instrument_id:
                    continue

            # Match request_hash
            if request_hash is not None:
                if key_req is not None and key_req != "*" and key_req != request_hash:
                    continue

            matching_keys.append(key)

        if len(matching_keys) > 1:
            target_hashes = {active_map[k] for k in matching_keys}
            if len(target_hashes) > 1:
                scope_desc = f"purpose '{purpose}'"
                if instrument_id:
                    scope_desc += f", instrument '{instrument_id}'"
                if request_hash:
                    scope_desc += f", request_hash '{request_hash}'"
                raise AmbiguousSnapshotError(
                    f"Ambiguous active snapshot query for {scope_desc}: found multiple active entries "
                    f"({sorted(matching_keys)}). Must specify narrower scope."
                )
            target_hash = target_hashes.pop()
        elif len(matching_keys) == 1:
            target_hash = active_map[matching_keys[0]]
        else:
            return None

        history = storage.get("history", [])
        for entry in history:
            if entry.get("snapshot_hash") == target_hash:
                envelope = entry.get("envelope")
                if envelope:
                    snap = deserialize_snapshot_envelope(envelope)
                    if snap.active_key != matching_keys[0]:
                        raise CorruptedStorageError(
                            f"Active pointer scope '{matching_keys[0]}' targets snapshot scope '{snap.active_key}'"
                        )
                    if snap.purpose != purpose:
                        raise CorruptedStorageError("Active pointer target purpose does not match query")
                    if instrument_id is not None and snap.instrument_id != instrument_id:
                        raise CorruptedStorageError("Active pointer target instrument does not match query")
                    if request_hash is not None and snap.request_hash != request_hash:
                        raise CorruptedStorageError("Active pointer target request does not match query")
                    return snap
        return None

    def fetch_latest_contract_snapshot(
        self,
        purpose: str,
        *,
        instrument_id: str | None = None,
        request_hash: str | None = None,
    ) -> SelectedInputSet | None:
        """Retrieve the latest/active valid SelectedInputSet snapshot for a given purpose."""
        active = self.fetch_active_contract_snapshot(
            purpose, instrument_id=instrument_id, request_hash=request_hash
        )
        if active is not None:
            return active
        snapshots = self.fetch_contract_snapshots(
            purpose=purpose, instrument_id=instrument_id, request_hash=request_hash
        )
        return snapshots[-1] if snapshots else None

    def persist_contract_calculation(
        self, record: CalculationRecord, *, project_compatible: bool = True
    ) -> None:
        """Persist a single CalculationRecord into the run contract storage and optional projection.

        Enforces:
        - Atomic sqlite transaction
        - Run ID match between record and manager
        - Lineage hash integrity
        - Result numeric is None when status is UNAVAILABLE or FAILED
        - Referenced snapshot hash exists in history
        - Bound inputs match referenced snapshot slots (no duplicate slots)
        - Preceding calculations exist in current run
        - Idempotent retry for identical calculation
        - Payload budget (< 256 KB)
        """
        if record.run_id != self.run_id:
            raise InputIntegrityError(
                f"Calculation run_id '{record.run_id}' does not match manager run_id '{self.run_id}'"
            )
        if not record.verify_lineage():
            raise InputIntegrityError(
                f"Calculation '{record.calculation_id}' lineage hash verification failed"
            )
        if record.status in (CalculationStatus.UNAVAILABLE, CalculationStatus.FAILED) and record.result_numeric is not None:
            raise InputIntegrityError(
                f"Calculation '{record.calculation_id}' has status {record.status} but non-None result_numeric"
            )

        calc_envelope = serialize_calculation_envelope(record)

        with self._mutation_connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("run metadata disappeared")

            storage = extract_contract_storage(row["metadata_json"], expected_run_id=self.run_id)
            meta_dict = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

            calc_entries = list(storage.get("calculations", []))
            # Idempotent retry check
            for entry in calc_entries:
                if entry.get("calculation_id") == record.calculation_id:
                    existing = deserialize_calculation_envelope(entry["envelope"])
                    if existing == record:
                        return
                    raise InputIntegrityError(
                        f"Calculation '{record.calculation_id}' already exists with differing payload"
                    )

            # Snapshot reference check
            matching_snap_entry = None
            for h_entry in storage.get("history", []):
                if h_entry.get("snapshot_hash") == record.selection_snapshot_hash:
                    matching_snap_entry = h_entry
                    break
            if matching_snap_entry is None:
                raise InputIntegrityError(
                    f"Referenced selection snapshot hash '{record.selection_snapshot_hash}' does not exist in run contract history"
                )

            snap = deserialize_snapshot_envelope(matching_snap_entry["envelope"])
            snap_slots_by_id = {s.slot_id: s for s in snap.slots}

            seen_calc_slot_ids: set[str] = set()
            for bound_slot in record.bound_inputs:
                if bound_slot.slot_id in seen_calc_slot_ids:
                    raise InputIntegrityError(
                        f"Calculation '{record.calculation_id}' contains duplicate bound input slot '{bound_slot.slot_id}'"
                    )
                seen_calc_slot_ids.add(bound_slot.slot_id)
                if bound_slot.slot_id not in snap_slots_by_id:
                    raise InputIntegrityError(
                        f"Calculation '{record.calculation_id}' bound input slot '{bound_slot.slot_id}' not found in referenced snapshot"
                    )
                snap_slot = snap_slots_by_id[bound_slot.slot_id]
                _validate_bound_slot_match(record.calculation_id, bound_slot, snap_slot)

            # Check preceding calculations
            existing_calc_ids = {c["calculation_id"] for c in calc_entries}
            for prec_id in record.preceding_calculation_ids:
                if prec_id not in existing_calc_ids:
                    raise InputIntegrityError(
                        f"Calculation '{record.calculation_id}' references non-existent preceding calculation '{prec_id}'"
                    )

            calc_entries.append(
                {
                    "calculation_id": record.calculation_id,
                    "committed_at": datetime.now(timezone.utc).isoformat(),
                    "envelope": calc_envelope,
                }
            )
            storage["calculations"] = calc_entries
            meta_dict[CONTRACT_STORAGE_KEY] = storage

            if project_compatible:
                connection.execute(
                    "INSERT INTO calculations "
                    "(calculation_id, run_id, calculation_name, formula, inputs_json, result_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.calculation_id,
                        self.run_id,
                        record.calculation_name,
                        f"{record.formula_id}:{record.formula_version}",
                        json.dumps(
                            [to_canonical_dict(s) for s in record.bound_inputs], sort_keys=True
                        ),
                        json.dumps(
                            {
                                "numeric": format_decimal(record.result_numeric)
                                if record.result_numeric is not None
                                else None,
                                "unit": record.result_unit,
                                "currency": record.result_currency,
                                "payload": to_canonical_dict(record.result_payload),
                                "status": str(record.status),
                                "lineage_hash": record.lineage_hash,
                            },
                            sort_keys=True,
                        ),
                        record.calculated_at or datetime.now(timezone.utc).isoformat(),
                    ),
                )

            connection.execute(
                "UPDATE run_metadata SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta_dict, sort_keys=True), self.run_id),
            )

    def persist_selection_request(self, request: Any) -> None:
        """Persist a SelectionRequest into the run contract storage."""
        # Local import to avoid circular dependency
        from investment_stack.contracts.slots import SelectionRequest
        from investment_stack.contracts.storage import serialize_request_envelope

        if not isinstance(request, SelectionRequest):
            raise TypeError("Expected a SelectionRequest instance")

        req_hash = request.compute_request_hash()
        req_envelope = serialize_request_envelope(request)

        with self._mutation_connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM run_metadata WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("run metadata disappeared")

            storage = extract_contract_storage(row["metadata_json"], expected_run_id=self.run_id)
            meta_dict = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

            requests = list(storage.get("requests", []))
            for entry in requests:
                if entry.get("request_hash") == req_hash:
                    return  # Idempotent retry

            requests.append(
                {
                    "request_hash": req_hash,
                    "committed_at": datetime.now(timezone.utc).isoformat(),
                    "envelope": req_envelope,
                }
            )
            storage["requests"] = requests
            meta_dict[CONTRACT_STORAGE_KEY] = storage

            connection.execute(
                "UPDATE run_metadata SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta_dict, sort_keys=True), self.run_id),
            )

    def fetch_contract_calculations(self) -> tuple[CalculationRecord, ...]:
        """Retrieve and strictly verify all CalculationRecords from the run contract storage."""
        meta = self.fetch_metadata()
        storage = extract_contract_storage(meta.get("metadata_json"), expected_run_id=self.run_id)
        calc_entries = storage.get("calculations", [])
        calcs: list[CalculationRecord] = []
        for entry in calc_entries:
            envelope = entry.get("envelope")
            if envelope:
                calcs.append(deserialize_calculation_envelope(envelope))
        return tuple(calcs)

    def verify_contract_storage_integrity(self) -> bool:
        """Verify hash chaining, revisions, active pointers, and content integrity across the entire contract history."""
        meta = self.fetch_metadata()
        storage = extract_contract_storage(meta.get("metadata_json"), expected_run_id=self.run_id)
        history = storage.get("history", [])
        expected_prev_hash = ""
        expected_rev = 1
        known_snapshot_hashes: set[str] = set()

        for entry in history:
            if entry.get("revision") != expected_rev:
                return False
            expected_rev += 1

            prev_hash = entry.get("previous_snapshot_hash", "")
            if prev_hash != expected_prev_hash:
                return False
            envelope = entry.get("envelope")
            if not envelope:
                return False
            try:
                snap = deserialize_snapshot_envelope(envelope)
                if snap.snapshot_hash != entry.get("snapshot_hash"):
                    return False
                if not snap.verify_hash():
                    return False
                expected_prev_hash = snap.snapshot_hash
                known_snapshot_hashes.add(snap.snapshot_hash)
            except Exception:
                return False

        # Verify active_selections pointers point to existing snapshots in history
        active_selections = storage.get("active_selections", {})
        if not isinstance(active_selections, dict):
            return False
        for purpose, active_h in active_selections.items():
            if active_h not in known_snapshot_hashes:
                return False

        # Verify calculations
        for c_entry in storage.get("calculations", []):
            c_envelope = c_entry.get("envelope")
            if not c_envelope:
                return False
            try:
                calc = deserialize_calculation_envelope(c_envelope)
                if not calc.verify_lineage():
                    return False
                if calc.selection_snapshot_hash not in known_snapshot_hashes:
                    return False
            except Exception:
                return False
        return True
