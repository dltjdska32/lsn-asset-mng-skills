from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from investment_stack.migrations.personal import (
    CURRENT_PERSONAL_SCHEMA_VERSION,
    PERSONAL_MIGRATIONS,
)
from investment_stack.personal.backup import (
    BackupError,
    BackupResult,
    BackupStatus,
    PersonalBackupService,
)
from investment_stack.personal.manager import (
    MigrationStatus,
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    RestoreStatus,
    StorageNotWritableError,
)
from investment_stack.personal.validation import validate_personal_database
from investment_stack.storage.migrations import Migration
from investment_stack.storage.sqlite import sqlite_readonly_connection, sqlite_transaction
from tests.storage_support import (
    create_database_at_migrations,
    file_digest,
    sqlite_connection,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 14, 1, 2, 3, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class FailingBackupService:
    def create(self, *args: object, **kwargs: object) -> object:
        raise BackupError("simulated disk write failure")


class InvalidBackupService:
    def create(self, *args: object, **kwargs: object) -> object:
        raise BackupError("simulated independent backup validation failure")


class StaticBackupService:
    def __init__(self, result: BackupResult) -> None:
        self.result = result

    def create(self, *args: object, **kwargs: object) -> BackupResult:
        return self.result


class PersonalBackupTests(unittest.TestCase):
    def test_online_backup_is_independently_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            result = manager.create_backup(reason="manual")
            self.assertEqual(result.status.value, "SUCCESS")
            self.assertTrue(result.path.is_file())
            self.assertTrue(result.validation.valid)
            self.assertRegex(result.path.name, r"^personal-\d{8}-\d{6}-manual\.db$")

    def test_backup_collision_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = datetime(2026, 8, 14, 1, 2, 3, tzinfo=timezone.utc)
            service = PersonalBackupService(root / "backups", clock=lambda: fixed)
            manager = PersonalDatabaseManager(
                root / "data/personal.db",
                backup_directory=root / "backups",
                backup_service=service,
            )
            manager.initialize()
            first = manager.create_backup(reason="manual")
            digest = file_digest(first.path)
            with self.assertRaises(BackupError):
                manager.create_backup(reason="manual")
            self.assertEqual(file_digest(first.path), digest)

    def test_retention_separates_general_and_migration_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = PersonalBackupService(
                root / "backups",
                clock=MutableClock(),
                general_retention=30,
                migration_retention=10,
            )
            manager = PersonalDatabaseManager(
                root / "data/personal.db",
                backup_directory=root / "backups",
                backup_service=service,
            )
            manager.initialize()
            for _ in range(31):
                service.create(manager.database_path, reason="manual")
            for _ in range(11):
                service.create(manager.database_path, reason="migration")
            names = [path.name for path in (root / "backups").glob("*.db")]
            self.assertEqual(sum(name.endswith("-manual.db") for name in names), 30)
            self.assertEqual(sum(name.endswith("-migration.db") for name in names), 10)

    def test_invalid_source_is_not_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "personal.db"
            source.write_bytes(b"not sqlite")
            service = PersonalBackupService(root / "backups")
            with self.assertRaises(BackupError):
                service.create(source, reason="manual")
            self.assertEqual(list((root / "backups").glob("*.db")), [])

    def test_sqlite_backup_error_is_normalized_and_cleans_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            real_connection = sqlite_readonly_connection

            @contextmanager
            def failing_connection(
                path: Path, **kwargs: object
            ) -> object:
                with real_connection(path, **kwargs) as connection:
                    class FailingSource:
                        def backup(self, destination: sqlite3.Connection) -> None:
                            raise sqlite3.OperationalError("injected backup I/O failure")

                    yield FailingSource()

            with patch(
                "investment_stack.personal.backup.sqlite_readonly_connection",
                failing_connection,
            ), self.assertRaises(BackupError) as raised:
                manager.create_backup(reason="manual")
            self.assertNotIsInstance(raised.exception.__cause__, BackupError)
            backup_root = root / "backups"
            self.assertEqual(
                [path for path in backup_root.iterdir() if path.is_file()], []
            )

    def test_backup_cleanup_permission_error_is_reported_and_not_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            real_readonly = sqlite_readonly_connection
            real_unlink = Path.unlink

            @contextmanager
            def failing_source(path: Path, **kwargs: object) -> object:
                with real_readonly(path, **kwargs):
                    class FailingSource:
                        def backup(self, destination: sqlite3.Connection) -> None:
                            raise sqlite3.OperationalError("injected backup failure")

                    yield FailingSource()

            def fail_temporary_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path.name.endswith(".tmp"):
                    raise PermissionError("injected cleanup permission failure")
                real_unlink(path, *args, **kwargs)

            with patch(
                "investment_stack.personal.backup.sqlite_readonly_connection",
                failing_source,
            ), patch.object(Path, "unlink", fail_temporary_unlink), self.assertRaises(
                BackupError
            ) as raised:
                manager.create_backup(reason="manual")

            self.assertIn("cleanup failed", str(raised.exception))
            leftovers = [path for path in (root / "backups").iterdir() if path.is_file()]
            self.assertTrue(any(path.name.endswith(".tmp") for path in leftovers))
            manager.backup_service.prune(active_database=manager.database_path)
            self.assertFalse(any(path.name.startswith("personal-") for path in leftovers))

    def test_backup_destination_permission_failure_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            with patch(
                "investment_stack.personal.backup.os.open",
                side_effect=PermissionError("injected destination permission failure"),
            ), self.assertRaises(BackupError):
                manager.create_backup(reason="manual")
            self.assertEqual(
                [path for path in (root / "backups").iterdir() if path.is_file()],
                [],
            )

    def test_independent_backup_validation_failure_cleans_temp_and_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()

            def fail_temporary_validation(
                path: Path, *, require_current: bool = True
            ) -> object:
                report = validate_personal_database(
                    path, require_current=require_current
                )
                if Path(path).name.startswith(".personal-"):
                    return replace(
                        report,
                        valid=False,
                        errors=("injected independent validation failure",),
                    )
                return report

            with patch(
                "investment_stack.personal.backup.validate_personal_database",
                side_effect=fail_temporary_validation,
            ), self.assertRaises(BackupError):
                manager.create_backup(reason="manual")
            self.assertEqual(
                [path for path in (root / "backups").iterdir() if path.is_file()],
                [],
            )

    def test_invalid_backups_do_not_consume_retention_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = PersonalBackupService(
                root / "backups", general_retention=1, migration_retention=1
            )
            manager = PersonalDatabaseManager(
                root / "data/personal.db",
                backup_directory=root / "backups",
                backup_service=service,
            )
            manager.initialize()
            valid = service.create(manager.database_path, reason="manual").path
            invalid_names = (
                "personal-20990101-000001-manual.db",
                "personal-20990101-000002-manual.db",
            )
            for name in invalid_names:
                (root / "backups" / name).write_bytes(b"not sqlite")

            service.prune(active_database=manager.database_path)

            self.assertTrue(valid.is_file())
            self.assertTrue(validate_personal_database(valid).valid)
            remaining = list((root / "backups").glob("personal-*.db"))
            self.assertEqual(remaining, [valid])
            quarantined = list((root / "backups/invalid").rglob("personal-*.db"))
            self.assertEqual(len(quarantined), len(invalid_names))


class PersonalMigrationTests(unittest.TestCase):
    def _assert_returned_backup_blocks_migration(
        self, root: Path, path: Path, backup_result: BackupResult
    ) -> None:
        manager = PersonalDatabaseManager(
            path,
            backup_directory=root / "manager-backups",
            backup_service=StaticBackupService(backup_result),
        )
        called = False

        def hook(migration: Migration, connection: sqlite3.Connection) -> None:
            nonlocal called
            called = True

        result = manager.migrate(hook=hook)
        self.assertEqual(result.status, MigrationStatus.MIGRATION_ABORTED)
        self.assertFalse(called)
        with sqlite_connection(path, readonly=True) as connection:
            self.assertEqual(
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                1,
            )

    def test_existing_old_schema_is_backed_up_then_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")
            startup = manager.startup()
            self.assertEqual(startup.status, PersonalDatabaseStatus.VALID)
            self.assertEqual(
                startup.validation.schema_version, CURRENT_PERSONAL_SCHEMA_VERSION
            )
            migration_backups = list((root / "backups").glob("*-migration.db"))
            self.assertEqual(len(migration_backups), 1)
            self.assertTrue(
                validate_personal_database(
                    migration_backups[0], require_current=False
                ).valid
            )

    def test_second_migration_run_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            result = manager.migrate()
            self.assertEqual(result.status, MigrationStatus.UP_TO_DATE)
            self.assertIsNone(result.backup)
            with sqlite_connection(manager.database_path, readonly=True) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    len(PERSONAL_MIGRATIONS),
                )

    def test_migration_exception_rolls_back_and_retains_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")

            def fail_on_second(migration: Migration, connection: sqlite3.Connection) -> None:
                if migration.version == 2:
                    raise RuntimeError("injected migration failure")

            result = manager.migrate(hook=fail_on_second)
            self.assertEqual(result.status, MigrationStatus.MIGRATION_FAILED)
            self.assertEqual(result.previous_version, 1)
            self.assertEqual(result.current_version, 1)
            self.assertEqual(manager.status, PersonalDatabaseStatus.STARTUP_BLOCKED)
            with sqlite_connection(path, readonly=True) as connection:
                self.assertEqual(
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    1,
                )
                indexes = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                    "AND name='idx_transactions_state_version'"
                ).fetchone()[0]
                self.assertEqual(indexes, 0)

    def test_backup_failure_aborts_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(
                path,
                backup_directory=root / "backups",
                backup_service=FailingBackupService(),
            )
            called = False

            def hook(migration: Migration, connection: sqlite3.Connection) -> None:
                nonlocal called
                called = True

            result = manager.migrate(hook=hook)
            self.assertEqual(result.status, MigrationStatus.MIGRATION_ABORTED)
            self.assertFalse(called)
            self.assertEqual(result.current_version, 1)

    def test_backup_validation_failure_aborts_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(
                path,
                backup_directory=root / "backups",
                backup_service=InvalidBackupService(),
            )
            called = False

            def hook(migration: Migration, connection: sqlite3.Connection) -> None:
                nonlocal called
                called = True

            result = manager.migrate(hook=hook)
            self.assertEqual(result.status, MigrationStatus.MIGRATION_ABORTED)
            self.assertFalse(called)
            self.assertIn("validation", result.reason)

    def test_invalid_returned_backup_results_abort_before_executor(self) -> None:
        cases = (
            "invalid-status",
            "invalid-validation",
            "zero-byte",
            "missing",
            "wrong-schema",
            "wrong-instance",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "data/personal.db"
                create_database_at_migrations(source, PERSONAL_MIGRATIONS[:1])
                source_report = validate_personal_database(
                    source, require_current=False
                )
                real_service = PersonalBackupService(root / "real-backups")
                valid_result = real_service.create(
                    source, reason="migration", allow_older_schema=True
                )
                if case == "invalid-status":
                    returned = replace(valid_result, status=BackupStatus.INVALID)
                elif case == "invalid-validation":
                    returned = replace(
                        valid_result,
                        validation=replace(
                            valid_result.validation,
                            valid=False,
                            errors=("injected validation failure",),
                        ),
                    )
                elif case == "zero-byte":
                    candidate = root / "zero.db"
                    candidate.touch()
                    returned = replace(
                        valid_result, path=candidate, validation=source_report
                    )
                elif case == "missing":
                    returned = replace(
                        valid_result,
                        path=root / "missing.db",
                        validation=source_report,
                    )
                elif case == "wrong-schema":
                    candidate = root / "wrong-schema.db"
                    create_database_at_migrations(candidate, PERSONAL_MIGRATIONS)
                    returned = BackupResult(
                        BackupStatus.SUCCESS,
                        candidate,
                        "migration",
                        valid_result.created_at,
                        validate_personal_database(candidate),
                    )
                else:
                    candidate = root / "wrong-instance.db"
                    create_database_at_migrations(
                        candidate, PERSONAL_MIGRATIONS[:1]
                    )
                    returned = BackupResult(
                        BackupStatus.SUCCESS,
                        candidate,
                        "migration",
                        valid_result.created_at,
                        validate_personal_database(
                            candidate, require_current=False
                        ),
                    )
                self._assert_returned_backup_blocks_migration(
                    root, source, returned
                )

    def test_post_migration_validation_failure_marks_database_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")
            source = manager._validate(require_current=False)
            invalid_post = replace(
                source,
                valid=False,
                schema_version=2,
                errors=("injected post-migration validation failure",),
            )
            with patch.object(manager, "_validate", side_effect=(source, invalid_post)):
                result = manager.migrate()
            self.assertEqual(result.status, MigrationStatus.POST_VALIDATION_FAILED)
            self.assertEqual(manager.status, PersonalDatabaseStatus.INVALID)

    def test_duplicate_migration_identifier_is_rejected(self) -> None:
        duplicate = Migration(
            version=2,
            migration_id=PERSONAL_MIGRATIONS[0].migration_id,
            statements=("SELECT 1",),
        )
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            ValueError, "duplicate migration id"
        ):
            PersonalDatabaseManager(
                Path(temporary) / "personal.db",
                backup_directory=Path(temporary) / "backups",
                migrations=(PERSONAL_MIGRATIONS[0], duplicate),
            )


class PersonalRestoreTests(unittest.TestCase):
    @staticmethod
    def _set_marker(manager: PersonalDatabaseManager, value: str) -> None:
        with sqlite_connection(manager.database_path) as connection:
            with sqlite_transaction(connection):
                connection.execute(
                    "INSERT OR REPLACE INTO storage_metadata VALUES (?, ?, ?)",
                    ("marker", value, "2026-08-14T00:00:00+00:00"),
                )

    @staticmethod
    def _read_marker(manager: PersonalDatabaseManager) -> str | None:
        with sqlite_connection(manager.database_path, readonly=True) as connection:
            row = connection.execute(
                "SELECT metadata_value FROM storage_metadata WHERE metadata_key = ?",
                ("marker",),
            ).fetchone()
        return None if row is None else str(row[0])

    def _post_replace_failure(self, manager: PersonalDatabaseManager) -> object:
        original_validate = manager._validate
        failed = False

        def injected(*, require_current: bool) -> object:
            nonlocal failed
            report = original_validate(require_current=require_current)
            if not failed and self._read_marker(manager) == "candidate":
                failed = True
                return replace(
                    report,
                    valid=False,
                    errors=("injected reopened validation failure",),
                )
            return report

        return injected

    def test_valid_candidate_replaces_active_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db", backup_directory=root / "candidate-backups"
            )
            active.initialize()
            candidate.initialize()
            with sqlite_connection(candidate.database_path) as connection:
                with sqlite_transaction(connection):
                    connection.execute(
                        "INSERT INTO storage_metadata VALUES (?, ?, ?)",
                        ("marker", "candidate", "2026-08-14T00:00:00+00:00"),
                    )
            result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORED)
            self.assertTrue(result.validation.valid)
            self.assertIsNotNone(result.emergency_backup)
            with sqlite_connection(active.database_path, readonly=True) as connection:
                marker = connection.execute(
                    "SELECT metadata_value FROM storage_metadata WHERE metadata_key = ?",
                    ("marker",),
                ).fetchone()[0]
            self.assertEqual(marker, "candidate")

    def test_restore_quiesces_crash_wal_and_uses_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(candidate, "candidate-new")
            script = (
                "import os, sqlite3, sys\n"
                "connection = sqlite3.connect(sys.argv[1])\n"
                "connection.execute('PRAGMA journal_mode=WAL')\n"
                "connection.execute('PRAGMA wal_autocheckpoint=0')\n"
                "connection.execute(\"INSERT OR REPLACE INTO storage_metadata VALUES "
                "('marker','active-old-wal','2026-08-14T00:00:00+00:00')\")\n"
                "connection.commit()\n"
                "os._exit(0)\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script, str(active.database_path)],
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertTrue(Path(f"{active.database_path}-wal").exists())

            result = active.restore(candidate.database_path)

            self.assertEqual(result.status, RestoreStatus.RESTORED)
            self.assertEqual(self._read_marker(active), "candidate-new")
            self.assertEqual(active.instance_id, candidate.instance_id)
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(f"{active.database_path}{suffix}").exists())

    def test_post_replace_failure_rolls_back_and_revalidates_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            with patch.object(
                active, "_validate", side_effect=self._post_replace_failure(active)
            ):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.VALID)
            self.assertEqual(self._read_marker(active), "original")
            active.assert_writable()

    def test_rollback_replace_failure_never_leaves_stale_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            real_replace = os.replace

            def fail_rollback(source: Path, destination: Path) -> None:
                if Path(source).name.endswith(".rollback"):
                    raise PermissionError("injected rollback replace lock")
                real_replace(source, destination)

            with patch.object(
                active, "_validate", side_effect=self._post_replace_failure(active)
            ), patch("investment_stack.personal.manager.os.replace", fail_rollback):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.STARTUP_BLOCKED)
            with self.assertRaises(StorageNotWritableError):
                active.assert_writable()

    def test_rollback_copy_failure_never_leaves_stale_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            real_copy = active._online_copy

            def fail_rollback_copy(source: Path, destination: Path) -> None:
                if destination.name.endswith(".rollback"):
                    raise sqlite3.OperationalError("injected rollback copy failure")
                real_copy(source, destination)

            with patch.object(
                active, "_validate", side_effect=self._post_replace_failure(active)
            ), patch.object(active, "_online_copy", side_effect=fail_rollback_copy):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.STARTUP_BLOCKED)

    def test_rollback_reopen_validation_failure_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            original_validate = active._validate
            replacement_failed = False

            def fail_replacement_and_rollback(*, require_current: bool) -> object:
                nonlocal replacement_failed
                report = original_validate(require_current=require_current)
                marker = self._read_marker(active)
                if marker == "candidate":
                    replacement_failed = True
                    return replace(
                        report,
                        valid=False,
                        errors=("injected replacement validation failure",),
                    )
                if replacement_failed and marker == "original":
                    return replace(
                        report,
                        valid=False,
                        errors=("injected rollback reopen failure",),
                    )
                return report

            with patch.object(
                active, "_validate", side_effect=fail_replacement_and_rollback
            ):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.STARTUP_BLOCKED)
            with self.assertRaises(StorageNotWritableError):
                active.assert_writable()

    def test_rollback_copy_validation_failure_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            real_validated_copy = active._validated_copy

            def fail_rollback_validation(
                source: Path,
                destination: Path,
                *,
                expected_instance_id: str,
            ) -> object:
                report = real_validated_copy(
                    source,
                    destination,
                    expected_instance_id=expected_instance_id,
                )
                if destination.name.endswith(".rollback"):
                    raise RuntimeError("injected rollback copy validation failure")
                return report

            with patch.object(
                active, "_validate", side_effect=self._post_replace_failure(active)
            ), patch.object(
                active, "_validated_copy", side_effect=fail_rollback_validation
            ):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.STARTUP_BLOCKED)

    def test_first_replace_failure_revalidates_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            self._set_marker(active, "original")
            self._set_marker(candidate, "candidate")
            before = file_digest(active.database_path)
            real_replace = os.replace

            def fail_first_replace(source: Path, destination: Path) -> None:
                if Path(source).name.endswith(".restore"):
                    raise PermissionError("injected first replace failure")
                real_replace(source, destination)

            with patch("investment_stack.personal.manager.os.replace", fail_first_replace):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.VALID)
            self.assertEqual(file_digest(active.database_path), before)

    def test_restore_cleanup_failure_blocks_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            with patch.object(
                active,
                "_cleanup_sqlite_artifacts",
                return_value=("injected cleanup failure",),
            ):
                result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.STARTUP_BLOCKED)

    def test_manager_owned_writer_blocks_reentrant_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            with active.guarded_write_transaction():
                result = active.restore(candidate.database_path)
                self.assertEqual(result.status, RestoreStatus.RESTORE_FAILED)
            self.assertEqual(active.status, PersonalDatabaseStatus.VALID)

    @unittest.skipUnless(sys.platform == "win32", "Windows file sharing semantics")
    def test_open_sqlite_handle_blocks_restore_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            before = file_digest(active.database_path)
            held = sqlite3.connect(active.database_path)
            try:
                result = active.restore(candidate.database_path)
            finally:
                held.close()
            self.assertNotEqual(result.status, RestoreStatus.RESTORED)
            self.assertEqual(file_digest(active.database_path), before)

    def test_corrupt_candidate_leaves_active_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            active.initialize()
            before = file_digest(active.database_path)
            candidate = root / "corrupt.db"
            candidate.write_bytes(b"not-a-database")
            result = active.restore(candidate)
            self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)
            self.assertEqual(file_digest(active.database_path), before)

    def test_same_path_restore_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            active.initialize()
            result = active.restore(active.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)

    def test_old_schema_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            active.initialize()
            old_candidate = root / "old/personal.db"
            create_database_at_migrations(old_candidate, PERSONAL_MIGRATIONS[:1])
            before = file_digest(active.database_path)
            result = active.restore(old_candidate)
            self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)
            self.assertEqual(file_digest(active.database_path), before)

    def test_foreign_key_corrupt_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            candidate = PersonalDatabaseManager(
                root / "candidate/personal.db",
                backup_directory=root / "candidate-backups",
            )
            active.initialize()
            candidate.initialize()
            raw = sqlite3.connect(candidate.database_path)
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute(
                "INSERT INTO transaction_entries (entry_id, transaction_id, created_at) "
                "VALUES (?, ?, ?)",
                ("bad-entry", "missing-transaction", "2026-08-14T00:00:00+00:00"),
            )
            raw.commit()
            raw.close()
            before = file_digest(active.database_path)
            result = active.restore(candidate.database_path)
            self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)
            self.assertEqual(file_digest(active.database_path), before)
