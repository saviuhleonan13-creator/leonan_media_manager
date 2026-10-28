"""Compatibility checks use a frozen V0.1 schema and synthetic files only."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

from PIL import Image

from app import create_app
from test_app import ProjectTestCase, png


class MigrationTests(ProjectTestCase):
    def make_v01_registry(self):
        old = self.root / "V0.1 sintética"
        (old / "media").mkdir(parents=True)
        (old / "thumbs").mkdir()
        content = png()
        sha = hashlib.sha256(content).hexdigest()
        (old / "media" / (sha + ".png")).write_bytes(content)
        with Image.open(io.BytesIO(content)) as image:
            image.convert("RGB").save(old / "thumbs" / (sha + ".jpg"))
        schema = (Path(__file__).parent / "fixtures" / "v01_schema.sql").read_text()
        with closing(sqlite3.connect(old / "registry.sqlite3")) as db, db:
            db.executescript(schema)
            db.execute("INSERT INTO episodes(id,code,title) VALUES(7,'EP04','Acervo sintético V0.1')")
            db.execute("INSERT INTO takes(id,episode_id,number,title,prompt,notes,status) VALUES(11,7,4,'Cena sintética','Prompt sintético','Observação sintética','approved')")
            db.execute("INSERT INTO assets(id,sha,kind,original_name,extension,dhash,width,height) VALUES(19,?,'image','Imagem V0.1.png','.png','0000000000000000',320,180)", (sha,))
            db.execute("INSERT INTO bindings(id,take_id,asset_id,kind,version,label,original_name,active) VALUES(23,11,19,'image','1','Histórico','Imagem V0.1.png',0)")
            db.execute("INSERT INTO bindings(id,take_id,asset_id,kind,version,label,original_name,active) VALUES(24,11,19,'image','3.1','Em uso','Imagem V0.1.png',1)")
        return old

    def fingerprints(self, root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()}

    def rows(self, root):
        with closing(sqlite3.connect(root / "registry.sqlite3")) as db, db:
            db.row_factory = sqlite3.Row
            return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
                    for table in ("episodes", "takes", "bindings", "assets")}

    def test_copy_whole_v01_data_to_new_folder_preserves_every_record_and_media(self):
        original = self.make_v01_registry()
        before = self.fingerprints(original)
        expected = self.rows(original)
        copied = self.root / "V0.2 teste" / "data"
        shutil.copytree(original, copied)
        app = create_app(copied)
        client = app.test_client()
        state = client.get("/api/state").json
        for table in ("episodes", "takes", "bindings"):
            self.assertEqual(state[table], expected[table])
        self.assertEqual(self.rows(copied), expected)
        self.assertEqual(self.fingerprints(copied), before)
        self.assertEqual(self.fingerprints(original), before)
        export = client.get("/api/export")
        restored_app = create_app(self.root / "restauração vazia")
        restored = restored_app.test_client()
        response = self.restore(export.data, restored, {"X-App-Token": restored_app.config["APP_TOKEN"]})
        self.assertEqual(response.status_code, 200, response.data)
        restored_state = restored.get("/api/state").json
        self.assertEqual(restored_state["episodes"][0]["code"], "EP04")
        self.assertEqual(restored_state["takes"][0]["number"], 4)
        self.assertEqual(restored_state["takes"][0]["status"], "approved")
        self.assertEqual([b["version"] for b in restored_state["bindings"]], ["1", "3.1"])
        self.assertEqual(self.fingerprints(original), before)
        export.close()

    def test_v01_backup_format_restores_without_schema_conversion(self):
        original = self.make_v01_registry()
        manifest = self.rows(original)
        manifest.update(format="leonan-media-manager", version=1)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("project.json", json.dumps(manifest))
            for asset in manifest["assets"]:
                name = asset["sha"] + asset["extension"]
                bundle.writestr("media/" + name, (original / "media" / name).read_bytes())
        before = self.fingerprints(original)
        self.assertEqual(self.restore(buffer.getvalue()).status_code, 200)
        state = self.state()
        self.assertEqual(state["takes"][0]["status"], "approved")
        self.assertEqual([b["active"] for b in state["bindings"]], [0, 1])
        self.assertEqual(self.fingerprints(original), before)
