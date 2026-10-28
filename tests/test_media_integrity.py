"""Failure injection uses synthetic media and temporary registries only."""
from contextlib import closing

import errno
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import app as module
from app import MediaStorageError, create_app, publish_verified, verify_file
from test_app import ProjectTestCase, png


class MediaIntegrityTests(ProjectTestCase):
    def paths(self):
        source = self.root / 'synthetic.bin'
        source.write_bytes(b'synthetic bytes' * 100)
        return source, self.root / 'destination.bin'

    def publish(self, source, target):
        publish_verified(source, target, hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size)

    def database(self, root=None):
        # sqlite3 context manages commit/rollback; closing releases Windows handles.
        with closing(sqlite3.connect((root or self.app.config['DATA_DIR']) / 'registry.sqlite3')) as db, db:
            db.row_factory = sqlite3.Row
            return {table: [{k: row[k] for k in row.keys()}
                            for row in db.execute('SELECT * FROM ' + table + ' ORDER BY id')]
                    for table in ('episodes', 'takes', 'assets', 'bindings')}

    def test_complete_and_existing_correct_and_wrong_reference(self):
        source, target = self.paths()
        self.publish(source, target)
        before = target.stat().st_mtime_ns
        self.publish(source, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(target.stat().st_mtime_ns, before)
        with self.assertRaises(MediaStorageError):
            publish_verified(source, target, '0' * 64, source.stat().st_size)
        with self.assertRaises(MediaStorageError):
            publish_verified(source, target, hashlib.sha256(source.read_bytes()).hexdigest(), 1)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_existing_divergent_never_overwritten(self):
        source, target = self.paths()
        target.write_bytes(b'preexisting')
        with self.assertRaises(MediaStorageError):
            self.publish(source, target)
        self.assertEqual(target.read_bytes(), b'preexisting')

    def test_partial_write_disk_full_permission_and_retry(self):
        source, target = self.paths()
        for code in (errno.ENOSPC, errno.EACCES, errno.EIO):
            def fail(incoming, output):
                output.write(b'partial')
                raise OSError(code, 'synthetic failure')
            with self.subTest(code=code), patch('app.shutil.copyfileobj', side_effect=fail):
                with self.assertRaises(MediaStorageError):
                    self.publish(source, target)
            self.assertFalse(target.exists())
        self.publish(source, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_link_failure_no_fallback(self):
        source, target = self.paths()
        with patch('app.os.link', side_effect=PermissionError('synthetic')):
            with self.assertRaises(MediaStorageError):
                self.publish(source, target)
        self.assertFalse(target.exists())

    def test_corrupt_staging_and_fsync_failure(self):
        source, target = self.paths()
        with patch('app.shutil.copyfileobj', side_effect=lambda i, o: o.write(b'wrong')):
            with self.assertRaises(MediaStorageError):
                self.publish(source, target)
        self.assertFalse(target.exists())
        with patch('app.os.fsync', side_effect=OSError('synthetic')):
            with self.assertRaises(MediaStorageError):
                self.publish(source, target)
        self.assertFalse(target.exists())

    def test_concurrent_publish_same_content(self):
        source, target = self.paths()
        barrier = threading.Barrier(2)
        original_link = os.link
        def simultaneous(a, b):
            barrier.wait(timeout=10)
            original_link(a, b)
        with patch('app.os.link', side_effect=simultaneous), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.publish, source, target) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_concurrent_conflicting_content(self):
        source, target = self.paths()
        other = self.root / 'other.bin'
        other.write_bytes(b'different synthetic bytes')
        barrier = threading.Barrier(2)
        original_link = os.link
        def simultaneous(a, b):
            barrier.wait(timeout=10)
            original_link(a, b)
        with patch('app.os.link', side_effect=simultaneous), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.publish, s, target) for s in (source, other)]
            errors = [f.exception(timeout=15) for f in futures]
        self.assertEqual(sum(e is None for e in errors), 1)
        self.assertEqual(sum(isinstance(e, MediaStorageError) for e in errors), 1)
        self.assertIn(target.read_bytes(), (source.read_bytes(), other.read_bytes()))

    def test_process_interrupted_during_write_then_retry(self):
        source, target = self.paths()
        script = '''import os, sys
from pathlib import Path
import app
source, target = map(Path, sys.argv[1:])
def interrupted(i, o):
    o.write(b'partial'); o.flush(); os.fsync(o.fileno()); os._exit(73)
app.shutil.copyfileobj = interrupted
app.publish_verified(source, target, '0'*64, source.stat().st_size)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(source), str(target)],
                                cwd=Path(module.__file__).parent, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertFalse(target.exists())
        residue = list(self.root.glob('.leonan-copy-*'))
        self.assertEqual(len(residue), 1)
        self.publish(source, target)
        self.assertTrue(residue[0].exists())  # no automatic orphan cleanup
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_registered_missing_and_corrupt_reuse_preserves_database(self):
        _, take = self.episode_take()
        response = self.upload(take)
        asset = self.state()['assets'][0]
        target = self.app.config['DATA_DIR'] / 'media' / (asset['sha'] + asset['extension'])
        before = self.database()
        target.write_bytes(b'corrupt synthetic fixture')
        self.assertEqual(self.upload(take).status_code, 503)
        self.assertEqual(self.post(f'/api/takes/{take}/link', json={'asset_id': asset['id']}).status_code, 503)
        self.assertEqual(self.patch(f"/api/bindings/{response.json['id']}", {'active': True}).status_code, 503)
        self.assertEqual(self.database(), before)
        self.assertEqual(target.read_bytes(), b'corrupt synthetic fixture')
        moved = target.with_suffix('.held')
        target.rename(moved)  # synthetic fixture only, preserve bytes
        self.assertEqual(self.upload(take).status_code, 503)
        self.assertEqual(self.database(), before)
        self.assertTrue(moved.exists())

    def test_failed_import_preserves_prior_records_and_files(self):
        _, take = self.episode_take()
        self.upload(take)
        before = self.database()
        media = self.app.config['DATA_DIR'] / 'media'
        snapshot = {p.name: p.read_bytes() for p in media.iterdir()}
        with patch('app.os.link', side_effect=OSError('synthetic')):
            result = self.upload(take, png('blue'))
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.database(), before)
        self.assertEqual({p.name: p.read_bytes() for p in media.iterdir()}, snapshot)

    def test_sqlite_failure_after_publication_and_retry(self):
        _, take = self.episode_take()
        before = self.database()
        path = self.app.config['DATA_DIR'] / 'registry.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON bindings BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        response = self.upload(take)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.database(), before)
        sha = hashlib.sha256(png()).hexdigest()
        target = self.app.config['DATA_DIR'] / 'media' / (sha + '.png')
        verify_file(target, sha)
        stamp = target.stat().st_mtime_ns
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('DROP TRIGGER synthetic_failure')
        self.assertEqual(self.upload(take).status_code, 201)
        self.assertEqual(target.stat().st_mtime_ns, stamp)

    def backup_fixture(self):
        _, take = self.episode_take()
        self.upload(take, png('orange'), version='1')
        self.upload(take, png('blue'), version='2')
        self.patch(f'/api/takes/{take}', {'status': 'approved', 'prompt': 'Synthetic prompt'})
        return self.export()

    def empty_restore_target(self):
        root = self.root / 'restore-empty'
        app = create_app(root)
        app.testing = True
        return root, app.test_client(), {'X-App-Token': app.config['APP_TOKEN']}

    def test_roundtrip_empty_preserves_history_and_hashes(self):
        backup = self.backup_fixture()
        root, client, headers = self.empty_restore_target()
        self.assertEqual(self.restore(backup, client, headers).status_code, 200)
        # Empty target allocates identical IDs for this synthetic fixture.
        self.assertEqual(self.database(root), self.database())
        for path in (root / 'media').iterdir():
            verify_file(path, path.stem)
        with closing(sqlite3.connect(root / 'registry.sqlite3')) as db, db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_restore_partial_failure_rolls_back_and_retry(self):
        backup = self.backup_fixture()
        root, client, headers = self.empty_restore_target()
        before = self.database(root)
        original_publish = module.publish_verified
        count = 0
        def fail_second_media(source, target, sha, size):
            nonlocal count
            if target.parent.name == 'media':
                count += 1
                if count == 2:
                    raise MediaStorageError('synthetic interruption')
            original_publish(source, target, sha, size)
        with patch('app.publish_verified', side_effect=fail_second_media):
            response = self.restore(backup, client, headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.database(root), before)
        preserved = {p.name: p.read_bytes() for p in (root / 'media').iterdir()}
        self.assertEqual(len(preserved), 1)
        self.assertEqual(self.restore(backup, client, headers).status_code, 200)
        for name, content in preserved.items():
            self.assertEqual((root / 'media' / name).read_bytes(), content)
        self.assertEqual(self.database(root), self.database())

    def test_restore_sql_failure_after_new_records_rolls_back(self):
        backup = self.backup_fixture()
        root, client, headers = self.empty_restore_target()
        before = self.database(root)
        with closing(sqlite3.connect(root / 'registry.sqlite3')) as db, db:
            db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON bindings BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        response = self.restore(backup, client, headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.database(root), before)
        for path in (root / 'media').iterdir():
            verify_file(path, path.stem)

    def test_restore_corrupt_preexisting_destination_is_preserved(self):
        backup = self.backup_fixture()
        root, client, headers = self.empty_restore_target()
        sha = hashlib.sha256(png('orange')).hexdigest()
        target = root / 'media' / (sha + '.png')
        target.write_bytes(b'preexisting synthetic corruption')
        before = self.database(root)
        self.assertEqual(self.restore(backup, client, headers).status_code, 503)
        self.assertEqual(self.database(root), before)
        self.assertEqual(target.read_bytes(), b'preexisting synthetic corruption')

    def test_registered_reuse_commit_failure_rolls_back(self):
        _, take = self.episode_take()
        self.upload(take)
        before = self.database()
        real_connect = sqlite3.connect
        class FailCommit(sqlite3.Connection):
            def __exit__(self, typ, value, traceback):
                if typ is None and self.in_transaction:
                    self.rollback()
                    raise sqlite3.OperationalError('synthetic commit failure')
                return super().__exit__(typ, value, traceback)
        def connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=FailCommit)
        with patch('app.sqlite3.connect', side_effect=connect):
            response = self.upload(take)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.database(), before)

    def test_backup_hash_mismatch_cannot_create_bindings(self):
        backup = self.rewrite_backup(self.backup_fixture(), corrupt=True)
        root, client, headers = self.empty_restore_target()
        before = self.database(root)
        self.assertEqual(self.restore(backup, client, headers).status_code, 400)
        self.assertEqual(self.database(root), before)
        self.assertEqual(list((root / 'media').iterdir()), [])
