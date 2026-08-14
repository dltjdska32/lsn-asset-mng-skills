from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from investment_stack.evidence.paths import UnsafeRunPath, resolve_run_db_path, validate_run_id
from investment_stack.personal.paths import (
    UnsafeStoragePath,
    resolve_backup_directory,
    resolve_personal_db_path,
)


class PersonalPathResolutionTests(unittest.TestCase):
    def test_windows_default(self) -> None:
        path = resolve_personal_db_path(
            system="Windows",
            environ={"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            home=Path("C:/Users/test"),
        )
        self.assertEqual(
            path,
            Path("C:/Users/test/AppData/Local/investment-stack/personal/personal.db").resolve(),
        )

    def test_macos_default(self) -> None:
        home = Path(tempfile.gettempdir()).resolve() / "mac-home"
        path = resolve_personal_db_path(system="Darwin", environ={}, home=home)
        self.assertEqual(
            path,
            (home / "Library/Application Support/investment-stack/personal/personal.db").resolve(),
        )

    def test_linux_xdg_and_fallback(self) -> None:
        home = Path(tempfile.gettempdir()).resolve() / "linux-home"
        xdg = home / "xdg"
        self.assertEqual(
            resolve_personal_db_path(
                system="Linux", environ={"XDG_DATA_HOME": str(xdg)}, home=home
            ),
            (xdg / "investment-stack/personal/personal.db").resolve(),
        )
        self.assertEqual(
            resolve_personal_db_path(system="Linux", environ={}, home=home),
            (home / ".local/share/investment-stack/personal/personal.db").resolve(),
        )

    def test_resolution_is_lazy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = resolve_personal_db_path(root / "missing" / "personal.db")
            self.assertFalse(path.parent.exists())

    def test_override_inside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(UnsafeStoragePath):
                resolve_personal_db_path(
                    root / "personal.db", repository_root=root
                )

    def test_git_repository_is_detected_without_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / ".git").mkdir()
            with self.assertRaises(UnsafeStoragePath):
                resolve_personal_db_path(root / "nested/personal.db")

    def test_invalid_personal_paths_are_rejected(self) -> None:
        with self.assertRaises(UnsafeStoragePath):
            resolve_personal_db_path(Path("relative/personal.db"))
        with self.assertRaises(UnsafeStoragePath):
            resolve_personal_db_path(Path(tempfile.gettempdir()) / "personal.sqlite")

    def test_backup_path_uses_os_data_directory(self) -> None:
        home = Path(tempfile.gettempdir()).resolve() / "backup-home"
        path = resolve_backup_directory(system="Linux", environ={}, home=home)
        self.assertEqual(path, (home / ".local/share/investment-stack/backups").resolve())


class RunPathResolutionTests(unittest.TestCase):
    def test_run_path_is_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            path = resolve_run_db_path(workspace, "run-20260814_01")
            self.assertEqual(path, (workspace / "runs/run-20260814_01/run.db").resolve())

    def test_malicious_run_ids_are_rejected(self) -> None:
        for run_id in ("../escape", "..", ".", "a..b", "a/b", "a\\b", "", "한글"):
            with self.subTest(run_id=run_id), self.assertRaises(UnsafeRunPath):
                validate_run_id(run_id)
