"""Test-only storage fixtures kept entirely in temporary directories."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from investment_stack.storage.migrations import (
    Migration,
    apply_pending_migrations,
    ensure_migration_table,
)
from investment_stack.storage.sqlite import sqlite_transaction


@contextmanager
def sqlite_connection(
    path: Path, *, readonly: bool = False
) -> Iterator[sqlite3.Connection]:
    """Test-only raw connection for fixture creation and deliberate tampering."""

    database = Path(path).resolve(strict=False)
    if readonly:
        target = f"{database.as_uri()}?mode=ro"
    else:
        database.parent.mkdir(parents=True, exist_ok=True)
        target = str(database)
    connection = sqlite3.connect(target, uri=readonly, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def create_database_at_migrations(path: Path, migrations: Sequence[Migration]) -> None:
    with sqlite_connection(path) as connection:
        with sqlite_transaction(connection):
            ensure_migration_table(connection)
            apply_pending_migrations(connection, migrations)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_directory_link(link: Path, target: Path) -> bool:
    """Create a test-only directory symlink or Windows junction."""

    link = Path(link)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        if os.name != "nt":
            return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and link.exists()
