"""Localhost-only, read-only JSON API + static graphical dashboard."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from . import storage
from .paths import current_path, source_web, INSTALL_DIR, db_path

PORT = 18777


class Handler(BaseHTTPRequestHandler):
    server_version = 'FACOResourceWatch/1.0.3'

    def log_message(self, format_, *args):
        # Avoid logging user process names/queries into world-accessible logs.
        return

    def _headers(self, status, kind='application/json; charset=utf-8', length=0):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, value, status=200):
        body = json.dumps(value, separators=(',', ':')).encode()
        self._headers(status, length=len(body))
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._headers(405, length=0)

    def do_POST(self):
        self._send({'error': 'Read-only API'}, 405)

    def do_GET(self):
        # Prevent DNS rebinding / malicious origins from reading process data.
        host = self.headers.get('Host', '')
        allowed_hosts = {f'127.0.0.1:{self.server.server_port}',
                         f'localhost:{self.server.server_port}'}
        if host not in allowed_hosts:
            self._send({'error': 'Invalid host'}, 403)
            return
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{h}' for h in allowed_hosts}:
            self._send({'error': 'Cross-origin access refused'}, 403)
            return
        site = self.headers.get('Sec-Fetch-Site', '')
        if site == 'cross-site':
            self._send({'error': 'Cross-site request refused'}, 403)
            return
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        def arg(name, default):
            return q.get(name, [default])[0]
        if url.path == '/api/health':
            self._send({'ok': True, 'service': 'FACO Resource Watch', 'version': '1.0.3',
                        'install_path': str(INSTALL_DIR.resolve()), 'data_path': str(db_path()),
                        'pid': os.getpid()})
        elif url.path == '/api/current':
            try:
                curr = json.loads(current_path().read_text(encoding='utf-8'))
                self._send(curr)
            except (OSError, ValueError):
                self._send({'error': 'Waiting for first sample'}, 503)
        elif url.path in ('/api/history', '/api/processes', '/api/process-history'):
            try:
                conn = storage.connect(readonly=True)
                try:
                    span = storage.clamp_range(arg('range', 3600))
                    gpu = storage.gpu_option(arg('gpu', 0))
                    if url.path == '/api/history':
                        result = storage.query_history(conn, span, gpu)
                    elif url.path == '/api/processes':
                        result = storage.query_process_summary(conn, span, gpu)
                    else:
                        result = storage.query_process_history(
                            conn, span, gpu, arg('pid', 0), arg('start', ''))
                finally:
                    conn.close()
                self._send(result)
            except Exception as exc:
                self._send({'error': f'History database unavailable: {str(exc)[:120]}'}, 503)
        elif url.path in ('/', '/app.js', '/app.css', '/favicon.svg'):
            item = 'index.html' if url.path == '/' else url.path.lstrip('/')
            path = source_web() / item
            try:
                contents = path.read_bytes()
                mimetype = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
                if item.endswith('.js'):
                    mimetype = 'text/javascript'
                self._headers(200, f'{mimetype}; charset=utf-8', len(contents))
                self.wfile.write(contents)
            except OSError:
                self._send({'error': 'Missing application file'}, 404)
        else:
            self._send({'error': 'Not found'}, 404)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=PORT):
    return LocalServer(('127.0.0.1', int(port)), Handler)
