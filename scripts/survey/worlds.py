"""Durable, bounded world jobs over immutable photo and boundary snapshots."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from shapely.geometry import Polygon, shape

from survey.core import Conflict, canonical, digest, utc

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'survey-world-1'
ACTIVE = {'queued', 'processing'}


def source_files():
    files = [*Path(__file__).parent.glob('world*.py'), ROOT/'training/default_model.json',
             *[ROOT/'training'/name for name in ('__init__.py','infer.py','common.py','data.py','runtime.py','evaluate.py','metrics.py')],
             ROOT/'scripts/survey/core.py', ROOT/'scripts/survey/batch.py',
             ROOT/'scripts/survey/__init__.py', ROOT/'scripts/aerial_survey.py',
             ROOT/'scripts/terrain/world_core.py', ROOT/'scripts/terrain/world_geometry.py',
             ROOT/'scripts/terrain/world_build.py', ROOT/'scripts/terrain/uv.lock', ROOT/'uv.lock',
             ROOT/'scripts/terrain/pyproject.toml', ROOT/'pyproject.toml',
             ROOT/'validation/terrain-demo/assets/cow-original.glb', ROOT/'validation/terrain-demo/assets/cow-normal.png',
             *[p for p in (ROOT/'validation/world-viewer').iterdir() if p.is_file()]]
    return sorted(set(files))


def code_hash():
    return digest(canonical({str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in source_files()}))


class Worlds:
    def __init__(self, store, batches, start_worker=True):
        self.store, self.batches = store, batches
        self.root = store.root/'worlds'
        self.root.mkdir(exist_ok=True)
        self.wake = threading.Event()
        self.stopping = threading.Event()
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS world_jobs(
                id TEXT PRIMARY KEY, request_hash TEXT UNIQUE, batch_id TEXT, parcel_id TEXT,
                created REAL, updated REAL, status TEXT, message TEXT, result TEXT)''')
        if start_worker:
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    def recent(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM world_jobs ORDER BY created DESC LIMIT 30')]
        return [self.get(ident) for ident in ids]

    def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{24}', ident):
            raise ValueError('Choose a saved world.')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM world_jobs WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError('World not found.')
        value = dict(row)
        value['result'] = json.loads(value['result']) if value['result'] else None
        if value['status'] == 'processing':
            try:
                value['message'] = json.loads((self.root/ident/'progress.json').read_text())['message']
            except (OSError, ValueError, KeyError):
                pass
        value['created_utc'] = utc(value.pop('created'))
        value['url'] = f'/worlds/{ident}/' if value['status'] == 'ready' else None
        return value

    def create(self, batch_id, parcel_id):
        batch, parcel = self.batches.get(batch_id), self.store.parcel(parcel_id)
        if batch['status'] != 'ready':
            raise ValueError('Wait for the photo map to finish first.')
        if not batch['photos'] or any(not p['placement']['corners'] for p in batch['photos']):
            raise ValueError('Every photo needs GPS, altitude, lens and near-vertical DJI camera direction. Start a batch containing supported photos.')
        dates = {p['meta']['captured_local'][:10] if p['meta']['captured_local'] else None for p in batch['photos']}
        if None in dates or len(dates) != 1:
            raise ValueError('Use photographs from one dated survey flight.')
        from datetime import datetime
        times = [datetime.fromisoformat(p['meta']['captured_local']).timestamp() for p in batch['photos']]
        if max(times)-min(times) > 600:
            raise ValueError('Use one survey captured within ten minutes; split longer flights into batches.')
        polygon = Polygon(parcel['map_vertices'])
        west, south, east, north = polygon.bounds
        if max(east-west, north-south) > 800 or polygon.area < 100:
            raise ValueError('Choose a field at least 100 m² and at most 800 m across.')
        if not batch['result']['coverage'] or polygon.intersection(shape(batch['result']['coverage'])).area < 100:
            raise ValueError('The boundary must overlap at least 100 m² of uploaded imagery.')
        request = {'version': VERSION, 'code_sha256': code_hash(), 'batch': batch, 'parcel': parcel,
                   'model': json.loads((ROOT/'training/default_model.json').read_text())}
        request_hash = digest(canonical(request)); ident = request_hash[:24]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM world_jobs WHERE request_hash=?', (request_hash,)).fetchone()
            if existing:
                return self.get(existing[0])
            count = db.execute("SELECT count(*) FROM world_jobs WHERE status IN ('queued','processing')").fetchone()[0]
            if count >= 3:
                raise Conflict('Three worlds are already processing or queued. Wait for a build to finish.')
            folder = self.root/ident
            folder.mkdir(exist_ok=True); (folder/'inputs').mkdir(exist_ok=True)
            for photo in batch['photos']:
                raw, _ = self.batches.photo(batch_id, photo['id'])
                if digest(raw) != photo['meta']['byte_sha256']:
                    raise ValueError('Saved photograph integrity check failed.')
                ext = '.png' if photo['meta']['format'] == 'PNG' else '.jpg'
                (folder/'inputs'/(photo['meta']['byte_sha256']+ext)).write_bytes(raw)
            (folder/'request.json').write_bytes(canonical(request))
            now = time.time()
            db.execute('INSERT INTO world_jobs VALUES(?,?,?,?,?,?,?, ?,NULL)',
                       (ident, request_hash, batch_id, parcel_id, now, now, 'queued', 'Waiting to build your world…'))
        self.wake.set()
        return self.get(ident)

    def retry(self, ident):
        self.get(ident)
        with self.store.connect() as db:
            db.execute("UPDATE world_jobs SET status='queued',message='Retry queued…',updated=? WHERE id=? AND status='failed'", (time.time(), ident))
        self.wake.set()
        return self.get(ident)

    def _worker(self):
        import fcntl
        # One process owns this state's worker. SQLite and snapshots survive restart.
        with (self.root/'worker.lock').open('a') as lock:
            while not self.stopping.is_set():
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.stopping.wait(1)
            else:
                return
            with self.store.connect() as db:
                db.execute("UPDATE world_jobs SET status='queued',message='Resuming interrupted build…' WHERE status='processing'")
            while not self.stopping.is_set():
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute("SELECT id FROM world_jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if row:
                        db.execute("UPDATE world_jobs SET status='processing',message='Preparing world…',updated=? WHERE id=?", (time.time(), row[0]))
                if not row:
                    self.wake.wait(1); self.wake.clear(); continue
                ident = row[0]; folder = self.root/ident
                try:
                    with (folder/'worker.log').open('ab') as log:
                        run = subprocess.run([sys.executable, str(Path(__file__).with_name('world_pipeline.py')),
                                              '--job', str(folder)], cwd=ROOT, stdout=log, stderr=log,
                                             pass_fds=(lock.fileno(),), timeout=2700)
                    if run.returncode:
                        try: message = json.loads((folder/'error.json').read_text())['error']
                        except (OSError, ValueError, KeyError): message = 'The world worker stopped unexpectedly. Retry the build.'
                        raise ValueError(message)
                    result = json.loads((folder/'result.json').read_text())
                    with self.store.connect() as db:
                        db.execute("UPDATE world_jobs SET status='ready',message='Your world is ready.',result=?,updated=? WHERE id=?", (canonical(result).decode(), time.time(), ident))
                except Exception as error:
                    with self.store.connect() as db:
                        db.execute("UPDATE world_jobs SET status='failed',message=?,updated=? WHERE id=?", (str(error), time.time(), ident))

    def asset(self, ident, relative):
        job = self.get(ident)
        if job['status'] != 'ready':
            raise KeyError('World is not ready.')
        base = (self.root/ident/'build').resolve()
        manifest = json.loads((base/'build-manifest.json').read_text())
        relative = relative or 'index.html'
        if relative != 'build-manifest.json' and relative not in manifest['output_sha256']:
            raise KeyError('World asset not found.')
        path = (base/relative).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise KeyError('World asset not found.')
        return path
