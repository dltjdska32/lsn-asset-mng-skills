"""Fail-closed startup, migration, backup, guarded writes, and restore."""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Callable, Iterator, Sequence

from investment_stack.migrations.personal import PERSONAL_MIGRATIONS
from investment_stack.personal.backup import (
    BackupError,
    BackupResult,
    BackupStatus,
    PersonalBackupService,
)
from investment_stack.personal.paths import (
    UnsafeStoragePath,
    resolve_backup_directory,
    resolve_personal_db_path,
    validate_personal_operational_path,
)
from investment_stack.personal.validation import (
    PersonalValidationReport,
    validate_personal_connection,
    validate_personal_database,
)
from investment_stack.storage.migrations import (
    Migration,
    MigrationHook,
    apply_pending_migrations,
    ensure_migration_table,
    validate_migration_catalog,
)
from investment_stack.storage.identity import (
    PathIdentity,
    StorageIdentityError,
    get_path_identity,
    verify_opened_database_identity,
)
from investment_stack.storage.permissions import protect_directory, protect_file
from investment_stack.storage.sqlite import (
    _sqlite_write_connection,
    sqlite_readonly_connection,
    sqlite_transaction,
)


class PersonalDatabaseStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    READ_ONLY_RECOVERY_MODE = "READ_ONLY_RECOVERY_MODE"
    STARTUP_BLOCKED = "STARTUP_BLOCKED"


class MigrationStatus(StrEnum):
    MIGRATED = "MIGRATED"
    UP_TO_DATE = "UP_TO_DATE"
    MIGRATION_ABORTED = "MIGRATION_ABORTED"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    POST_VALIDATION_FAILED = "POST_VALIDATION_FAILED"


class RestoreStatus(StrEnum):
    RESTORED = "RESTORED"
    RESTORE_REJECTED = "RESTORE_REJECTED"
    RESTORE_FAILED = "RESTORE_FAILED"


class StorageNotWritableError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartupResult:
    status: PersonalDatabaseStatus
    validation: PersonalValidationReport | None
    reason: str | None = None


@dataclass(frozen=True)
class MigrationResult:
    status: MigrationStatus
    previous_version: int | None
    current_version: int | None
    backup: BackupResult | None
    reason: str | None = None


@dataclass(frozen=True)
class RestoreResult:
    status: RestoreStatus
    validation: PersonalValidationReport | None
    emergency_backup: BackupResult | None
    reason: str | None = None


def _assert_personal_db_status_writable(status: PersonalDatabaseStatus) -> None:
    if status is not PersonalDatabaseStatus.VALID:
        raise StorageNotWritableError(
            f"personal database mutation blocked while status is {status.value}"
        )


def _default_writability_probe(path: Path) -> bool:
    target = path if path.exists() else path.parent
    return os.access(target, os.W_OK)


class PersonalDatabaseManager:
    """Coordinates storage safety without implementing ledger behavior."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        backup_directory: str | Path | None = None,
        repository_root: Path | None = None,
        migrations: Sequence[Migration] = PERSONAL_MIGRATIONS,
        backup_service: PersonalBackupService | None = None,
        writability_probe: Callable[[Path], bool] = _default_writability_probe,
    ) -> None:
        self.migrations = validate_migration_catalog(migrations)
        self.repository_root = (
            None
            if repository_root is None
            else Path(repository_root).expanduser().resolve(strict=False)
        )
        self.database_path = resolve_personal_db_path(
            database_path, repository_root=self.repository_root
        )
        self._database_path_anchor = self.database_path
        resolved_backup_directory = resolve_backup_directory(
            backup_directory, repository_root=self.repository_root
        )
        self.backup_service = backup_service or PersonalBackupService(
            resolved_backup_directory,
            repository_root=self.repository_root,
        )
        self.writability_probe = writability_probe
        self.status = PersonalDatabaseStatus.STARTUP_BLOCKED
        self.last_error: str | None = None
        self._instance_id: str | None = None
        self._database_identity: PathIdentity | None = None
        self._operation_lock = RLock()
        self._write_in_progress = False

    @property
    def current_schema_version(self) -> int:
        return self.migrations[-1].version

    @property
    def instance_id(self) -> str | None:
        return self._instance_id

    @staticmethod
    def _sidecar_paths(path: Path) -> tuple[Path, ...]:
        return (
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
            Path(f"{path}-journal"),
        )

    @classmethod
    def _cleanup_sqlite_artifacts(cls, path: Path) -> tuple[str, ...]:
        errors: list[str] = []
        for artifact in (path, *cls._sidecar_paths(path)):
            try:
                artifact.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"could not remove {artifact.name}: {exc}")
        return tuple(errors)

    def _operational_database_path(self) -> Path:
        return validate_personal_operational_path(
            self.database_path,
            repository_root=self.repository_root,
            expected_suffix=".db",
            expected_resolved=self._database_path_anchor,
        )

    def _validate(self, *, require_current: bool) -> PersonalValidationReport:
        return validate_personal_database(
            self._operational_database_path(),
            require_current=require_current,
            migrations=self.migrations,
        )

    def _set_valid(self, report: PersonalValidationReport) -> bool:
        try:
            database_path = self._operational_database_path()
            identity = get_path_identity(database_path)
            if report.path.resolve(strict=False) != identity.resolved_path:
                raise StorageIdentityError(
                    "validation report path does not match the active database"
                )
        except (OSError, ValueError, StorageIdentityError) as exc:
            self._set_blocked(f"personal database identity validation failed: {exc}")
            return False
        self._database_identity = identity
        self.status = PersonalDatabaseStatus.VALID
        self.last_error = None
        self._instance_id = report.instance_id
        return True

    def _set_blocked(self, reason: str) -> None:
        self.status = PersonalDatabaseStatus.STARTUP_BLOCKED
        self.last_error = reason

    def _verify_active_and_set_status(
        self, expected_instance_id: str | None
    ) -> PersonalValidationReport | None:
        try:
            report = self._validate(require_current=True)
        except (OSError, ValueError) as exc:
            self._set_blocked(f"active database revalidation failed: {exc}")
            return None
        if (
            report.valid
            and report.instance_id is not None
            and (
                expected_instance_id is None
                or report.instance_id == expected_instance_id
            )
            and self.writability_probe(report.path)
        ):
            self._set_valid(report)
        else:
            self._set_blocked("active database could not be proven safe after restore")
        return report

    def initialize(self) -> StartupResult:
        """Create a new personal database and validate it before enabling writes."""

        with self._operation_lock:
            self._set_blocked("personal database initialization in progress")
            try:
                database_path = self._operational_database_path()
                if database_path.exists():
                    raise FileExistsError(database_path)
                protect_directory(database_path.parent)
                database_path = self._operational_database_path()
                descriptor = os.open(
                    database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
                os.close(descriptor)
                database_path = self._operational_database_path()
                database_identity = get_path_identity(database_path)
                with _sqlite_write_connection(
                    database_path, expected_identity=database_identity
                ) as connection:
                    with sqlite_transaction(connection):
                        ensure_migration_table(connection)
                        apply_pending_migrations(connection, self.migrations)
                        verify_opened_database_identity(
                            connection,
                            expected_path=database_path,
                            expected_identity=database_identity,
                        )
                protect_file(database_path)
            except FileExistsError:
                raise
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                self._set_blocked(f"personal database initialization failed: {exc}")
                return StartupResult(self.status, None, self.last_error)

            report = self._validate(require_current=True)
            if not report.valid:
                self.status = PersonalDatabaseStatus.INVALID
                self.last_error = "; ".join(report.errors)
                return StartupResult(self.status, report, self.last_error)
            if not self.writability_probe(database_path):
                self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                self.last_error = "personal database is not writable"
                return StartupResult(self.status, report, self.last_error)
            self._set_valid(report)
            return StartupResult(self.status, report)

    def startup(self, *, auto_migrate: bool = True) -> StartupResult:
        """Fail closed on corruption, incompatible schema, or unwritable storage."""

        with self._operation_lock:
            try:
                database_path = self._operational_database_path()
            except UnsafeStoragePath as exc:
                self._set_blocked(f"personal database path validation failed: {exc}")
                return StartupResult(self.status, None, self.last_error)
            if not database_path.exists():
                return self.initialize()
            report = self._validate(require_current=False)
            if not report.valid:
                self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                self.last_error = "; ".join(report.errors)
                return StartupResult(self.status, report, self.last_error)
            if report.schema_version != self.current_schema_version:
                if not auto_migrate:
                    self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                    self.last_error = "personal database migration is required"
                    return StartupResult(self.status, report, self.last_error)
                migration = self.migrate()
                final = self._validate(require_current=True)
                return StartupResult(self.status, final, migration.reason)
            exact = self._validate(require_current=True)
            if not exact.valid:
                self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                self.last_error = "; ".join(exact.errors)
                return StartupResult(self.status, exact, self.last_error)
            if not self.writability_probe(database_path):
                self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                self.last_error = "personal database is not writable"
                return StartupResult(self.status, exact, self.last_error)
            self._set_valid(exact)
            return StartupResult(self.status, exact)

    @contextmanager
    def guarded_write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield the only supported personal mutation connection after fresh checks."""

        with self._operation_lock:
            _assert_personal_db_status_writable(self.status)
            if self._write_in_progress:
                raise StorageNotWritableError(
                    "nested personal database write boundaries are not supported"
                )
            self._write_in_progress = True
            try:
                database_path = self._operational_database_path()
                if not self.writability_probe(database_path):
                    self.status = PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE
                    self.last_error = "personal database became read-only"
                    _assert_personal_db_status_writable(self.status)
                database_identity = self._database_identity
                if database_identity is None:
                    self._set_blocked("personal database identity was not established")
                    raise StorageNotWritableError(self.last_error)
                with _sqlite_write_connection(
                    database_path, expected_identity=database_identity
                ) as connection:
                    with sqlite_transaction(connection):
                        before = validate_personal_connection(
                            connection,
                            path=database_path,
                            require_current=True,
                            migrations=self.migrations,
                        )
                        if (
                            not before.valid
                            or before.instance_id is None
                            or before.instance_id != self._instance_id
                        ):
                            self.status = PersonalDatabaseStatus.INVALID
                            self.last_error = "personal database changed after startup"
                            raise StorageNotWritableError(self.last_error)
                        yield connection
                        after = validate_personal_connection(
                            connection,
                            path=database_path,
                            require_current=True,
                            migrations=self.migrations,
                        )
                        if (
                            not after.valid
                            or after.instance_id != before.instance_id
                        ):
                            self.status = PersonalDatabaseStatus.INVALID
                            self.last_error = "personal database became invalid during mutation"
                            raise StorageNotWritableError(self.last_error)
                        verify_opened_database_identity(
                            connection,
                            expected_path=database_path,
                            expected_identity=database_identity,
                        )
            except StorageNotWritableError:
                raise
            except (OSError, sqlite3.Error, StorageIdentityError, ValueError) as exc:
                self._set_blocked(f"personal database write boundary failed: {exc}")
                raise StorageNotWritableError(self.last_error) from exc
            finally:
                self._write_in_progress = False

    def assert_writable(self) -> None:
        with self.guarded_write_transaction():
            pass

    def _validate_backup_result(
        self,
        backup: object,
        *,
        source: PersonalValidationReport,
        expected_reason: str,
    ) -> BackupResult:
        if not isinstance(backup, BackupResult):
            raise BackupError("backup service returned an unsupported result")
        if backup.status is not BackupStatus.SUCCESS:
            raise BackupError("backup service did not return SUCCESS")
        if backup.validation is None or not backup.validation.valid:
            raise BackupError("backup service returned an invalid validation result")
        if backup.reason != expected_reason:
            raise BackupError("backup reason mismatch")
        if backup.path is None:
            raise BackupError("backup path is missing")
        path = validate_personal_operational_path(
            backup.path,
            repository_root=self.repository_root,
            expected_suffix=".db",
        )
        if not path.is_file() or path.stat().st_size == 0:
            raise BackupError("backup path is missing, empty, or not a regular file")
        active = self._operational_database_path()
        try:
            same_as_source = path == active or path.samefile(active)
        except OSError:
            same_as_source = path == active
        if same_as_source:
            raise BackupError("backup path is the active database")
        if any(sidecar.exists() for sidecar in self._sidecar_paths(path)):
            raise BackupError("backup retained SQLite sidecar files")
        independent = validate_personal_database(
            path,
            require_current=False,
            migrations=self.migrations,
        )
        if not independent.valid:
            raise BackupError("backup failed manager-owned independent validation")
        if independent.schema_version != source.schema_version:
            raise BackupError("backup schema version does not match the source")
        if (
            independent.instance_id is None
            or independent.instance_id != source.instance_id
        ):
            raise BackupError("backup instance identity does not match the source")
        return replace(backup, path=path, validation=independent)

    def create_backup(self, *, reason: str = "manual") -> BackupResult:
        with self._operation_lock:
            report = self._validate(require_current=True)
            if not report.valid:
                self.status = PersonalDatabaseStatus.INVALID
                self.last_error = "backup source database is invalid"
                raise BackupError(self.last_error)
            try:
                result = self.backup_service.create(
                    self._operational_database_path(), reason=reason
                )
                return self._validate_backup_result(
                    result, source=report, expected_reason=reason
                )
            except BackupError:
                raise
            except (OSError, sqlite3.Error, ValueError) as exc:
                raise BackupError(f"backup creation failed: {exc}") from exc

    def _validate_inside_migration(
        self, connection: sqlite3.Connection, *, expected_instance_id: str
    ) -> None:
        report = validate_personal_connection(
            connection,
            path=self._operational_database_path(),
            require_current=True,
            migrations=self.migrations,
        )
        if not report.valid:
            raise RuntimeError(
                "in-transaction personal database validation failed: "
                + "; ".join(report.errors)
            )
        if report.instance_id != expected_instance_id:
            raise RuntimeError("in-transaction instance identity changed")

    def migrate(self, *, hook: MigrationHook | None = None) -> MigrationResult:
        """Validate, verify a backup, migrate atomically, then validate again."""

        with self._operation_lock:
            self._set_blocked("personal database migration in progress")
            try:
                source = self._validate(require_current=False)
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.last_error = f"pre-migration source validation failed: {exc}"
                return MigrationResult(
                    MigrationStatus.MIGRATION_ABORTED, None, None, None, self.last_error
                )
            previous = source.schema_version
            if not source.valid or source.instance_id is None:
                self.status = PersonalDatabaseStatus.INVALID
                self.last_error = "pre-migration source validation failed"
                return MigrationResult(
                    MigrationStatus.MIGRATION_ABORTED,
                    previous,
                    previous,
                    None,
                    self.last_error,
                )
            try:
                source_path = self._operational_database_path()
                source_identity = get_path_identity(source_path)
                if (
                    self._database_identity is not None
                    and source_identity != self._database_identity
                ):
                    raise StorageIdentityError(
                        "personal database filesystem identity changed before migration"
                    )
                self._database_identity = source_identity
            except (OSError, ValueError, StorageIdentityError) as exc:
                self._set_blocked(f"pre-migration identity validation failed: {exc}")
                return MigrationResult(
                    MigrationStatus.MIGRATION_ABORTED,
                    previous,
                    previous,
                    None,
                    self.last_error,
                )
            if previous == self.current_schema_version:
                exact = self._validate(require_current=True)
                if exact.valid:
                    identity_valid = self._set_valid(exact)
                else:
                    identity_valid = False
                    self.status = PersonalDatabaseStatus.INVALID
                    self.last_error = "; ".join(exact.errors)
                return MigrationResult(
                    (
                        MigrationStatus.UP_TO_DATE
                        if identity_valid
                        else MigrationStatus.POST_VALIDATION_FAILED
                    ),
                    previous,
                    previous,
                    None,
                    self.last_error,
                )
            try:
                raw_backup = self.backup_service.create(
                    self._operational_database_path(),
                    reason="migration",
                    allow_older_schema=True,
                )
                backup = self._validate_backup_result(
                    raw_backup, source=source, expected_reason="migration"
                )
            except (BackupError, OSError, sqlite3.Error, ValueError) as exc:
                self._set_blocked(f"migration backup failed: {exc}")
                return MigrationResult(
                    MigrationStatus.MIGRATION_ABORTED,
                    previous,
                    previous,
                    None,
                    self.last_error,
                )

            try:
                database_path = self._operational_database_path()
                with _sqlite_write_connection(
                    database_path, expected_identity=source_identity
                ) as connection:
                    with sqlite_transaction(connection):
                        apply_pending_migrations(
                            connection, self.migrations, hook=hook
                        )
                        self._validate_inside_migration(
                            connection, expected_instance_id=source.instance_id
                        )
                        verify_opened_database_identity(
                            connection,
                            expected_path=database_path,
                            expected_identity=source_identity,
                        )
            except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                rolled_back = self._validate(require_current=False)
                self._set_blocked(
                    f"migration rolled back: {exc}; recovery: inspect the verified "
                    f"migration backup at {backup.path} before retrying"
                )
                return MigrationResult(
                    MigrationStatus.MIGRATION_FAILED,
                    previous,
                    rolled_back.schema_version,
                    backup,
                    self.last_error,
                )

            post = self._validate(require_current=True)
            if not post.valid or post.instance_id != source.instance_id:
                self.status = PersonalDatabaseStatus.INVALID
                self.last_error = "post-migration validation failed: " + "; ".join(
                    post.errors
                )
                return MigrationResult(
                    MigrationStatus.POST_VALIDATION_FAILED,
                    previous,
                    post.schema_version,
                    backup,
                    self.last_error,
                )
            if not self._set_valid(post):
                return MigrationResult(
                    MigrationStatus.POST_VALIDATION_FAILED,
                    previous,
                    post.schema_version,
                    backup,
                    self.last_error,
                )
            protect_file(self._operational_database_path())
            return MigrationResult(
                MigrationStatus.MIGRATED,
                previous,
                post.schema_version,
                backup,
            )

    @staticmethod
    def _online_copy(source: Path, destination: Path) -> None:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        destination_identity = get_path_identity(destination)
        with sqlite_readonly_connection(source) as source_connection:
            with _sqlite_write_connection(
                destination, expected_identity=destination_identity
            ) as destination_connection:
                source_connection.backup(destination_connection)

    def _assert_sidecars_absent(self, path: Path) -> None:
        present = [sidecar.name for sidecar in self._sidecar_paths(path) if sidecar.exists()]
        if present:
            raise RuntimeError("SQLite sidecars remain: " + ", ".join(present))

    def _quiesce_active_database(self, active: Path) -> None:
        """Checkpoint WAL and close the active DB in DELETE journal mode."""

        active_identity = self._database_identity
        if active_identity is None:
            active_identity = get_path_identity(active)
            self._database_identity = active_identity
        with _sqlite_write_connection(
            active, expected_identity=active_identity
        ) as connection:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if journal_mode == "wal":
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if int(checkpoint[0]) != 0 or int(checkpoint[1]) != 0 or int(checkpoint[2]) != 0:
                    raise RuntimeError("active WAL could not be fully checkpointed")
            resulting_mode = str(
                connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
            ).lower()
            if resulting_mode != "delete":
                raise RuntimeError("active database did not enter DELETE journal mode")
            verify_opened_database_identity(
                connection,
                expected_path=active,
                expected_identity=active_identity,
            )
        for sidecar in self._sidecar_paths(active):
            if not sidecar.exists():
                continue
            if sidecar.stat().st_size != 0:
                raise RuntimeError(f"non-empty SQLite sidecar remained: {sidecar.name}")
            sidecar.unlink()
        self._assert_sidecars_absent(active)

    def _validated_copy(
        self,
        source: Path,
        destination: Path,
        *,
        expected_instance_id: str,
    ) -> PersonalValidationReport:
        self._online_copy(source, destination)
        report = validate_personal_database(
            destination,
            require_current=True,
            migrations=self.migrations,
        )
        if not report.valid or report.instance_id != expected_instance_id:
            raise RuntimeError("SQLite copy failed validation or identity check")
        self._assert_sidecars_absent(destination)
        return report

    def restore(
        self,
        candidate_path: Path,
        *,
        create_emergency_backup: bool = True,
    ) -> RestoreResult:
        """Replace the active DB only after quiesce, copy, and identity checks."""

        with self._operation_lock:
            if self._write_in_progress:
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED,
                    None,
                    None,
                    "restore cannot start inside an active write transaction",
                )
            previous_instance_id = self._instance_id
            self._set_blocked("personal database restore in progress")
            emergency: BackupResult | None = None
            candidate_validation: PersonalValidationReport | None = None
            final: PersonalValidationReport | None = None
            temporary: Path | None = None
            rollback_copy: Path | None = None
            replaced = False
            cleanup_errors: list[str] = []

            try:
                active = self._operational_database_path()
                candidate = validate_personal_operational_path(
                    candidate_path,
                    repository_root=self.repository_root,
                    expected_suffix=".db",
                )
            except (OSError, ValueError) as exc:
                self._set_blocked(f"restore path validation failed: {exc}")
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED, None, None, self.last_error
                )

            same_file = candidate == active
            if not same_file and candidate.exists() and active.exists():
                try:
                    same_file = candidate.samefile(active)
                except OSError:
                    same_file = False
            if same_file:
                self._verify_active_and_set_status(previous_instance_id)
                return RestoreResult(
                    RestoreStatus.RESTORE_REJECTED,
                    None,
                    None,
                    "restore candidate cannot be the active database",
                )

            candidate_validation = validate_personal_database(
                candidate, require_current=True, migrations=self.migrations
            )
            if not candidate_validation.valid or candidate_validation.instance_id is None:
                self._verify_active_and_set_status(previous_instance_id)
                return RestoreResult(
                    RestoreStatus.RESTORE_REJECTED,
                    candidate_validation,
                    None,
                    "restore candidate validation failed",
                )
            candidate_instance_id = candidate_validation.instance_id

            active_validation: PersonalValidationReport | None = None
            if active.exists():
                active_validation = self._validate(require_current=True)
                if active_validation.valid and active_validation.instance_id is not None:
                    try:
                        active_identity = get_path_identity(active)
                        if (
                            self._database_identity is not None
                            and active_identity != self._database_identity
                        ):
                            raise StorageIdentityError(
                                "active database filesystem identity changed"
                            )
                        self._database_identity = active_identity
                    except (OSError, ValueError, StorageIdentityError) as exc:
                        self._set_blocked(f"active database identity check failed: {exc}")
                        return RestoreResult(
                            RestoreStatus.RESTORE_FAILED,
                            candidate_validation,
                            None,
                            self.last_error,
                        )
                    if previous_instance_id is None:
                        previous_instance_id = active_validation.instance_id
                        self._instance_id = previous_instance_id
                    if (
                        previous_instance_id is not None
                        and active_validation.instance_id != previous_instance_id
                    ):
                        self._set_blocked("active database instance identity changed")
                        return RestoreResult(
                            RestoreStatus.RESTORE_FAILED,
                            candidate_validation,
                            None,
                            self.last_error,
                        )
                    if not create_emergency_backup:
                        self._set_blocked("verified emergency backup is required")
                        return RestoreResult(
                            RestoreStatus.RESTORE_REJECTED,
                            candidate_validation,
                            None,
                            self.last_error,
                        )
                    try:
                        self._quiesce_active_database(active)
                        active_validation = self._validate(require_current=True)
                        if (
                            not active_validation.valid
                            or active_validation.instance_id != previous_instance_id
                        ):
                            raise RuntimeError("active database changed during quiesce")
                        raw_emergency = self.backup_service.create(
                            active, reason="pre-restore"
                        )
                        emergency = self._validate_backup_result(
                            raw_emergency,
                            source=active_validation,
                            expected_reason="pre-restore",
                        )
                    except (BackupError, OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
                        self._set_blocked(f"emergency backup failed: {exc}")
                        return RestoreResult(
                            RestoreStatus.RESTORE_FAILED,
                            candidate_validation,
                            emergency,
                            self.last_error,
                        )
                else:
                    try:
                        self._assert_sidecars_absent(active)
                    except RuntimeError as exc:
                        self._set_blocked(
                            f"invalid active database has unsafe sidecars: {exc}"
                        )
                        return RestoreResult(
                            RestoreStatus.RESTORE_FAILED,
                            candidate_validation,
                            None,
                            self.last_error,
                        )

            protect_directory(active.parent)
            temporary = active.parent / f".{active.name}.{uuid.uuid4().hex}.restore"
            primary_error: Exception | None = None
            rollback_error: Exception | None = None
            rollback_succeeded = False
            try:
                self._validated_copy(
                    candidate,
                    temporary,
                    expected_instance_id=candidate_instance_id,
                )
                self._assert_sidecars_absent(active)
                os.replace(temporary, active)
                replaced = True
                protect_file(active)
                self._assert_sidecars_absent(active)
                final = self._validate(require_current=True)
                if not final.valid or final.instance_id != candidate_instance_id:
                    raise RuntimeError(
                        "active database failed post-restore validation or identity check"
                    )
                self._assert_sidecars_absent(active)
            except Exception as exc:
                primary_error = exc
                self._set_blocked(f"restore failed: {exc}")
                if replaced and emergency is not None and emergency.path is not None:
                    rollback_copy = active.parent / (
                        f".{active.name}.{uuid.uuid4().hex}.rollback"
                    )
                    try:
                        self._assert_sidecars_absent(active)
                        self._validated_copy(
                            emergency.path,
                            rollback_copy,
                            expected_instance_id=previous_instance_id or "",
                        )
                        os.replace(rollback_copy, active)
                        protect_file(active)
                        self._assert_sidecars_absent(active)
                        rollback_validation = self._validate(require_current=True)
                        if (
                            not rollback_validation.valid
                            or rollback_validation.instance_id != previous_instance_id
                        ):
                            raise RuntimeError("rollback database failed reopen validation")
                        rollback_succeeded = True
                        final = rollback_validation
                    except Exception as exc_rollback:
                        rollback_error = exc_rollback
                        self._set_blocked(
                            f"restore failed: {primary_error}; rollback failed: {rollback_error}"
                        )
                elif not replaced:
                    final = self._verify_active_and_set_status(previous_instance_id)
            finally:
                if temporary is not None:
                    cleanup_errors.extend(self._cleanup_sqlite_artifacts(temporary))
                if rollback_copy is not None:
                    cleanup_errors.extend(self._cleanup_sqlite_artifacts(rollback_copy))

            if primary_error is not None:
                if rollback_succeeded and final is not None:
                    self._set_valid(final)
                elif self.status is PersonalDatabaseStatus.VALID and final is not None:
                    pass
                else:
                    self.status = PersonalDatabaseStatus.STARTUP_BLOCKED
                reason_parts = [f"restore failed: {primary_error}"]
                if rollback_error is not None:
                    reason_parts.append(f"rollback failed: {rollback_error}")
                if cleanup_errors:
                    reason_parts.append("cleanup failed: " + "; ".join(cleanup_errors))
                self.last_error = "; ".join(reason_parts)
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED,
                    candidate_validation,
                    emergency,
                    self.last_error,
                )

            if cleanup_errors:
                self._set_blocked("restore cleanup failed: " + "; ".join(cleanup_errors))
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED,
                    candidate_validation,
                    emergency,
                    self.last_error,
                )

            if final is None:
                self._set_blocked("restore completed without final validation")
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED,
                    candidate_validation,
                    emergency,
                    self.last_error,
                )
            if not self._set_valid(final):
                return RestoreResult(
                    RestoreStatus.RESTORE_FAILED,
                    final,
                    emergency,
                    self.last_error,
                )
            return RestoreResult(
                RestoreStatus.RESTORED,
                final,
                emergency,
            )
