from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import investment_stack.storage.sqlite as sqlite_policy
from investment_stack.storage.identity import get_path_identity
from investment_stack.storage.sqlite import (
    ConnectionPolicy,
    _sqlite_write_connection,
    sqlite_readonly_connection,
    sqlite_transaction,
)


@contextmanager
def manager_owned_writer(
    path: Path, *, policy: ConnectionPolicy = ConnectionPolicy()
) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)
    identity = get_path_identity(path)
    with _sqlite_write_connection(
        path, expected_identity=identity, policy=policy
    ) as connection:
        yield connection


class SQLitePolicyTests(unittest.TestCase):
    def test_policy_enables_foreign_keys_timeout_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.db"
            with manager_owned_writer(
                path, policy=ConnectionPolicy(busy_timeout_ms=1234)
            ) as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 1234)
                connection.execute("CREATE TABLE values_table (name TEXT)")
                connection.execute("INSERT INTO values_table VALUES (?)", ("safe",))
                row = connection.execute("SELECT name FROM values_table").fetchone()
                self.assertEqual(row["name"], "safe")

    def test_explicit_transaction_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rollback.db"
            with manager_owned_writer(path) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    with sqlite_transaction(connection):
                        connection.execute("INSERT INTO sample VALUES (?)", ("not-committed",))
                        raise RuntimeError("boom")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 0)

    def test_connection_is_closed_by_context_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "closed.db"
            with manager_owned_writer(path) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_nested_transactions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with manager_owned_writer(Path(temporary) / "nested.db") as connection:
                with sqlite_transaction(connection):
                    with self.assertRaisesRegex(RuntimeError, "nested"):
                        with sqlite_transaction(connection):
                            pass

    def test_supported_generic_connection_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "readonly.db"
            with manager_owned_writer(path) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
            with sqlite_readonly_connection(path) as connection:
                self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO sample VALUES ('blocked')")

    def test_supported_surface_has_no_generic_writable_opener(self) -> None:
        self.assertFalse(hasattr(sqlite_policy, "sqlite_connection"))
        with self.assertRaises(ImportError):
            exec(
                "from investment_stack.storage.sqlite import sqlite_connection",
                {},
            )
        self.assertNotIn("_sqlite_write_connection", sqlite_policy.__all__)
        self.assertEqual(
            sqlite_policy.__all__,
            ["ConnectionPolicy", "sqlite_readonly_connection", "sqlite_transaction"],
        )
