"""Character packs compose cleanly and each cat gets its own memory file."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "neco"))

from prompt import avatar_path, build_persona, list_characters, load_character  # noqa: E402


class CharacterTests(unittest.TestCase):
    def test_shipped_cats(self):
        self.assertEqual(set(list_characters()), {"neco", "neco-chaos", "len", "sakamoto", "luna"})

    def test_every_cat_builds_both_modes(self):
        for cat in list_characters():
            info = load_character(cat)
            for mode in ("full", "lite"):
                prompt = build_persona(owner="Sam", mode=mode, character=cat)
                self.assertIn(info["name"], prompt, (cat, mode))
                self.assertNotIn("{name}", prompt, (cat, mode))
                self.assertNotIn("Echo", prompt, (cat, mode))
                self.assertIn("Sam", prompt, (cat, mode))
            self.assertTrue(info["chat_title"].endswith(" — idle"))

    def test_unknown_cat_is_rejected(self):
        with self.assertRaises(ValueError):
            build_persona(character="garfield")

    def test_placeholder_avatar_when_none_supplied(self):
        for cat in list_characters():
            path = avatar_path(cat)
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"), cat)


class MemoryLinkTests(unittest.TestCase):
    def setUp(self):
        os.environ["NECO_CHARACTER"] = "len"
        import heartbeat  # imported late: reads the environment at import
        self.heartbeat = heartbeat
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name) / ".runtime"
        self.runtime.mkdir()
        self.legacy = self.runtime / "neco-memory.sqlite3"

    def link(self, cat):
        self.heartbeat.link_active_memory(self.runtime, self.runtime / "memory" / f"{cat}.sqlite3")

    def test_existing_database_becomes_necos(self):
        self.legacy.write_bytes(b"old records")
        self.link("neco")
        self.assertTrue(self.legacy.is_symlink())
        self.assertEqual(os.readlink(self.legacy), "memory/neco.sqlite3")
        self.assertEqual((self.runtime / "memory/neco.sqlite3").read_bytes(), b"old records")

    def test_switching_cats_keeps_each_memory(self):
        self.legacy.write_bytes(b"neco records")
        self.link("neco")
        self.link("len")
        self.assertEqual(os.readlink(self.legacy), "memory/len.sqlite3")
        self.link("neco")
        self.assertEqual(self.legacy.read_bytes(), b"neco records")


if __name__ == "__main__":
    unittest.main()


class MoodTests(unittest.TestCase):
    def test_neco_has_three_moods_and_static_cats_reuse_one(self):
        from prompt import mood_paths
        neco = mood_paths("neco")
        self.assertEqual(len(set(neco.values())), 3)
        luna = mood_paths("luna")
        self.assertEqual(len(set(luna.values())), 1)
