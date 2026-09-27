import os
from pathlib import Path
import unittest

class TestPackaging(unittest.TestCase):
    """Test packaging prerequisites and skill sync behavior."""

    def setUp(self):
        self.project_root = Path(__file__).resolve().parents[1]

    def test_manifest_exclusions(self):
        """Verify MANIFEST.in explicitly excludes sensitive paths."""
        manifest_path = self.project_root / "MANIFEST.in"
        self.assertTrue(manifest_path.exists(), "MANIFEST.in is missing")

        content = manifest_path.read_text(encoding="utf-8")

        required_exclusions = [
            "global-exclude personal.db",
            "global-exclude run.db",
            "prune workspace/runs",
            "prune logs",
            "global-exclude .env"
        ]

        for exc in required_exclusions:
            self.assertIn(exc, content, f"MANIFEST.in missing exclusion: {exc}")

    def test_pyproject_dependencies(self):
        """Verify pyproject.toml contains required dependencies."""
        toml_path = self.project_root / "pyproject.toml"
        self.assertTrue(toml_path.exists(), "pyproject.toml is missing")

        content = toml_path.read_text(encoding="utf-8")

        self.assertIn("tzdata; sys_platform == 'win32'", content)
        self.assertIn("truststore", content)

    def test_skill_sync_script_exists(self):
        """Verify sync_agent_skills script exists and has check option."""
        script_path = self.project_root / "scripts" / "sync_agent_skills.py"
        self.assertTrue(script_path.exists(), "sync_agent_skills.py is missing")

        content = script_path.read_text(encoding="utf-8")
        self.assertIn("check_only: bool = False", content)
        self.assertIn("target_bytes =", content)
        self.assertIn("source_bytes !=", content)
        self.assertIn("agents/openai.yaml", content)

    def test_built_artifacts_contain_skills(self):
        """Dynamically check built wheel and sdist to ensure all 8 skills and metadata are included."""
        dist_dir = self.project_root / "dist"

        # We must FAIL if the build hasn't happened, as this is a strict verification step.
        self.assertTrue(dist_dir.exists(), "No dist/ directory found. Coordinator must run 'python -m build' first.")

        wheels = list(dist_dir.glob("*.whl"))
        sdists = list(dist_dir.glob("*.tar.gz"))

        self.assertTrue(wheels, "No wheel found in dist/. Coordinator must run 'python -m build' first.")
        self.assertTrue(sdists, "No sdist found in dist/. Coordinator must run 'python -m build' first.")

        import tarfile
        import zipfile

        expected_skills = [
            "investment-orchestrator",
            "fundamental-analysis",
            "valuation",
            "fund-analysis",
            "alternative-asset-analysis",
            "personal-asset-analysis",
            "investment-report",
            "review",
        ]

        sensitive_patterns = ["personal.db", "run.db", "workspace/runs", ".env"]

        def _check_strict_allowlist(items, container_name):
            """Ensure no arbitrary files sneaked into the skills or runtime directories."""
            for name, is_dir in items:
                # Normalize path separators for checking
                norm_name = name.replace("\\", "/")

                # Check for sensitive files
                for sp in sensitive_patterns:
                    self.assertFalse(sp in norm_name, f"Sensitive pattern {sp} found in {container_name}: {norm_name}")

                if is_dir:
                    continue

                # Check strict allowlist for skills directories
                if "skills/" in norm_name or ".agents/skills/" in norm_name:
                    is_allowed = norm_name.endswith("SKILL.md") or norm_name.endswith("openai.yaml")
                    self.assertTrue(is_allowed, f"Unauthorized file found in skills data inside {container_name}: {norm_name}")

                # Check runtime boundary (only .py allowed for actual package sources)
                # In sdist it is typically `pkgname-version/runtime/...`
                # In wheel it is typically `investment_stack/...`
                if "/runtime/" in "/" + norm_name or norm_name.startswith("runtime/"):
                    if ".egg-info/" in norm_name:
                        continue
                    self.assertTrue(norm_name.endswith(".py"), f"Non-.py file leaked into runtime in sdist {container_name}: {norm_name}")
                if norm_name.startswith("investment_stack/"):
                    self.assertTrue(norm_name.endswith(".py"), f"Non-.py file leaked into investment_stack in wheel {container_name}: {norm_name}")

        for whl in wheels:
            with zipfile.ZipFile(whl, "r") as z:
                items = [(info.filename, info.is_dir()) for info in z.infolist()]
                _check_strict_allowlist(items, whl.name)

                names = [item[0] for item in items]
                for expected_skill in expected_skills:
                    has_skill_md = any(expected_skill in n and "SKILL.md" in n for n in names)
                    has_ui_meta = any(expected_skill in n and "openai.yaml" in n for n in names)
                    self.assertTrue(has_skill_md, f"SKILL.md for {expected_skill} missing in wheel {whl.name}")
                    self.assertTrue(has_ui_meta, f"UI metadata openai.yaml for {expected_skill} missing in wheel {whl.name}")

        for sdist in sdists:
            with tarfile.open(sdist, "r:gz") as t:
                items = [(member.name, member.isdir()) for member in t.getmembers()]
                _check_strict_allowlist(items, sdist.name)

                names = [item[0] for item in items]
                for expected_skill in expected_skills:
                    has_skill_md = any(expected_skill in n and "SKILL.md" in n for n in names)
                    has_ui_meta = any(expected_skill in n and "openai.yaml" in n for n in names)
                    self.assertTrue(has_skill_md, f"SKILL.md for {expected_skill} missing in sdist {sdist.name}")
                    self.assertTrue(has_ui_meta, f"UI metadata openai.yaml for {expected_skill} missing in sdist {sdist.name}")

    def test_installation_target_skills(self):
        """Verify deployed files in sys.prefix match exactly if the package is installed."""
        import sys

        # When installed via wheel data_files, skills land in sys.prefix.
        deployed_skills_dir = Path(sys.prefix) / "skills"
        deployed_agents_dir = Path(sys.prefix) / ".agents" / "skills"

        # If running purely in the source repo without pip install, skip this specific check.
        # But if the coordinator runs it in the target venv as requested, it will run.
        if not deployed_skills_dir.exists() or not deployed_agents_dir.exists():
            self.skipTest("Target deployed skills not found in sys.prefix. Coordinator must install the wheel in a venv and run the test with that venv's python.")

        expected_skills = [
            "investment-orchestrator",
            "fundamental-analysis",
            "valuation",
            "fund-analysis",
            "alternative-asset-analysis",
            "personal-asset-analysis",
            "investment-report",
            "review",
        ]

        for skill in expected_skills:
            # Check original
            orig_md = deployed_skills_dir / skill / "SKILL.md"
            orig_yaml = deployed_skills_dir / skill / "agents" / "openai.yaml"
            self.assertTrue(orig_md.exists(), f"Missing deployed {orig_md}")
            self.assertTrue(orig_yaml.exists(), f"Missing deployed {orig_yaml}")

            # Check mirror
            mirror_md = deployed_agents_dir / skill / "SKILL.md"
            mirror_yaml = deployed_agents_dir / skill / "agents" / "openai.yaml"
            self.assertTrue(mirror_md.exists(), f"Missing deployed mirror {mirror_md}")
            self.assertTrue(mirror_yaml.exists(), f"Missing deployed mirror {mirror_yaml}")

            # Check byte equality
            self.assertEqual(orig_md.read_bytes(), mirror_md.read_bytes(), f"Byte mismatch for {skill} SKILL.md after deployment")
            self.assertEqual(orig_yaml.read_bytes(), mirror_yaml.read_bytes(), f"Byte mismatch for {skill} openai.yaml after deployment")

if __name__ == "__main__":
    unittest.main()
