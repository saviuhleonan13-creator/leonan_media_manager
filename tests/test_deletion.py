"""All fixtures are synthetic and isolated; never open an operator's data directory."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import time
from unittest.mock import patch
import unittest
import zipfile

from app import create_app
from test_app import ProjectTestCase, png


def semantic_project(state):
    assets = {a["id"]: a for a in state["assets"]}
    episodes = []
    for episode in state["episodes"]:
        takes = []
        for take in state["takes"]:
            if take["episode_id"] != episode["id"]:
                continue
            bindings = sorted((assets[b["asset_id"]]["sha"], b["kind"], b["version"], b["label"],
                               b["original_name"], b["active"]) for b in state["bindings"] if b["take_id"] == take["id"])
            takes.append((take["number"], take["title"], take["prompt"], take["notes"], take["status"], bindings))
        episodes.append((episode["code"], episode["title"], sorted(takes)))
    return sorted(episodes)


class DeletionTests(ProjectTestCase):
    def preview(self, kind, row_id):
        response = self.client.get(f"/api/{kind}/{row_id}/deletion-preview")
        self.assertEqual(response.status_code, 200, response.data)
        return response.json

    def confirmation(self, kind, row_id):
        preview = self.preview(kind, row_id)
        data = {"confirmation_token": preview["confirmation_token"], "confirm_code": preview["episode"]["code"],
                "backup_confirmed": True}
        if kind == "takes":
            data["confirm_number"] = preview["take"]["number"]
        return data

    def delete(self, kind, row_id, data=None):
        return self.client.delete(f"/api/{kind}/{row_id}", headers=self.headers,
                                  json=data if data is not None else self.confirmation(kind, row_id))

    def raw_database(self):
        with sqlite3.connect(self.root / "project" / "registry.sqlite3") as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                    for table in ("episodes", "takes", "bindings", "assets")}

    def media_bytes(self):
        root = self.root / "project"
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for directory in ("media", "thumbs") for path in (root / directory).iterdir()}

    def test_episode_removal_preserves_other_episode_and_all_local_files(self):
        pilot, pilot_take = self.episode_take("PILOTO", 1)
        self.upload(pilot_take, png("blue"), name="piloto sintético.png")
        ep04, take04 = self.episode_take()
        self.upload(take04, png("green"), name="EP04 sintético.png")
        self.patch(f"/api/takes/{take04}", {"status": "approved", "notes": "Teste sintético"})
        before = self.state()
        files = self.media_bytes()
        preview = self.preview("episodes", pilot)
        self.assertEqual((preview["take_count"], preview["image_count"], preview["video_count"]), (1, 1, 0))
        self.assertEqual(preview["episode"]["code"], "PILOTO")
        self.assertEqual(self.delete("episodes", pilot).status_code, 200)
        after = self.state()
        self.assertEqual([e["id"] for e in after["episodes"]], [ep04])
        self.assertEqual(after["takes"], [t for t in before["takes"] if t["id"] == take04])
        self.assertEqual(after["bindings"], [b for b in before["bindings"] if b["take_id"] == take04])
        self.assertEqual(len(after["assets"]), 1)
        self.assertEqual(files, self.media_bytes())
        self.assertTrue((self.root / "project" / "registry.sqlite3").is_file())
        self.assertEqual(len(self.raw_database()["assets"]), 2)

    def test_delete_one_take_preserves_numbers_status_history_and_versions(self):
        episode, first = self.episode_take(number=4)
        second = self.post(f"/api/episodes/{episode}/takes", json={"number": 8, "title": "Outro take"}).json["id"]
        self.upload(first)
        self.upload(second, png("blue"), version="1")
        self.upload(second, png("green"), version="2")
        self.patch(f"/api/takes/{second}", {"status": "approved", "prompt": "Prompt sintético"})
        before = self.state()
        self.assertEqual(self.delete("takes", first).status_code, 200)
        after = self.state()
        self.assertEqual(after["takes"], [t for t in before["takes"] if t["id"] == second])
        self.assertEqual(after["bindings"], [b for b in before["bindings"] if b["take_id"] == second])
        self.assertEqual(after["takes"][0]["number"], 8)
        first_version = next(b for b in after["bindings"] if b["version"] == "1")
        self.assertEqual(self.patch(f"/api/bindings/{first_version['id']}", {"active": True}).status_code, 200)
        self.assertEqual(len(self.state()["bindings"]), 2)
        self.raw_database()

    def test_shared_image_remains_even_when_only_historical_reference_survives(self):
        pilot, first = self.episode_take("PILOTO", 1)
        shared = self.upload(first).json["asset_id"]
        _, second = self.episode_take()
        linked = self.post(f"/api/takes/{second}/link", json={"asset_id": shared, "version": "1"}).json["id"]
        self.upload(second, png("green"), version="2")
        self.assertEqual(self.delete("episodes", pilot).status_code, 200)
        state = self.state()
        self.assertIn(shared, [a["id"] for a in state["assets"]])
        self.assertEqual(self.patch(f"/api/bindings/{linked}", {"active": True}).status_code, 200)
        response = self.client.get(f"/media/{shared}")
        self.assertEqual(response.data, png())
        response.close()

    def test_shared_image_survives_take_deletion(self):
        episode, first = self.episode_take()
        second = self.post(f"/api/episodes/{episode}/takes", json={"number": 7}).json["id"]
        shared = self.upload(first).json["asset_id"]
        self.post(f"/api/takes/{second}/link", json={"asset_id": shared, "version": "3"})
        self.assertEqual(self.delete("takes", first).status_code, 200)
        self.assertEqual([b["asset_id"] for b in self.state()["bindings"]], [shared])
        self.assertEqual([a["id"] for a in self.state()["assets"]], [shared])

    def test_orphans_are_hidden_from_library_similarity_and_export_not_physically_deleted(self):
        pilot, first = self.episode_take("PILOTO", 1)
        orphan = self.upload(first).json["asset_id"]
        _, second = self.episode_take()
        self.upload(second, png(shift=2))
        self.assertTrue(self.state()["similarities"])
        files = self.media_bytes()
        self.assertEqual(self.delete("episodes", pilot).status_code, 200)
        self.assertEqual(self.state()["similarities"], [])
        self.assertNotIn(orphan, [a["id"] for a in self.state()["assets"]])
        self.assertEqual(self.post(f"/api/takes/{second}/link", json={"asset_id": orphan}).status_code, 400)
        with zipfile.ZipFile(io.BytesIO(self.export())) as bundle:
            manifest = json.loads(bundle.read("project.json"))
            self.assertEqual(len(manifest["assets"]), 1)
            self.assertEqual(len(bundle.namelist()), 2)
        self.assertEqual(files, self.media_bytes())
        self.assertEqual(len(self.raw_database()["assets"]), 2)

    def test_original_operator_file_not_modified_by_deletion(self):
        original = self.root / "original fora do acervo.png"
        original.write_bytes(png())
        before = original.read_bytes()
        episode, take = self.episode_take()
        self.upload(take, original.read_bytes())
        self.delete("episodes", episode)
        self.assertEqual(original.read_bytes(), before)

    def test_preview_and_cancel_make_no_changes(self):
        episode, take = self.episode_take()
        self.upload(take)
        before, files = self.raw_database(), self.media_bytes()
        self.preview("episodes", episode)
        self.preview("takes", take)
        self.assertEqual(before, self.raw_database())
        self.assertEqual(files, self.media_bytes())

    def test_explicit_code_backup_and_take_identity_required(self):
        episode, take = self.episode_take()
        before = self.raw_database()
        for kind, row_id in (("episodes", episode), ("takes", take)):
            data = self.confirmation(kind, row_id)
            for bad in ({**data, "confirm_code": "WRONG"}, {**data, "backup_confirmed": False},
                        {**data, "backup_confirmed": "true"}, {**data, "confirmation_token": "bad"}, {}):
                self.assertEqual(self.delete(kind, row_id, bad).status_code, 400)
                self.assertEqual(before, self.raw_database())
        data = self.confirmation("takes", take)
        self.assertEqual(self.delete("takes", take, {**data, "confirm_number": 5}).status_code, 400)

    def test_csrf_invalid_identifiers_and_wrong_target(self):
        episode, take = self.episode_take()
        for path in ("/api/episodes/999/deletion-preview", "/api/takes/999/deletion-preview", "/api/takes/nope"):
            self.assertEqual(self.client.get(path).status_code, 404)
        data = self.confirmation("episodes", episode)
        self.assertEqual(self.client.delete(f"/api/episodes/{episode}", json=data).status_code, 403)
        self.assertEqual(self.delete("episodes", 999, data).status_code, 400)
        self.assertEqual(self.delete("takes", take, data).status_code, 400)
        self.assertEqual(len(self.state()["takes"]), 1)

    def test_repeat_request_cannot_delete_recreated_id(self):
        episode, _ = self.episode_take()
        data = self.confirmation("episodes", episode)
        self.assertEqual(self.delete("episodes", episode, data).status_code, 200)
        self.assertEqual(self.delete("episodes", episode, data).status_code, 409)
        recreated, _ = self.episode_take()
        self.assertEqual(recreated, episode)  # SQLite may reuse a deleted maximum ROWID.
        self.assertEqual(self.delete("episodes", recreated, data).status_code, 409)
        self.assertEqual(len(self.state()["takes"]), 1)

    def test_all_outstanding_previews_are_invalidated_when_parent_is_deleted(self):
        episode, take = self.episode_take()
        first = self.confirmation("episodes", episode)
        other = self.confirmation("episodes", episode)
        take_review = self.confirmation("takes", take)
        self.delete("episodes", episode, first)
        recreated, recreated_take = self.episode_take()
        self.assertEqual((recreated, recreated_take), (episode, take))
        self.assertEqual(self.delete("episodes", recreated, other).status_code, 409)
        self.assertEqual(self.delete("takes", recreated_take, take_review).status_code, 409)
        self.assertEqual(len(self.state()["takes"]), 1)

    def test_changed_take_or_episode_requires_fresh_review(self):
        episode, take = self.episode_take()
        take_data = self.confirmation("takes", take)
        episode_data = self.confirmation("episodes", episode)
        self.upload(take)
        self.assertEqual(self.delete("takes", take, take_data).status_code, 409)
        self.assertEqual(self.delete("episodes", episode, episode_data).status_code, 409)
        self.assertEqual(self.delete("takes", take).status_code, 200)

    def test_expired_confirmation_does_not_delete(self):
        episode, _ = self.episode_take()
        data = self.confirmation("episodes", episode)
        later = int(time.time()) + 700
        with patch("itsdangerous.timed.TimestampSigner.get_timestamp", return_value=later):
            self.assertEqual(self.delete("episodes", episode, data).status_code, 400)
        self.assertEqual(len(self.state()["episodes"]), 1)

    def test_mid_transaction_error_rolls_back_all_bindings_and_takes(self):
        episode, take = self.episode_take()
        self.upload(take)
        before, files = self.raw_database(), self.media_bytes()
        data = self.confirmation("episodes", episode)
        with sqlite3.connect(self.root / "project" / "registry.sqlite3") as db:
            db.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON takes BEGIN SELECT RAISE(ABORT, 'test'); END")
        self.assertEqual(self.delete("episodes", episode, data).status_code, 503)
        self.assertEqual(before, self.raw_database())
        self.assertEqual(files, self.media_bytes())
        with sqlite3.connect(self.root / "project" / "registry.sqlite3") as db:
            db.execute("DROP TRIGGER reject_delete")
        self.assertEqual(self.delete("episodes", episode, data).status_code, 200)

    def test_commit_error_does_not_consume_confirmation_or_leave_partial_deletion(self):
        episode, take = self.episode_take()
        self.upload(take)
        data = self.confirmation("episodes", episode)
        before = self.raw_database()
        real_connect = sqlite3.connect

        class RejectCommit(sqlite3.Connection):
            def __exit__(self, *args):
                self.rollback()
                raise sqlite3.OperationalError("simulated commit failure")

        def fail_commit(database, timeout):
            return real_connect(database, timeout=timeout, factory=RejectCommit)

        with patch("app.sqlite3.connect", side_effect=fail_commit):
            self.assertEqual(self.delete("episodes", episode, data).status_code, 503)
        self.assertEqual(before, self.raw_database())
        self.assertEqual(self.delete("episodes", episode, data).status_code, 200)

    def test_database_unavailable_returns_error_without_success(self):
        episode, _ = self.episode_take()
        data = self.confirmation("episodes", episode)
        before = self.raw_database()
        with patch("app.sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")):
            response = self.delete("episodes", episode, data)
            self.assertEqual(response.status_code, 503)
            self.assertIn("não confirmou", response.json["error"])
        self.assertEqual(before, self.raw_database())

    def test_last_take_and_empty_episode_can_be_deleted_independently(self):
        episode, take = self.episode_take()
        self.assertEqual(self.delete("takes", take).status_code, 200)
        self.assertEqual(len(self.state()["episodes"]), 1)
        self.assertEqual(self.state()["takes"], [])
        self.assertEqual(self.preview("episodes", episode)["take_count"], 0)
        self.assertEqual(self.delete("episodes", episode).status_code, 200)
        self.assertEqual(self.state()["episodes"], [])

    def test_export_restore_after_deletion_preserves_remaining_semantics(self):
        pilot, pilot_take = self.episode_take("PILOTO", 1)
        self.upload(pilot_take)
        _, take = self.episode_take()
        self.upload(take, png("blue"), version="1")
        self.upload(take, png("green"), version="3.2")
        self.patch(f"/api/takes/{take}", {"status": "approved", "notes": "Sintético"})
        self.delete("episodes", pilot)
        restored_app = create_app(self.root / "empty-restored")
        restored = restored_app.test_client()
        response = self.restore(self.export(), restored, {"X-App-Token": restored_app.config["APP_TOKEN"]})
        self.assertEqual(response.status_code, 200, response.data)
        state = restored.get("/api/state").json
        self.assertEqual(semantic_project(state), semantic_project(self.state()))
        for asset in state["assets"]:
            download = restored.get(asset["url"])
            self.assertEqual(hashlib.sha256(download.data).hexdigest(), asset["sha"])
            download.close()
            thumbnail = restored.get(asset["thumbnail_url"])
            self.assertEqual(thumbnail.status_code, 200)
            thumbnail.close()

    def test_pre_deletion_backup_can_restore_removed_history(self):
        episode, take = self.episode_take()
        self.upload(take, version="1.3")
        before = semantic_project(self.state())
        backup = self.export()
        self.delete("episodes", episode)
        self.assertEqual(self.restore(backup).status_code, 200)
        self.assertEqual(semantic_project(self.state()), before)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg não instalado")
    def test_delete_actual_synthetic_pilot_preserves_shared_video_and_thumbnail(self):
        pilot = self.post("/api/demo").json["id"]
        video = next(a for a in self.state()["assets"] if a["kind"] == "video")
        _, ep04_take = self.episode_take()
        self.post(f"/api/takes/{ep04_take}/link", json={"asset_id": video["id"], "version": "1.3"})
        preview = self.preview("episodes", pilot)
        self.assertEqual((preview["take_count"], preview["image_count"], preview["video_count"], preview["binding_count"]), (3, 3, 1, 4))
        files = self.media_bytes()
        self.assertEqual(self.delete("episodes", pilot).status_code, 200)
        self.assertEqual(self.media_bytes(), files)
        response = self.client.get(video["url"], headers={"Range": "bytes=0-99"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.data), 100)
        response.close()
        thumbnail = self.client.get(video["thumbnail_url"])
        self.assertEqual(thumbnail.status_code, 200)
        thumbnail.close()
        self.raw_database()


if __name__ == "__main__":
    unittest.main()
