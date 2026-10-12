"""Background sampler/HTTP service lifecycle."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sqlite3
import threading
import time
from .collector import CpuSampler, ProcessSampler, system_sample
from .gpu import GpuSampler
from .paths import current_path, logs_dir
from . import storage

LOG = logging.getLogger('faco-watch')


def configure_logs():
    logs_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    handler = RotatingFileHandler(logs_dir() / 'collector.log', maxBytes=3 * 1024**2,
                                  backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    LOG.addHandler(handler)
    LOG.addHandler(logging.StreamHandler())


def atomic_json(path, obj):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file = path.with_name(path.name + f'.tmp.{os.getpid()}')
    try:
        fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(obj, stream, separators=(',', ':'))
            stream.flush()
        os.replace(file, path)
    finally:
        try:
            file.unlink(missing_ok=True)
        except OSError:
            pass


class SamplerThread(threading.Thread):
    def __init__(self, stop, period=1.0, gpu_reader=None, cpu_reader=None, process_reader=None, db=None, latest_file=None,
                 retry_period=5.0):
        super().__init__(name='FACO sampler', daemon=True)
        self.stop = stop
        self.period = period
        self.retry_period = retry_period
        self.cpu = cpu_reader or CpuSampler()
        self.process_reader = process_reader or ProcessSampler()
        self.gpu = gpu_reader or GpuSampler()
        self.db = db
        self.latest_file = latest_file or current_path()
        self.latest = None
        self.last_error = None

    def collect_once(self, conn):
        snap = system_sample(self.cpu)
        gpu = self.gpu.sample()
        snap.update(gpu)
        snap['system_processes'] = self.process_reader.sample()
        storage.save(conn, snap)
        atomic_json(self.latest_file, snap)
        self.latest = snap
        return snap

    def run(self):
        conn = self.db
        last_cleanup = 0
        last_failure_log = 0
        next_tick = time.monotonic()
        try:
            while not self.stop.is_set():
                if conn is None:
                    # External FACO drive may mount *after* the user service
                    # starts. Retry instead of terminating the collector thread.
                    try:
                        conn = storage.connect()
                        LOG.info('History storage connected')
                        last_failure_log = 0
                    except (OSError, sqlite3.Error) as exc:
                        self.last_error = str(exc)
                        if time.monotonic() - last_failure_log >= 30:
                            LOG.warning('Storage unavailable; retrying: %s', exc)
                            last_failure_log = time.monotonic()
                        self.stop.wait(self.retry_period)
                        next_tick = time.monotonic()
                        continue
                try:
                    self.collect_once(conn)
                    self.last_error = None
                    last_failure_log = 0
                except (OSError, sqlite3.Error) as exc:
                    self.last_error = str(exc)
                    if time.monotonic() - last_failure_log >= 30:
                        LOG.warning('Storage/sampling I/O failed; reconnecting: %s', exc)
                        last_failure_log = time.monotonic()
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass
                    conn = None
                    self.stop.wait(self.retry_period)
                    continue
                except Exception as exc:
                    self.last_error = str(exc)
                    if time.monotonic() - last_failure_log >= 30:
                        LOG.exception('Sampling failed; retrying')
                        last_failure_log = time.monotonic()
                if time.monotonic() - last_cleanup > 3600:
                    try:
                        storage.prune(conn)
                    except Exception:
                        LOG.exception('History maintenance failure')
                    last_cleanup = time.monotonic()
                next_tick += self.period
                self.stop.wait(max(0, next_tick - time.monotonic()))
                if next_tick < time.monotonic() - 2 * self.period:
                    next_tick = time.monotonic()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass


def serve(port=18777):
    from .server import make_server
    configure_logs()
    LOG.info('Starting FACO Resource Watch')
    stop = threading.Event()
    sampler = SamplerThread(stop)
    server = make_server(port)
    sampler.start()
    def shutdown(signum, frame):
        LOG.info('Received signal %s; shutting down', signum)
        stop.set()
        # Avoid deadlock: serve_forever must be shut down on a different thread.
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        stop.set()
        sampler.join(timeout=7)
        server.server_close()
        LOG.info('Stopped')
