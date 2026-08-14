"""Best-effort private filesystem permissions for sensitive artifacts."""

from __future__ import annotations

import logging
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def protect_directory(path: Path) -> None:
    """Create and restrict a directory without making portability a blocker."""

    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError as exc:
        LOGGER.warning("could not restrict storage directory %s: %s", directory, exc)


def protect_file(path: Path) -> None:
    """Best-effort owner-only permission for a sensitive file."""

    file_path = Path(path)
    try:
        file_path.chmod(0o600)
    except OSError as exc:
        LOGGER.warning("could not restrict storage file %s: %s", file_path, exc)
