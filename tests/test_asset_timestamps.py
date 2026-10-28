"""Timestamp policy: synthetic fixtures, no sleeps, restores into empty registries."""
from contextlib import closing
import hashlib
import io
import json
import sqlite3
from unittest.mock import patch
import zipfile

from app import create_app
from test_app import ProjectTestCase, png


class AssetTimestampTests(ProjectTestCase):
    def backup(self):
        _, take = self.episode_take()
        self.upload(take, png('orange'), version='1')
        self.upload(take, png('blue'), version='2')
        self.patch(f'/api/takes/{take}', {'status': 'approved', 'notes': 'Synthetic history'})
        dates = ['2001-02-03 04:05:06', '2004-02-29 23:59:59']
        with closing(sqlite3.connect(self.app.config['DATA_DIR'] / 'registry.sqlite3')) as db, db:
            for asset, date in zip(self.state()['assets'], dates):
                db.execute('UPDATE assets SET created_at=? WHERE id=?', (date, asset['id']))
        backup = self.export()
        with zipfile.ZipFile(io.BytesIO(backup)) as bundle:
            manifest = json.loads(bundle.read('project.json'))
        self.assertEqual([a['created_at'] for a in manifest['assets']], dates)
        return backup

    def empty(self, name):
        app = create_app(self.root / name)
        app.testing = True
        client = app.test_client()
        self.assertEqual(client.get('/api/state').json['episodes'], [])
        return app, client, {'X-App-Token': app.config['APP_TOKEN']}

    def clock(self, root):
        with closing(sqlite3.connect(root / 'registry.sqlite3')) as db:
            return db.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]

    def test_exact_roundtrip_preserves_old_dates_and_all_metadata(self):
        backup = self.backup()
        original = self.state()
        app, client, headers = self.empty('roundtrip')
        response = self.restore(backup, client, headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['warnings'], [])
        restored = client.get('/api/state').json
        for table in ('episodes', 'takes', 'assets', 'bindings'):
            self.assertEqual(restored[table], original[table])
        for asset in restored['assets']:
            path = app.config['DATA_DIR'] / 'media' / (asset['sha'] + asset['extension'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha'])

    def test_missing_timestamp_uses_sqlite_default_with_structured_warning(self):
        backup = self.backup()
        def remove(manifest):
            del manifest['assets'][0]['created_at']
        backup = self.rewrite_backup(backup, remove)
        app, client, headers = self.empty('missing')
        before = self.clock(app.config['DATA_DIR'])
        response = self.restore(backup, client, headers)
        after = self.clock(app.config['DATA_DIR'])
        self.assertEqual(response.status_code, 200)
        restored = client.get('/api/state').json['assets']
        self.assertLessEqual(before, restored[0]['created_at'])
        self.assertLessEqual(restored[0]['created_at'], after)
        self.assertEqual(restored[1]['created_at'], '2004-02-29 23:59:59')
        warning, = response.json['warnings']
        self.assertEqual(warning['code'], 'created_at_missing')
        self.assertEqual(warning['asset_id'], self.state()['assets'][0]['id'])
        self.assertEqual(warning['sha'], restored[0]['sha'])
        self.assertIn('não foi recuperada', warning['message'])

    def test_invalid_timestamps_rejected_before_storage_or_record_changes(self):
        backup = self.backup()
        invalid = [None, 123, True, [], {}, '', '2001-2-03 04:05:06', '2001-02-03T04:05:06',
                   '2001-02-03 04:05:06Z', ' 2001-02-03 04:05:06', '2001-02-03 04:05:06\n',
                   '2001-02-29 04:05:06', '0000-01-01 00:00:00', '2001-13-01 00:00:00',
                   '2001-01-01 24:00:00', '2001-01-01 00:60:00', '2001-01-01 00:00:60',
                   "2001-02-03 04:05:06'; DELETE FROM assets;--", 'x' * 1000]
        for index, value in enumerate(invalid):
            with self.subTest(value=value):
                data = self.rewrite_backup(backup, lambda m: m['assets'][1].update(created_at=value))
                app, client, headers = self.empty(f'invalid-{index}')
                root = app.config['DATA_DIR']
                before = (root / 'registry.sqlite3').read_bytes()
                with patch('app.publish_verified', side_effect=AssertionError('validation too late')):
                    response = self.restore(data, client, headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual((root / 'registry.sqlite3').read_bytes(), before)
                self.assertEqual(list((root / 'media').iterdir()), [])
                self.assertEqual(list((root / 'thumbs').iterdir()), [])

    def test_duplicate_sha_conflicting_or_missing_dates_rejected(self):
        backup = self.backup()
        for index, timestamp in enumerate(('2002-01-01 00:00:00', None)):
            def duplicate(manifest):
                asset = dict(manifest['assets'][0], id=999)
                if timestamp is None:
                    del asset['created_at']
                else:
                    asset['created_at'] = timestamp
                manifest['assets'].append(asset)
            with self.subTest(timestamp=timestamp):
                app, client, headers = self.empty(f'conflict-{index}')
                before = (app.config['DATA_DIR'] / 'registry.sqlite3').read_bytes()
                with patch('app.publish_verified', side_effect=AssertionError('validation too late')):
                    response = self.restore(self.rewrite_backup(backup, duplicate), client, headers)
                self.assertEqual(response.status_code, 400)
                self.assertEqual((app.config['DATA_DIR'] / 'registry.sqlite3').read_bytes(), before)

    def test_duplicate_sha_with_same_date_reuses_new_asset_without_changing_date(self):
        backup = self.backup()
        def duplicate(manifest):
            manifest['assets'].append(dict(manifest['assets'][0], id=999))
            manifest['bindings'].append(dict(manifest['bindings'][0], id=999, asset_id=999, active=0))
        app, client, headers = self.empty('agree')
        response = self.restore(self.rewrite_backup(backup, duplicate), client, headers)
        self.assertEqual(response.status_code, 200)
        state = client.get('/api/state').json
        self.assertEqual(len(state['assets']), 2)
        self.assertEqual(len(state['bindings']), 3)
        self.assertEqual(state['assets'][0]['created_at'], '2001-02-03 04:05:06')
        self.assertEqual(state['bindings'][0]['asset_id'], state['bindings'][2]['asset_id'])

    def test_normal_import_defaults_and_reimport_does_not_change_existing_date(self):
        _, take = self.episode_take()
        root = self.app.config['DATA_DIR']
        before = self.clock(root)
        self.assertEqual(self.upload(take).status_code, 201)
        after = self.clock(root)
        asset = self.state()['assets'][0]
        self.assertLessEqual(before, asset['created_at'])
        self.assertLessEqual(asset['created_at'], after)
        with closing(sqlite3.connect(root / 'registry.sqlite3')) as db, db:
            db.execute('UPDATE assets SET created_at=? WHERE id=?', ('2001-02-03 04:05:06', asset['id']))
        self.assertEqual(self.upload(take, version='2').status_code, 201)
        self.assertEqual(self.post(f'/api/takes/{take}/link', json={'asset_id': asset['id']}).status_code, 201)
        self.assertEqual(len(self.state()['assets']), 1)
        self.assertEqual(self.state()['assets'][0]['created_at'], '2001-02-03 04:05:06')

    def test_sqlite_failure_rolls_back_restored_dates_and_records(self):
        backup = self.backup()
        app, client, headers = self.empty('rollback')
        path = app.config['DATA_DIR'] / 'registry.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON bindings BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        self.assertEqual(self.restore(backup, client, headers).status_code, 503)
        with closing(sqlite3.connect(path)) as db:
            for table in ('assets', 'episodes', 'takes', 'bindings'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_future_well_formed_timestamp_preserved(self):
        backup = self.rewrite_backup(self.backup(), lambda m: m['assets'][0].update(created_at='9999-12-31 23:59:59'))
        _, client, headers = self.empty('future')
        self.assertEqual(self.restore(backup, client, headers).status_code, 200)
        self.assertEqual(client.get('/api/state').json['assets'][0]['created_at'], '9999-12-31 23:59:59')
