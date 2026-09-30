"""Synchronize Codex repo-local discovery files from authoritative skills/."""

from __future__ import annotations

import shutil
from pathlib import Path


EXPECTED_SKILLS = frozenset(
    {
        "investment-orchestrator",
        "fundamental-analysis",
        "valuation",
        "fund-analysis",
        "alternative-asset-analysis",
        "personal-asset-analysis",
        "investment-report",
        "review",
    }
)


def sync(project_root: Path, check_only: bool = False) -> None:
    source_root = project_root / "skills"
    discovery_root = project_root / ".agents" / "skills"

    for root, label in ((source_root, "authoritative"), (discovery_root, "discovery")):
        if root.is_symlink():
            raise ValueError(f"Skills root must not be a symlink: {label}")
        if root.exists():
            symlinks = [path for path in root.rglob("*") if path.is_symlink()]
            if symlinks:
                raise ValueError(f"Symlinks are not allowed under {label} skills root: {symlinks}")

    expected = set(EXPECTED_SKILLS)
    source_names = {path.name for path in source_root.iterdir() if path.is_dir()} if source_root.is_dir() else set()
    if source_names != expected:
        raise ValueError(
            f"Authoritative skills inventory mismatch: missing={sorted(expected - source_names)}, "
            f"unexpected={sorted(source_names - expected)}"
        )

    if discovery_root.exists():
        mirror_names = {path.name for path in discovery_root.iterdir() if path.is_dir()}
        unexpected_mirrors = mirror_names - expected
        if unexpected_mirrors:
            raise ValueError(f"Unexpected discovery skill directories: {sorted(unexpected_mirrors)}")

    files_to_sync = ("SKILL.md", "agents/openai.yaml")
    allowed_relative_files = {Path(name) / rel for name in EXPECTED_SKILLS for rel in files_to_sync}
    for root, label in ((source_root, "authoritative"), (discovery_root, "discovery")):
        if not root.exists():
            continue
        actual = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
        unexpected = actual - allowed_relative_files
        if unexpected:
            raise ValueError(f"Unexpected files under {label} skills root: {sorted(map(str, unexpected))}")

    if not check_only:
        discovery_root.mkdir(parents=True, exist_ok=True)

    mismatches = []

    for name in sorted(EXPECTED_SKILLS):
        for file_rel_path in files_to_sync:
            source = source_root / name / file_rel_path
            if not source.is_file():
                raise FileNotFoundError(f"Missing authoritative skill source: {source}")

            target = discovery_root / name / file_rel_path

            if not check_only:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            if not target.is_file():
                mismatches.append(f"{name}/{file_rel_path}: Target missing")
                continue

            # Verify byte equality
            source_bytes = source.read_bytes()
            target_bytes = target.read_bytes()

            if source_bytes != target_bytes:
                mismatches.append(f"{name}/{file_rel_path}: Byte mismatch")

    if mismatches:
        raise ValueError(f"Skill mirror synchronization failed or drifted: {mismatches}")


if __name__ == "__main__":
    import sys
    check_mode = "--check" in sys.argv
    sync(Path(__file__).resolve().parents[1], check_only=check_mode)
