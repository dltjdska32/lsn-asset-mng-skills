"""Validated SQLite Online Backup API operations and retention."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable

from investment_stack.personal.validation import (
    PersonalValidationReport,
    validate_personal_database,
)
from investment_stack.personal.paths import validate_personal_operational_path
from investment_stack.storage.identity import get_path_identity
from investment_stack.storage.permissions import protect_directory, protect_file
from investment_stack.storage.sqlite import (
    _sqlite_write_connection,
    sqlite_readonly_connection,
)


BACKUP_REASON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
BACKUP_FILENAME_PATTERN = re.compile(
    r"^personal-(?P<date>\d{8})-(?P<time>\d{6})-(?P<reason>[a-z0-9][a-z0-9-]{0,31})\.db$"
)


class BackupStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INVALID = "INVALID"
    FAILED = "FAILED"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupResult:
    status: BackupStatus
    path: Path | None
    reason: str
    created_at: datetime
    validation: PersonalValidationReport | None
    error: str | None = None


class PersonalBackupService:
    """Creates validated, non-overwriting personal database backups."""

    def __init__(
        self,
        backup_directory: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        general_retention: int = 30,
        migration_retention: int = 10,
        repository_root: Path | None = None,
    ) -> None:
        if general_retention < 1 or migration_retention < 1:
            raise ValueError("backup retention must keep at least one backup")
        self.backup_directory = Path(backup_directory).expanduser().resolve(strict=False)
        self.repository_root = (
            None
            if repository_root is None
            else Path(repository_root).expanduser().resolve(strict=False)
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.general_retention = general_retention
        self.migration_retention = migration_retention

    @staticmethod
    def _artifact_paths(path: Path) -> tuple[Path, ...]:
        return (
            path,
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
            Path(f"{path}-journal"),
        )

    @classmethod
    def _cleanup_artifacts(cls, path: Path) -> tuple[str, ...]:
        errors: list[str] = []
        for artifact in cls._artifact_paths(path):
            try:
                artifact.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"could not remove {artifact.name}: {exc}")
        return tuple(errors)

    def _validate_backup_directory(self) -> Path:
        return validate_personal_operational_path(
            self.backup_directory,
            repository_root=self.repository_root,
            expected_suffix=None,
            expected_resolved=self.backup_directory,
        )

    def _quarantine_invalid(self, path: Path) -> bool:
        quarantine_root = self.backup_directory / "invalid"
        try:
            protect_directory(quarantine_root)
            quarantine = quarantine_root / f"{path.name}.{uuid.uuid4().hex}"
            quarantine.mkdir(exist_ok=False)
            protect_directory(quarantine)
            for artifact in self._artifact_paths(path):
                if artifact.exists():
                    os.replace(artifact, quarantine / artifact.name)
            return True
        except OSError:
            return False

    @staticmethod
    def validate_reason(reason: str) -> str:
        if not isinstance(reason, str) or not BACKUP_REASON_PATTERN.fullmatch(reason):
            raise ValueError("backup reason must be lowercase alphanumeric with optional hyphens")
        return reason

    def create(
        self,
        source_path: Path,
        *,
        reason: str,
        allow_older_schema: bool = False,
    ) -> BackupResult:
        safe_reason = self.validate_reason(reason)
        self._validate_backup_directory()
        source = validate_personal_operational_path(
            source_path,
            repository_root=self.repository_root,
            expected_suffix=".db",
        )
        source_validation = validate_personal_database(
            source, require_current=not allow_older_schema
        )
        created_at = self.clock()
        if not source_validation.valid:
            raise BackupError("source database validation failed before backup")

        protect_directory(self.backup_directory)
        filename = f"personal-{created_at:%Y%m%d-%H%M%S}-{safe_reason}.db"
        destination = (self.backup_directory / filename).resolve(strict=False)
        try:
            destination.relative_to(self.backup_directory)
        except ValueError as exc:
            raise BackupError("backup destination escaped backup directory") from exc
        if destination == source:
            raise BackupError("backup destination cannot be the active database")

        temporary = self.backup_directory / f".{filename}.{uuid.uuid4().hex}.tmp"
        reserved = False
        published = False
        try:
            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            reserved = True
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            temporary_identity = get_path_identity(temporary)
            with sqlite_readonly_connection(source) as source_connection:
                with _sqlite_write_connection(
                    temporary, expected_identity=temporary_identity
                ) as destination_connection:
                    source_connection.backup(destination_connection)
            candidate_validation = validate_personal_database(
                temporary, require_current=not allow_older_schema
            )
            if not candidate_validation.valid:
                raise BackupError("created backup failed independent validation")
            if candidate_validation.instance_id != source_validation.instance_id:
                raise BackupError("created backup instance identity mismatch")
            if any(path.exists() for path in self._artifact_paths(temporary)[1:]):
                raise BackupError("created backup retained SQLite sidecar files")
            os.replace(temporary, destination)
            reserved = False
            published = True
            protect_file(destination)
            final_validation = validate_personal_database(
                destination, require_current=not allow_older_schema
            )
            if not final_validation.valid:
                raise BackupError("final backup failed validation")
            if final_validation.instance_id != source_validation.instance_id:
                raise BackupError("final backup instance identity mismatch")
            self.prune(active_database=source)
            return BackupResult(
                BackupStatus.SUCCESS,
                destination,
                safe_reason,
                created_at,
                final_validation,
            )
        except (OSError, sqlite3.Error, BackupError, ValueError) as exc:
            cleanup_errors = list(self._cleanup_artifacts(temporary))
            if reserved or published:
                cleanup_errors.extend(self._cleanup_artifacts(destination))
            cleanup_note = (
                "; cleanup failed: " + "; ".join(cleanup_errors)
                if cleanup_errors
                else ""
            )
            if isinstance(exc, BackupError):
                if cleanup_errors:
                    raise BackupError(f"{exc}{cleanup_note}") from exc
                raise
            raise BackupError(f"backup creation failed: {exc}{cleanup_note}") from exc

    def prune(self, *, active_database: Path) -> tuple[Path, ...]:
        """Prune only recognized backup files, always retaining newest verified slots."""

        active = Path(active_database).expanduser().resolve(strict=False)
        self._validate_backup_directory()
        if not self.backup_directory.exists():
            return ()
        removed: list[Path] = []
        verified: list[tuple[datetime, str, Path]] = []
        for path in self.backup_directory.glob("personal-????????-??????-*.db"):
            match = BACKUP_FILENAME_PATTERN.fullmatch(path.name)
            if match is None:
                continue
            try:
                same_as_active = path.resolve(strict=False) == active or (
                    path.exists() and active.exists() and path.samefile(active)
                )
            except OSError:
                same_as_active = False
            if same_as_active:
                continue
            try:
                created_at = datetime.strptime(
                    match.group("date") + match.group("time"), "%Y%m%d%H%M%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                if self._quarantine_invalid(path):
                    removed.append(path)
                continue
            report = validate_personal_database(path, require_current=False)
            if not report.valid:
                if self._quarantine_invalid(path):
                    removed.append(path)
                continue
            verified.append((created_at, match.group("reason"), path))

        verified.sort(key=lambda item: (item[0], item[2].name), reverse=True)
        migration = [item[2] for item in verified if item[1] == "migration"]
        general = [item[2] for item in verified if item[1] != "migration"]
        for group, limit in (
            (migration, self.migration_retention),
            (general, self.general_retention),
        ):
            for path in group[limit:]:
                self._cleanup_artifacts(path)
                removed.append(path)
        return tuple(removed)
