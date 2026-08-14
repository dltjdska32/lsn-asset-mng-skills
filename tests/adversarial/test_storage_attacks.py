from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_stack.evidence.manager import RunDatabaseManager
from investment_stack.evidence.paths import UnsafeRunPath
from investment_stack.migrations.personal import PERSONAL_MIGRATIONS
from investment_stack.personal.backup import BackupError, PersonalBackupService
from investment_stack.personal.manager import (
    PersonalDatabaseManager,
    PersonalDatabaseStatus,
    StorageNotWritableError,
)
from investment_stack.personal.paths import UnsafeStoragePath, resolve_backup_directory
from investment_stack.personal.validation import validate_personal_database
from investment_stack.storage.migrations import Migration, validate_migration_catalog
from investment_stack.storage.sqlite import sqlite_transaction
from tests.storage_support import create_directory_link, sqlite_connection


class StorageAdversarialTests(unittest.TestCase):
    def test_backup_reason_path_traversal_is_rejected(self) -> None:
        service = PersonalBackupService(Path(tempfile.gettempdir()) / "unused-backups")
        for reason in ("../escape", "a/b", "a\\b", "..", "UPPER", ""):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                service.validate_reason(reason)

    def test_backup_directory_traversal_into_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary).resolve()
            with self.assertRaises(UnsafeStoragePath):
                resolve_backup_directory(
                    repository / "nested/../backups", repository_root=repository
                )

    def test_malicious_and_oversized_run_ids_are_rejected(self) -> None:
        workspace = Path(tempfile.gettempdir()) / "workspace"
        for run_id in ("../../pwn", "C:\\absolute", "/absolute", "a" * 129, "x..y"):
            with self.subTest(run_id=run_id), self.assertRaises(UnsafeRunPath):
                RunDatabaseManager(workspace, run_id)

    def test_empty_zero_byte_and_partial_personal_databases_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zero = root / "zero.db"
            zero.touch()
            self.assertFalse(validate_personal_database(zero).valid)
            partial = root / "partial.db"
            raw = sqlite3.connect(partial)
            raw.execute("CREATE TABLE accounts (account_id TEXT PRIMARY KEY)")
            raw.commit()
            raw.close()
            self.assertFalse(validate_personal_database(partial).valid)

    def test_migration_history_checksum_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            with sqlite_connection(manager.database_path) as connection:
                with sqlite_transaction(connection):
                    connection.execute(
                        "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
                        ("tampered",),
                    )
            report = validate_personal_database(manager.database_path)
            self.assertFalse(report.valid)
            self.assertTrue(any("checksum mismatch" in error for error in report.errors))

    def test_foreign_key_violation_is_detected_even_if_inserted_unsafely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            raw = sqlite3.connect(manager.database_path)
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute(
                "INSERT INTO transaction_entries (entry_id, transaction_id, created_at) "
                "VALUES (?, ?, ?)",
                ("bad-entry", "missing-transaction", "2026-08-14T00:00:00+00:00"),
            )
            raw.commit()
            raw.close()
            report = validate_personal_database(manager.database_path)
            self.assertFalse(report.valid)
            self.assertTrue(any("foreign_key_check" in error for error in report.errors))

    def test_schema_signature_detects_pk_fk_index_and_unique_tampering(self) -> None:
        cases = ("pk-fk", "index", "unique")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manager = PersonalDatabaseManager(
                    root / "personal.db", backup_directory=root / "backups"
                )
                manager.initialize()
                raw = sqlite3.connect(manager.database_path)
                raw.execute("PRAGMA foreign_keys = OFF")
                if case == "pk-fk":
                    raw.executescript(
                        """
                        ALTER TABLE transaction_entries RENAME TO old_transaction_entries;
                        CREATE TABLE transaction_entries (
                            entry_id TEXT,
                            transaction_id TEXT NOT NULL,
                            account_id TEXT,
                            instrument_id TEXT,
                            liability_id TEXT,
                            entry_type TEXT,
                            quantity_delta NUMERIC,
                            amount_delta NUMERIC,
                            currency TEXT,
                            created_at TEXT NOT NULL
                        );
                        INSERT INTO transaction_entries
                            (entry_id, transaction_id, account_id, instrument_id,
                             liability_id, entry_type, quantity_delta, amount_delta,
                             currency, created_at)
                        SELECT entry_id, transaction_id, account_id, instrument_id,
                               liability_id, entry_type, quantity_delta, amount_delta,
                               currency, created_at
                        FROM old_transaction_entries;
                        DROP TABLE old_transaction_entries;
                        """
                    )
                elif case == "index":
                    raw.execute("DROP INDEX idx_transactions_state_version")
                else:
                    raw.executescript(
                        """
                        ALTER TABLE instrument_aliases RENAME TO old_instrument_aliases;
                        CREATE TABLE instrument_aliases (
                            alias_id TEXT PRIMARY KEY,
                            instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
                            alias TEXT NOT NULL,
                            provider TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL
                        );
                        INSERT INTO instrument_aliases SELECT * FROM old_instrument_aliases;
                        DROP TABLE old_instrument_aliases;
                        """
                    )
                raw.commit()
                raw.close()
                report = validate_personal_database(manager.database_path)
                self.assertFalse(report.valid)
                self.assertTrue(
                    any("signature mismatch" in error for error in report.errors),
                    report.errors,
                )

    def test_guarded_write_rejects_post_startup_corruption_and_replacement(self) -> None:
        cases = ("truncate", "replacement", "schema", "instance", "fk-structure")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manager = PersonalDatabaseManager(
                    root / "personal.db", backup_directory=root / "backups"
                )
                manager.initialize()
                if case == "truncate":
                    manager.database_path.write_bytes(b"truncated")
                elif case == "replacement":
                    replacement = PersonalDatabaseManager(
                        root / "replacement.db",
                        backup_directory=root / "replacement-backups",
                    )
                    replacement.initialize()
                    os.replace(replacement.database_path, manager.database_path)
                elif case == "schema":
                    raw = sqlite3.connect(manager.database_path)
                    raw.execute("DROP INDEX idx_transactions_state_version")
                    raw.commit()
                    raw.close()
                elif case == "instance":
                    with sqlite_connection(manager.database_path) as connection:
                        with sqlite_transaction(connection):
                            connection.execute(
                                "UPDATE storage_metadata SET metadata_value = ? "
                                "WHERE metadata_key = 'personal_db_instance_id'",
                                ("0123456789abcdef0123456789abcdef",),
                            )
                else:
                    raw = sqlite3.connect(manager.database_path)
                    raw.execute("PRAGMA foreign_keys = OFF")
                    raw.executescript(
                        """
                        ALTER TABLE transaction_entries RENAME TO old_transaction_entries;
                        CREATE TABLE transaction_entries (
                            entry_id TEXT PRIMARY KEY,
                            transaction_id TEXT NOT NULL,
                            account_id TEXT,
                            instrument_id TEXT,
                            liability_id TEXT,
                            entry_type TEXT,
                            quantity_delta NUMERIC,
                            amount_delta NUMERIC,
                            currency TEXT,
                            created_at TEXT NOT NULL
                        );
                        INSERT INTO transaction_entries
                            (entry_id, transaction_id, account_id, instrument_id,
                             liability_id, entry_type, quantity_delta, amount_delta,
                             currency, created_at)
                        SELECT entry_id, transaction_id, account_id, instrument_id,
                               liability_id, entry_type, quantity_delta, amount_delta,
                               currency, created_at
                        FROM old_transaction_entries;
                        DROP TABLE old_transaction_entries;
                        """
                    )
                    raw.commit()
                    raw.close()
                with self.assertRaises(StorageNotWritableError):
                    manager.assert_writable()
                self.assertNotEqual(manager.status, PersonalDatabaseStatus.VALID)

    def test_guarded_write_transaction_allows_a_valid_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "personal.db", backup_directory=root / "backups"
            )
            manager.initialize()
            with manager.guarded_write_transaction() as connection:
                connection.execute(
                    "INSERT INTO storage_metadata VALUES (?, ?, ?)",
                    ("guard-test", "ok", "2026-08-14T00:00:00+00:00"),
                )
            self.assertEqual(manager.status, PersonalDatabaseStatus.VALID)

    def test_personal_parent_junction_swap_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repository = root / "repository"
            captured = repository / "captured"
            repository.mkdir()
            (repository / ".git").mkdir()
            captured.mkdir()
            personal_parent = root / "outside/data"
            personal_parent.mkdir(parents=True)
            manager = PersonalDatabaseManager(
                personal_parent / "personal.db",
                backup_directory=root / "outside/backups",
                repository_root=repository,
            )
            personal_parent.rename(root / "outside/data-original")
            if not create_directory_link(personal_parent, captured):
                self.skipTest("directory links are unavailable")
            result = manager.initialize()
            self.assertEqual(result.status, PersonalDatabaseStatus.STARTUP_BLOCKED)
            self.assertFalse((captured / "personal.db").exists())

    def test_personal_validation_open_race_cannot_write_escaped_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            data = root / "data"
            escaped = root / "escaped"
            manager = PersonalDatabaseManager(
                data / "personal.db", backup_directory=root / "backups"
            )
            self.assertEqual(manager.initialize().status, PersonalDatabaseStatus.VALID)
            escaped.mkdir()
            shutil.copy2(manager.database_path, escaped / "personal.db")
            original = root / "data-original"
            real_writer = __import__(
                "investment_stack.personal.manager", fromlist=["_sqlite_write_connection"]
            )._sqlite_write_connection
            swapped = False

            def swap_then_open(path: Path, **kwargs: object) -> object:
                nonlocal swapped
                if not swapped:
                    data.rename(original)
                    if not create_directory_link(data, escaped):
                        self.skipTest("directory links are unavailable")
                    swapped = True
                return real_writer(path, **kwargs)

            with patch(
                "investment_stack.personal.manager._sqlite_write_connection",
                swap_then_open,
            ), self.assertRaises(StorageNotWritableError):
                with manager.guarded_write_transaction() as connection:
                    connection.execute(
                        "INSERT INTO storage_metadata VALUES (?, ?, ?)",
                        ("escaped-write", "bad", "2026-08-14T00:00:00+00:00"),
                    )

            def escaped_write_count(path: Path) -> int:
                raw = sqlite3.connect(path)
                try:
                    return int(
                        raw.execute(
                            "SELECT COUNT(*) FROM storage_metadata WHERE metadata_key = ?",
                            ("escaped-write",),
                        ).fetchone()[0]
                    )
                finally:
                    raw.close()

            self.assertEqual(escaped_write_count(original / "personal.db"), 0)
            self.assertEqual(escaped_write_count(escaped / "personal.db"), 0)
            self.assertEqual(manager.status, PersonalDatabaseStatus.STARTUP_BLOCKED)
            with self.assertRaises(StorageNotWritableError):
                manager.assert_writable()

    def test_backup_directory_junction_swap_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repository = root / "repository"
            captured = repository / "captured"
            repository.mkdir()
            (repository / ".git").mkdir()
            captured.mkdir()
            backup_directory = root / "outside/backups"
            backup_directory.mkdir(parents=True)
            manager = PersonalDatabaseManager(
                root / "outside/personal.db",
                backup_directory=backup_directory,
                repository_root=repository,
            )
            manager.initialize()
            backup_directory.rename(root / "outside/backups-original")
            if not create_directory_link(backup_directory, captured):
                self.skipTest("directory links are unavailable")
            with self.assertRaises(BackupError):
                manager.create_backup(reason="manual")
            self.assertEqual(list(captured.iterdir()), [])

    def test_run_root_junction_escape_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside"
            if not create_directory_link(workspace / "runs", outside):
                self.skipTest("directory links are unavailable")
            with self.assertRaises(UnsafeRunPath):
                RunDatabaseManager(workspace, "safe-run")
            self.assertFalse((outside / "safe-run/run.db").exists())

    def test_readonly_probe_forces_recovery_mode_and_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "personal.db",
                backup_directory=root / "backups",
                writability_probe=lambda path: False,
            )
            startup = manager.initialize()
            self.assertEqual(startup.status, PersonalDatabaseStatus.READ_ONLY_RECOVERY_MODE)
            with self.assertRaises(StorageNotWritableError):
                manager.assert_writable()

    def test_duplicate_migration_version_and_id_are_detected(self) -> None:
        duplicate_version = Migration(
            version=1, migration_id="different", statements=("SELECT 1",)
        )
        with self.assertRaisesRegex(ValueError, "duplicate migration version"):
            validate_migration_catalog((PERSONAL_MIGRATIONS[0], duplicate_version))
        duplicate_id = Migration(
            version=2,
            migration_id=PERSONAL_MIGRATIONS[0].migration_id,
            statements=("SELECT 1",),
        )
        with self.assertRaisesRegex(ValueError, "duplicate migration id"):
            validate_migration_catalog((PERSONAL_MIGRATIONS[0], duplicate_id))

    def test_run_partial_database_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "partial-run")
            manager.database_path.parent.mkdir(parents=True)
            raw = sqlite3.connect(manager.database_path)
            raw.execute("CREATE TABLE run_metadata (run_id TEXT)")
            raw.commit()
            raw.close()
            self.assertFalse(manager.open().valid)

    def test_repository_has_no_database_artifacts_and_ignores_them(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        database_files = [
            path
            for path in repository.rglob("*")
            if path.is_file()
            and (
                path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
                or path.name.endswith((".db-wal", ".db-shm", ".db-journal"))
            )
        ]
        self.assertEqual(database_files, [])
        ignore = (repository / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            "*.db",
            "*.db-shm",
            "*.db-wal",
            "*.db-journal",
            ".*.restore",
            ".*.rollback",
            "*.backup.tmp",
            "*.db.tmp",
            "workspace/runs/",
        ):
            self.assertIn(pattern, ignore)
