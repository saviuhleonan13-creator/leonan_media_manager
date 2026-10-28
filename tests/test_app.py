from contextlib import closing
import sqlite3

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw

from app import create_app


def png(color="orange", shift=0):
    image = Image.new("RGB", (320, 180), "#263a43")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20 + shift, 20, 150 + shift, 150), fill=color)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.app = create_app(self.root / "project")
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {"X-App-Token": self.app.config["APP_TOKEN"]}

    def post(self, path, **kwargs):
        return self.client.post(path, headers=self.headers, **kwargs)

    def patch(self, path, data):
        return self.client.patch(path, headers=self.headers, json=data)

    def state(self):
        return self.client.get("/api/state").get_json()

    def episode_take(self, code="EP04", number=4):
        response = self.post("/api/episodes", json={"code": code, "title": "A cozinha"})
        self.assertEqual(response.status_code, 201)
        episode = response.json["id"]
        response = self.post(f"/api/episodes/{episode}/takes", json={"number": number, "title": "Caramela dá a ordem"})
        self.assertEqual(response.status_code, 201)
        return episode, response.json["id"]

    def upload(self, take, data=None, name="nome original sem take.png", version="3", kind="image"):
        return self.post(f"/api/takes/{take}/media", data={"file": (io.BytesIO(data or png()), name),
                          "version": version, "kind": kind, "label": "Caramela manda limpar a cozinha"})

    def export(self):
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 200)
        data = response.data
        response.close()
        return data

    def restore(self, data, client=None, token=None):
        return (client or self.client).post("/api/restore", headers=token or self.headers,
                                           data={"file": (io.BytesIO(data), "backup.zip")})

    def rewrite_backup(self, data, mutate=None, extra=None, corrupt=False):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(output, "w") as bundle:
            for name in original.namelist():
                content = original.read(name)
                if name == "project.json" and mutate:
                    manifest = json.loads(content)
                    mutate(manifest)
                    content = json.dumps(manifest).encode()
                elif name.startswith("media/") and corrupt:
                    content = b"corrupted media"
                bundle.writestr(name, content)
            if extra:
                bundle.writestr(*extra)
        return output.getvalue()


class MediaManagerTests(ProjectTestCase):
    def test_initial_screen_and_local_request_protection(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"LEONAN MEDIA MANAGER", page.data)
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.assertEqual(self.client.post("/api/episodes", json={"code": "BAD"}).status_code, 403)
        self.assertEqual(self.client.get("/api/state", base_url="http://attacker.example").status_code, 403)
        self.assertEqual(self.state()["episodes"], [])

    def test_original_bytes_preserved_and_real_thumbnail(self):
        _, take = self.episode_take()
        original = self.root / "meu original.png"
        original.write_bytes(png())
        before = hashlib.sha256(original.read_bytes()).hexdigest()
        response = self.upload(take, original.read_bytes())
        self.assertEqual(response.status_code, 201)
        asset = self.state()["assets"][0]
        self.assertEqual(asset["sha"], before)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
        download = self.client.get(asset["url"] + "/download")
        self.assertEqual(download.data, original.read_bytes())
        self.assertIn("attachment", download.headers["Content-Disposition"])
        thumbnail = self.client.get(asset["thumbnail_url"])
        with Image.open(io.BytesIO(thumbnail.data)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertGreater(image.width, 0)
        self.assertEqual(self.state()["takes"][0]["status"], "investigating")
        download.close()
        thumbnail.close()

    def test_versions_manual_approval_and_switch_back(self):
        _, take = self.episode_take()
        first = self.upload(take).json["id"]
        self.patch(f"/api/takes/{take}", {"status": "approved"})
        second = self.upload(take, png("green"), version="3.1").json["id"]
        state = self.state()
        self.assertEqual(state["takes"][0]["status"], "investigating")
        self.assertEqual([b["id"] for b in state["bindings"] if b["active"]], [second])
        self.assertEqual(len(state["assets"]), 2)
        self.patch(f"/api/takes/{take}", {"status": "approved"})
        self.patch(f"/api/bindings/{first}", {"active": True})
        self.assertEqual([b["id"] for b in self.state()["bindings"] if b["active"]], [first])
        self.assertEqual(self.state()["takes"][0]["status"], "investigating")

    def test_unlink_preserves_copy_and_history(self):
        _, take = self.episode_take()
        binding = self.upload(take).json["id"]
        self.patch(f"/api/bindings/{binding}", {"active": False})
        state = self.state()
        self.assertEqual(state["bindings"][0]["active"], 0)
        self.assertEqual(len(state["assets"]), 1)
        response = self.client.get(state["assets"][0]["url"])
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_identical_files_deduplicate_but_keep_original_names(self):
        _, take = self.episode_take()
        self.upload(take, name="Flow sem identificação.png")
        self.upload(take, name="cópia corrigida talvez.png")
        state = self.state()
        self.assertEqual(len(state["assets"]), 1)
        self.assertEqual(len(state["bindings"]), 2)
        self.assertEqual(state["bindings"][1]["original_name"], "cópia corrigida talvez.png")

    def test_near_images_report_heuristic_without_approving(self):
        _, take = self.episode_take()
        self.upload(take)
        self.upload(take, png(shift=2))
        self.assertEqual(len(self.state()["similarities"]), 1)
        self.assertEqual(self.state()["takes"][0]["status"], "investigating")

    def test_relink_wrong_take_and_missing_version(self):
        episode, take = self.episode_take()
        asset = self.upload(take, version="").json["asset_id"]
        other = self.post(f"/api/episodes/{episode}/takes", json={"number": 5}).json["id"]
        response = self.post(f"/api/takes/{other}/link", json={"asset_id": asset, "version": "1.3"})
        self.assertEqual(response.status_code, 201)
        state = self.state()
        self.assertEqual(state["bindings"][0]["version"], "")
        self.assertEqual(state["bindings"][1]["take_id"], other)
        self.assertEqual(state["bindings"][1]["version"], "1.3")

    def test_take_metadata_order_and_three_statuses_only(self):
        episode, take = self.episode_take()
        self.patch(f"/api/takes/{take}", {"number": 2, "prompt": "Manter câmera fixa", "notes": "Conferir continuidade", "status": "discarded"})
        self.assertEqual(self.state()["takes"][0]["prompt"], "Manter câmera fixa")
        self.assertEqual(self.state()["takes"][0]["number"], 2)
        self.assertEqual(self.patch(f"/api/takes/{take}", {"status": "pending"}).status_code, 400)
        self.assertEqual(self.post(f"/api/episodes/{episode}/takes", json={"number": 2}).status_code, 409)
        self.assertEqual(self.patch(f"/api/takes/{take}", {"number": 0}).status_code, 400)

    def test_edit_identification_requires_review(self):
        _, take = self.episode_take()
        binding = self.upload(take).json["id"]
        self.patch(f"/api/takes/{take}", {"status": "approved"})
        self.patch(f"/api/bindings/{binding}", {"version": "3.2", "label": "Correção de enquadramento"})
        self.assertEqual(self.state()["bindings"][0]["version"], "3.2")
        self.assertEqual(self.state()["takes"][0]["status"], "investigating")

    def test_invalid_media_is_not_registered(self):
        _, take = self.episode_take()
        self.assertEqual(self.upload(take, b"not a PNG").status_code, 400)
        self.assertEqual(self.upload(take, png(), kind="video").status_code, 400)
        self.assertEqual(len(self.state()["assets"]), 0)
        self.assertEqual(len(self.state()["bindings"]), 0)
        self.assertEqual(list((self.root / "project" / "media").iterdir()), [])

    def test_export_restore_portable_roundtrip_with_versions_and_status(self):
        _, take = self.episode_take()
        self.upload(take)
        self.upload(take, png("green"), name="outra versão.png", version="3.1")
        self.patch(f"/api/takes/{take}", {"status": "approved", "notes": "Conferido", "prompt": "Plano médio"})
        with closing(sqlite3.connect(self.app.config["DATA_DIR"] / "registry.sqlite3")) as db, db:
            for asset, date in zip(self.state()["assets"], ("2001-02-03 04:05:06", "2002-03-04 05:06:07")):
                db.execute("UPDATE assets SET created_at=? WHERE id=?", (date, asset["id"]))
        data = self.export()
        destination = create_app(self.root / "restored")
        client = destination.test_client()
        response = self.restore(data, client, {"X-App-Token": destination.config["APP_TOKEN"]})
        self.assertEqual(response.status_code, 200, response.data)
        original, restored = self.state(), client.get("/api/state").json
        for table in ("episodes", "takes", "assets", "bindings"):
            self.assertEqual(original[table], restored[table])
        for asset in restored["assets"]:
            response = client.get(asset["url"])
            self.assertEqual(hashlib.sha256(response.data).hexdigest(), asset["sha"])
            response.close()

    def test_restore_merges_without_overwriting_existing_episode(self):
        self.episode_take()
        data = self.export()
        self.assertEqual(self.restore(data).status_code, 200)
        self.assertEqual(self.restore(data).status_code, 200)
        codes = [ep["code"] for ep in self.state()["episodes"]]
        self.assertEqual(codes, ["EP04", "EP04 (restaurado 2)", "EP04 (restaurado 3)"])

    def test_restore_rejects_corruption_without_partial_registry(self):
        _, take = self.episode_take()
        self.upload(take)
        before = self.state()
        data = self.rewrite_backup(self.export(), corrupt=True)
        self.assertEqual(self.restore(data).status_code, 400)
        self.assertEqual(self.state(), before)

    def test_restore_rejects_traversal_and_bad_manifest(self):
        self.episode_take()
        backup = self.export()
        data = self.rewrite_backup(backup, extra=("../escaped.txt", b"bad"))
        self.assertEqual(self.restore(data).status_code, 400)
        self.assertFalse((self.root / "escaped.txt").exists())
        for mutate in [lambda m: m.update(version=99), lambda m: m["takes"][0].update(status="auto-approved"),
                       lambda m: m["takes"][0].update(episode_id=999)]:
            with self.subTest(mutate=mutate):
                self.assertEqual(self.restore(self.rewrite_backup(backup, mutate)).status_code, 400)

    def test_registry_survives_server_restart(self):
        self.episode_take()
        restarted = create_app(self.root / "project").test_client()
        self.assertEqual(restarted.get("/api/state").json["takes"], self.state()["takes"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não instalado")
    def test_real_video_thumbnail_playback_bytes_and_range(self):
        _, take = self.episode_take()
        video = self.root / "Flow output.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", str(video)], check=True)
        response = self.upload(take, video.read_bytes(), name=video.name, version="1.3", kind="video")
        self.assertEqual(response.status_code, 201, response.data)
        asset = self.state()["assets"][0]
        self.assertEqual(asset["kind"], "video")
        self.assertGreater(asset["duration"], 0)
        thumbnail = self.client.get(asset["thumbnail_url"])
        self.assertEqual(Image.open(io.BytesIO(thumbnail.data)).format, "JPEG")
        response = self.client.get(asset["url"], headers={"Range": "bytes=0-99"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, video.read_bytes()[:100])
        thumbnail.close()
        response.close()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não instalado")
    def test_pilot_is_useful_and_repeatable(self):
        response = self.post("/api/demo")
        self.assertEqual(response.status_code, 201, response.data)
        state = self.state()
        self.assertEqual(len(state["takes"]), 3)
        self.assertEqual(len([a for a in state["assets"] if a["kind"] == "video"]), 1)
        self.assertTrue(state["similarities"])
        self.assertTrue(all(t["status"] == "investigating" for t in state["takes"]))
        self.assertEqual(self.post("/api/demo").json["id"], response.json["id"])
        self.assertEqual(self.state(), state)

    def test_images_work_without_ffmpeg(self):
        _, take = self.episode_take()
        with patch("app.shutil.which", return_value=None):
            self.assertFalse(self.state()["ffmpeg_available"])
            self.assertEqual(self.upload(take).status_code, 201)

    def test_malformed_requests_return_useful_errors(self):
        _, take = self.episode_take()
        self.assertEqual(self.post("/api/episodes", json=[]).status_code, 400)
        self.assertEqual(self.patch(f"/api/takes/{take}", {"status": []}).status_code, 400)
        self.assertEqual(self.post(f"/api/takes/{take}/link", json={"asset_id": []}).status_code, 400)

    def test_backup_and_media_size_limits_are_enforced(self):
        _, take = self.episode_take()
        with patch("app.MAX_MEDIA", 10):
            self.assertEqual(self.upload(take).status_code, 400)
        self.upload(take)
        with patch("app.MAX_RESTORE", 10):
            self.assertEqual(self.client.get("/api/export").status_code, 400)


if __name__ == "__main__":
    unittest.main()
