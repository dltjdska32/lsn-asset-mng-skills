from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import zipfile


EXPECTED_SKILLS = {
    "investment-orchestrator",
    "fundamental-analysis",
    "valuation",
    "fund-analysis",
    "alternative-asset-analysis",
    "personal-asset-analysis",
    "investment-report",
    "review",
}
SKILL_FILES = {"SKILL.md", "agents/openai.yaml"}
POLICY_SKILLS = {'investment-orchestrator','personal-asset-analysis','valuation','investment-report','review'}
def skill_files(skill):
    return SKILL_FILES | ({'references/capital-allocation-policy.md'} if skill in POLICY_SKILLS else set())
EXPECTED_CONFIGS = {
    "freshness.yaml", "materiality.yaml", "providers.yaml", "reconciliation.yaml", "web_research.yaml",
}


class TestPackaging(unittest.TestCase):
    """Enforce the exact source, wheel, and installed-skill allowlists."""

    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]

    def _package_version(self):
        project = tomllib.loads((self.project_root / "pyproject.toml").read_text(encoding="utf-8"))
        return project["project"]["version"]

    def _runtime_sources(self):
        runtime_root = self.project_root / "runtime"
        return {
            path.relative_to(runtime_root).as_posix()
            for path in runtime_root.rglob("*.py")
        }

    def _skill_payload_paths(self):
        return {
            f"{base}/{skill}/{file}"
            for base in ("skills", ".agents/skills")
            for skill in EXPECTED_SKILLS
            for file in skill_files(skill)
        }

    def _assert_no_sensitive_paths(self, names, artifact):
        blocked_components = {
            ".git", ".venv", "cache", "caches", "credentials", "secrets",
            "backups", "backup", "logs", "__pycache__", "workspace",
        }
        blocked_suffixes = (
            ".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3",
            ".pem", ".key", ".p12", ".pfx", ".log",
        )
        for raw_name in names:
            normalized = raw_name.replace("\\", "/").lower()
            parts = normalized.split("/")
            blocked = (
                any(part in blocked_components for part in parts)
                or normalized.endswith(blocked_suffixes)
                or any(part == ".env" or part.startswith(".env.") for part in parts)
            )
            self.assertFalse(blocked, f"Excluded path found in {artifact}: {raw_name}")

    def test_manifest_exclusions(self):
        content = (self.project_root / "MANIFEST.in").read_text(encoding="utf-8")
        for exclusion in (
            "global-exclude *.db*", "global-exclude *.sqlite*", "prune workspace/runs",
            "prune workspace/cache", "prune .git", "prune .venv", "prune logs",
            "global-exclude .env", "global-exclude .env.*", "global-exclude *.pem",
            "global-exclude *.key", "global-exclude *.p12", "global-exclude *.pfx",
        ):
            self.assertIn(exclusion, content)

    def test_pyproject_declares_windows_timezone_data_and_tls_dependencies(self):
        project = tomllib.loads((self.project_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertIn("tzdata; sys_platform == 'win32'", project["dependencies"])
        self.assertTrue(any(dependency.startswith("truststore>=") for dependency in project["dependencies"]))
        self.assertEqual(project["requires-python"], ">=3.11")

    def test_sync_tool_is_present_and_inventory_is_exact(self):
        source = (self.project_root / "scripts" / "sync_agent_skills.py").read_text(encoding="utf-8")
        self.assertIn("check_only: bool = False", source)
        self.assertIn("Byte mismatch", source)
        self.assertIn("agents/openai.yaml", source)
        self.assertIn("Unexpected files under", source)
        source_dirs = {path.name for path in (self.project_root / "skills").iterdir() if path.is_dir()}
        mirror_dirs = {path.name for path in (self.project_root / ".agents" / "skills").iterdir() if path.is_dir()}
        self.assertEqual(source_dirs, EXPECTED_SKILLS)
        self.assertEqual(mirror_dirs, EXPECTED_SKILLS)
        for skill in EXPECTED_SKILLS:
            for rel_path in skill_files(skill):
                source_path = self.project_root / "skills" / skill / rel_path
                mirror_path = self.project_root / ".agents" / "skills" / skill / rel_path
                self.assertTrue(source_path.is_file())
                self.assertTrue(mirror_path.is_file())
                source_bytes = source_path.read_bytes()
                self.assertEqual(source_bytes, mirror_path.read_bytes())
                if rel_path == "agents/openai.yaml":
                    metadata = source_bytes.decode("utf-8")
                    for field in ("interface:", "display_name:", "short_description:", "default_prompt:"):
                        self.assertIn(field, metadata, f"{skill} UI metadata missing {field}")

    def test_distribution_and_runtime_versions_are_not_conflated(self):
        version = self._package_version()
        init_source = (self.project_root / "runtime" / "investment_stack" / "__init__.py").read_text(encoding="utf-8")
        runtime_version = re.search(r'__version__\s*=\s*["\']([^"\']+)', init_source)
        self.assertIsNotNone(runtime_version)
        self.assertEqual(version, runtime_version.group(1))
        architecture = (self.project_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("Canonical Final Architecture v1.3", architecture)
        self.assertNotEqual(version, "1.3")

    def test_unpacked_sdist_runs_version_metadata_check(self):
        sdists = sorted((self.project_root / "dist").glob("*.tar.gz"))
        self.assertTrue(sdists, "Build an sdist before testing its packaged version check.")

        with tempfile.TemporaryDirectory(prefix="investment-stack-sdist-") as temporary_dir:
            destination = Path(temporary_dir)
            with tarfile.open(sdists[0], "r:gz") as artifact:
                for member in artifact.getmembers():
                    relative = Path(*Path(member.name).parts)
                    self.assertFalse(relative.is_absolute())
                    self.assertNotIn("..", relative.parts)
                    target = destination / relative
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = artifact.extractfile(member)
                        self.assertIsNotNone(source)
                        target.write_bytes(source.read())

            sdist_root = next(destination.iterdir())
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "test_packaging.TestPackaging.test_distribution_and_runtime_versions_are_not_conflated"],
                cwd=sdist_root / "tests",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_built_artifacts_match_exact_allowlists(self):
        dist_dir = self.project_root / "dist"
        self.assertTrue(dist_dir.is_dir(), "Build wheel and sdist before the packaging tests.")
        wheels = sorted(dist_dir.glob("*.whl"))
        sdists = sorted(dist_dir.glob("*.tar.gz"))
        self.assertTrue(wheels, "No wheel found in dist/.")
        self.assertTrue(sdists, "No sdist found in dist/.")

        version = self._package_version()
        skills = self._skill_payload_paths()
        runtime = self._runtime_sources()
        wheel_data_prefix = f"investment_stack-{version}.data/data/"
        wheel_skill_paths = {wheel_data_prefix + path for path in skills}
        wheel_config_paths = {wheel_data_prefix + f"config/{name}" for name in EXPECTED_CONFIGS}
        wheel_runtime_paths = set(runtime)
        wheel_metadata = {
            f"investment_stack-{version}.dist-info/{name}"
            for name in ("METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD")
        }
        expected_wheel = wheel_skill_paths | wheel_config_paths | wheel_runtime_paths | wheel_metadata

        sdist_root = f"investment_stack-{version}/"
        sdist_fixed_paths = {
            "ARCHITECTURE.md", "MANIFEST.in", "PKG-INFO", "README.md", "pyproject.toml", "setup.py", "setup.cfg",
            "docs/workflow/deployment-allowlist.md", "scripts/sync_agent_skills.py",
            "scripts/build_verified_distribution.py", "scripts/capture_market_data.py",
            "scripts/run_personal_portfolio.py", "scripts/run_asset_analysis.py", "scripts/run_equity_screening.py",
            "tests/test_packaging.py", "tests/test_r15_skill_sync.py",
        }
        sdist_config_paths = {f"config/{name}" for name in EXPECTED_CONFIGS}
        sdist_runtime = {f"runtime/{path}" for path in runtime}
        sdist_egg_info = {
            f"runtime/investment_stack.egg-info/{name}"
            for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt")
        }
        expected_sdist = {
            sdist_root + path
            for path in sdist_fixed_paths | sdist_config_paths | sdist_runtime | skills | sdist_egg_info
        }

        for wheel in wheels:
            with zipfile.ZipFile(wheel) as artifact:
                names = set(artifact.namelist())
            self._assert_no_sensitive_paths(names, wheel.name)
            self.assertEqual(names, expected_wheel,
                             f"Wheel allowlist mismatch: missing={sorted(expected_wheel - names)}, extra={sorted(names - expected_wheel)}")

        for sdist in sdists:
            with tarfile.open(sdist, "r:gz") as artifact:
                names = {member.name for member in artifact.getmembers() if member.isfile()}
            self._assert_no_sensitive_paths(names, sdist.name)
            self.assertEqual(names, expected_sdist,
                             f"Sdist allowlist mismatch: missing={sorted(expected_sdist - names)}, extra={sorted(names - expected_sdist)}")

    def test_installed_skill_and_ui_discovery_files_are_exact(self):
        installed_source = Path(sys.prefix) / "skills"
        installed_mirror = Path(sys.prefix) / ".agents" / "skills"
        if not installed_source.exists() or not installed_mirror.exists():
            self.skipTest("Install the wheel with this interpreter before checking installed skill files.")

        if sys.platform == "win32":
            from importlib.metadata import version
            from zoneinfo import ZoneInfo

            self.assertTrue(version("tzdata"))
            ZoneInfo("America/New_York")
            ZoneInfo("Asia/Seoul")

        self.assertEqual({path.name for path in installed_source.iterdir() if path.is_dir()}, EXPECTED_SKILLS)
        self.assertEqual({path.name for path in installed_mirror.iterdir() if path.is_dir()}, EXPECTED_SKILLS)
        expected_files = {f"{skill}/{file}" for skill in EXPECTED_SKILLS for file in skill_files(skill)}
        for root in (installed_source, installed_mirror):
            actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(actual, expected_files)
        for skill in EXPECTED_SKILLS:
            for rel_path in skill_files(skill):
                self.assertEqual(
                    (installed_source / skill / rel_path).read_bytes(),
                    (installed_mirror / skill / rel_path).read_bytes(),
                )

        installed_config = Path(sys.prefix) / "config"
        self.assertEqual({path.name for path in installed_config.iterdir() if path.is_file()}, EXPECTED_CONFIGS)


if __name__ == "__main__":
    unittest.main()
