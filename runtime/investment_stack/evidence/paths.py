"""Run workspace path validation and collision policy."""

from __future__ import annotations

import re
import stat
from pathlib import Path


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafeRunPath(ValueError):
    """Raised for traversal, aliases, or malformed run identifiers."""


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


def _reject_reparse_chain(path: Path, *, workspace: Path) -> None:
    for component in (path, *path.parents):
        if _is_reparse_point(component):
            raise UnsafeRunPath(
                f"run storage path uses a symbolic link or reparse point: {component}"
            )
        if component == workspace:
            break


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise UnsafeRunPath("run_id must use 1-128 ASCII letters, digits, '.', '_' or '-'")
    if run_id in {".", ".."} or ".." in run_id:
        raise UnsafeRunPath("run_id cannot contain traversal segments")
    return run_id


def resolve_run_db_path(
    workspace_root: Path,
    run_id: str,
    *,
    expected_resolved: Path | None = None,
) -> Path:
    """Resolve workspace/runs/<run-id>/run.db and prove it stays contained."""

    safe_run_id = validate_run_id(run_id)
    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    lexical_runs_root = workspace / "runs"
    _reject_reparse_chain(lexical_runs_root, workspace=workspace)
    runs_root = lexical_runs_root.resolve(strict=False)
    if not _is_within(runs_root, workspace):
        raise UnsafeRunPath("workspace/runs escaped the canonical workspace")
    lexical_candidate = lexical_runs_root / safe_run_id / "run.db"
    _reject_reparse_chain(lexical_candidate, workspace=workspace)
    candidate = lexical_candidate.resolve(strict=False)
    if not _is_within(candidate, runs_root) or not _is_within(candidate, workspace):
        raise UnsafeRunPath("run database escaped workspace/runs")
    if expected_resolved is not None and candidate != expected_resolved:
        raise UnsafeRunPath("run database target changed after validation")
    return candidate
