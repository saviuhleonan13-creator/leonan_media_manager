"""Isolated tests that never touch the real Media Manager data folder."""
import tempfile
import unittest
from pathlib import Path

from production_engine import parse_filename, preview


class TestMediaPreview(unittest.TestCase):
    def test_attachment_suffix_does_not_claim_version(self):
        self.assertIsNone(parse_filename("EP14_IMG07(1).png")["version"])

    def test_explicit_version(self):
        self.assertEqual(parse_filename("EP14_IMG05_V2.png")["version"], "V2")
        self.assertEqual(parse_filename("EP14_TAKE07_V1.4.mp4")["version"], "V1.4")

    def test_flow_filename_not_guessed(self):
        self.assertIsNone(parse_filename("Caramelo_asks_about_free_bag.mp4"))

    def test_no_writes_and_conflict_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("EP14_IMG05.png", "EP14_IMG05_V2.png",
                         "EP14_TAKE05.mp4", "EP14_IMG07.png",
                         "Flow_random.mp4", "EP15_IMG01.png"):
                (root / name).write_bytes(b"content")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = preview(root, "EP14", 7)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual(result["mode"], "READ_ONLY_PREVIEW")
            self.assertIn("Flow_random.mp4", result["unmatched_media"])
            self.assertEqual(len(result["takes"][4]["images"]), 2)
            self.assertTrue(any("Multiplas" in w for w in result["takes"][4]["warnings"]))
            self.assertEqual(len(result["takes"][6]["videos"]), 0)

    def test_invalid_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                preview(Path(directory), "wrong")


if __name__ == "__main__":
    unittest.main()
