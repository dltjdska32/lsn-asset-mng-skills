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


def sync(project_root: Path) -> None:
    source_root = project_root / "skills"
    discovery_root = project_root / ".agents" / "skills"
    discovery_root.mkdir(parents=True, exist_ok=True)
    for name in sorted(EXPECTED_SKILLS):
        source = source_root / name / "SKILL.md"
        if not source.is_file():
            raise FileNotFoundError(source)
        target = discovery_root / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


if __name__ == "__main__":
    sync(Path(__file__).resolve().parents[1])
