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
    if not check_only:
        discovery_root.mkdir(parents=True, exist_ok=True)

    mismatches = []

    files_to_sync = ["SKILL.md", "agents/openai.yaml"]

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
