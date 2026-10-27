"""Isolated tests that never touch the real Media Manager data folder."""
import json
import os
import subprocess
import sys
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

from production_engine import parse_filename, preview, is_link


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
            self.assertTrue(any("Múltiplos" in w for w in result["takes"][4]["warnings"]))
            self.assertEqual(len(result["takes"][6]["videos"]), 0)

    def test_invalid_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                preview(Path(directory), "wrong")


    def test_complete_take_numbers_and_episode_sizes(self):
        with tempfile.TemporaryDirectory(prefix="Conferência com espaços ") as directory:
            root = Path(directory)
            for n in (1, 8, 9, 10, 80):
                name = f"EP14_IMG{n:02d}.png"
                (root / name).write_bytes(b"synthetic")
                self.assertEqual(parse_filename(name)["take"], n)
            for count in (7, 8):
                result = preview(root, "EP14", count)
                self.assertEqual(len(result["takes"]), count)
                self.assertEqual(len(result["takes"][0]["images"]), 1)
                for n in (9, 10, 80):
                    self.assertIn(f"EP14_IMG{n:02d}.png", result["unmatched_media"])
                self.assertEqual("EP14_IMG08.png" in result["unmatched_media"], count == 7)

    def test_versions_and_ambiguity(self):
        for version in ("V1", "V2", "V10", "V1.4"):
            self.assertEqual(parse_filename(f"EP14_IMG01_{version}.png")["version"], version)
        for tail in ("_V1_V2", "_V1.2.3", "_V", "V2", "_V2final", "_final", "_V1-V10"):
            result = parse_filename(f"EP14_IMG01{tail}.png")
            self.assertIsNone(result["version"], tail)
            self.assertTrue(result["warnings"], tail)
        for suffix in ("(1)", " (2)", "(10)"):
            result = parse_filename(f"EP14_IMG01{suffix}.png")
            self.assertIsNone(result["version"])
            self.assertTrue(result["warnings"])
        self.assertEqual(parse_filename("EP14_IMG01_V10 (2).png")["version"], "V10")

    def test_exclusions_other_episodes_and_invalid_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ("EP14_IMG01.png.png", "EP14_IMG02.JPG.png", "EP14_IMG00.png",
                     "EP14_TAKE02.png", "random.mp4", "EP15_IMG01_V2.png", "EP14_IMG01_V1.png")
            for name in names:
                (root / name).write_bytes(b"synthetic")
            result = preview(root, "EP14")
            self.assertEqual(set(result["unmatched_media"]), set(names[:5]))
            self.assertIn("duplicadas", next(item["reason"] for item in result["excluded_media"] if item["filename"] == "EP14_IMG01.png.png"))
            self.assertEqual(result["other_episode_media"][0]["episode"], "EP15")
            self.assertEqual(len(result["takes"][0]["images"]), 1)

    def test_snapshot_reproducibility_and_no_content_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("EP14_IMG01.png", "ep14_img01.PNG", "notes.txt"):
                (root / name).write_bytes(b"synthetic")
            def snapshot():
                return {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in root.iterdir()}
            before = snapshot()
            with patch("builtins.open", side_effect=AssertionError("content opened")), patch.object(Path, "open", side_effect=AssertionError("content opened")):
                first = preview(root, "EP14")
                second = preview(root, "EP14")
            self.assertEqual(first, second)
            self.assertEqual(before, snapshot())

    def test_missing_non_directory_and_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "inexistente"):
                preview(root / "missing", "EP14")
            file = root / "file"
            file.write_bytes(b"synthetic")
            with self.assertRaisesRegex(ValueError, "não é uma pasta"):
                preview(file, "EP14")
            with patch("production_engine.os.scandir", side_effect=PermissionError):
                with self.assertRaisesRegex(ValueError, "Acesso negado"):
                    preview(root, "EP14")
            with patch("production_engine.os.scandir", side_effect=OSError):
                with self.assertRaisesRegex(ValueError, "Não foi possível"):
                    preview(root, "EP14")

    def test_symlinks_and_ancestors_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            outside = root / "outside"
            source.mkdir()
            outside.mkdir()
            (outside / "EP14_IMG01.png").write_bytes(b"synthetic")
            try:
                (source / "EP14_IMG01.png").symlink_to(outside / "EP14_IMG01.png")
                (source / "linked").symlink_to(outside, target_is_directory=True)
                (root / "alias").symlink_to(source, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Links não disponíveis: {exc}")
            result = preview(source, "EP14")
            self.assertEqual(len(result["ignored_entries"]), 2)
            self.assertFalse(result["takes"][0]["images"])
            for path in (root / "alias", source / "linked", root / "alias" / "linked"):
                with self.assertRaisesRegex(ValueError, "links ou junções"):
                    preview(path, "EP14")

    def test_windows_reparse_metadata(self):
        from types import SimpleNamespace
        self.assertTrue(is_link(SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)))
        self.assertFalse(is_link(SimpleNamespace(st_mode=0o100644, st_file_attributes=0x20)))

    def test_cli_text_json_and_error(self):
        script = Path(__file__).resolve().parents[1] / "production_engine.py"
        with tempfile.TemporaryDirectory(prefix="Teste São Paulo ") as directory:
            root = Path(directory)
            (root / "EP14_IMG10.png").write_bytes(b"synthetic")
            base = [sys.executable, "-B", str(script), "--source", str(root), "--episode", "EP14"]
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            def run(args):
                return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)
            text_result = run(base)
            self.assertEqual(text_result.returncode, 0)
            self.assertIn("SOMENTE LEITURA", text_result.stdout)
            self.assertIn("TAKE 10 fora", text_result.stdout)
            json_result = run(base + ["--format", "json"])
            self.assertEqual(json_result.returncode, 0)
            self.assertEqual(json.loads(json_result.stdout)["unmatched_media"], ["EP14_IMG10.png"])
            error = run(base + ["--source", str(root / "missing")])
            self.assertEqual(error.returncode, 2)
            self.assertIn("inexistente", error.stderr)
            self.assertNotIn("Traceback", error.stderr)
            self.assertEqual([p.name for p in root.iterdir()], ["EP14_IMG10.png"])


if __name__ == "__main__":
    unittest.main()
