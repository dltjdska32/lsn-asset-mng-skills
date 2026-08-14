"""Executable checks for architecture boundaries implemented in Phase 1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from investment_stack.pipelines import PIPELINES
from investment_stack.routing import RequestMode


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


@dataclass(frozen=True, slots=True)
class InvariantResult:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def validate_runtime_invariants(project_root: Path | None = None) -> tuple[InvariantResult, ...]:
    results = [
        InvariantResult(
            "exactly_seven_request_modes",
            len(RequestMode) == 7,
            f"found {len(RequestMode)}",
        ),
        InvariantResult(
            "one_fixed_pipeline_per_mode",
            set(PIPELINES) == set(RequestMode),
            f"mapped {len(PIPELINES)} pipelines",
        ),
    ]

    if project_root is not None:
        root = project_root.resolve()
        skills_dir = root / "skills"
        actual_skills = (
            {path.name for path in skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()}
            if skills_dir.is_dir()
            else set()
        )
        results.append(
            InvariantResult(
                "exactly_eight_skills",
                actual_skills == EXPECTED_SKILLS,
                f"found {sorted(actual_skills)}",
            )
        )
        forbidden = [
            root / "runtime" / "investment_stack" / "dag",
            root / "runtime" / "investment_stack" / "outbox",
            root / "research-cache.db",
        ]
        present = [str(path.relative_to(root)) for path in forbidden if path.exists()]
        results.append(
            InvariantResult(
                "forbidden_components_absent",
                not present,
                "none found" if not present else f"found {present}",
            )
        )

    return tuple(results)

