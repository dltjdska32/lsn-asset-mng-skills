from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.migrations.personal import PERSONAL_MIGRATIONS
from investment_stack.personal.backup import BackupError
from investment_stack.personal.manager import (
    MigrationStatus,
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    RestoreStatus,
    StorageNotWritableError,
)
from investment_stack.storage.migrations import Migration
from tests.storage_support import create_database_at_migrations, file_digest


class AlwaysFailBackup:
    def create(self, *args: object, **kwargs: object) -> object:
        raise BackupError("acceptance injected backup failure")


class Phase2AcceptanceTests(unittest.TestCase):
    def test_scenario_a_first_run_creates_valid_external_personal_db(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "os-data/personal/personal.db",
                backup_directory=root / "os-data/backups",
                repository_root=root / "repository",
            )
            result = manager.startup()
            self.assertEqual(result.status, PersonalDatabaseStatus.VALID)
            self.assertTrue(result.validation.valid)

    def test_scenario_b_old_schema_requires_verified_backup_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "os-data/personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")
            result = manager.migrate()
            self.assertEqual(result.status, MigrationStatus.MIGRATED)
            self.assertTrue(result.backup.validation.valid)
            self.assertEqual(result.backup.validation.schema_version, 1)

    def test_scenario_c_backup_failure_aborts_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(
                path,
                backup_directory=root / "backups",
                backup_service=AlwaysFailBackup(),
            )
            result = manager.migrate()
            self.assertEqual(result.status, MigrationStatus.MIGRATION_ABORTED)
            self.assertEqual(result.current_version, 1)

    def test_scenario_d_migration_failure_rolls_back_every_statement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "personal.db"
            create_database_at_migrations(path, PERSONAL_MIGRATIONS[:1])
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")

            def fail(migration: Migration, connection: sqlite3.Connection) -> None:
                if migration.version == 2:
                    raise RuntimeError("acceptance rollback")

            result = manager.migrate(hook=fail)
            self.assertEqual(result.status, MigrationStatus.MIGRATION_FAILED)
            self.assertEqual(result.current_version, 1)
            with self.assertRaises(StorageNotWritableError):
                manager.assert_writable()

    def test_scenario_e_bad_restore_candidate_never_changes_active_db(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "active/personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            before = file_digest(manager.database_path)
            bad = root / "candidate.db"
            bad.write_bytes(b"")
            result = manager.restore(bad)
            self.assertEqual(result.status, RestoreStatus.RESTORE_REJECTED)
            self.assertEqual(file_digest(manager.database_path), before)

    def test_scenario_f_invalid_personal_db_enters_recovery_and_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "personal.db"
            path.write_bytes(b"corrupt")
            manager = PersonalDatabaseManager(path, backup_directory=root / "backups")
            startup = manager.startup()
            self.assertEqual(startup.status, PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE)
            with self.assertRaises(StorageNotWritableError):
                manager.assert_writable()

    def test_scenario_g_run_corruption_is_isolated_from_personal_db(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            personal = PersonalDatabaseManager(
                root / "personal.db", backup_directory=root / "backups"
            )
            personal.initialize()
            run = RunDatabaseManager(root / "workspace", "isolated-run")
            run.database_path.parent.mkdir(parents=True)
            run.database_path.write_bytes(b"broken")
            self.assertFalse(run.open().valid)
            self.assertEqual(personal.status, PersonalDatabaseStatus.VALID)
            personal.assert_writable()
