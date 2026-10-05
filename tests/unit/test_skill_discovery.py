from __future__ import annotations

import unittest
from pathlib import Path

from investment_stack.invariants import EXPECTED_SKILLS, validate_runtime_invariants


ROOT = Path(__file__).resolve().parents[2]


class SkillDiscoveryTests(unittest.TestCase):
    def test_exactly_eight_discovery_skills_match_authoritative_source(self) -> None:
        discovered = {
            path.name
            for path in (ROOT / ".agents" / "skills").iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        self.assertEqual(discovered, set(EXPECTED_SKILLS))
        for name in EXPECTED_SKILLS:
            source = ROOT / "skills" / name / "SKILL.md"
            target = ROOT / ".agents" / "skills" / name / "SKILL.md"
            self.assertEqual(target.read_bytes(), source.read_bytes(), name)
            text = target.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), name)
            frontmatter = text.split("---", 2)[1]
            self.assertIn(f"name: {name}", frontmatter)
            self.assertIn("description:", frontmatter)

    def test_invariants_report_discovery_and_mirror_checks(self) -> None:
        results = {result.name: result for result in validate_runtime_invariants(ROOT)}
        self.assertTrue(results["exactly_eight_repo_local_discovery_skills"].passed)
        self.assertTrue(results["repo_local_discovery_mirrors_authoritative_skills"].passed)


if __name__ == "__main__":
    unittest.main()
