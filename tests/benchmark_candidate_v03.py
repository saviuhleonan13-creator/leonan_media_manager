"""Optional Linux benchmark; generates AVI fixtures and uses fresh temporary data.

Requires a Git checkout with V0.2 commit, FFmpeg and application dependencies.
Does not launch a server or read any existing project data. Prints JSON only.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = '7825a470e2943e9f1cbc2cd80202b40b1016f4b3'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def measure(module, source, data):
    app = module.create_app(data)
    app.testing = True
    client = app.test_client()
    headers = {'X-App-Token': app.config['APP_TOKEN']}
    episode = client.post('/api/episodes', headers=headers, json={'code': 'SYNTHETIC'}).json['id']
    take = client.post(f'/api/episodes/{episode}/takes', headers=headers, json={'number': 1}).json['id']
    stop = threading.Event()
    peak = {'tmp_bytes': 0, 'data_logical_bytes': 0, 'data_unique_inode_bytes': 0}
    def sample():
        while not stop.is_set():
            logical = temporary = 0
            unique = {}
            for path in data.rglob('*'):
                try:
                    if not path.is_file():
                        continue
                    info = path.stat()
                    logical += info.st_size
                    unique[(info.st_dev, info.st_ino)] = info.st_size
                    if 'tmp' in path.relative_to(data).parts or path.name.startswith('.leonan-copy-'):
                        temporary += info.st_size
                except FileNotFoundError:
                    pass
            peak['tmp_bytes'] = max(peak['tmp_bytes'], temporary)
            peak['data_logical_bytes'] = max(peak['data_logical_bytes'], logical)
            peak['data_unique_inode_bytes'] = max(peak['data_unique_inode_bytes'], sum(unique.values()))
            stop.wait(.002)
    thread = threading.Thread(target=sample)
    thread.start()
    started = time.perf_counter()
    try:
        with source.open('rb') as stream:
            response = client.post(f'/api/takes/{take}/media', headers=headers,
                                   data={'file': (stream, source.name), 'kind': 'video', 'version': '1'})
        elapsed = time.perf_counter() - started
        assert response.status_code == 201, response.data
    finally:
        stop.set()
        thread.join()
    stored = next((data / 'media').iterdir())
    with source.open('rb') as a, stored.open('rb') as b:
        assert hashlib.file_digest(a, 'sha256').digest() == hashlib.file_digest(b, 'sha256').digest()
    return dict(seconds=elapsed, **peak)


def main():
    old_source = subprocess.check_output(['git', 'show', f'{BASE}:app.py'], cwd=ROOT)
    results = []
    with tempfile.TemporaryDirectory(prefix='leonan-v03-benchmark-') as folder:
        root = Path(folder)
        baseline_path = root / 'baseline.py'
        baseline_path.write_bytes(old_source)
        modules = {'v02': load('benchmark_baseline', baseline_path),
                   'candidate': load('benchmark_candidate', ROOT / 'app.py')}
        for seconds in (4, 16):
            source = root / f'synthetic-{seconds}s.avi'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                            f'testsrc2=size=640x360:rate=30:duration={seconds}',
                            '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', '-threads', '1', str(source)], check=True)
            samples = {'v02': [], 'candidate': []}
            for repeat in range(3):
                order = ('v02', 'candidate') if repeat % 2 == 0 else ('candidate', 'v02')
                for label in order:
                    # Each run owns a separate directory, removed by its fixture.
                    with tempfile.TemporaryDirectory(dir=root, prefix='run-') as run:
                        samples[label].append(measure(modules[label], source, Path(run) / 'registry'))
            results.append({'video_bytes': source.stat().st_size, 'duration_seconds': seconds,
                            'samples': samples,
                            'median_seconds': {k: statistics.median(s['seconds'] for s in v) for k, v in samples.items()}})
        print(json.dumps({'baseline': BASE, 'python': sys.version, 'results': results}, indent=2))


if __name__ == '__main__':
    main()
