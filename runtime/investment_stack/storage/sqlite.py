"""Central SQLite connection and transaction policy.

The supported generic opener is read-only. Writable connections are an internal
primitive that requires a manager-owned filesystem identity captured before open.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from investment_stack.storage.identity import (
    PathIdentity,
    verify_opened_database_identity,
)


__all__ = ["ConnectionPolicy", "sqlite_readonly_connection", "sqlite_transaction"]


@dataclass(frozen=True)
class ConnectionPolicy:
    """SQLite settings shared by personal and run databases."""

    busy_timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        if not 0 <= self.busy_timeout_ms <= 600_000:
            raise ValueError("busy_timeout_ms must be between 0 and 600000")


DEFAULT_CONNECTION_POLICY = ConnectionPolicy()


def _configure_connection(
    connection: sqlite3.Connection,
    *,
    readonly: bool,
    policy: ConnectionPolicy,
) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {policy.busy_timeout_ms:d}")
    if readonly:
        connection.execute("PRAGMA query_only = ON")


@contextmanager
def sqlite_readonly_connection(
    path: Path,
    *,
    policy: ConnectionPolicy = DEFAULT_CONNECTION_POLICY,
) -> Iterator[sqlite3.Connection]:
    """Open a configured read-only SQLite connection and always close it."""

    database_path = Path(path).expanduser().resolve(strict=False)
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    target = f"{database_path.as_uri()}?mode=ro"

    connection = sqlite3.connect(
        target,
        uri=True,
        timeout=policy.busy_timeout_ms / 1_000,
        isolation_level=None,
        check_same_thread=True,
    )
    try:
        _configure_connection(connection, readonly=True, policy=policy)
        yield connection
    finally:
        connection.close()


@contextmanager
def _sqlite_verified_read_connection(
    path: Path,
    *,
    expected_identity: PathIdentity,
    policy: ConnectionPolicy = DEFAULT_CONNECTION_POLICY,
) -> Iterator[sqlite3.Connection]:
    """Internal read boundary bound to a manager-owned file identity."""

    database_path = expected_identity.lexical_path
    target = f"{database_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(
        target,
        uri=True,
        timeout=policy.busy_timeout_ms / 1_000,
        isolation_level=None,
        check_same_thread=True,
    )
    try:
        _configure_connection(connection, readonly=True, policy=policy)
        verify_opened_database_identity(
            connection,
            expected_path=path,
            expected_identity=expected_identity,
        )
        yield connection
        verify_opened_database_identity(
            connection,
            expected_path=path,
            expected_identity=expected_identity,
        )
    finally:
        connection.close()


@contextmanager
def _sqlite_write_connection(
    path: Path,
    *,
    expected_identity: PathIdentity,
    policy: ConnectionPolicy = DEFAULT_CONNECTION_POLICY,
) -> Iterator[sqlite3.Connection]:
    """Internal writable opener; verify the opened object before yielding it."""

    database_path = expected_identity.lexical_path
    connection = sqlite3.connect(
        str(database_path),
        timeout=policy.busy_timeout_ms / 1_000,
        isolation_level=None,
        check_same_thread=True,
    )
    try:
        _configure_connection(connection, readonly=False, policy=policy)
        verify_opened_database_identity(
            connection,
            expected_path=path,
            expected_identity=expected_identity,
        )
        yield connection
        verify_opened_database_identity(
            connection,
            expected_path=path,
            expected_identity=expected_identity,
        )
    finally:
        connection.close()


@contextmanager
def sqlite_transaction(
    connection: sqlite3.Connection,
    *,
    immediate: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Run a single explicit atomic transaction with rollback on any error."""

    if connection.in_transaction:
        raise RuntimeError("nested SQLite transactions are not supported")
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
