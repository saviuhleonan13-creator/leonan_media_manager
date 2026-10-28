"""Candidate-only recovery checks: synthetic inputs, initially empty restores."""
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import zipfile

from app import create_app
from test_app import ProjectTestCase, png
from test_deletion import semantic_project


class IntegrationV03Tests(ProjectTestCase):
    def inventory(self, root):
        return {str(p.relative_to(root)): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in root.rglob('*') if p.is_file()}

    def test_full_copy_preserves_orphans_and_portable_restore_preserves_references(self):
        _, take = self.episode_take()
        self.upload(take, png('orange'), version='1')
        self.upload(take, png('blue'), version='2')
        self.patch(f'/api/takes/{take}', {'status': 'approved', 'notes': 'Synthetic recovery'})
        _, discarded = self.episode_take('SYNTHETIC', 1)
        orphan_id = self.upload(discarded, png('green')).json['asset_id']
        preview = self.client.get(f'/api/takes/{discarded}/deletion-preview').json
        response = self.client.delete(f'/api/takes/{discarded}', headers=self.headers, json={
            'confirmation_token': preview['confirmation_token'], 'confirm_code': 'SYNTHETIC',
            'confirm_number': 1, 'backup_confirmed': True})
        self.assertEqual(response.status_code, 200)
        original = self.app.config['DATA_DIR']
        before = self.inventory(original)
        expected = semantic_project(self.state())
        # No server or open connections: copy all files, including unreferenced media.
        copied = self.root / 'full-copy'
        shutil.copytree(original, copied)
        self.assertEqual(self.inventory(copied), before)
        with closing(sqlite3.connect(copied / 'registry.sqlite3')) as db, db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            sha, ext = db.execute('SELECT sha,extension FROM assets WHERE id=?', (orphan_id,)).fetchone()
        self.assertTrue((copied / 'media' / (sha + ext)).is_file())
        copied_app = create_app(copied)
        copied_client = copied_app.test_client()
        self.assertEqual(semantic_project(copied_client.get('/api/state').json), expected)
        with copied_client.get('/api/export') as export:
            backup = export.data
        with zipfile.ZipFile(io.BytesIO(backup)) as bundle:
            manifest = json.loads(bundle.read('project.json'))
            self.assertNotIn(orphan_id, [a['id'] for a in manifest['assets']])
            self.assertNotIn('media/' + sha + ext, bundle.namelist())
        restored_app = create_app(self.root / 'empty-restore')
        restored = restored_app.test_client()
        self.assertEqual(restored.get('/api/state').json['episodes'], [])
        result = self.restore(backup, restored, {'X-App-Token': restored_app.config['APP_TOKEN']})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(semantic_project(restored.get('/api/state').json), expected)
        restored_root = restored_app.config['DATA_DIR']
        for asset in restored.get('/api/state').json['assets']:
            name = asset['sha'] + asset['extension']
            self.assertEqual((restored_root / 'media' / name).stat().st_size, (original / 'media' / name).stat().st_size)
            self.assertEqual(hashlib.sha256((restored_root / 'media' / name).read_bytes()).hexdigest(), asset['sha'])
        self.assertEqual(self.inventory(original), before)
        self.assertEqual(self.inventory(copied), before)

    def test_schema_matches_frozen_v01_v02_structure(self):
        frozen = self.root / 'frozen.sqlite3'
        schema = (Path(__file__).parent / 'fixtures' / 'v01_schema.sql').read_text()
        with closing(sqlite3.connect(frozen)) as db, db:
            db.executescript(schema)
        def structure(path):
            with closing(sqlite3.connect(path)) as db, db:
                result = {}
                for table in ('episodes', 'takes', 'assets', 'bindings'):
                    result[table] = (db.execute(f'PRAGMA table_info({table})').fetchall(),
                                     db.execute(f'PRAGMA foreign_key_list({table})').fetchall(),
                                     db.execute(f'PRAGMA index_list({table})').fetchall())
                    for index in db.execute(f'PRAGMA index_list({table})').fetchall():
                        result[index[1]] = db.execute(f'PRAGMA index_info("{index[1]}")').fetchall()
                return result
        self.assertEqual(structure(frozen), structure(self.app.config['DATA_DIR'] / 'registry.sqlite3'))

    def test_invalid_archives_rejected_in_empty_destination(self):
        _, take = self.episode_take()
        self.upload(take)
        backup = self.export()
        cases = [self.rewrite_backup(backup, corrupt=True),
                 self.rewrite_backup(backup, extra=('../escaped.txt', b'synthetic'))]
        for mutate in (lambda m: m.update(version=99),
                       lambda m: m['takes'][0].update(status='auto-approved'),
                       lambda m: m['takes'][0].update(episode_id=999)):
            cases.append(self.rewrite_backup(backup, mutate))
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                destination = create_app(self.root / f'empty-invalid-{index}')
                client = destination.test_client()
                before = client.get('/api/state').json
                self.assertEqual(before['episodes'], [])
                response = self.restore(data, client, {'X-App-Token': destination.config['APP_TOKEN']})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(client.get('/api/state').json, before)
                self.assertFalse((self.root / 'escaped.txt').exists())

    def test_pre_deletion_backup_recovers_history_in_new_empty_registry(self):
        episode, take = self.episode_take()
        self.upload(take, png('orange'), version='1')
        self.upload(take, png('blue'), version='2')
        expected = semantic_project(self.state())
        backup = self.export()
        preview = self.client.get(f'/api/episodes/{episode}/deletion-preview').json
        response = self.client.delete(f'/api/episodes/{episode}', headers=self.headers, json={
            'confirmation_token': preview['confirmation_token'], 'confirm_code': 'EP04',
            'backup_confirmed': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()['episodes'], [])
        destination = create_app(self.root / 'new-empty-pre-deletion-restore')
        client = destination.test_client()
        for table in ('episodes', 'takes', 'assets', 'bindings'):
            self.assertEqual(client.get('/api/state').json[table], [])
        self.assertEqual(self.restore(backup, client, {'X-App-Token': destination.config['APP_TOKEN']}).status_code, 200)
        self.assertEqual(semantic_project(client.get('/api/state').json), expected)
        self.assertEqual(self.state()['episodes'], [])
