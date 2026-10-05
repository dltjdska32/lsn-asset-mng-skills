"""Filesystem identity checks for SQLite operation boundaries.

Path validation alone is not an operation boundary: a directory can be replaced
after validation and before SQLite opens the file.  These helpers bind an open
connection to the file and parent directory identities captured by its manager.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class StorageIdentityError(RuntimeError):
    """Raised when a storage path cannot be bound to one filesystem object."""


@dataclass(frozen=True)
class FileIdentity:
    """Portable identity exposed by ``stat`` (volume/device plus file id/inode)."""

    device: int
    inode: int


@dataclass(frozen=True)
class PathIdentity:
    """Identity of a database path and the directory that owns its name."""

    lexical_path: Path
    resolved_path: Path
    parent: FileIdentity
    target: FileIdentity | None


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _identity_from_stat(path: Path, *, follow_symlinks: bool) -> FileIdentity:
    try:
        details = path.stat(follow_symlinks=follow_symlinks)
    except OSError as exc:
        raise StorageIdentityError(f"could not read filesystem identity for {path}: {exc}") from exc
    device = int(details.st_dev)
    inode = int(details.st_ino)
    if device == 0 or inode == 0:
        raise StorageIdentityError(f"stable filesystem identity is unavailable for {path}")
    return FileIdentity(device, inode)


def has_reparse_component(path: Path) -> bool:
    """Return whether any existing path component is a symlink/reparse point.

    Errors other than a missing not-yet-created component fail closed because an
    unreadable component cannot be proven safe for sensitive storage.
    """

    candidate = _absolute_path(Path(path))
    for component in (candidate, *candidate.parents):
        try:
            details = component.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StorageIdentityError(
                f"could not inspect storage path component {component}: {exc}"
            ) from exc
        if stat.S_ISLNK(details.st_mode):
            return True
        attributes = int(getattr(details, "st_file_attributes", 0))
        if attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            return True
    return False


def get_path_identity(path: Path, *, require_target: bool = True) -> PathIdentity:
    """Capture the current database name, parent, and target identities."""

    lexical = _absolute_path(Path(path))
    if has_reparse_component(lexical):
        raise StorageIdentityError(
            f"sensitive storage path contains a symbolic link or reparse point: {lexical}"
        )
    if not lexical.parent.is_dir():
        raise StorageIdentityError(f"storage parent directory does not exist: {lexical.parent}")
    parent_identity = _identity_from_stat(lexical.parent, follow_symlinks=False)
    try:
        target_identity = _identity_from_stat(lexical, follow_symlinks=False)
    except StorageIdentityError:
        if require_target or lexical.exists():
            raise
        target_identity = None
    try:
        resolved = lexical.resolve(strict=require_target)
    except OSError as exc:
        raise StorageIdentityError(f"could not resolve storage path {lexical}: {exc}") from exc
    return PathIdentity(lexical, resolved, parent_identity, target_identity)


def verify_opened_database_identity(
    connection: object,
    *,
    expected_path: Path,
    expected_identity: PathIdentity,
) -> PathIdentity:
    """Prove SQLite opened the expected file before a transaction may begin."""

    rows = connection.execute("PRAGMA database_list").fetchall()  # type: ignore[attr-defined]
    main_rows = [row for row in rows if str(row[1]) == "main"]
    if len(main_rows) != 1 or not str(main_rows[0][2]):
        raise StorageIdentityError("SQLite did not report exactly one main database path")

    current = get_path_identity(expected_path, require_target=True)
    opened = get_path_identity(Path(str(main_rows[0][2])), require_target=True)
    if current.resolved_path != expected_identity.resolved_path:
        raise StorageIdentityError("database path resolved target changed before open")
    if current.parent != expected_identity.parent:
        raise StorageIdentityError("database parent directory identity changed before open")
    if expected_identity.target is None:
        raise StorageIdentityError("writable database target was not reserved before open")
    if current.target != expected_identity.target:
        raise StorageIdentityError("database file identity changed before open")
    if opened.resolved_path != current.resolved_path or opened.target != current.target:
        raise StorageIdentityError("opened SQLite database is not the expected filesystem object")
    return current
