from __future__ import annotations

import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_stack.evidence.manager import RunDatabaseManager, RunDatabaseStatus
from investment_stack.evidence.paths import UnsafeRunPath
from investment_stack.personal.manager import PersonalDatabaseManager, PersonalDatabaseStatus
from tests.storage_support import create_directory_link, sqlite_connection


class RunStorageTests(unittest.TestCase):
    def test_run_workspaces_are_isolated_and_collisions_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            first = RunDatabaseManager(workspace, "run-001")
            second = RunDatabaseManager(workspace, "run-002")
            self.assertTrue(first.create().valid)
            self.assertTrue(second.create().valid)
            self.assertNotEqual(first.database_path, second.database_path)
            with self.assertRaises(FileExistsError):
                RunDatabaseManager(workspace, "run-001").create()

    def test_basic_metadata_and_evidence_crud_is_parameterized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "crud-run")
            manager.create()
            manager.update_metadata(
                run_status="READY",
                request_mode="DEEP_RESEARCH",
                metadata={"safe": True},
            )
            manager.add_evidence(
                evidence_id="evidence-1'); DROP TABLE evidence; --",
                evidence_type="USER_SUPPLIED",
                source_uri="local://fixture",
            )
            metadata = manager.fetch_metadata()
            self.assertEqual(metadata["run_status"], "READY")
            with sqlite_connection(manager.database_path, readonly=True) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 1)

    def test_corrupt_run_is_invalid_without_shared_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "bad-run")
            manager.database_path.parent.mkdir(parents=True)
            manager.database_path.write_bytes(b"corrupt")
            report = manager.open()
            self.assertFalse(report.valid)
            self.assertEqual(manager.status, RunDatabaseStatus.INVALID)

    def test_missing_metadata_blocks_update_and_invalidates_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "missing-row")
            manager.create()
            raw = sqlite3.connect(manager.database_path)
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute("DELETE FROM run_metadata")
            raw.commit()
            raw.close()
            with self.assertRaises(RuntimeError):
                manager.update_metadata(run_status="READY")
            self.assertEqual(manager.status, RunDatabaseStatus.INVALID)

    def test_truncated_run_blocks_mutation_and_invalidates_only_that_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            broken = RunDatabaseManager(workspace, "broken")
            healthy = RunDatabaseManager(workspace, "healthy")
            broken.create()
            healthy.create()
            broken.database_path.write_bytes(b"truncated")
            with self.assertRaises(sqlite3.DatabaseError):
                broken.update_metadata(run_status="READY")
            self.assertEqual(broken.status, RunDatabaseStatus.INVALID)
            healthy.update_metadata(run_status="READY")
            self.assertEqual(healthy.status, RunDatabaseStatus.VALID)

    def test_run_directory_junction_swap_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            manager = RunDatabaseManager(workspace, "swapped-run")
            runs = workspace / "runs"
            runs.mkdir(parents=True)
            outside = root / "outside"
            if not create_directory_link(runs / "swapped-run", outside):
                self.skipTest("directory links are unavailable")
            with self.assertRaises(UnsafeRunPath):
                manager.create()
            self.assertFalse((outside / "run.db").exists())

    def test_run_validation_open_race_cannot_write_escaped_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            manager = RunDatabaseManager(workspace, "race-run")
            self.assertTrue(manager.create().valid)
            personal = PersonalDatabaseManager(
                root / "personal/personal.db", backup_directory=root / "backups"
            )
            self.assertEqual(personal.initialize().status, PersonalDatabaseStatus.VALID)

            run_directory = manager.database_path.parent
            original = run_directory.with_name("race-run-original")
            escaped = root / "escaped-run"
            escaped.mkdir()
            shutil.copy2(manager.database_path, escaped / "run.db")
            real_writer = __import__(
                "investment_stack.evidence.manager", fromlist=["_sqlite_write_connection"]
            )._sqlite_write_connection
            swapped = False

            def swap_then_open(path: Path, **kwargs: object) -> object:
                nonlocal swapped
                if not swapped:
                    run_directory.rename(original)
                    if not create_directory_link(run_directory, escaped):
                        self.skipTest("directory links are unavailable")
                    swapped = True
                return real_writer(path, **kwargs)

            with patch(
                "investment_stack.evidence.manager._sqlite_write_connection",
                swap_then_open,
            ), self.assertRaises(RuntimeError):
                manager.update_metadata(run_status="ESCAPED")

            def run_status(path: Path) -> str:
                raw = sqlite3.connect(path)
                try:
                    return str(raw.execute("SELECT run_status FROM run_metadata").fetchone()[0])
                finally:
                    raw.close()

            self.assertEqual(run_status(original / "run.db"), "CREATED")
            self.assertEqual(run_status(escaped / "run.db"), "CREATED")
            self.assertEqual(manager.status, RunDatabaseStatus.INVALID)
            self.assertEqual(personal.status, PersonalDatabaseStatus.VALID)

    @staticmethod
    def _replace_provider_states(path: Path, definition: str) -> None:
        raw = sqlite3.connect(path)
        try:
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute("ALTER TABLE provider_states RENAME TO old_provider_states")
            raw.execute(definition)
            raw.execute("DROP TABLE old_provider_states")
            raw.execute(
                "CREATE INDEX idx_provider_states_run_id ON provider_states(run_id)"
            )
            raw.commit()
        finally:
            raw.close()

    def test_run_schema_detects_provider_states_foreign_key_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "fk-tamper")
            manager.create()
            self._replace_provider_states(
                manager.database_path,
                "CREATE TABLE provider_states ("
                "provider_state_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
                "provider_name TEXT NOT NULL, provider_status TEXT NOT NULL, "
                "metadata_json TEXT, updated_at TEXT NOT NULL)",
            )
            self.assertFalse(manager.open().valid)
            self.assertEqual(manager.status, RunDatabaseStatus.INVALID)

    def test_run_schema_detects_required_column_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "column-tamper")
            manager.create()
            self._replace_provider_states(
                manager.database_path,
                "CREATE TABLE provider_states ("
                "provider_state_id TEXT PRIMARY KEY, "
                "run_id TEXT NOT NULL REFERENCES run_metadata(run_id), "
                "provider_status TEXT NOT NULL, metadata_json TEXT, "
                "updated_at TEXT NOT NULL)",
            )
            self.assertFalse(manager.open().valid)

    def test_run_schema_detects_primary_key_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "pk-tamper")
            manager.create()
            self._replace_provider_states(
                manager.database_path,
                "CREATE TABLE provider_states ("
                "provider_state_id TEXT, "
                "run_id TEXT NOT NULL REFERENCES run_metadata(run_id), "
                "provider_name TEXT NOT NULL, provider_status TEXT NOT NULL, "
                "metadata_json TEXT, updated_at TEXT NOT NULL)",
            )
            self.assertFalse(manager.open().valid)

    def test_run_schema_detects_required_index_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "index-tamper")
            manager.create()
            raw = sqlite3.connect(manager.database_path)
            raw.execute("DROP INDEX idx_provider_states_run_id")
            raw.commit()
            raw.close()
            self.assertFalse(manager.open().valid)

    def test_run_schema_detects_unexpected_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "version-tamper")
            manager.create()
            raw = sqlite3.connect(manager.database_path)
            raw.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                (2, "unexpected", "2026-08-14T00:00:00+00:00", "unexpected"),
            )
            raw.commit()
            raw.close()
            self.assertFalse(manager.open().valid)

    def test_run_schema_detects_missing_run_metadata_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "metadata-tamper")
            manager.create()
            raw = sqlite3.connect(manager.database_path)
            raw.execute("PRAGMA foreign_keys = OFF")
            raw.execute("DROP TABLE run_metadata")
            raw.commit()
            raw.close()
            self.assertFalse(manager.open().valid)
