from __future__ import annotations

import io
import json
import subprocess
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from investment_stack.cli import main
from investment_stack.invariants import EXPECTED_SKILLS, validate_runtime_invariants


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CliIntegrationTest(unittest.TestCase):
    def capture(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_route_returns_mode_and_fixed_pipeline(self) -> None:
        code, payload = self.capture(["route", "FANUC 분석해", "--json"])
        self.assertEqual(0, code)
        self.assertEqual("SINGLE_ASSET_ANALYSIS", payload["mode"])
        self.assertEqual("auto_pass_requested_assets", payload["pipeline"][0])

    def test_project_invariants_pass(self) -> None:
        results = validate_runtime_invariants(PROJECT_ROOT)
        self.assertTrue(all(result.passed for result in results), results)
        self.assertEqual(8, len(EXPECTED_SKILLS))

    def test_check_command_is_machine_readable(self) -> None:
        code, payload = self.capture(
            ["check", "--project-root", str(PROJECT_ROOT), "--json"]
        )
        self.assertEqual(0, code)
        self.assertTrue(payload["passed"])

    def test_package_metadata_uses_proprietary_spdx_license_reference(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
            project = tomllib.load(file)["project"]
        self.assertEqual("LicenseRef-Proprietary", project["license"])

    def test_sensitive_runtime_paths_are_ignored_without_hiding_env_example(self) -> None:
        ignored = (
            ".env",
            ".env.local",
            "personal.db",
            "personal.db-wal",
            "personal.db-shm",
            "test.sqlite",
            "backup/personal.db.bak",
            "backups/personal.zip",
            "exports/portfolio.csv",
            "workspace/runs/run-1/run.db",
            "tests/tmp/test-ledger.sqlite",
        )
        for path in ignored:
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "-q", "--", path],
                    cwd=PROJECT_ROOT,
                    check=False,
                )
                self.assertEqual(0, result.returncode)

        env_example = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".env.example"],
            cwd=PROJECT_ROOT,
            check=False,
        )
        self.assertEqual(1, env_example.returncode)


if __name__ == "__main__":
    unittest.main()
