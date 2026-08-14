"""Reusable exact SQLite schema signatures derived from migration catalogs."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from investment_stack.storage.migrations import (
    Migration,
    apply_pending_migrations,
    ensure_migration_table,
)

_SQL_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ColumnSignature:
    name: str
    declared_type: str
    not_null: bool
    primary_key_position: int


@dataclass(frozen=True)
class ForeignKeySignature:
    foreign_key_id: int
    sequence: int
    source_column: str
    referenced_table: str
    referenced_column: str
    on_update: str
    on_delete: str
    match: str


@dataclass(frozen=True)
class IndexSignature:
    name: str | None
    unique: bool
    origin: str
    partial: bool
    columns: tuple[str | None, ...]


@dataclass(frozen=True)
class TableSignature:
    columns: tuple[ColumnSignature, ...]
    foreign_keys: tuple[ForeignKeySignature, ...]
    indexes: tuple[IndexSignature, ...]


@dataclass(frozen=True)
class TriggerSignature:
    name: str
    table: str
    canonical_sql: str


@dataclass(frozen=True)
class SchemaSignature:
    tables: tuple[tuple[str, TableSignature], ...]
    triggers: tuple[TriggerSignature, ...] = ()


def canonicalize_sqlite_sql(sql: str | None) -> str:
    """Normalize SQLite DDL enough to compare trigger signatures."""

    if not sql:
        return ""
    return _SQL_WHITESPACE.sub(" ", sql).strip().casefold()


def introspect_schema(connection: sqlite3.Connection) -> SchemaSignature:
    table_names = [
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    tables: list[tuple[str, TableSignature]] = []
    for table_name in table_names:
        columns = tuple(
            ColumnSignature(
                str(row["name"]),
                str(row["type"] or "").upper(),
                bool(row["notnull"]),
                int(row["pk"]),
            )
            for row in connection.execute(
                "SELECT name, type, \"notnull\", pk FROM pragma_table_info(?) ORDER BY cid",
                (table_name,),
            ).fetchall()
        )
        foreign_keys = tuple(
            ForeignKeySignature(
                int(row["id"]),
                int(row["seq"]),
                str(row["from"]),
                str(row["table"]),
                str(row["to"]),
                str(row["on_update"]).upper(),
                str(row["on_delete"]).upper(),
                str(row["match"]).upper(),
            )
            for row in connection.execute(
                "SELECT id, seq, \"from\", \"table\", \"to\", on_update, on_delete, "
                "\"match\" FROM pragma_foreign_key_list(?) ORDER BY id, seq",
                (table_name,),
            ).fetchall()
        )
        indexes: list[IndexSignature] = []
        for row in connection.execute(
            "SELECT name, \"unique\", origin, partial FROM pragma_index_list(?)",
            (table_name,),
        ).fetchall():
            index_name = str(row["name"])
            origin = str(row["origin"])
            index_columns = tuple(
                None if column["name"] is None else str(column["name"])
                for column in connection.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                    (index_name,),
                ).fetchall()
            )
            indexes.append(
                IndexSignature(
                    index_name if origin == "c" else None,
                    bool(row["unique"]),
                    origin,
                    bool(row["partial"]),
                    index_columns,
                )
            )
        indexes.sort(key=lambda item: (item.origin, item.name or "", item.columns))
        tables.append((table_name, TableSignature(columns, foreign_keys, tuple(indexes))))
    triggers = tuple(
        TriggerSignature(
            str(row["name"]),
            str(row["tbl_name"]),
            canonicalize_sqlite_sql(None if row["sql"] is None else str(row["sql"])),
        )
        for row in connection.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master "
            "WHERE type = 'trigger' ORDER BY name"
        ).fetchall()
    )
    return SchemaSignature(tuple(tables), triggers)


@lru_cache(maxsize=32)
def expected_schema_signature(
    catalog: tuple[Migration, ...], schema_version: int
) -> SchemaSignature:
    if not 1 <= schema_version <= len(catalog):
        raise ValueError("schema version is outside the migration catalog")
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        ensure_migration_table(connection)
        apply_pending_migrations(connection, catalog[:schema_version])
        connection.commit()
        return introspect_schema(connection)
    finally:
        connection.close()


def schema_signature_errors(
    actual: SchemaSignature, expected: SchemaSignature
) -> list[str]:
    errors: list[str] = []
    actual_tables = dict(actual.tables)
    expected_tables = dict(expected.tables)
    missing = sorted(expected_tables.keys() - actual_tables.keys())
    unexpected = sorted(actual_tables.keys() - expected_tables.keys())
    if missing:
        errors.append("missing required tables: " + ", ".join(missing))
    if unexpected:
        errors.append("unexpected schema tables: " + ", ".join(unexpected))
    for table_name in sorted(actual_tables.keys() & expected_tables.keys()):
        actual_table = actual_tables[table_name]
        expected_table = expected_tables[table_name]
        if actual_table.columns != expected_table.columns:
            errors.append(f"column signature mismatch: {table_name}")
        if actual_table.foreign_keys != expected_table.foreign_keys:
            errors.append(f"foreign key signature mismatch: {table_name}")
        if actual_table.indexes != expected_table.indexes:
            errors.append(f"index/unique signature mismatch: {table_name}")
    actual_triggers = {item.name: item for item in actual.triggers}
    expected_triggers = {item.name: item for item in expected.triggers}
    missing_triggers = sorted(expected_triggers.keys() - actual_triggers.keys())
    unexpected_triggers = sorted(actual_triggers.keys() - expected_triggers.keys())
    if missing_triggers:
        errors.append("missing schema triggers: " + ", ".join(missing_triggers))
    if unexpected_triggers:
        errors.append("unexpected schema triggers: " + ", ".join(unexpected_triggers))
    for name in sorted(actual_triggers.keys() & expected_triggers.keys()):
        actual_trigger = actual_triggers[name]
        expected_trigger = expected_triggers[name]
        if actual_trigger.table != expected_trigger.table:
            errors.append(f"trigger target mismatch: {name}")
        if actual_trigger.canonical_sql != expected_trigger.canonical_sql:
            errors.append(f"trigger signature mismatch: {name}")
    return errors
