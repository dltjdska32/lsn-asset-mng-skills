"""Operating-system-aware personal storage path resolution."""

from __future__ import annotations

import os
import platform
import stat
from collections.abc import Mapping
from pathlib import Path


PERSONAL_DB_OVERRIDE_ENV = "INVESTMENT_STACK_PERSONAL_DB_PATH"
BACKUP_DIR_OVERRIDE_ENV = "INVESTMENT_STACK_BACKUP_DIR"


class UnsafeStoragePath(ValueError):
    """Raised when a sensitive storage path violates its boundary."""


def _contains_nul(value: str) -> bool:
    return "\x00" in value


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _reject_reparse_chain(path: Path) -> None:
    for component in (path, *path.parents):
        if _is_reparse_point(component):
            raise UnsafeStoragePath(
                f"sensitive storage path uses a symbolic link or reparse point: {component}"
            )


def _data_home(
    *,
    system: str,
    environ: Mapping[str, str],
    home: Path,
) -> Path:
    if system == "Windows":
        configured = environ.get("LOCALAPPDATA")
        return Path(configured) if configured else home / "AppData" / "Local"
    if system == "Darwin":
        return home / "Library" / "Application Support"
    configured = environ.get("XDG_DATA_HOME")
    return Path(configured) if configured else home / ".local" / "share"


def _validate_sensitive_path(
    candidate: Path,
    *,
    repository_root: Path | None,
    expected_suffix: str | None,
) -> Path:
    raw = str(candidate)
    if _contains_nul(raw):
        raise UnsafeStoragePath("storage path contains a NUL byte")
    expanded = candidate.expanduser()
    if not expanded.is_absolute():
        raise UnsafeStoragePath("storage path must be absolute")
    resolved = expanded.resolve(strict=False)
    if expected_suffix is not None and resolved.suffix.lower() != expected_suffix:
        raise UnsafeStoragePath(f"storage path must end with {expected_suffix}")
    if repository_root is not None:
        repository = Path(repository_root).expanduser().resolve(strict=False)
        if _is_within(resolved, repository):
            raise UnsafeStoragePath("personal storage must not be inside the repository")
    else:
        for parent in (resolved, *resolved.parents):
            if (parent / ".git").exists():
                raise UnsafeStoragePath("personal storage must not be inside a Git repository")
    return resolved


def validate_personal_operational_path(
    candidate: str | Path,
    *,
    repository_root: Path | None,
    expected_suffix: str | None,
    expected_resolved: Path | None = None,
) -> Path:
    """Revalidate a sensitive path immediately before a filesystem operation."""

    lexical = Path(candidate).expanduser()
    _reject_reparse_chain(lexical)
    resolved = _validate_sensitive_path(
        lexical,
        repository_root=repository_root,
        expected_suffix=expected_suffix,
    )
    if expected_resolved is not None and resolved != expected_resolved:
        raise UnsafeStoragePath("sensitive storage path target changed after validation")
    return resolved


def resolve_personal_db_path(
    override: str | Path | None = None,
    *,
    repository_root: Path | None = None,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    create_parent: bool = False,
) -> Path:
    """Resolve a validated personal.db path without eagerly creating it."""

    environment = os.environ if environ is None else environ
    selected = override if override is not None else environment.get(PERSONAL_DB_OVERRIDE_ENV)
    if selected is None:
        os_name = platform.system() if system is None else system
        user_home = Path.home() if home is None else Path(home)
        selected = _data_home(system=os_name, environ=environment, home=user_home) / (
            "investment-stack/personal/personal.db"
        )
    path = _validate_sensitive_path(
        Path(selected), repository_root=repository_root, expected_suffix=".db"
    )
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_backup_directory(
    override: str | Path | None = None,
    *,
    repository_root: Path | None = None,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    create: bool = False,
) -> Path:
    """Resolve the sensitive backup directory outside the source repository."""

    environment = os.environ if environ is None else environ
    selected = override if override is not None else environment.get(BACKUP_DIR_OVERRIDE_ENV)
    if selected is None:
        os_name = platform.system() if system is None else system
        user_home = Path.home() if home is None else Path(home)
        selected = _data_home(system=os_name, environ=environment, home=user_home) / (
            "investment-stack/backups"
        )
    path = _validate_sensitive_path(
        Path(selected), repository_root=repository_root, expected_suffix=None
    )
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
