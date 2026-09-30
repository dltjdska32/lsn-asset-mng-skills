from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.sync_agent_skills import EXPECTED_SKILLS, sync


class TestR15SkillSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        project = Path(__file__).resolve().parents[1]
        shutil.copytree(project / "skills", self.root / "skills")
        shutil.copytree(project / ".agents" / "skills", self.root / ".agents" / "skills")

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_eight_skill_mirror_inventory_passes(self):
        sync(self.root, check_only=True)
        self.assertEqual({path.name for path in (self.root / "skills").iterdir()}, set(EXPECTED_SKILLS))

    def test_sync_repairs_missing_mirror_file_and_check_does_not_repair(self):
        mirror = self.root / ".agents" / "skills" / "review" / "agents" / "openai.yaml"
        expected = mirror.read_bytes()
        mirror.unlink()
        with self.assertRaisesRegex(ValueError, "Target missing"):
            sync(self.root, check_only=True)
        self.assertFalse(mirror.exists())
        sync(self.root)
        self.assertEqual(mirror.read_bytes(), expected)
        sync(self.root, check_only=True)

    def test_unexpected_skill_directory_is_rejected_instead_of_silently_ignored(self):
        extra = self.root / ".agents" / "skills" / "unexpected"
        extra.mkdir()
        with self.assertRaisesRegex(ValueError, "Unexpected discovery skill directories"):
            sync(self.root)
        self.assertTrue(extra.exists())

    def test_unexpected_source_or_mirror_file_is_rejected(self):
        extra_source = self.root / "skills" / "review" / "credential.json"
        extra_source.write_text("synthetic", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected files under authoritative"):
            sync(self.root)
        extra_source.unlink()
        extra_mirror = self.root / ".agents" / "skills" / "review" / "cache.bin"
        extra_mirror.write_bytes(b"synthetic")
        with self.assertRaisesRegex(ValueError, "Unexpected files under discovery"):
            sync(self.root, check_only=True)


if __name__ == "__main__":
    unittest.main()
