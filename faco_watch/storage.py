"""SQLite time-series history: WAL allows simultaneous sampler and GUI queries."""
import json
import math
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote
from .paths import db_path, CONFIG

RETENTION_SECONDS = 7 * 24 * 3600
MAX_POINTS = 560

SAMPLE_FIELDS = [
    'cpu_percent', 'ram_percent', 'ram_used_bytes', 'ram_total_bytes', 'cpu_temp_c',
    'gpu_percent', 'gpu_mem_percent', 'gpu_temp_c', 'vram_used_bytes', 'vram_total_bytes',
    'video_encode_percent', 'video_decode_percent',
]

SCHEMA = '''
CREATE TABLE IF NOT EXISTS samples (
 ts INTEGER NOT NULL, gpu_index INTEGER NOT NULL,
 cpu_percent REAL, ram_percent REAL, ram_used_bytes INTEGER, ram_total_bytes INTEGER,
 cpu_temp_c REAL, gpu_percent REAL, gpu_mem_percent REAL, gpu_temp_c REAL,
 vram_used_bytes INTEGER, vram_total_bytes INTEGER,
 video_encode_percent REAL, video_decode_percent REAL,
 PRIMARY KEY (ts, gpu_index)
);
CREATE TABLE IF NOT EXISTS process_samples (
 ts INTEGER NOT NULL, gpu_index INTEGER NOT NULL, pid INTEGER NOT NULL,
 start_ticks TEXT NOT NULL, name TEXT NOT NULL, kind TEXT,
 vram_bytes INTEGER, sm_percent REAL, memory_io_percent REAL,
 encode_percent REAL, decode_percent REAL,
 PRIMARY KEY (ts, gpu_index, pid, start_ticks)
);
CREATE INDEX IF NOT EXISTS process_by_gpu_time ON process_samples(gpu_index, ts);
CREATE INDEX IF NOT EXISTS process_by_identity_time ON process_samples(gpu_index, pid, start_ticks, ts);
'''



def ensure_storage_available(target):
    target = Path(target)
    if not target.is_absolute():
        return
    try:
        startup = json.loads((CONFIG / 'startup.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        startup = {}
    mounts = startup.get('require_mounts', [])
    if not isinstance(mounts, list):
        mounts = []
    if startup.get('require_mount'):
        mounts.append(startup['require_mount'])
    for root in mounts:
        mount = Path(str(root))
        if not mount.is_absolute() or not mount.is_mount():
            raise OSError(f'Configured storage mount unavailable: {mount}')
    # Also protect legacy databases and externally overridden data dirs that
    # may not yet have a corresponding new-style startup configuration.
    parts = target.parts
    removable = ((len(parts) > 2 and parts[1] in ('media', 'mnt')) or
                 (len(parts) > 3 and parts[1:3] == ('run', 'media')))
    if removable:
        current = target.parent
        while not current.exists() and current != current.parent:
            current = current.parent
        blocked = (Path('/media'), Path('/mnt'), Path('/run/media'))
        has_mounted_drive = False
        while current != current.parent:
            if current not in blocked and current.is_mount():
                has_mounted_drive = True
                break
            current = current.parent
        if not has_mounted_drive:
            raise OSError(f'External storage not mounted: {target}')


def connect(path=None, readonly=False):
    target = Path(path or db_path())
    # Never create a fake drive directory if custom storage disappears after
    # initial boot. The installer's mount preflight is repeated at every DB
    # reconnection (and read-only query), including /mnt and /run/media.
    ensure_storage_available(target)
    if not readonly:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            target.parent.chmod(0o700)
        except OSError:
            pass
    if readonly:
        conn = sqlite3.connect(f'file:{quote(str(target))}?mode=ro', uri=True, timeout=5)
    else:
        conn = sqlite3.connect(str(target), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    if readonly:
        conn.execute('PRAGMA query_only=ON')
    else:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.executescript(SCHEMA)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    return conn


def save(conn, snapshot):
    ts = int(snapshot['ts'])
    cpu = snapshot
    ram = cpu['ram']
    gpus = snapshot.get('gpus', [])
    # Keep an independent system row even when NVIDIA disconnects. The old
    # per-GPU copies remain for upgrades and historical compatibility.
    for gpu in [None, *gpus]:
        fields = [
            cpu.get('cpu_percent'), ram.get('percent'), ram.get('used_bytes'), ram.get('total_bytes'),
            cpu.get('cpu_temp_c'), gpu.get('percent') if gpu else None,
            gpu.get('memory_controller_percent') if gpu else None,
            gpu.get('temp_c') if gpu else None,
            gpu.get('vram_used_bytes') if gpu else None,
            gpu.get('vram_total_bytes') if gpu else None,
            gpu.get('video_encode_percent') if gpu else None,
            gpu.get('video_decode_percent') if gpu else None,
        ]
        conn.execute('INSERT OR REPLACE INTO samples VALUES (' + ','.join('?' * 14) + ')',
                     (ts, gpu['index'] if gpu else -1, *fields))
    for p in snapshot.get('processes', []):
        conn.execute('''INSERT OR REPLACE INTO process_samples VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (
            ts, p['gpu_index'], p['pid'], p['start_ticks'], p['name'][:160],
            p['type'], p.get('vram_bytes'), p.get('sm_percent'),
            p.get('memory_io_percent'), p.get('encode_percent'), p.get('decode_percent'),
        ))
    conn.commit()


def prune(conn, now=None):
    cutoff = int(now if now is not None else time.time()) - RETENTION_SECONDS
    conn.execute('DELETE FROM samples WHERE ts < ?', (cutoff,))
    conn.execute('DELETE FROM process_samples WHERE ts < ?', (cutoff,))
    conn.commit()


def clamp_range(seconds):
    try:
        return min(RETENTION_SECONDS, max(15, int(seconds)))
    except (TypeError, ValueError):
        return 3600


def gpu_option(value):
    try:
        return max(-1, min(15, int(value)))
    except (TypeError, ValueError):
        return 0


def group_step(seconds):
    return max(1, math.ceil(seconds / MAX_POINTS))


def query_history(conn, seconds=3600, gpu_index=0, now=None):
    """Merge dedicated system samples and selected GPU samples by time bucket.

    Before v1.0.2, CPU/RAM/temperature were stored only in GPU-index rows.
    When a bucket has no separate system record, reuse the legacy values.
    """
    seconds = clamp_range(seconds)
    step = group_step(seconds)
    since = int(now if now is not None else time.time()) - seconds
    averages = ', '.join(f'ROUND(AVG({field}), 2) AS {field}'
                         for field in SAMPLE_FIELDS)
    peak_names = [field for field in SAMPLE_FIELDS
                  if field.endswith('percent') or field in
                  ('cpu_temp_c', 'gpu_temp_c', 'ram_used_bytes', 'vram_used_bytes')]
    peaks = ', '.join(f'MAX({field}) AS {field}_peak' for field in peak_names)
    query = f'''SELECT CAST(ts / ? AS INTEGER)*? AS ts, {averages}, {peaks},
      MAX(gpu_percent) AS gpu_peak_percent, MAX(cpu_percent) AS cpu_peak_percent,
      MAX(vram_used_bytes) AS vram_peak_bytes,
      MAX(gpu_temp_c) AS gpu_peak_temp_c, COUNT(*) AS sample_count
      FROM samples WHERE ts >= ? AND gpu_index = ?
      GROUP BY CAST(ts / ? AS INTEGER) ORDER BY ts ASC'''

    def bucket_rows(index):
        return [dict(row) for row in conn.execute(query,
                 (step, step, since, index, step)).fetchall()]

    system = {row['ts']: row for row in bucket_rows(-1)}
    if gpu_index == -1:
        return {'seconds': seconds, 'bucket_seconds': step,
                'rows': [system[k] for k in sorted(system)]}
    gpu_rows = {row['ts']: row for row in bucket_rows(gpu_index)}
    system_fields = ('cpu_percent', 'ram_percent', 'ram_used_bytes',
                     'ram_total_bytes', 'cpu_temp_c')
    system_keys = set(system_fields) | {f'{f}_peak' for f in system_fields
                                            if f in peak_names} | {
        'cpu_peak_percent', 'sample_count'
    }
    merged = []
    for ts in sorted(system.keys() | gpu_rows.keys()):
        sysrow = system.get(ts)
        grow = gpu_rows.get(ts)
        if sysrow is None:
            merged.append(grow)  # pre-upgrade history on a GPU-bearing system
        elif grow is None:
            merged.append(sysrow)
        else:
            row = dict(grow)
            for field in system_keys:
                row[field] = sysrow[field]
            merged.append(row)
    return {'seconds': seconds, 'bucket_seconds': step, 'rows': merged}


def query_process_summary(conn, seconds=3600, gpu_index=0, now=None):
    seconds = clamp_range(seconds)
    since = int(now if now is not None else time.time()) - seconds
    rows = conn.execute('''SELECT gpu_index, pid, start_ticks, MAX(name) AS name,
      MAX(kind) AS kind, MIN(ts) AS first_seen, MAX(ts) AS last_seen,
      COUNT(*) AS observations, ROUND(AVG(sm_percent), 1) AS avg_sm_percent,
      MAX(sm_percent) AS peak_sm_percent, MAX(vram_bytes) AS peak_vram_bytes,
      ROUND(AVG(vram_bytes)) AS avg_vram_bytes
      FROM process_samples WHERE ts >= ? AND gpu_index = ?
      GROUP BY gpu_index, pid, start_ticks
      ORDER BY COALESCE(peak_sm_percent, -1) DESC, peak_vram_bytes DESC,
      observations DESC, last_seen DESC LIMIT 100''', (since, gpu_index)).fetchall()
    return {'seconds': seconds, 'rows': [dict(row) for row in rows]}


def query_process_history(conn, seconds=3600, gpu_index=0, pid=0, start_ticks='', now=None):
    seconds = clamp_range(seconds)
    step = group_step(seconds)
    since = int(now if now is not None else time.time()) - seconds
    try:
        pid = max(1, int(pid))
    except (TypeError, ValueError):
        pid = 0
    # Identity must match both PID and kernel process start time.
    rows = conn.execute('''SELECT CAST(ts / ? AS INTEGER)*? AS ts,
      ROUND(AVG(sm_percent),2) AS sm_percent, MAX(sm_percent) AS peak_sm_percent,
      ROUND(AVG(vram_bytes)) AS vram_bytes, MAX(vram_bytes) AS peak_vram_bytes,
      COUNT(*) AS sample_count
      FROM process_samples WHERE ts >= ? AND gpu_index = ? AND pid = ? AND start_ticks = ?
      GROUP BY CAST(ts / ? AS INTEGER) ORDER BY ts''',
                        (step, step, since, gpu_index, pid, str(start_ticks)[:60], step)).fetchall()
    return {'seconds': seconds, 'bucket_seconds': step,
            'rows': [dict(row) for row in rows]}
