from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from investment_stack.evidence.manager import REQUIRED_RUN_TABLES, RunDatabaseManager
from investment_stack.migrations.personal import CURRENT_PERSONAL_SCHEMA_VERSION
from investment_stack.migrations.run import CURRENT_RUN_SCHEMA_VERSION
from investment_stack.personal.manager import PersonalDatabaseManager, PersonalDatabaseStatus
from investment_stack.personal.validation import REQUIRED_PERSONAL_TABLES
from tests.storage_support import sqlite_connection


class StorageSchemaTests(unittest.TestCase):
    def test_personal_initialization_has_required_tables_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = PersonalDatabaseManager(
                root / "data/personal.db", backup_directory=root / "backups"
            )
            result = manager.initialize()
            self.assertEqual(result.status, PersonalDatabaseStatus.VALID)
            self.assertEqual(result.validation.schema_version, CURRENT_PERSONAL_SCHEMA_VERSION)
            self.assertEqual(str(UUID(result.validation.instance_id)).replace("-", ""), result.validation.instance_id)
            with sqlite_connection(manager.database_path, readonly=True) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(REQUIRED_PERSONAL_TABLES.issubset(tables))

    def test_run_initialization_has_independent_schema_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RunDatabaseManager(Path(temporary) / "workspace", "schema-run")
            report = manager.create()
            self.assertTrue(report.valid)
            with sqlite_connection(manager.database_path, readonly=True) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
            self.assertTrue(REQUIRED_RUN_TABLES.issubset(tables))
            self.assertEqual(version, CURRENT_RUN_SCHEMA_VERSION)
            self.assertNotEqual(CURRENT_PERSONAL_SCHEMA_VERSION, CURRENT_RUN_SCHEMA_VERSION)
