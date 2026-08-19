"""Executable checks for frozen v1.3 architecture boundaries."""

from __future__ import annotations

import tomllib
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

FORBIDDEN_RUNTIME_COMPONENTS = (
    "dag",
    "outbox",
    "server",
    "api",
    "scheduler",
    "microservices",
    "mcp",
)

FORBIDDEN_ROOT_COMPONENTS = (
    "server",
    "api",
    "scheduler",
    "microservices",
    "outbox",
)



_SENSITIVE_RUNTIME_SUFFIXES = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".db.bak",
    ".sqlite",
    ".sqlite3",
    ".secret",
)


def _sensitive_runtime_artifacts(root: Path) -> tuple[str, ...]:
    """Return repo-local runtime/secret artifacts that must never ship in a release."""

    ignored_parts = {".git", ".venv", "dist", "build", "__pycache__", ".pytest_cache"}
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        name = path.name
        lower = name.lower()
        is_env_secret = lower == ".env" or (lower.startswith(".env.") and lower != ".env.example")
        is_secret_file = lower == ".secrets" or lower.startswith("secrets.")
        is_runtime_db = lower.endswith(_SENSITIVE_RUNTIME_SUFFIXES)
        if is_env_secret or is_secret_file or is_runtime_db:
            found.append(str(path.relative_to(root)))
    return tuple(sorted(found))

FORBIDDEN_DEPENDENCIES = frozenset(
    {
        "fastapi",
        "uvicorn",
        "flask",
        "django",
        "redis",
        "celery",
        "kafka-python",
        "psycopg",
        "psycopg2",
    }
)


@dataclass(frozen=True, slots=True)
class InvariantResult:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def _project_dependency_names(root: Path) -> frozenset[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return frozenset()
    with pyproject.open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    dependencies = project.get("dependencies", ()) or ()
    names: set[str] = set()
    for dependency in dependencies:
        token = str(dependency).strip().split(";", 1)[0].strip()
        for separator in ("[", "<", ">", "=", "!", "~", " "):
            token = token.split(separator, 1)[0]
        if token:
            names.add(token.lower().replace("_", "-"))
    return frozenset(names)


def validate_runtime_invariants(project_root: Path | None = None) -> tuple[InvariantResult, ...]:
    """Validate structural invariants that can be checked without mutating user data."""

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
        discovery_dir = root / ".agents" / "skills"
        discovered_skills = (
            {path.name for path in discovery_dir.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()}
            if discovery_dir.is_dir()
            else set()
        )
        results.append(
            InvariantResult(
                "exactly_eight_repo_local_discovery_skills",
                discovered_skills == EXPECTED_SKILLS,
                f"found {sorted(discovered_skills)}",
            )
        )
        drifted_skills = sorted(
            name
            for name in EXPECTED_SKILLS
            if not (skills_dir / name / "SKILL.md").is_file()
            or not (discovery_dir / name / "SKILL.md").is_file()
            or (skills_dir / name / "SKILL.md").read_bytes()
            != (discovery_dir / name / "SKILL.md").read_bytes()
        )
        results.append(
            InvariantResult(
                "repo_local_discovery_mirrors_authoritative_skills",
                not drifted_skills,
                "all discovery files match skills/" if not drifted_skills else f"drifted {drifted_skills}",
            )
        )

        runtime_root = root / "runtime" / "investment_stack"
        forbidden_paths = [runtime_root / name for name in FORBIDDEN_RUNTIME_COMPONENTS]
        forbidden_paths.extend(root / name for name in FORBIDDEN_ROOT_COMPONENTS)
        present = [str(path.relative_to(root)) for path in forbidden_paths if path.exists()]
        results.append(
            InvariantResult(
                "forbidden_components_absent",
                not present,
                "none found" if not present else f"found {present}",
            )
        )

        cache_files = sorted(
            str(path.relative_to(root))
            for path in root.rglob("research-cache.db")
            if ".git" not in path.parts
        )
        results.append(
            InvariantResult(
                "research_cache_db_absent",
                not cache_files,
                "none found" if not cache_files else f"found {cache_files}",
            )
        )

        architecture = root / "ARCHITECTURE.md"
        architecture_text = architecture.read_text(encoding="utf-8") if architecture.is_file() else ""
        frozen = "ARCHITECTURE FROZEN" in architecture_text and "v1.3" in architecture_text
        results.append(
            InvariantResult(
                "canonical_architecture_frozen_v1_3",
                frozen,
                "v1.3 frozen architecture present" if frozen else "missing frozen v1.3 marker",
            )
        )

        dependencies = _project_dependency_names(root)
        forbidden_dependencies = sorted(dependencies & FORBIDDEN_DEPENDENCIES)
        results.append(
            InvariantResult(
                "server_infrastructure_dependencies_absent",
                not forbidden_dependencies,
                "none found" if not forbidden_dependencies else f"found {forbidden_dependencies}",
            )
        )

        news_skill = any(name in actual_skills for name in {"news", "news-analysis", "latest-news"})
        results.append(
            InvariantResult(
                "news_remains_inside_existing_web_research_boundary",
                not news_skill and "web_research" in {path.name for path in runtime_root.iterdir() if path.is_dir()},
                "no separate news skill; web_research runtime present",
            )
        )

        sensitive_artifacts = _sensitive_runtime_artifacts(root)
        results.append(
            InvariantResult(
                "sensitive_runtime_artifacts_absent",
                not sensitive_artifacts,
                "none found" if not sensitive_artifacts else f"found {list(sensitive_artifacts)}",
            )
        )

    return tuple(results)
